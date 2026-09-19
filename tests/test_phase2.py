"""Phase 2 — the index / key cluster. Run: .venv/bin/python tests/test_phase2.py

No game install required. The wrong-key failure is reproduced with containers that are ACTUALLY
AES-encrypted (fake_paks.write_encrypted), because that is the only way to get the real shape of
it: AES-ECB with the wrong key does not fail, it returns garbage, and only the parse downstream
notices.

The three repros from PHASES.md, in order:
  1. wrong key -> empty tree -> correct key -> tree repopulates, with NO cache wipe
  2. a paks folder under a path containing [Steam] is found, and every check agrees it is
  3. a mod named "[WIP] Test" can still be locked, repatched and globbed for
"""
import os, sys, json, shutil, tempfile, traceback, contextlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fake_paks

PASS, FAIL = [], []

GOOD_KEY = "ab" * 32
BAD_KEY  = "cd" * 32


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


import io_lib
import atelier.config as CFG
import atelier.index as IDX


@contextlib.contextmanager
def sandbox():
    """Redirect every piece of global state these tests touch into a temp tree.

    config's paths are module-level and point at the real install: without this, set_aes_key()
    would rewrite the developer's own Tools/AES_KEY.txt and mr_config.json.
    """
    tmp   = tempfile.mkdtemp()
    tools = os.path.join(tmp, "Tools"); os.makedirs(tools)
    paks  = os.path.join(tmp, "Paks");  os.makedirs(paks)
    saved = (CFG.CONFIG_FILE, CFG.TOOLS, CFG.AES_KEY_FILE, CFG.PAKS,
             IDX.PAKS, IDX._CACHE_FILE, IDX._INDEX, IDX._FAILED, io_lib.AES_KEY)
    CFG.CONFIG_FILE  = os.path.join(tmp, "mr_config.json")
    CFG.TOOLS        = tools
    CFG.AES_KEY_FILE = os.path.join(tools, "AES_KEY.txt")
    CFG.PAKS = IDX.PAKS = paks
    IDX._CACHE_FILE  = os.path.join(tmp, "cli_index_cache.json")
    IDX._INDEX, IDX._FAILED = None, []
    try:
        yield type("Sandbox", (), {"root": tmp, "tools": tools, "paks": paks})
    finally:
        (CFG.CONFIG_FILE, CFG.TOOLS, CFG.AES_KEY_FILE, CFG.PAKS,
         IDX.PAKS, IDX._CACHE_FILE, IDX._INDEX, IDX._FAILED, io_lib.AES_KEY) = saved
        shutil.rmtree(tmp, ignore_errors=True)


def use_key(k):
    """Set the key the way config.set_aes_key does, minus the config write."""
    io_lib.AES_KEY = bytes.fromhex(k)


def rebuild():
    """What the app does when Setup is saved: drop the in-memory index and browse again."""
    IDX._INDEX = None
    return IDX.ensure_index()


# ══ #1 — the AES key belongs in the index cache key ══════════════════════════
section("#1  index cache key")


def t_key_is_part_of_the_cache_key():
    with sandbox() as sb:
        fake_paks.write_encrypted(os.path.join(sb.paks, "pakchunkEnc-Windows.utoc"), GOOD_KEY)
        use_key(GOOD_KEY); a = IDX._utoc_key()
        use_key(BAD_KEY);  b = IDX._utoc_key()
        assert a != b, "two different AES keys produced the same cache key"
        assert GOOD_KEY not in a and BAD_KEY not in b, "the key itself must not land in the cache"


def t_wrong_key_then_right_key_recovers():
    """THE repro. Wrong key -> empty tree. Correct key -> tree, without touching _cache.

    Before Phase 2 the empty index was written to disk under a cache key made only of the .utoc
    stats, so correcting the key in Setup forced a rebuild that was immediately satisfied from
    that same poisoned cache. Only a reinstall (which deletes _cache wholesale) appeared to help.
    """
    with sandbox() as sb:
        fake_paks.write_encrypted(os.path.join(sb.paks, "pakchunkEnc-Windows.utoc"), GOOD_KEY)

        use_key(BAD_KEY)
        assert rebuild() == [], "a wrong key must yield an empty index"
        assert len(IDX.index_warnings()) == 1, IDX.index_warnings()

        use_key(GOOD_KEY)
        entries = rebuild()
        assert [e[0] for e in entries] == ["Characters/T_Test.uasset"], entries
        assert IDX.index_warnings() == [], IDX.index_warnings()
        assert os.path.exists(IDX._CACHE_FILE), "the now-clean build should cache"


def t_good_index_is_not_served_to_a_wrong_key():
    """The same guard in the other direction: a cache built under key A must not be handed to B.

    Without it, a rotated key would show a full, stale tree whose assets no longer extract —
    the same bug wearing the other face.
    """
    with sandbox() as sb:
        fake_paks.write_encrypted(os.path.join(sb.paks, "pakchunkEnc-Windows.utoc"), GOOD_KEY)
        use_key(GOOD_KEY)
        assert len(rebuild()) == 1
        cached = json.load(open(IDX._CACHE_FILE, encoding="utf-8"))

        use_key(BAD_KEY)
        assert rebuild() == [], "the cached good index was served back under a different key"
        assert IDX._utoc_key() != cached["key"]


def t_cache_hit_still_works_for_an_unchanged_key():
    """The fix must not cost a re-index on every launch — same key, same paks, still a cache hit."""
    with sandbox() as sb:
        fake_paks.write_encrypted(os.path.join(sb.paks, "pakchunkEnc-Windows.utoc"), GOOD_KEY)
        use_key(GOOD_KEY)
        rebuild()
        # Plant a sentinel in the cache file. If the next build reads it back, the disk cache was
        # used; if it re-indexes, the sentinel is gone and the real entry is there instead.
        c = json.load(open(IDX._CACHE_FILE, encoding="utf-8"))
        c["entries"] = [["Sentinel/FromCache.uasset", "cached.utoc", "Marvel/Content/Marvel/"]]
        json.dump(c, open(IDX._CACHE_FILE, "w"))
        assert [e[0] for e in rebuild()] == ["Sentinel/FromCache.uasset"], \
            "an unchanged key + unchanged paks must still hit the disk cache"


def t_failure_records_the_container_identity():
    """PHASES.md Phase 5 note: record WHICH container failed and which key it wants, now, so the
    multi-key work is reading a log instead of re-deriving the problem."""
    with sandbox() as sb:
        guid = b"\x42" * 16
        fake_paks.write_encrypted(os.path.join(sb.paks, "pakchunkEnc-Windows.utoc"), GOOD_KEY,
                                  enc_guid=guid)
        use_key(BAD_KEY)
        rebuild()
        w = IDX.index_warnings()
        assert len(w) == 1, w
        assert w[0]["container"] == "pakchunkEnc-Windows.utoc", w
        assert w[0]["encrypted"] is True, w
        assert w[0]["enc_guid"] == guid.hex(), w


for n, f in [("the AES key is part of the cache key (and not stored in it)", t_key_is_part_of_the_cache_key),
             ("wrong key -> right key recovers with NO cache wipe", t_wrong_key_then_right_key_recovers),
             ("an index built under another key is never served back", t_good_index_is_not_served_to_a_wrong_key),
             ("an unchanged key still gets a cache hit", t_cache_hit_still_works_for_an_unchanged_key),
             ("a failed container records its identity and enc_guid", t_failure_records_the_container_identity)]:
    check(n, f)


# ══ #8 — one writer for AES_KEY.txt ══════════════════════════════════════════
section("#8  single AES key writer")


def t_set_aes_key_updates_everything_at_once():
    with sandbox():
        io_lib.AES_KEY = b""
        assert CFG.set_aes_key("0x" + GOOD_KEY) is True
        assert open(CFG.AES_KEY_FILE).read().strip() == GOOD_KEY, "file (UAssetTool reads this)"
        assert io_lib.AES_KEY == bytes.fromhex(GOOD_KEY), "io_lib (our own pak reader)"
        assert CFG._load_config()["aes_key"] == GOOD_KEY, "config (survives a restart)"
        assert CFG.get_aes_key() == GOOD_KEY
        assert CFG.set_aes_key(GOOD_KEY) is False, "re-setting the same key is not a change"


def t_set_aes_key_rejects_a_typo():
    with sandbox():
        for bad in ("", "0x123", "z" * 64, GOOD_KEY[:-1]):
            try:
                CFG.set_aes_key(bad)
            except ValueError:
                continue
            raise AssertionError(f"accepted {bad!r}")
        assert not os.path.exists(CFG.AES_KEY_FILE), "a rejected key must not be written"


def t_set_aes_key_invalidates_the_index():
    with sandbox() as sb:
        fake_paks.write_encrypted(os.path.join(sb.paks, "pakchunkEnc-Windows.utoc"), GOOD_KEY)
        use_key(BAD_KEY)
        assert rebuild() == []
        CFG.set_aes_key(GOOD_KEY)
        assert IDX._INDEX is None, "changing the key must drop the in-memory index"
        assert len(IDX.ensure_index()) == 1, "and the next browse must see the repaired tree"


def t_fetched_key_is_not_clobbered_on_the_next_launch():
    """The startup race: a stale saved key used to overwrite a freshly fetched one every launch.

    _auto_fetch_aes now writes through set_aes_key, which persists to config — so the rotation
    is what the NEXT startup reads back.
    """
    import urllib.request
    with sandbox():
        CFG.set_aes_key(BAD_KEY)                       # the stale saved key
        real = urllib.request.urlopen

        class FakeResp:
            def read(self): return json.dumps({"mainKey": "0x" + GOOD_KEY}).encode()
            def __enter__(self): return self
            def __exit__(self, *a): return False

        urllib.request.urlopen = lambda *a, **k: FakeResp()
        try:
            CFG._auto_fetch_aes()
        finally:
            urllib.request.urlopen = real
        assert open(CFG.AES_KEY_FILE).read().strip() == GOOD_KEY, "file must hold the fetched key"
        assert CFG._load_config()["aes_key"] == GOOD_KEY, \
            "the fetched key must be persisted, or the old one wins on the next launch"
        assert io_lib.AES_KEY == bytes.fromhex(GOOD_KEY), "io_lib must see it without a restart"


def t_config_writes_do_not_drop_each_other():
    """_save_config is the one read-modify-write path, so a background fetch racing a Settings
    save can no longer make one of the two vanish."""
    import threading
    with sandbox():
        CFG._save_config(paks="/p", aes_key=BAD_KEY)
        done = threading.Barrier(3)

        def w(k, v):
            done.wait(); CFG._save_config(**{k: v})

        ts = [threading.Thread(target=w, args=a) for a in (("mods_folder", "/m"), ("usmap", "/u"))]
        for t in ts: t.start()
        done.wait()
        for t in ts: t.join()
        cfg = CFG._load_config()
        assert cfg["paks"] == "/p" and cfg["mods_folder"] == "/m" and cfg["usmap"] == "/u", cfg


def t_setup_save_fixes_a_poisoned_index():
    """End to end, through the actual Setup handler: the sentence the whole phase is judged on.

    "wrong key -> browse tree empty -> enter the correct key -> still empty" was true until now,
    and only a reinstall cured it. This drives /api/save_paks exactly as the frontend does.
    """
    import atelier.web.routes as R
    import atelier.handlers.pak_thumb as PT
    fake_paks.settle_background_index()   # the import starts a real-index warmup thread
    with sandbox() as sb:
        root = os.path.join(sb.root, "MarvelRivals")
        paks = os.path.join(root, "MarvelGame", "Marvel", "Content", "Paks"); os.makedirs(paks)
        fake_paks.write_encrypted(os.path.join(paks, "pakchunkEnc-Windows.utoc"), GOOD_KEY)

        saved_req, saved_resp, saved_warm = R.request, R.response, PT.start_warmup
        saved_paks = (R.PAKS, PT.PAKS)
        PT.start_warmup = lambda *a, **k: None

        def save(key):
            R.request  = type("R", (), {"json": {"path": root, "aes_key": key}})()
            R.response = type("R", (), {"content_type": ""})()
            return json.loads(R.api_save_paks())

        try:
            assert save(BAD_KEY)["ok"] is True
            assert IDX.ensure_index() == [], "precondition: the wrong key gives an empty tree"

            out = save(GOOD_KEY)
            assert out["ok"] is True, out
            entries = IDX.ensure_index()
            assert [e[0] for e in entries] == ["Characters/T_Test.uasset"], \
                "entering the correct key in Setup must repopulate the tree, with no reinstall"

            bad = save("not-a-key")
            assert bad["ok"] is False and "hexadecimal" in bad["error"], bad
        finally:
            R.request, R.response, PT.start_warmup = saved_req, saved_resp, saved_warm
            R.PAKS, PT.PAKS = saved_paks


for n, f in [("set_aes_key updates file + io_lib + config together", t_set_aes_key_updates_everything_at_once),
             ("a malformed key is rejected, not written", t_set_aes_key_rejects_a_typo),
             ("changing the key invalidates the index", t_set_aes_key_invalidates_the_index),
             ("a fetched key survives the next launch", t_fetched_key_is_not_clobbered_on_the_next_launch),
             ("concurrent config writes do not drop each other", t_config_writes_do_not_drop_each_other),
             ("saving the right key in Setup fixes a poisoned index", t_setup_save_fixes_a_poisoned_index)]:
    check(n, f)


# ══ #3 — square brackets are glob metacharacters ═════════════════════════════
section("#3  bracketed paths")

import glob as _glob


def t_dir_glob_finds_what_glob_cannot():
    tmp = tempfile.mkdtemp()
    try:
        d = os.path.join(tmp, "[Steam]", "Paks"); os.makedirs(d)
        open(os.path.join(d, "pakchunk0-Windows.utoc"), "wb").close()
        assert _glob.glob(d + "/*.utoc") == [], "precondition: plain glob is blind here"
        assert len(CFG.dir_glob(d, "*.utoc")) == 1, "dir_glob must see through the brackets"
    finally:
        shutil.rmtree(tmp)


def t_bracketed_paks_folder_is_found_and_indexed():
    """everikreal's report: "it says every path is valid in the settings" next to "no pak files"."""
    with sandbox() as sb:
        paks = os.path.join(sb.root, "[Steam]", "steamapps", "Paks"); os.makedirs(paks)
        fake_paks.write_encrypted(os.path.join(paks, "pakchunkEnc-Windows.utoc"), GOOD_KEY)
        CFG.PAKS = IDX.PAKS = paks
        use_key(GOOD_KEY)
        assert CFG.has_pak_files(paks) is True, "the prereq check must find the containers"
        assert len(rebuild()) == 1, "and the index must see them too"
        msgs = [m for _lvl, m in CFG._prereq_issues(need_tool=False)]
        assert not any("No pak files found" in m for m in msgs), msgs


def t_every_paks_check_gives_the_same_answer():
    """Settings' live validator, Settings' save handler and the prereq check used to be three
    different tests. They now share has_pak_files, so they cannot disagree again."""
    import atelier.web.routes as R
    from atelier.web.routes import _validate_and_build_paks
    with sandbox() as sb:
        root = os.path.join(sb.root, "[Games]", "MarvelRivals")
        paks = os.path.join(root, "MarvelGame", "Marvel", "Content", "Paks"); os.makedirs(paks)
        fake_paks.write_encrypted(os.path.join(paks, "pakchunkEnc-Windows.utoc"), GOOD_KEY)
        CFG.PAKS = paks
        got, err = _validate_and_build_paks(root)
        assert err is None, err
        assert os.path.normpath(got) == os.path.normpath(paks), got
        assert CFG.has_pak_files(got) is True
        # An empty folder must be rejected by BOTH, for the same reason.
        empty = os.path.join(sb.root, "[Games]", "Empty", "MarvelGame", "Marvel", "Content", "Paks")
        os.makedirs(empty)
        assert CFG.has_pak_files(empty) is False
        empty_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(empty))))
        assert _validate_and_build_paks(empty_root)[1] is not None

        # ...and the live validator (the green tick in Settings) must say the same thing.
        class Q:
            def __init__(self, p): self.p = p
            def get(self, _k, _d=""): return self.p
        saved_req, saved_resp = R.request, R.response
        R.request  = type("R", (), {"query": Q(root)})()
        R.response = type("R", (), {"content_type": ""})()
        try:
            assert json.loads(R.api_validate_paks())["status"] == "ok"
            R.request = type("R", (), {"query": Q(empty_root)})()
            assert json.loads(R.api_validate_paks())["status"] == "wrong_folder"
        finally:
            R.request, R.response = saved_req, saved_resp


def t_mod_stem_strips_brackets():
    from atelier.web.routes import _mod_stem
    assert _mod_stem("[WIP] Test") == "WIP Test"
    assert _mod_stem("Re[c]olor?.v2") == "Recolorv2"
    assert _mod_stem("") == "Mod"
    assert _mod_stem("[]") == "Mod", "a name that is only metacharacters still needs a stem"


def t_bracketed_mod_folder_still_locks():
    """modlock globbed the mod folder, so a bracketed mod name reported itself as unlocked."""
    from atelier.handlers import modlock
    tmp = tempfile.mkdtemp()
    try:
        d = os.path.join(tmp, "[WIP] Test"); os.makedirs(d)
        with open(os.path.join(d, "mod_9999999_P.ucas"), "wb") as f:
            f.write(b"\x00" * 64 + modlock.TAG + b"terces" + modlock.TAG + b"\x00" * 64)
        assert modlock.lock_code(d) == "terces", modlock.lock_code(d)
        assert modlock.is_locked(d) is True
    finally:
        shutil.rmtree(tmp)


def t_bracketed_output_dir_is_scanned():
    """texture.cmd_export's fallback scan for the packed container."""
    tmp = tempfile.mkdtemp()
    try:
        out = os.path.join(tmp, "[exported]"); os.makedirs(out)
        open(os.path.join(out, "Mod_9999999_P.utoc"), "wb").close()
        assert len(CFG.dir_glob(out, "*_P.utoc")) == 1
    finally:
        shutil.rmtree(tmp)


def t_recursive_dir_glob_survives_brackets():
    """repatch walks the unpack tree with ** — the escape must not break recursion."""
    tmp = tempfile.mkdtemp()
    try:
        deep = os.path.join(tmp, "[WIP] Test", "unpacked", "Marvel", "Content")
        os.makedirs(deep)
        open(os.path.join(deep, "T_Test.uasset"), "wb").close()
        hits = CFG.dir_glob(os.path.join(tmp, "[WIP] Test"), "**/*.uasset", recursive=True)
        assert len(hits) == 1, hits
    finally:
        shutil.rmtree(tmp)


for n, f in [("dir_glob sees through [brackets]", t_dir_glob_finds_what_glob_cannot),
             ("a paks folder under [Steam] is found AND indexed", t_bracketed_paks_folder_is_found_and_indexed),
             ("Settings and the prereq check agree", t_every_paks_check_gives_the_same_answer),
             ("_mod_stem strips [ and ]", t_mod_stem_strips_brackets),
             ("a bracketed mod folder still locks", t_bracketed_mod_folder_still_locks),
             ("a bracketed output folder is scanned", t_bracketed_output_dir_is_scanned),
             ("recursive dir_glob survives brackets", t_recursive_dir_glob_survives_brackets)]:
    check(n, f)


print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
for n, e in FAIL:
    print(f"  - {n}: {type(e).__name__}: {e}")
sys.exit(1 if FAIL else 0)
