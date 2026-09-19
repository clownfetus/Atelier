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

def _vanilla_paks_dir():
    """Hardlink mirror of PAKS's TOP-LEVEL files only. AtelierMesh's CUE4Parse provider scans
    the directory it's given recursively, so pointing it at PAKS directly also picks up whatever
    lives in PAKS/~mods (or any other subfolder the "Copy to mods folder" setting points at) --
    installed mods then win pack-stacking and the 3D viewport shows modded content, unlike the file
    browser and the Blender export path, which both resolve assets through index.ensure_index()'s
    non-recursive `glob(PAKS + "/*.utoc")` and so only ever see vanilla containers. Mirroring PAKS's
    top level with hardlinks (instant, no extra disk use, same-volume only) keeps the viewport in
    sync with everything else without needing to touch AtelierMesh itself. Falls back to the real
    PAKS dir (mods included) if hardlinking isn't possible, e.g. PAKS is on another volume."""
    try:
        wanted = {f: os.path.join(PAKS, f) for f in os.listdir(PAKS)
                  if os.path.isfile(os.path.join(PAKS, f))}
    except OSError:
        return PAKS
    os.makedirs(_VANILLA_PAKS, exist_ok=True)
    try:
        have = set(os.listdir(_VANILLA_PAKS))
    except OSError:
        return PAKS
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
        except OSError:
            return PAKS  # cross-volume, no permission, etc. -- better vanilla-or-mods than a broken mirror
    return _VANILLA_PAKS

def atelier_mesh(asset, out_dir):
    """Decode an MR mesh (content-mount path, no ext) to glTF (.glb) under out_dir."""
    return hostos.run_exe(
        [ATELIER_MESH, "--paks", os.path.abspath(_vanilla_paks_dir()), "--aes", _aes_hex(),
         "--usmap", USMAP, "--asset", asset, "--out", os.path.abspath(out_dir)],
        capture_output=True, text=True, cwd=ROOT)

# A UAssetTool call that is still running after this long is wedged, not slow: the measured
# worst case is ~15s for a single-asset extract fallback. Overridable for very large batches.
UAT_TIMEOUT = 300
try:
    UAT_TIMEOUT = max(10, int(os.environ.get("ATELIER_UAT_TIMEOUT", UAT_TIMEOUT)))
except ValueError:
    pass


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

    Bounded: a hung tool used to block the calling request forever with nothing logged."""
    secs = UAT_TIMEOUT if timeout is None else timeout
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
    _out_q = queue.Queue()
    _proc = hostos.popen_exe([UAT], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, cwd=ROOT, text=True, encoding="utf-8")
    proc, q = _proc, _out_q

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
    global _proc, _out_q
    with _lock:
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
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _kill_worker()
                print(f"  [warn] uat_json timed out after {secs}s; worker killed",
                      file=sys.stderr, flush=True)
                return {"success": False,
                        "message": f"UAssetTool did not respond within {secs}s"}
            try:
                line = q.get(timeout=remaining)
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


@atexit.register
def _shutdown():
    if _proc and _proc.poll() is None:
        try: _proc.terminate()
        except Exception: pass
