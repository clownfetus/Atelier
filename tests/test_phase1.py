"""Phase 1 — diagnostics. Run: .venv/bin/python tests/test_phase1.py

No game install required: synthetic containers (fake_paks.py) reproduce the two real failure
shapes seen in user logs, and the subprocess layer is stubbed.
"""
import os, sys, json, time, shutil, tempfile, threading, subprocess, traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fake_paks

PASS, FAIL = [], []


def check(name, fn):
    try:
        fn()
        PASS.append(name); print(f"  PASS  {name}")
    except Exception as e:
        FAIL.append((name, e)); print(f"  FAIL  {name}\n        {type(e).__name__}: {e}")
        if os.environ.get("VERBOSE"):
            traceback.print_exc()


def section(t):
    print(f"\n\033[1m{t}\033[0m" if sys.stdout.isatty() else f"\n{t}")


# ══ #4 — index records failures, surfaces them, and never caches a bad build ══
section("#4  index warnings")

import atelier.index as IDX


def _fresh_index(tmp, **kinds):
    fake_paks.make_dir(tmp, **kinds)
    IDX.PAKS = tmp
    IDX._INDEX = None
    IDX._FAILED = []
    IDX._CACHE_FILE = os.path.join(tmp, "cli_index_cache.json")
    return IDX.ensure_index()


def t_clean_build_caches():
    tmp = tempfile.mkdtemp()
    _fresh_index(tmp, clean=2)
    assert IDX.index_warnings() == [], IDX.index_warnings()
    assert os.path.exists(IDX._CACHE_FILE), "a clean build must still be cached"
    shutil.rmtree(tmp)


def t_failures_are_recorded():
    tmp = tempfile.mkdtemp()
    _fresh_index(tmp, clean=1, overflow=1, utf16=1)
    w = IDX.index_warnings()
    names = sorted(f["container"] for f in w)
    assert len(w) == 2, f"expected 2 failures, got {w}"
    assert names == ["pakchunkOverflow0-Windows.utoc", "pakchunkUtf160-Windows.utoc"], names
    assert all(f["error"] for f in w), "each failure must carry its error text"
    shutil.rmtree(tmp)


def t_bad_build_is_not_cached():
    """The regression that made 'just reinstall it' the only cure."""
    tmp = tempfile.mkdtemp()
    _fresh_index(tmp, clean=1, utf16=1)
    assert not os.path.exists(IDX._CACHE_FILE), \
        "a build with failed containers must NOT be persisted"
    shutil.rmtree(tmp)


def t_recovery_without_wiping_cache():
    """Break a container, index, then repair it: the next build must see the repair.

    Previously the poisoned index was cached and _utoc_key ignored everything but the .utoc
    stats, so the broken result was served back until _cache was deleted by hand.
    """
    tmp = tempfile.mkdtemp()
    _fresh_index(tmp, clean=1, utf16=1)
    assert len(IDX.index_warnings()) == 1
    # "fix the key": the container now reads cleanly
    fake_paks.write(os.path.join(tmp, "pakchunkUtf160-Windows.utoc"), fake_paks.clean_blob())
    IDX._INDEX = None                      # what routes.py does after Setup is saved
    IDX.ensure_index()
    assert IDX.index_warnings() == [], "repaired container must clear the warning"
    assert os.path.exists(IDX._CACHE_FILE), "a now-clean build should cache"
    shutil.rmtree(tmp)


def t_unindexed_container_is_not_a_failure():
    """global.utoc carries NO directory index (Indexed unset, dir_index_size 0) and ships with
    every install — it holds the shader library and name map, not assets.

    Found by running Phase 2's verification against a real game install: treating it as a failed
    container put a false "usually a wrong or stale AES key" warning on screen at every launch,
    and, because a warned build is deliberately never cached, meant the 546k-asset index was
    rebuilt from scratch every time (19s instead of 1s).
    """
    tmp = tempfile.mkdtemp()
    fake_paks.make_dir(tmp, clean=1)
    fake_paks.write(os.path.join(tmp, "global.utoc"), b"")      # no directory index at all
    _fresh_index(tmp)
    assert IDX.index_warnings() == [], \
        f"a container with no directory index is normal, not a failure: {IDX.index_warnings()}"
    assert os.path.exists(IDX._CACHE_FILE), "and the build must still be cached"
    shutil.rmtree(tmp)


def t_warnings_survive_a_cache_hit():
    tmp = tempfile.mkdtemp()
    _fresh_index(tmp, clean=2)
    IDX._INDEX = None; IDX._FAILED = [{"container": "x", "error": "y"}]
    IDX.ensure_index()                      # served from the cache file
    assert IDX.index_warnings() == [], "a cached clean build must report no warnings"
    shutil.rmtree(tmp)


for n, f in [("clean build is cached", t_clean_build_caches),
             ("failures recorded with container + error", t_failures_are_recorded),
             ("build with failures is NOT cached", t_bad_build_is_not_cached),
             ("repairing a container recovers without wiping _cache", t_recovery_without_wiping_cache),
             ("cache hit reports warnings from the cache", t_warnings_survive_a_cache_hit),
             ("a container with no directory index is not a failure", t_unindexed_container_is_not_a_failure)]:
    check(n, f)


# ══ #7 — the thumbnail path survives a bad container ═════════════════════════
section("#7  pak_thumb guard")

import atelier.handlers.pak_thumb as PT


def t_get_toc_returns_none():
    tmp = tempfile.mkdtemp(); fake_paks.make_dir(tmp, clean=0, utf16=1)
    PT.PAKS = tmp
    with PT._toc_lock: PT._toc_cache.clear()
    assert PT._get_toc("pakchunkUtf160-Windows.utoc") is None
    shutil.rmtree(tmp)


def t_get_toc_does_not_kill_thread():
    """The actual bug: an unhandled exception killed the warmup thread silently."""
    tmp = tempfile.mkdtemp(); fake_paks.make_dir(tmp, clean=0, overflow=1)
    PT.PAKS = tmp
    with PT._toc_lock: PT._toc_cache.clear()
    survived = []
    def body():
        PT._get_toc("pakchunkOverflow0-Windows.utoc")
        survived.append(True)            # unreachable before the fix
    th = threading.Thread(target=body); th.start(); th.join(10)
    assert survived == [True], "thread died inside _get_toc"
    shutil.rmtree(tmp)


def t_failure_is_cached_not_retried():
    tmp = tempfile.mkdtemp(); fake_paks.make_dir(tmp, clean=0, utf16=1)
    PT.PAKS = tmp
    with PT._toc_lock: PT._toc_cache.clear()
    PT._get_toc("pakchunkUtf160-Windows.utoc")
    assert PT._toc_cache.get("pakchunkUtf160-Windows.utoc") is None
    assert "pakchunkUtf160-Windows.utoc" in PT._toc_cache, "the miss must be memoised"
    shutil.rmtree(tmp)


def t_clean_container_still_works():
    tmp = tempfile.mkdtemp(); fake_paks.make_dir(tmp, clean=1)
    PT.PAKS = tmp
    with PT._toc_lock: PT._toc_cache.clear()
    entry = PT._get_toc("pakchunkClean0-Windows.utoc")
    assert entry is not None and entry[0]._dir == {}, entry
    shutil.rmtree(tmp)


for n, f in [("bad container returns None", t_get_toc_returns_none),
             ("bad container does not kill the thread", t_get_toc_does_not_kill_thread),
             ("the miss is memoised", t_failure_is_cached_not_retried),
             ("clean container still parses", t_clean_container_still_works)]:
    check(n, f)


# ══ #5 — three distinct reasons, not one sentence ════════════════════════════
section("#5  missing_reason")

import atelier.handlers.texture as TX


class _Ctx:
    """Swap extract_info / index state for the duration of a test."""
    def __init__(self, found=None, failed=()):
        self.found, self.failed = found, list(failed)
    def __enter__(self):
        self._ei, self._ew, self._idx = TX.extract_info, IDX.index_warnings, IDX.ensure_index
        TX.extract_info = lambda gr: (self.found or (None, None, None))
        IDX.index_warnings = lambda: self.failed
        IDX.ensure_index = lambda: []
        return self
    def __exit__(self, *a):
        TX.extract_info, IDX.index_warnings, IDX.ensure_index = self._ei, self._ew, self._idx


def t_not_indexed():
    with _Ctx():
        m = TX.missing_reason("Characters/1020/X/Materials/MI_X", "material")
    assert "not in any indexed pak container" in m, m
    assert "AES" not in m, "must not blame the key when nothing failed"


def t_container_failed():
    with _Ctx(failed=[{"container": "pakchunkHQ-Windows.utoc", "error": "utf-16"},
                      {"container": "pakchunkUI-Windows.utoc", "error": "utf-16"}]):
        m = TX.missing_reason("Characters/1020/X", "material")
    assert "2 pak container(s) failed" in m, m
    assert "pakchunkHQ-Windows.utoc" in m and "AES key" in m, m


def t_extract_failed():
    with _Ctx(found=("/tmp/whatever", "pakchunkCharacter-Windows.utoc", "Marvel/Content/Marvel/")):
        m = TX.missing_reason("Characters/1020/X", "material")
    assert "could not be extracted" in m and "pakchunkCharacter-Windows.utoc" in m, m
    assert "_logs" in m, "should point at the log"


def t_three_states_are_distinct():
    with _Ctx() as _:                       a = TX.missing_reason("A", "material")
    with _Ctx(failed=[{"container": "c", "error": "e"}]): b = TX.missing_reason("A", "material")
    with _Ctx(found=("/x", "c", "p")):      c = TX.missing_reason("A", "material")
    assert len({a, b, c}) == 3, "the three states must not collapse to one message"


def t_truncated_failure_list():
    with _Ctx(failed=[{"container": f"c{i}.utoc", "error": "e"} for i in range(5)]):
        m = TX.missing_reason("A", "material")
    assert "(+2 more)" in m, m


def t_check_index_false_makes_no_index_claim():
    """Levels are .umap and index.py only records .uasset — so never claim 'not indexed'."""
    with _Ctx():
        m = TX.missing_reason("Maps/Foo/Bar.umap", "level asset", check_index=False)
    assert "indexed pak container" not in m, m
    assert "read cleanly" in m, m


def t_kind_appears():
    for kind in ("material", "curve", "StringTable", "VFX asset", "level asset"):
        with _Ctx():
            assert TX.missing_reason("A", kind).startswith(kind), kind


for n, f in [("not indexed", t_not_indexed),
             ("container failed -> names it and blames the key", t_container_failed),
             ("in index but extraction failed", t_extract_failed),
             ("all three messages differ", t_three_states_are_distinct),
             ("long failure list is truncated", t_truncated_failure_list),
             ("check_index=False makes no index claim", t_check_index_false_makes_no_index_claim),
             ("the asset kind leads the message", t_kind_appears)]:
    check(n, f)


# ══ #6 — nothing blocks forever, stderr is not swallowed ═════════════════════
section("#6  UAT timeouts")

import atelier.tools as T
from atelier import hostos


def t_uat_timeout_returns_result():
    real = hostos.run_exe
    def boom(args, **kw):
        assert "timeout" in kw, "uat() must pass a timeout through"
        raise subprocess.TimeoutExpired(args, kw["timeout"])
    hostos.run_exe = boom
    try:
        r = T.uat(["extract_iostore_legacy", "x", "y"], timeout=5)
        assert r.returncode == -9, r.returncode
        assert "timed out" in r.stderr, r.stderr
    finally:
        hostos.run_exe = real


def t_uat_passes_default_timeout():
    real, seen = hostos.run_exe, {}
    def cap(args, **kw):
        seen.update(kw)
        class R: returncode, stdout, stderr = 0, "", ""
        return R()
    hostos.run_exe = cap
    try:
        T.uat(["x"])
        assert seen.get("timeout") == T.UAT_TIMEOUT, seen.get("timeout")
    finally:
        hostos.run_exe = real


class _HangingProc:
    """A worker that accepts a request and then never answers."""
    def __init__(self):
        self.killed = False
        r, w = os.pipe()                       # nothing is ever written to r
        self.stdout = os.fdopen(r, "r")
        self._w = w
        er, ew = os.pipe(); os.close(ew)
        self.stderr = os.fdopen(er, "r")
        self.stdin = open(os.devnull, "w")
    def poll(self):  return None if not self.killed else -9
    def kill(self):  self.killed = True; os.close(self._w)


def t_uat_json_times_out_and_kills_worker():
    """The export hang: an unbounded readline() under a global lock."""
    real = hostos.popen_exe
    proc = _HangingProc()
    hostos.popen_exe = lambda *a, **kw: proc
    T._proc = None
    try:
        t0 = time.monotonic()
        d = T.uat_json({"command": "noop"}, timeout=2)
        dt = time.monotonic() - t0
        assert d["success"] is False, d
        assert "did not respond" in d["message"], d
        assert 1.5 < dt < 6, f"returned after {dt:.1f}s — should be ~2s"
        assert proc.killed, "a wedged worker must be killed, not reused"
        assert T._proc is None, "the dead worker must not stay installed"
    finally:
        hostos.popen_exe = real; T._proc = None


def t_uat_json_wait_is_bounded_for_other_callers():
    """A wedged worker must not block other callers FOREVER.

    It still serialises them: _lock is held across the wait, because releasing it would let two
    requests interleave on one pipe and desync the replies. So the guarantee here is bounded, not
    concurrent — a second caller waits at most one timeout for the first, then its own. True
    concurrency needs request IDs or a worker pool; out of scope for Phase 1.
    """
    real = hostos.popen_exe
    hostos.popen_exe = lambda *a, **kw: _HangingProc()
    T._proc = None
    try:
        done = []
        threading.Thread(target=lambda: (T.uat_json({"c": 1}, timeout=2), done.append(1)),
                         daemon=True).start()
        time.sleep(0.3)
        t0 = time.monotonic()
        T.uat_json({"c": 2}, timeout=2)
        total = time.monotonic() - t0
        # bounded by the first caller's remaining timeout plus its own — never unbounded
        assert total < 2 * 2 + 3, f"second caller waited {total:.1f}s — should be bounded"
    finally:
        hostos.popen_exe = real; T._proc = None


def t_uat_json_reads_a_reply():
    real = hostos.popen_exe
    class _Answering:
        def __init__(self):
            r, w = os.pipe()
            os.write(w, b"starting up\n")           # non-JSON noise first, as the real tool does
            os.write(w, json.dumps({"success": True, "data": 42}).encode() + b"\n")
            os.close(w)
            self.stdout = os.fdopen(r, "r")
            er, ew = os.pipe(); os.close(ew); self.stderr = os.fdopen(er, "r")
            self.stdin = open(os.devnull, "w")
        def poll(self): return None
        def kill(self): pass
    hostos.popen_exe = lambda *a, **kw: _Answering()
    T._proc = None
    try:
        d = T.uat_json({"c": 1}, timeout=5)
        assert d == {"success": True, "data": 42}, d
    finally:
        hostos.popen_exe = real; T._proc = None


def t_worker_stderr_is_not_devnull():
    src = open(os.path.join(os.path.dirname(__file__), "..", "atelier", "tools.py")).read()
    assert "stderr=subprocess.DEVNULL" not in src, "worker stderr must not be discarded"
    assert "stderr=subprocess.PIPE" in src and "[uat]" in src, "stderr must be pumped and logged"


for n, f in [("uat() converts a timeout into a result", t_uat_timeout_returns_result),
             ("uat() passes the default timeout", t_uat_passes_default_timeout),
             ("uat_json() times out and kills the worker", t_uat_json_times_out_and_kills_worker),
             ("a wedged worker bounds other callers", t_uat_json_wait_is_bounded_for_other_callers),
             ("a normal reply still works", t_uat_json_reads_a_reply),
             ("worker stderr is logged, not discarded", t_worker_stderr_is_not_devnull)]:
    check(n, f)


# ══ #9 — Explorer reveal reports failure ═════════════════════════════════════
section("#9  open_explorer")

import bottle
import atelier.web.routes as R


def _call(qs, reveal=None):
    bottle.request.bind({"QUERY_STRING": qs, "REQUEST_METHOD": "GET",
                         "PATH_INFO": "/api/open_explorer"})
    bottle.response.bind()
    real = R.hostos.reveal
    R.hostos.reveal = reveal or (lambda *a, **k: None)
    try:
        return json.loads(R.api_open_explorer())
    finally:
        R.hostos.reveal = real


def t_missing_path_reports():
    d = _call("path=/definitely/not/here/nope.png")
    assert d["ok"] is False and "import or export" in d["error"], d


def t_no_path_reports():
    d = _call("")
    assert d["ok"] is False and "No path" in d["error"], d


def t_existing_path_ok():
    f = tempfile.NamedTemporaryFile(suffix=".png", delete=False); f.close()
    try:
        d = _call("path=" + f.name)
        assert d["ok"] is True and d["path"] == f.name, d
    finally:
        os.unlink(f.name)


def t_reveal_failure_is_reported():
    f = tempfile.NamedTemporaryFile(suffix=".png", delete=False); f.close()
    try:
        def boom(*a, **k): raise RuntimeError("no xdg-open available")
        d = _call("path=" + f.name, reveal=boom)
        assert d["ok"] is False and "xdg-open" in d["error"], d
    finally:
        os.unlink(f.name)


def t_directory_fallback_still_selects_parent():
    tmp = tempfile.mkdtemp()
    seen = {}
    def rec(p, select=True): seen["p"], seen["s"] = p, select
    try:
        d = _call("path=" + os.path.join(tmp, "not-yet.png"), reveal=rec)
        assert d["ok"] is True and seen["p"] == tmp and seen["s"] is False, (d, seen)
    finally:
        shutil.rmtree(tmp)


for n, f in [("missing file is reported, not silent", t_missing_path_reports),
             ("empty path is reported", t_no_path_reports),
             ("existing file succeeds", t_existing_path_ok),
             ("a reveal error is reported", t_reveal_failure_is_reported),
             ("falls back to the parent folder", t_directory_fallback_still_selects_parent)]:
    check(n, f)


print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
for n, e in FAIL:
    print(f"  - {n}: {type(e).__name__}: {e}")
sys.exit(1 if FAIL else 0)
