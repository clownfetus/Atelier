import os, sys, json, time, queue, subprocess, threading, atexit
from atelier.config import TOOLS, CNW, ROOT, PAKS, USMAP, _CACHE, get_aes_key
from atelier import hostos

UAT = os.path.join(TOOLS, "UAssetTool.exe")

# Cap concurrent heavy texture extract/decode. The viewport fires up to 2N requests at once (N
# materials x albedo+emissive), the server is ThreadingMixIn, and one-shot uat() is unlocked — so
# without this each request becomes its own UAssetTool process that re-parses the ~248k-entry
# pakchunkCharacter container AND holds a full 4096² texture in RAM. On a big skin that swarm OOMs and
# takes the viewport down. Serialise to a few at a time: a decode is fast once it's running; it's the
# simultaneous pile-up that kills it. Override with ATELIER_TEX_CONCURRENCY if needed.
_TEX_CONCURRENCY = max(2, min(4, (os.cpu_count() or 4) // 2))
try:
    _TEX_CONCURRENCY = max(1, int(os.environ.get("ATELIER_TEX_CONCURRENCY", _TEX_CONCURRENCY)))
except ValueError:
    pass
tex_semaphore = threading.BoundedSemaphore(_TEX_CONCURRENCY)

# AtelierMesh: CUE4Parse-based mesh -> glTF (.glb) decoder for the 3D viewport.
ATELIER_MESH = os.path.join(TOOLS, "AtelierMesh", "AtelierMesh.exe")

def _aes_hex():
    """The current key in the 0x-prefixed form the .exe tools want. Reads through
    config.get_aes_key so there is one reader of AES_KEY.txt as well as one writer — a second
    copy of this parse is how io_lib and the tools ended up disagreeing about the key."""
    k = get_aes_key()
    return "0x" + k if k else ""

_VANILLA_PAKS = os.path.join(_CACHE, "vanilla_paks")

def _drive(path):
    return os.path.splitdrive(os.path.abspath(path))[0].upper()

def vanilla_paks():
    """(folder, problem): a hardlink mirror of PAKS's TOP-LEVEL files only, or PAKS itself and why.

    AtelierMesh's CUE4Parse provider scans the directory it's given recursively, so pointing it at
    PAKS directly also picks up whatever lives in PAKS/~mods (or any other subfolder the "Copy to
    mods folder" setting points at) -- installed mods then win pack-stacking and the 3D viewport
    shows modded content, unlike the file browser and the Blender export path, which both resolve
    assets through index.ensure_index()'s non-recursive `glob(PAKS + "/*.utoc")` and so only ever
    see vanilla containers. Mirroring PAKS's top level with hardlinks (instant, no extra disk use,
    same-volume only) keeps the viewport in sync with everything else without needing to touch
    AtelierMesh itself.

    When hardlinking isn't possible -- most often because Atelier's data folder and the game are on
    different drives -- this falls back to the real PAKS dir, mods included, and `problem` says why
    in words a user can act on. It is None when the mirror is in use."""
    try:
        wanted = {f: os.path.join(PAKS, f) for f in os.listdir(PAKS)
                  if os.path.isfile(os.path.join(PAKS, f))}
    except OSError as e:
        return PAKS, f"Atelier could not read the game's Paks folder ({e.strerror or e})"
    try:
        os.makedirs(_VANILLA_PAKS, exist_ok=True)
        have = set(os.listdir(_VANILLA_PAKS))
    except OSError as e:
        return PAKS, f"Atelier could not use its cache folder ({e.strerror or e})"
    for stale in have - wanted.keys():
        try: os.remove(os.path.join(_VANILLA_PAKS, stale))
        except OSError: pass
    for name, src in wanted.items():
        link = os.path.join(_VANILLA_PAKS, name)
        try:
            if os.path.exists(link):
                s_src, s_link = os.stat(src), os.stat(link)
                if s_src.st_size == s_link.st_size and int(s_src.st_mtime) == int(s_link.st_mtime):
                    continue
                os.remove(link)
            os.link(src, link)
        except OSError as e:
            # Cross-volume, no permission, etc. -- better vanilla-or-mods than a broken mirror.
            cache, game = _drive(_VANILLA_PAKS), _drive(PAKS)
            if cache and game and cache != game:
                return PAKS, f"Atelier's data folder is on {cache} and the game is on {game}"
            return PAKS, f"Atelier could not link the game's files into its cache ({e.strerror or e})"
    return _VANILLA_PAKS, None

def _vanilla_paks_dir():
    return vanilla_paks()[0]

def _mod_folders(paks):
    """Subfolders of the game's Paks folder (relative names) that hold mod containers."""
    found = []
    for dirpath, _dirs, files in os.walk(paks):
        if dirpath != paks and any(f.lower().endswith((".utoc", ".pak")) for f in files):
            found.append(os.path.relpath(dirpath, paks).replace("\\", "/"))
    return sorted(found)

def atelier_mesh(asset, out_dir):
    """Decode an MR mesh (content-mount path, no ext) to glTF (.glb) under out_dir.

    The result also carries `paks`, the folder the decoder read, and `mods_note`: None when it saw
    only the game's own containers, otherwise a sentence saying why installed mods were visible to
    it -- a mod that overrides the mesh is then a likely reason for a failed decode."""
    paks, problem = vanilla_paks()
    mods = _mod_folders(PAKS) if problem else []
    note = None
    if mods:
        shown = ", ".join(mods[:3]) + (f" and {len(mods) - 3} more" if len(mods) > 3 else "")
        note = f"{problem}, so Atelier could not keep installed mods out of this decode and also read {shown}"
    print(f"[atelier_mesh] {asset}: paks={paks} "
          + (f"(installed mods visible: {note})" if note else "(game files only)"),
          file=sys.stderr, flush=True)
    r = hostos.run_exe(
        [ATELIER_MESH, "--paks", os.path.abspath(paks), "--aes", _aes_hex(),
         "--usmap", USMAP, "--asset", asset, "--out", os.path.abspath(out_dir)],
        capture_output=True, text=True, cwd=ROOT)
    try:
        r.paks, r.mods_note = paks, note
    except AttributeError:
        pass
    return r

# A UAssetTool call that is still running after this long is wedged, not slow: the measured
# worst case is ~15s for a single-asset extract fallback. Overridable for very large batches.
UAT_TIMEOUT = 300
try:
    UAT_TIMEOUT = max(10, int(os.environ.get("ATELIER_UAT_TIMEOUT", UAT_TIMEOUT)))
except ValueError:
    pass

# ...except for the commands that ENCODE. Injecting a texture rebuilds its whole mip chain, and
# BC7 is the slowest encoder in the set: measured 2026-09-20, three 2048x2048 BC7 mip-chain
# injections plus the pack took 804s -- about 270s each, i.e. right up against the 300s cap. Two
# of three legitimate injections were killed by it before this existed, and the user saw
# "inject failed: UAssetTool timed out after 300s" on work that was simply large.
#
# PHASES.md's own pivot signal for #6 says to raise the limit rather than revert it and to write
# down the real duration, which is what this is. The point of the cap is to catch a WEDGED tool
# (the export hang: unbounded readline behind a global lock, never finishes, only a restart
# clears it), and 30 minutes still does that while leaving room for a 4096 texture.
UAT_SLOW_COMMANDS = {"inject_texture": 1800, "batch_inject_texture": 3600}
try:
    _slow = int(os.environ.get("ATELIER_UAT_INJECT_TIMEOUT", "0"))
    if _slow > 0:
        UAT_SLOW_COMMANDS = {k: max(10, _slow) for k in UAT_SLOW_COMMANDS}
except ValueError:
    pass


def _timeout_for(args):
    """The cap for this call: encoding commands get their own, everything else the default."""
    cmd = args[0] if args else ""
    return max(UAT_TIMEOUT, UAT_SLOW_COMMANDS.get(cmd, 0))


class _TimedOut:
    """CompletedProcess-alike so callers can keep checking .returncode / .stdout / .stderr."""
    def __init__(self, args, secs):
        self.args = args
        self.returncode = -9
        self.stdout = ""
        self.stderr = f"UAssetTool timed out after {secs}s"


def uat(args, timeout=None):
    """Run UAssetTool (one-shot). Pass ABSOLUTE paths — it requires them for output.
    Off Windows this goes through Wine, which is also what translates those absolute paths
    into the Z:\\ form the tool sees (see hostos._wrap).

    Bounded: a hung tool used to block the calling request forever with nothing logged. The bound
    depends on the command -- see UAT_SLOW_COMMANDS; an explicit `timeout` still wins."""
    secs = _timeout_for(args) if timeout is None else timeout
    try:
        return hostos.run_exe([UAT] + args, capture_output=True, text=True, cwd=ROOT,
                              timeout=secs)
    except subprocess.TimeoutExpired:
        print(f"  [warn] uat timed out after {secs}s: {' '.join(str(a) for a in args[:3])}",
              file=sys.stderr, flush=True)
        return _TimedOut(args, secs)

_proc = None
_lock = threading.Lock()
_out_q = None          # stdout lines from the current worker

_REQ_PATH_KEYS  = ("output_path", "base_path", "usmap_path", "file_path")
_REQ_PATHS_KEYS = ("file_paths",)

def _host_req(req):
    r"""Translate the path-valued fields of a worker request for the tool's view of the FS.

    Only for a Wine worker. A native Linux build shares our filesystem view, and handing it the
    Z:\ form makes every path in the request point at nothing — the reply comes back as a clean
    "0 succeeded, N failed" with no hint that the paths were the problem."""
    if hostos.IS_WINDOWS or hostos.native_tool(UAT):
        return req
    out = dict(req)
    for k in _REQ_PATH_KEYS:
        if isinstance(out.get(k), str):
            out[k] = hostos.to_host_path(out[k])
    for k in _REQ_PATHS_KEYS:
        if isinstance(out.get(k), (list, tuple)):
            out[k] = [hostos.to_host_path(v) for v in out[k]]
    return out


def _start_worker():
    """Spawn the worker plus one pump thread per stream.

    stdout goes to a queue so a reply can be awaited with a deadline — a bare readline() on the
    pipe cannot be interrupted, and it was being done while holding _lock, so one wedged worker
    blocked every UAssetTool call in the app. stderr is drained and logged instead of being sent
    to DEVNULL, which is why nobody ever saw why a worker had stopped answering.
    """
    global _proc, _out_q
    _proc, _out_q = _spawn_worker()
    return _proc, _out_q


def _spawn_worker():
    """A new worker process and its stdout queue, not installed anywhere."""
    q = queue.Queue()
    proc = hostos.popen_exe([UAT], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, cwd=ROOT, text=True, encoding="utf-8")

    def pump_out():
        try:
            for line in proc.stdout:
                q.put(line)
        except Exception:
            pass
        finally:
            q.put(None)          # EOF sentinel

    def pump_err():
        try:
            for line in proc.stderr:
                line = line.rstrip()
                if line:
                    print(f"  [uat] {line}", file=sys.stderr, flush=True)
        except Exception:
            pass

    for fn, name in ((pump_out, "uat-stdout"), (pump_err, "uat-stderr")):
        threading.Thread(target=fn, name=name, daemon=True).start()
    return proc, q


def _kill_worker():
    global _proc, _out_q
    p = _proc
    _proc = None; _out_q = None
    if p and p.poll() is None:
        try: p.kill()
        except Exception: pass


def uat_json(req, timeout=None):
    """Send one line-delimited JSON request to the persistent UAssetTool worker.
    Reusing one process keeps batch decode fast (startup paid once, parallel across all cores).

    Bounded by `timeout`: on expiry the worker is killed rather than reused, because a late reply
    would desync every subsequent request on the same pipe."""
    secs = UAT_TIMEOUT if timeout is None else timeout
    from atelier import jobs
    global _proc, _out_q
    with jobs.cancellable_lock(_lock):
        jobs.checkpoint()
        if _proc is None or _proc.poll() is not None:
            proc, q = _start_worker()
        else:
            proc, q = _proc, _out_q
        try:
            proc.stdin.write(json.dumps(_host_req(req)) + "\n"); proc.stdin.flush()
        except Exception as e:
            _kill_worker()
            return {"success": False, "message": f"UAssetTool worker not writable: {e}"}

        deadline = time.monotonic() + secs
        # Drain lines until the JSON reply (UAssetTool also writes human-readable status to stdout).
        while True:
            try:
                jobs.checkpoint()
            except jobs.Cancelled:
                _kill_worker()
                raise
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _kill_worker()
                print(f"  [warn] uat_json timed out after {secs}s; worker killed",
                      file=sys.stderr, flush=True)
                return {"success": False,
                        "message": f"UAssetTool did not respond within {secs}s"}
            try:
                line = q.get(timeout=min(remaining, 0.2))
            except queue.Empty:
                continue
            if line is None:                      # EOF
                _kill_worker()
                return {"success": False, "message": "UAssetTool worker closed unexpectedly"}
            s_line = line.strip()
            if s_line.startswith("{") and s_line.endswith("}"):
                try:
                    d = json.loads(s_line)
                    if isinstance(d, dict) and ("success" in d or "data" in d): return d
                except Exception: pass


# ── pooled workers for short per-asset requests ───────────────────────────────
# uat_json's single worker is held for whole batch decodes, and the per-asset paths (viewport
# texture decode, thumbnails, texture-info probes) used one-shot uat() instead: a fresh process per
# texture that re-loads the .usmap and pays .NET startup every time, and for thumbnails up to four
# of them (mip 4 -> 3 -> 2 -> 0). A small pool of persistent workers, sized like tex_semaphore,
# keeps the same concurrency while paying startup once per worker. Measured 2026-10-20 on a
# 2048² DXT5: one-shot extract_texture ~0.96s, warm worker extract_texture_png ~0.2-1.0s, and
# get_texture_info 0.2s against a full one-shot decode for the same three numbers.

class _PoolWorker:
    def __init__(self):
        self.proc = None
        self.q = None

    def kill(self):
        p, self.proc, self.q = self.proc, None, None
        if p and p.poll() is None:
            try: p.kill()
            except Exception: pass

    def request(self, req, secs):
        from atelier import jobs
        if self.proc is None or self.proc.poll() is not None:
            self.proc, self.q = _spawn_worker()
        try:
            self.proc.stdin.write(json.dumps(_host_req(req)) + "\n"); self.proc.stdin.flush()
        except Exception as e:
            self.kill()
            return {"success": False, "message": f"UAssetTool worker not writable: {e}"}
        deadline = time.monotonic() + secs
        while True:
            try:
                jobs.checkpoint()
            except jobs.Cancelled:
                self.kill()
                raise
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self.kill()
                return {"success": False, "message": f"UAssetTool did not respond within {secs}s"}
            try:
                line = self.q.get(timeout=min(remaining, 0.2))
            except queue.Empty:
                continue
            if line is None:
                self.kill()
                return {"success": False, "message": "UAssetTool worker closed unexpectedly"}
            s_line = line.strip()
            if s_line.startswith("{") and s_line.endswith("}"):
                try:
                    d = json.loads(s_line)
                    if isinstance(d, dict) and ("success" in d or "data" in d): return d
                except Exception: pass


_pool_idle = queue.LifoQueue()
for _ in range(_TEX_CONCURRENCY):
    _pool_idle.put(_PoolWorker())
_pool_all = list(_pool_idle.queue)
_pool_unsupported = set()     # actions an older UAssetTool build answered "Unknown action" to


def uat_pooled(req, timeout=None):
    """One JSON request on a pooled persistent worker, or None when the action is unsupported.

    Callers fall back to one-shot uat() on None, so an older UAssetTool build that lacks an action
    degrades to the previous behaviour instead of failing."""
    action = req.get("action")
    if action in _pool_unsupported:
        return None
    from atelier import jobs
    secs = UAT_TIMEOUT if timeout is None else timeout
    while True:
        try:
            worker = _pool_idle.get(timeout=0.1)
            break
        except queue.Empty:
            jobs.checkpoint()
    try:
        d = worker.request(req, secs)
    finally:
        _pool_idle.put(worker)
    if not d.get("success") and str(d.get("message", "")).startswith("Unknown action"):
        _pool_unsupported.add(action)
        return None
    return d


@atexit.register
def _shutdown():
    for w in _pool_all:
        w.kill()
    if _proc and _proc.poll() is None:
        try:
            _proc.terminate()
            _proc.wait(timeout=2)
        except Exception:
            try: _proc.kill()
            except Exception: pass
