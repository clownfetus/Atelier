"""Pak override order — TRIAGE #35. Run: .venv/bin/python tests/test_patch_override.py

The bug these guard against, in the words it was reported in: "my materials broke after the
update". On this install the patch container overrides 23,753 assets, 18,550 of them materials, so
almost every reported material is one the patch has taken over from a base chunk.

It was NOT a second AES key (the hypothesis in TRIAGE #2): every container here reports
enc_guid=0, the patch's directory index decrypts with the main key, and a patched material's chunk
reads in pure Python. What actually goes wrong is resolution — WHICH on-disk copy the work cache
hands back once a patch has moved an asset:

  * UAssetTool used to write patch assets under ent/Marvel/..., and now writes the mount path.
    A work cache filled either side of that change holds the same asset TWICE, one copy pre-patch.
  * extract_info predicted only one of those layouts, so for every patch asset the prediction
    missed, the asset cache was never recorded, and the loose fallback lookup chose between the
    two copies by os.walk order.

These tests work on the resolution layer with files staged on disk, which is the layer that picked
wrong. They do not re-verify that the extractor pulls the patch chunk rather than the base chunk —
that was checked directly against the real install (base 139,251 bytes vs patch 139,354 for
MI_1011001_1011_Body; the extractor returned the patch copy) and needs a game install to repeat.
"""
import os, sys, json, shutil, tempfile, traceback, contextlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

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


import atelier.config as CFG
import atelier.index as IDX
import atelier.asset_cache as AC
import atelier.handlers.texture as TX

GR      = "Characters/1011/1011001/Materials/1011/Lobby/MI_1011001_1011_Body"
VIRT    = GR + ".uasset"
PFX     = "Marvel/Content/Marvel/"
BASE_C  = "pakchunkCharacter-Windows.utoc"
PATCH_C = "Patch_-Windows_1.1.3870120_P.utoc"


@contextlib.contextmanager
def sandbox(container=PATCH_C):
    """A fake index naming ONE container for GR, and an empty work cache + asset cache."""
    tmp = tempfile.mkdtemp()
    work = os.path.join(tmp, "work"); os.makedirs(work)
    saved = (IDX._INDEX, TX.WORK_IMPORT_ROOT, CFG._CACHE, AC._PATH, dict(AC._data))
    IDX._INDEX = [(VIRT, container, PFX)]
    TX.WORK_IMPORT_ROOT = work
    AC._PATH = os.path.join(tmp, "extracted_assets.json")
    AC._data.clear(); AC._rebuild()
    try:
        yield type("S", (), {"root": tmp, "work": work})
    finally:
        IDX._INDEX, TX.WORK_IMPORT_ROOT, CFG._CACHE, AC._PATH, data = saved
        AC._data.clear(); AC._data.update(data); AC._rebuild()
        shutil.rmtree(tmp, ignore_errors=True)


def stage(work, prefix, body):
    """Write a fake extracted asset under <work>/<prefix>/<GR>, returning its stem."""
    stem = os.path.join(work, *(prefix.rstrip("/") + "/" + GR).split("/"))
    os.makedirs(os.path.dirname(stem), exist_ok=True)
    open(stem + ".uasset", "w").write(body)
    open(stem + ".uexp", "w").write(body)
    return stem


def read(stem):
    return open(stem + ".uasset").read()


# ══ both layouts are candidates ══════════════════════════════════════════════
section("layout")


def t_both_patch_layouts_are_predicted():
    """The current mount path AND the legacy ent/ one. Predicting a single layout is what left
    every patch asset uncached: the prediction simply never matched what was on disk."""
    with sandbox() as sb:
        cands = TX.work_candidates(GR)
        assert len(cands) == 2, cands
        assert cands[0].endswith(os.path.join("Marvel", "Content", "Marvel", *GR.split("/"))), cands[0]
        assert os.path.join("ent", "Marvel") in cands[1], cands[1]


def t_a_base_asset_has_one_layout():
    """Only patch assets ever went to ent/ — a base asset must not gain a phantom second candidate."""
    with sandbox(container=BASE_C) as sb:
        assert len(TX.work_candidates(GR)) == 1, TX.work_candidates(GR)


def t_extract_info_picks_the_copy_that_exists():
    """Whichever layout the tool used, the predicted path has to be the real one."""
    with sandbox() as sb:
        legacy = stage(sb.work, "ent/Marvel/", "patched-by-old-tool")
        cp, pak, pfx = TX.extract_info(GR)
        assert cp == legacy, (cp, legacy)
        assert pak == PATCH_C and pfx == PFX, (pak, pfx)


def t_with_nothing_on_disk_it_predicts_the_current_layout():
    """Callers use the prediction as 'where the extraction will land', so it must stay current."""
    with sandbox() as sb:
        cp, _pak, _pfx = TX.extract_info(GR)
        assert "ent" not in cp.split(os.sep), cp


for t in (t_both_patch_layouts_are_predicted, t_a_base_asset_has_one_layout,
          t_extract_info_picks_the_copy_that_exists,
          t_with_nothing_on_disk_it_predicts_the_current_layout):
    check(t.__doc__.splitlines()[0].strip(), t)


# ══ two copies of one asset ══════════════════════════════════════════════════
section("stale copies")


def t_two_copies_are_both_dropped():
    """THE repro. Extract before the patch, extract again after a tool update, and the same asset
    is on disk twice — one copy pre-patch. Nothing distinguishes them, so both must go."""
    with sandbox() as sb:
        stage(sb.work, "Marvel/Content/Marvel/", "PRE-patch base copy")
        stage(sb.work, "ent/Marvel/", "post-patch copy")
        assert TX._purge_ambiguous(GR) is True
        assert TX.work_candidates(GR) and not any(
            os.path.exists(c + ".uasset") for c in TX.work_candidates(GR)), "a stale copy survived"


def t_a_single_copy_is_left_alone():
    """Extraction overwrites one path anyway; deleting it would discard a usable asset if the
    extractor then fails — which on Linux it can, when Oodle is missing."""
    with sandbox() as sb:
        only = stage(sb.work, "Marvel/Content/Marvel/", "the only copy")
        assert TX._purge_ambiguous(GR) is False
        assert read(only) == "the only copy"


def t_ensure_work_base_does_not_serve_the_stale_copy():
    """End to end: with both copies present and no extractor available, it must refuse rather than
    hand back a coin-flip between pre- and post-patch bytes."""
    with sandbox() as sb:
        stage(sb.work, "Marvel/Content/Marvel/", "PRE-patch base copy")
        stage(sb.work, "ent/Marvel/", "post-patch copy")
        calls = []
        saved_uat, saved_retoc = TX.uat, TX.extract_via_retoc
        TX.uat = lambda args, **kw: (calls.append(args[0]),
                                     type("R", (), {"returncode": 1, "stdout": "", "stderr": ""}))[1]
        TX.extract_via_retoc = lambda grs: (calls.append("retoc"), {})[1]
        try:
            got = TX.ensure_work_base(GR)
        finally:
            TX.uat, TX.extract_via_retoc = saved_uat, saved_retoc
        assert got is None, f"served {got!r} — one of two copies, and no way to know which"
        assert calls, "it should at least have tried to re-extract"


for t in (t_two_copies_are_both_dropped, t_a_single_copy_is_left_alone,
          t_ensure_work_base_does_not_serve_the_stale_copy):
    check(t.__doc__.splitlines()[0].strip(), t)


# ══ the asset cache must notice a patch ══════════════════════════════════════
section("cache provenance")


def t_a_cache_entry_from_another_container_is_dropped():
    """The asset moved from a base chunk to a patch chunk — which is what a game patch IS. The
    bytes cached before it are pre-patch, and the recorded container is the only thing on disk
    that says so."""
    with sandbox() as sb:
        stale = stage(sb.work, "Marvel/Content/Marvel/", "PRE-patch base copy")
        AC.record(GR, stale, BASE_C, PFX)                      # cached before the patch
        calls = []
        saved_uat, saved_retoc = TX.uat, TX.extract_via_retoc
        TX.uat = lambda args, **kw: (calls.append(args[0]),
                                     type("R", (), {"returncode": 1, "stdout": "", "stderr": ""}))[1]
        TX.extract_via_retoc = lambda grs: (calls.append("retoc"), {})[1]
        try:
            TX.ensure_work_base(GR)
        finally:
            TX.uat, TX.extract_via_retoc = saved_uat, saved_retoc
        assert calls, "a cache hit from the wrong container must not short-circuit the extract"
        assert AC.get(GR) is None, "the stale entry should have been dropped"


def t_a_matching_cache_entry_is_still_a_fast_path():
    """The invalidation must not cost a re-extract on every call — same container, straight hit."""
    with sandbox() as sb:
        good = stage(sb.work, "Marvel/Content/Marvel/", "current copy")
        AC.record(GR, good, PATCH_C, PFX)
        saved_uat = TX.uat
        TX.uat = lambda *a, **k: (_ for _ in ()).throw(AssertionError("re-extracted on a valid hit"))
        try:
            assert TX.ensure_work_base(GR) == good
        finally:
            TX.uat = saved_uat


def t_a_legacy_entry_without_provenance_still_works():
    """Entries written before `pak` was recorded have nothing to compare; they must keep working
    rather than force a re-extract of every asset in an existing project."""
    with sandbox() as sb:
        good = stage(sb.work, "Marvel/Content/Marvel/", "current copy")
        AC.record(GR, good, "", "")
        saved_uat = TX.uat
        TX.uat = lambda *a, **k: (_ for _ in ()).throw(AssertionError("re-extracted a legacy entry"))
        try:
            assert TX.ensure_work_base(GR) == good
        finally:
            TX.uat = saved_uat


def t_the_fallback_path_records_the_cache():
    """Only the predicted-path branch used to record, so every asset the prediction missed — which
    was every patch asset while the layout map was stale — re-extracted on every operation."""
    with sandbox() as sb:
        landed = stage(sb.work, "ent/Marvel/", "extracted into the legacy layout")
        saved_uat, saved_retoc = TX.uat, TX.extract_via_retoc
        TX.uat = lambda args, **kw: type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})
        TX.extract_via_retoc = lambda grs: {}
        try:
            got = TX.ensure_work_base(GR)
        finally:
            TX.uat, TX.extract_via_retoc = saved_uat, saved_retoc
        assert got == landed, (got, landed)
        entry = AC.get(GR)
        assert entry and entry["cache_path"] == os.path.abspath(landed), entry
        assert entry["pak"] == PATCH_C, entry


for t in (t_a_cache_entry_from_another_container_is_dropped,
          t_a_matching_cache_entry_is_still_a_fast_path,
          t_a_legacy_entry_without_provenance_still_works,
          t_the_fallback_path_records_the_cache):
    check(t.__doc__.splitlines()[0].strip(), t)


print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
for name, err in FAIL:
    print(f"  FAILED: {name}\n          {type(err).__name__}: {err}")
sys.exit(1 if FAIL else 0)
