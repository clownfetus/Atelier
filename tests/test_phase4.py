"""Phase 4 — texture & material. Run: .venv/bin/python tests/test_phase4.py

PHASES.md calls this "the first phase that needs your game", meaning a mod has to be exported and
looked at in-engine. Most of it turned out to be checkable before that: the parts that decide
whether the mod is CORRECT — which path an asset is staged at, what the injected pixels actually
are, whether an option reaches the builder — are all on this side of the game, and they are what
this file asserts.

What is NOT here, and is still the in-game check PHASES.md asks for:
  * whether the shader honours a zero-alpha ColorID the way the region maths says it does (#12)
  * whether a UI texture stops being mip-blurred once its group is TEXTUREGROUP_UI (#20)
  * whether "blanked" reads as gone rather than as a black hole on a particular material (#22)

Tests that need the real UAssetTool and a real extracted texture SKIP without them, so this suite
still runs on a machine with no game installed.

Covered here:
  #10  Marvel_LQ — its own root, no longer evicted by its HQ twin, and reported when absent
  #12  turning the dye overlay off: a neutral ColorID mask, at the mask's own path
  #20  no-mips and the texture group, applied without losing the injected mip data
  #21  the Marvel_LQ twin: staged when the mount exists, skipped honestly when it does not
  #22  "remove a texture" — transparent where the format allows it, and SAID to be black where not
  #23  the whole texture set, with a manifest naming every slot
  ---  per-asset options: per project, removed rather than stored false, forgotten on delete
  #37  the HQ texture DLC invalidating work-cache copies that predate it

#13 (bulk curve / VFX editing) was deliberately left out of this phase.
"""
import os, re, sys, json, shutil, tempfile, traceback, contextlib, subprocess

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fake_paks

PASS, FAIL, SKIP = [], [], []
GOOD_KEY = "ab" * 32
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class _Skip(Exception):
    pass


def check(name, fn):
    try:
        fn()
        PASS.append(name); print(f"  PASS  {name}")
    except _Skip as e:
        SKIP.append(name); print(f"  SKIP  {name} — {e}")
    except Exception as e:
        FAIL.append((name, e)); print(f"  FAIL  {name}\n        {type(e).__name__}: {e}")
        if os.environ.get("VERBOSE"):
            traceback.print_exc()


def section(t):
    print(f"\n\033[1m{t}\033[0m" if sys.stdout.isatty() else f"\n{t}")


def read_text(rel):
    return open(os.path.join(ROOT, rel), encoding="utf-8").read()


import io_lib
import atelier.config as CFG
import atelier.index as IDX
import atelier.project_meta as PM
import atelier.handlers.texture as _TXMOD


@contextlib.contextmanager
def sandbox():
    """Same isolation as the Phase 2/3 suites: nothing here may touch the developer's own install."""
    tmp   = tempfile.mkdtemp()
    tools = os.path.join(tmp, "Tools"); os.makedirs(tools)
    paks  = os.path.join(tmp, "Paks");  os.makedirs(paks)
    proj  = os.path.join(tmp, "project"); os.makedirs(proj)
    # texture.py binds PAKS and WORK_IMPORT_ROOT at import, so overriding config alone leaves a
    # path back to the developer's real install — one missing project PNG and a test starts
    # extracting from the actual game. Pin those too; nothing in this suite may touch them.
    saved = (CFG.CONFIG_FILE, CFG.TOOLS, CFG.AES_KEY_FILE, CFG.PAKS, CFG.IMPORT_ROOT,
             CFG._active_project, IDX.PAKS, IDX._CACHE_FILE, IDX._INDEX, IDX._FAILED,
             IDX._LOOKUP, io_lib.AES_KEY, _TXMOD.PAKS, _TXMOD.WORK_IMPORT_ROOT)
    CFG.CONFIG_FILE  = os.path.join(tmp, "mr_config.json")
    CFG.TOOLS        = tools
    CFG.AES_KEY_FILE = os.path.join(tools, "AES_KEY.txt")
    CFG.PAKS = IDX.PAKS = paks
    CFG.IMPORT_ROOT  = proj
    CFG._active_project = ""
    IDX._CACHE_FILE  = os.path.join(tmp, "cli_index_cache.json")
    IDX._INDEX, IDX._FAILED, IDX._LOOKUP = None, [], None
    io_lib.AES_KEY = bytes.fromhex(GOOD_KEY)
    _TXMOD.PAKS = paks
    _TXMOD.WORK_IMPORT_ROOT = os.path.join(tmp, "work")
    try:
        yield type("Sandbox", (), {"root": tmp, "tools": tools, "paks": paks, "project": proj})
    finally:
        (CFG.CONFIG_FILE, CFG.TOOLS, CFG.AES_KEY_FILE, CFG.PAKS, CFG.IMPORT_ROOT,
         CFG._active_project, IDX.PAKS, IDX._CACHE_FILE, IDX._INDEX, IDX._FAILED,
         IDX._LOOKUP, io_lib.AES_KEY, _TXMOD.PAKS, _TXMOD.WORK_IMPORT_ROOT) = saved
        shutil.rmtree(tmp, ignore_errors=True)


def write_asset(paks_dir, container, mount, folder, name):
    """One encrypted container holding exactly one asset at mount/folder/name."""
    fake_paks.write_encrypted(os.path.join(paks_dir, container), GOOD_KEY,
                              blob=fake_paks.dir_index_blob(mount=mount, folder=folder, name=name))


# ══ #10 — the Marvel_LQ root ═════════════════════════════════════════════════
section("#10  Marvel_LQ")

LQ_MOUNT = "Marvel/Content/Marvel_LQ/"


def t_lq_gets_its_own_root():
    """Marvel_LQ mounts at its own root, the way a plugin does.

    Both Marvel mounts used to flatten onto the browse root, which made an LQ asset and its HQ twin
    ONE virtual path — and the dedup then kept the HQ one. Every LQ asset has an HQ twin, so the
    node people were told to look for could not appear even on an install that had one.
    """
    vp, pfx = IDX._virtual_path("../../../Marvel/Content/Marvel_LQ/UI/Textures/T_X.uasset")
    assert vp == "Marvel_LQ/UI/Textures/T_X.uasset", vp
    assert pfx == LQ_MOUNT, pfx


def t_the_lq_root_rebuilds_to_a_real_pak_path():
    """The synthetic root names the MOUNT, so it has to come back off before joining.

    Concatenating would give Marvel/Content/Marvel_LQ/Marvel_LQ/UI/... — a path that exists nowhere,
    which is exactly how a mod staged at a plugin path used to override nothing.
    """
    vp, pfx = IDX._virtual_path("../../../Marvel/Content/Marvel_LQ/UI/T_X.uasset")
    assert IDX.mount_join(pfx, vp) == "Marvel/Content/Marvel_LQ/UI/T_X.uasset", IDX.mount_join(pfx, vp)
    assert IDX.is_lq(vp) and not IDX.is_lq("UI/T_X.uasset")
    assert IDX.lq_counterpart("UI/T_X") == "Marvel_LQ/UI/T_X"
    assert IDX.lq_counterpart("Marvel_LQ/UI/T_X") == "UI/T_X"


def t_an_lq_asset_no_longer_shadows_its_twin():
    """THE repro, with containers: the same subpath in both mounts must yield TWO browsable assets."""
    with sandbox() as sb:
        write_asset(sb.paks, "pakchunkUI-Windows.utoc", "../../../Marvel/Content/Marvel", "UI", "T_Icon.uasset")
        write_asset(sb.paks, "pakchunkUILQ-Windows.utoc", "../../../Marvel/Content/Marvel_LQ", "UI", "T_Icon.uasset")
        vps = sorted(vp for vp, _c, _p in IDX.ensure_index())
        assert vps == ["Marvel_LQ/UI/T_Icon.uasset", "UI/T_Icon.uasset"], vps


def t_the_lq_section_appears_only_when_the_mount_does():
    """Browse must not invent the node, and must not hide it when it is real."""
    import atelier.web.browse as B
    with sandbox() as sb:
        write_asset(sb.paks, "pakchunkUI-Windows.utoc", "../../../Marvel/Content/Marvel", "UI", "T_Icon.uasset")
        names = [r["name"] for r in B.browse_dispatch("")]
        assert "Marvel_LQ" not in names, names
        assert not IDX.has_lq_mount()
    with sandbox() as sb:
        write_asset(sb.paks, "pakchunkUI-Windows.utoc", "../../../Marvel/Content/Marvel", "UI", "T_Icon.uasset")
        write_asset(sb.paks, "pakchunkUILQ-Windows.utoc", "../../../Marvel/Content/Marvel_LQ", "UI", "T_Icon.uasset")
        rows = B.browse_dispatch("")
        lq = next((r for r in rows if r["name"] == "Marvel_LQ"), None)
        assert lq is not None, [r["name"] for r in rows]
        assert "low-quality" in lq["label"], lq["label"]
        assert IDX.has_lq_mount()
        # and it is navigable, not a dead node
        kids = B.browse_dispatch("Marvel_LQ/UI")
        assert [k["name"] for k in kids] == ["T_Icon"], kids


def t_content_mounts_reports_what_was_read():
    """The fact fawnls could not get: which mounts this install actually has."""
    with sandbox() as sb:
        write_asset(sb.paks, "pakchunkUI-Windows.utoc", "../../../Marvel/Content/Marvel", "UI", "T_A.uasset")
        write_asset(sb.paks, "pakchunkUILQ-Windows.utoc", "../../../Marvel/Content/Marvel_LQ", "UI", "T_A.uasset")
        m = IDX.content_mounts()
        assert m == {"Marvel/Content/Marvel/": 1, LQ_MOUNT: 1}, m


def t_the_thumbnail_path_agrees_with_the_index():
    """Two halves of one lookup, mapped by two different functions — they have to match.

    pak_thumb finds the CONTAINER through a map built from the index, then finds the chunk in a
    directory listing it maps itself. Disagree on one mount and every lookup for that mount finds
    the container and then misses inside it, silently and forever.
    """
    from atelier.handlers.pak_thumb import _path_to_gr
    for raw in ("../../../Marvel/Content/Marvel_LQ/UI/T_X.uasset",
                "../../../Marvel/Content/Marvel/UI/T_X.uasset"):
        vp, _pfx = IDX._virtual_path(raw)
        assert _path_to_gr(raw) == vp[:-7], (raw, _path_to_gr(raw), vp)
    assert _path_to_gr("../../../Marvel/Content/Marvel/UI/T_X.uexp") is None


for t in (t_lq_gets_its_own_root, t_the_lq_root_rebuilds_to_a_real_pak_path,
          t_the_thumbnail_path_agrees_with_the_index,
          t_an_lq_asset_no_longer_shadows_its_twin,
          t_the_lq_section_appears_only_when_the_mount_does,
          t_content_mounts_reports_what_was_read):
    check(t.__doc__.splitlines()[0].strip() if t.__doc__ else t.__name__, t)


# ══ per-asset export options ═════════════════════════════════════════════════
section("export options are per project, and only exist once they are set")


def t_options_round_trip_per_project():
    """Two projects can ship the same texture differently — this is not an app setting."""
    with sandbox() as sb:
        b = os.path.join(sb.root, "projB"); os.makedirs(b)
        PM.set_asset_opts(sb.project, "UI/T_A", {"no_mips": True, "lod_group": "TEXTUREGROUP_UI"})
        PM.set_asset_opts(b, "UI/T_A", {"blank": True})
        assert PM.get_asset_opts(sb.project, "UI/T_A") == {"no_mips": True, "lod_group": "TEXTUREGROUP_UI"}
        assert PM.get_asset_opts(b, "UI/T_A") == {"blank": True}
        assert PM.get_asset_opts(sb.project) == {"UI/T_A": {"no_mips": True, "lod_group": "TEXTUREGROUP_UI"}}


def t_switching_an_option_off_removes_it():
    """"Off" and "never set" have to stay the same state.

    Storing no_mips=false would make a project that had only ever LOOKED at the control immune to a
    later change of default — the same trap the deselected-set exists to avoid for selection."""
    with sandbox() as sb:
        PM.set_asset_opts(sb.project, "UI/T_A", {"no_mips": True, "blank": True})
        PM.set_asset_opts(sb.project, "UI/T_A", {"no_mips": False})
        assert PM.get_asset_opts(sb.project, "UI/T_A") == {"blank": True}
        PM.set_asset_opts(sb.project, "UI/T_A", {"blank": False})
        raw = json.load(open(os.path.join(sb.project, ".atelier", "project.json"), encoding="utf-8"))
        assert raw.get("asset_opts") == {}, raw.get("asset_opts")


def t_deleting_an_asset_forgets_its_options():
    """A re-import must not silently inherit settings from an edit that was thrown away."""
    with sandbox() as sb:
        PM.set_asset_opts(sb.project, "UI/T_A", {"blank": True})
        PM.forget_asset(sb.project, "UI/T_A")
        assert PM.get_asset_opts(sb.project, "UI/T_A") == {}


def t_a_legacy_project_reads_as_defaults():
    """Every project made before Phase 4 has no asset_opts key at all."""
    with sandbox() as sb:
        os.makedirs(os.path.join(sb.project, ".atelier"), exist_ok=True)
        json.dump({"deselected": ["UI/T_B"]},
                  open(os.path.join(sb.project, ".atelier", "project.json"), "w"))
        assert PM.get_asset_opts(sb.project) == {}
        assert PM.get_deselected(sb.project) == {"UI/T_B"}


def t_the_sidebar_can_see_an_altered_export():
    """A texture set to ship blank looks exactly like one that ships normally — so it must be marked."""
    src = read_text("atelier/web/browse.py")
    assert '"opts": all_opts.get(gr) or {}' in src, "all_imported drops the options"
    js = read_text("gui/app.js")
    assert "_sbOptBadge" in js and "sb-opt" in js
    assert "sb-opt" in read_text("gui/style.css")


for t in (t_options_round_trip_per_project, t_switching_an_option_off_removes_it,
          t_deleting_an_asset_forgets_its_options, t_a_legacy_project_reads_as_defaults,
          t_the_sidebar_can_see_an_altered_export):
    check(t.__doc__.splitlines()[0].strip() if t.__doc__ else t.__name__, t)


# ══ #20 / #21 / #22 — what the options do to the staged asset ════════════════
section("#20 mips + texture group · #21 Marvel_LQ twin · #22 remove")

import atelier.handlers.texture as TX


@contextlib.contextmanager
def stub_uat(record, out_files=(".uasset",)):
    """Replace UAssetTool with a recorder that creates the files the caller checks for.

    The arguments ARE the deliverable here: whether --no-mips is passed, and which path the asset
    is written to. What a real tool does with them is the in-game half of this phase.
    """
    saved = TX.uat
    def fake(args, **kw):
        record.append(list(args))
        if args and args[0] in ("inject_texture", "from_json"):
            out = args[3] if args[0] == "inject_texture" else args[2]
            os.makedirs(os.path.dirname(out), exist_ok=True)
            for ext in out_files:
                open(out[:-7] + ext, "wb").write(b"stub")
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
    TX.uat = fake
    try:
        yield record
    finally:
        TX.uat = saved


def _fake_project_texture(sb, game_rel, size=(64, 64)):
    """A work-cache copy and a painted project PNG, the way an imported+edited texture looks."""
    from PIL import Image
    import atelier.asset_cache as _ac
    wb = os.path.join(sb.root, "work", *game_rel.split("/"))
    os.makedirs(os.path.dirname(wb), exist_ok=True)
    open(wb + ".uasset", "wb").write(b"stub")
    _ac.record(game_rel, wb, "pakchunkUI-Windows.utoc", "Marvel/Content/Marvel/")
    base = CFG.project_base(game_rel, sb.project)
    os.makedirs(os.path.dirname(base), exist_ok=True)
    Image.new("RGBA", size, (10, 20, 30, 255)).save(base + ".png")
    return wb


def t_no_mips_reaches_the_tool():
    """#20's mip half is one flag the tool already had — nothing was passing it."""
    with sandbox() as sb:
        write_asset(sb.paks, "pakchunkUI-Windows.utoc", "../../../Marvel/Content/Marvel", "UI", "T_A.uasset")
        _fake_project_texture(sb, "UI/T_A")
        rec = []
        with stub_uat(rec):
            TX.stage_inject(os.path.join(sb.root, "stage"), "UI/T_A", {"no_mips": True})
        inj = next(a for a in rec if a[0] == "inject_texture")
        assert "--no-mips" in inj, inj
        rec2 = []
        with stub_uat(rec2):
            TX.stage_inject(os.path.join(sb.root, "stage2"), "UI/T_A", {})
        assert "--no-mips" not in next(a for a in rec2 if a[0] == "inject_texture")


def t_a_texture_group_failure_does_not_lose_the_texture():
    """The group is an extra on top of a correct asset — it must never take the asset down.

    A texture that does not serialise a LODGroup at all is the ordinary case for this: the property
    only exists when it differs from the class default, and there is nothing honest to append.
    """
    with sandbox() as sb:
        write_asset(sb.paks, "pakchunkUI-Windows.utoc", "../../../Marvel/Content/Marvel", "UI", "T_A.uasset")
        _fake_project_texture(sb, "UI/T_A")
        saved = TX.set_texture_group
        TX.set_texture_group = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no LODGroup"))
        try:
            with stub_uat([]):
                desc = TX.stage_inject(os.path.join(sb.root, "stage"), "UI/T_A",
                                       {"lod_group": "TEXTUREGROUP_UI"})
        finally:
            TX.set_texture_group = saved
        stage = os.path.join(sb.root, "stage", "Marvel", "Content", "Marvel", "UI", "T_A.uasset")
        assert os.path.exists(stage), "the injected texture was lost with the failed group edit"
        assert "FAILED" in desc, desc


def t_an_unknown_texture_group_is_refused():
    """The dropdown is the whole list; anything else is a typo or a stale client."""
    assert TX.set_texture_group("/nope/T_A.uasset", "TEXTUREGROUP_Nonsense") is False
    assert "TEXTUREGROUP_UI" in TX.TEXTURE_GROUPS


def t_blank_says_when_it_can_only_be_black():
    """#22 cannot always mean invisible, and must not pretend it does.

    inject_texture keeps the base's pixel format, so a transparent PNG injected into a DXT1 texture
    comes back OPAQUE BLACK (measured on T_1050103_Body_01_D). Shipping that as "removed" is
    thetruedaveed's black-image confusion from the other side.
    """
    assert TX.format_has_alpha("DXT5") and TX.format_has_alpha("BC7")
    assert not TX.format_has_alpha("DXT1") and not TX.format_has_alpha("BC5")
    assert not TX.format_has_alpha("")
    with sandbox() as sb:
        write_asset(sb.paks, "pakchunkUI-Windows.utoc", "../../../Marvel/Content/Marvel", "UI", "T_A.uasset")
        _fake_project_texture(sb, "UI/T_A")
        saved = TX.texture_format
        try:
            TX.texture_format = lambda wb: "DXT1"
            with stub_uat([]):
                desc = TX.stage_inject(os.path.join(sb.root, "s1"), "UI/T_A", {"blank": True})
            assert "opaque black" in desc and "DXT1" in desc, desc
            TX.texture_format = lambda wb: "DXT5"
            with stub_uat([]):
                desc = TX.stage_inject(os.path.join(sb.root, "s2"), "UI/T_A", {"blank": True})
            assert desc.endswith("(blanked)"), desc
        finally:
            TX.texture_format = saved


def t_blanking_injects_a_transparent_image_not_the_painted_one():
    """And the user's artwork stays in the project — blanking is an export choice, not a delete."""
    from PIL import Image
    import numpy as np
    with sandbox() as sb:
        write_asset(sb.paks, "pakchunkUI-Windows.utoc", "../../../Marvel/Content/Marvel", "UI", "T_A.uasset")
        _fake_project_texture(sb, "UI/T_A")
        rec = []
        with stub_uat(rec):
            TX.stage_inject(os.path.join(sb.root, "stage"), "UI/T_A", {"blank": True})
        src = next(a for a in rec if a[0] == "inject_texture")[2]
        a = np.asarray(Image.open(src).convert("RGBA"))
        assert a[..., 3].max() == 0, "the blank is not transparent"
        painted = CFG.project_base("UI/T_A", sb.project) + ".png"
        assert os.path.exists(painted), "blanking destroyed the user's PNG"
        assert np.asarray(Image.open(painted).convert("RGBA"))[..., 3].max() == 255


def t_the_lq_twin_is_staged_only_where_the_mount_exists():
    """#21 must not pad the mod with a path the game never looks up.

    A current install has no Marvel_LQ mount at all (checked on build 3870120: zero Marvel_LQ paths
    across all 21 containers), so on most machines this option correctly does nothing and says so.
    """
    with sandbox() as sb:                      # no LQ mount
        write_asset(sb.paks, "pakchunkUI-Windows.utoc", "../../../Marvel/Content/Marvel", "UI", "T_A.uasset")
        _fake_project_texture(sb, "UI/T_A")
        with stub_uat([]):
            desc = TX.stage_inject(os.path.join(sb.root, "stage"), "UI/T_A", {"lq_twin": True})
        assert "no Marvel_LQ mount" in desc, desc
        assert not os.path.exists(os.path.join(sb.root, "stage", "Marvel", "Content", "Marvel_LQ"))
    with sandbox() as sb:                      # LQ mount present
        write_asset(sb.paks, "pakchunkUI-Windows.utoc", "../../../Marvel/Content/Marvel", "UI", "T_A.uasset")
        write_asset(sb.paks, "pakchunkUILQ-Windows.utoc", "../../../Marvel/Content/Marvel_LQ", "UI", "T_A.uasset")
        _fake_project_texture(sb, "UI/T_A")
        stage = os.path.join(sb.root, "stage")
        with stub_uat([], out_files=(".uasset", ".uexp", ".ubulk")):
            desc = TX.stage_inject(stage, "UI/T_A", {"lq_twin": True})
        assert "+Marvel_LQ copy" in desc, desc
        hq = os.path.join(stage, "Marvel", "Content", "Marvel", "UI", "T_A.uasset")
        lq = os.path.join(stage, "Marvel", "Content", "Marvel_LQ", "UI", "T_A.uasset")
        assert os.path.exists(hq) and os.path.exists(lq), os.listdir(stage)
        # the bulk files have to travel with it, or the twin ships a header pointing at nothing
        assert os.path.exists(lq[:-7] + ".ubulk"), "the LQ copy lost its bulk data"


def t_the_options_reach_the_builder():
    """An option nobody passes to build_mod is a checkbox that does nothing."""
    src = read_text("atelier/handlers/texture.py")
    assert "asset_opts.get(game_rel)" in src, "stage_inject is called without the asset's options"
    routes = read_text("atelier/web/routes.py")
    assert "asset_opts=_project_meta.get_asset_opts(get_import_root())" in routes, \
        "install_mod builds without the project's options"


def t_a_part_of_the_mod_that_did_not_build_is_reported():
    """build_mod reports per-item failures; the route used to drop them and say "Installed".

    An option that silently did not apply is indistinguishable from the game ignoring the edit —
    which makes the in-game checks this phase still needs unreadable, because a dye-off that never
    staged and a shader that ignores the mask look exactly the same from the sofa.
    """
    routes = read_text("atelier/web/routes.py")
    assert '"skipped": result.get("skipped")' in routes, "install_mod drops build_mod's skip list"
    assert '"applied": result.get("applied")' in routes
    js = read_text("gui/app.js")
    assert "did NOT go into the mod" in js, "the front end never shows a partial build"


for t in (t_no_mips_reaches_the_tool, t_a_texture_group_failure_does_not_lose_the_texture,
          t_an_unknown_texture_group_is_refused, t_blank_says_when_it_can_only_be_black,
          t_blanking_injects_a_transparent_image_not_the_painted_one,
          t_the_lq_twin_is_staged_only_where_the_mount_exists, t_the_options_reach_the_builder,
          t_a_part_of_the_mod_that_did_not_build_is_reported):
    check(t.__doc__.splitlines()[0].strip() if t.__doc__ else t.__name__, t)


# ══ #12 — turning the dye overlay off ════════════════════════════════════════
section("#12  the dye overlay off switch")

import atelier.handlers.dye as DY
import numpy as np
from PIL import Image


def t_there_is_no_material_parameter_for_this():
    """Why this ships a texture and not a parameter edit — the record of the decision.

    PHASES.md's pivot signal says to fall back to the alpha-ColorID trick if the material path
    cannot do it. It cannot: the real dyeing MIs (MI_1050103_Body_01, MI_10600_1060300_Equip_01)
    expose BaseTint, UseDyeingGBChannel and the Region N sets, and nothing that switches dyeing off.
    """
    src = read_text("atelier/handlers/dye.py")
    assert "THERE IS NO MATERIAL PARAMETER FOR THIS" in src
    assert "def stage_dye_off" in src


def t_a_neutral_mask_is_region_zero_everywhere():
    """Alpha IS the region index, and 0 means undyed — so an empty alpha channel disables dyeing.

    This is the arithmetic the whole feature rests on, run over the generated mask rather than
    asserted in prose: quantise its alpha the way composite() does and every texel must land on 0.
    """
    tmp = tempfile.mkdtemp()
    try:
        p = DY.neutral_mask_png(os.path.join(tmp, "m", "n.png"), (128, 128))
        a = np.asarray(Image.open(p).convert("RGBA"))
        reg = np.rint(a[..., 3].astype(np.float32) / DY.STEP).astype(np.int32)
        assert reg.max() == 0 and reg.min() == 0, np.unique(reg)
        # and the trap it is NOT: an opaque mask is region 7, a perfectly ordinary dyed region
        assert int(round(255 / DY.STEP)) == 7
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def t_a_mask_with_no_alpha_channel_is_refused():
    """Silently shipping one would dye the WHOLE surface with Region 7 — worse than doing nothing.

    inject_texture keeps the base's pixel format. If a ColorID ever shipped in a format without an
    independent alpha block, the "neutral" mask would come back alpha 255, i.e. region 7 everywhere.
    """
    with sandbox() as sb:
        saved = (DY.TX.ensure_work_base, DY.TX.texture_format, DY.dye_slots)
        DY.dye_slots = lambda gr: ("UI/T_Mask", "UI/T_D")
        wb = os.path.join(sb.root, "w"); open(wb + ".uasset", "wb").write(b"x")
        DY.TX.ensure_work_base = lambda gr: wb
        DY.TX.texture_format = lambda b: "DXT1"
        try:
            try:
                DY.stage_dye_off(os.path.join(sb.root, "stage"), "UI/MI_X")
                raise AssertionError("a no-alpha mask was accepted")
            except RuntimeError as e:
                assert "region 7" in str(e), str(e)
        finally:
            DY.TX.ensure_work_base, DY.TX.texture_format, DY.dye_slots = saved


def t_the_mask_is_staged_at_the_masks_own_path():
    """The material is untouched — which is what makes the toggle reversible.

    Staging it at the MATERIAL's path would override the material with a texture, and the Region
    colours the user also edited would be lost rather than merely stop applying.
    """
    with sandbox() as sb:
        write_asset(sb.paks, "pakchunkC-Windows.utoc", "../../../Marvel/Content/Marvel", "Textures", "T_Mask.uasset")
        saved = (DY.TX.ensure_work_base, DY.TX.texture_format, DY.dye_slots, DY.uat)
        DY.dye_slots = lambda gr: ("Textures/T_Mask", "Textures/T_D")
        wb = os.path.join(sb.root, "w"); open(wb + ".uasset", "wb").write(b"x")
        DY.TX.ensure_work_base = lambda gr: wb
        DY.TX.texture_format = lambda b: "DXT5"
        rec = []
        def fake(args, **kw):
            rec.append(list(args))
            os.makedirs(os.path.dirname(args[3]), exist_ok=True)
            open(args[3], "wb").write(b"stub")
            return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        DY.uat = fake
        stage = os.path.join(sb.root, "stage")
        try:
            name = DY.stage_dye_off(stage, "Materials/MI_X")
        finally:
            DY.TX.ensure_work_base, DY.TX.texture_format, DY.dye_slots, DY.uat = saved
        assert name == "T_Mask", name
        assert os.path.exists(os.path.join(stage, "Marvel", "Content", "Marvel", "Textures", "T_Mask.uasset"))
        assert not os.path.exists(os.path.join(stage, "Marvel", "Content", "Marvel", "Materials"))
        a = np.asarray(Image.open(rec[0][2]).convert("RGBA"))
        assert a[..., 3].max() == 0, "the staged mask is not neutral"


def t_the_builder_stages_the_mask_for_a_flagged_material():
    """The toggle is on the material; the extra asset has to come out of the BUILD, not the editor."""
    src = read_text("atelier/handlers/texture.py")
    assert '"dye_off"' in src and "stage_dye_off" in src, "build_mod ignores the dye-off option"
    # and a failure there must be reported, not swallowed into a broken mod
    assert "dye overlay not disabled" in src


def t_the_preview_shows_the_painted_texture():
    """finngmin's actual complaint: you paint the diffuse and nothing you painted ever shows.

    A preview built from the vanilla texture reproduces the complaint instead of answering it, so
    the dye compositor has to read the project's PNG when there is one.
    """
    with sandbox() as sb:
        gr = "Textures/T_D"
        base = CFG.project_base(gr, sb.project)
        os.makedirs(os.path.dirname(base), exist_ok=True)
        Image.new("RGBA", (32, 32), (255, 0, 255, 255)).save(base + ".png")
        DY._IMCACHE.clear()
        assert DY.edited_png(gr) == base + ".png"
        im = DY._tex_image(gr)
        assert np.asarray(im.convert("RGB"))[0, 0].tolist() == [255, 0, 255]
        # re-painting it must not be served from the cache
        Image.new("RGBA", (32, 32), (0, 255, 0, 255)).save(base + ".png")
        os.utime(base + ".png", (0, 0))
        assert np.asarray(DY._tex_image(gr).convert("RGB"))[0, 0].tolist() == [0, 255, 0]
        DY._IMCACHE.clear()


def t_dye_off_previews_the_undyed_texture():
    """A "disabled" checkbox next to a still-dyed picture is the same non-answer finngmin has."""
    with sandbox() as sb:
        mask, diff, mat = "Textures/T_Mask", "Textures/T_D", "Materials/MI_X"
        for gr, col in ((mask, (0, 0, 0, 255)), (diff, (255, 0, 255, 255))):
            b = CFG.project_base(gr, sb.project)
            os.makedirs(os.path.dirname(b), exist_ok=True)
            Image.new("RGBA", (32, 32), col).save(b + ".png")
        DY._IMCACHE.clear()
        saved = (DY.dye_slots, DY.dye_regions)
        DY.dye_slots   = lambda gr: (mask, diff)
        DY.dye_regions = lambda gr: {7: {"ColorA": [0, 0, 1, 1], "ColorB": [0, 0, 1, 1]}}
        try:
            off = np.asarray(Image.open(DY.dye_preview(mat, size=32, dye_off=True)).convert("RGB"))
            on  = np.asarray(Image.open(DY.dye_preview(mat, size=32)).convert("RGB"))
        finally:
            DY.dye_slots, DY.dye_regions = saved
            DY._IMCACHE.clear()
        assert off[5, 5].tolist() == [255, 0, 255], off[5, 5]    # exactly what was painted
        assert on[5, 5].tolist() != [255, 0, 255], on[5, 5]      # the dye overpaints it


for t in (t_there_is_no_material_parameter_for_this, t_a_neutral_mask_is_region_zero_everywhere,
          t_a_mask_with_no_alpha_channel_is_refused, t_the_mask_is_staged_at_the_masks_own_path,
          t_the_builder_stages_the_mask_for_a_flagged_material,
          t_the_preview_shows_the_painted_texture, t_dye_off_previews_the_undyed_texture):
    check(t.__doc__.splitlines()[0].strip() if t.__doc__ else t.__name__, t)


# ══ #23 — the whole texture set ══════════════════════════════════════════════
section("#23  every texture the material uses")


def t_the_bundle_names_every_slot():
    """One dyed BaseColor is not a starting point — repainting needs the set, and needs it labelled.

    The manifest is the point: "which file is which slot" is the same question the region overlay
    answers for colours, and the answer on record for this one was "noted".
    """
    import zipfile
    with sandbox() as sb:
        slots = {"BaseColor": "Textures/T_D", "Normal": "Textures/T_N", "ORM": "Textures/T_ORM"}
        for gr in slots.values():
            b = CFG.project_base(gr, sb.project)
            os.makedirs(os.path.dirname(b), exist_ok=True)
            Image.new("RGBA", (16, 16), (1, 2, 3, 255)).save(b + ".png")
        DY._IMCACHE.clear()
        saved = (DY.M.read_material, DY.dye_slots, DY._tex_image)
        DY.M.read_material = lambda gr, **k: {"textures": dict(slots, Broken="Textures/T_Gone")}
        DY.dye_slots = lambda gr: (None, None)          # not a dyeing material: no dyed entry
        # "Broken" stands for a slot that cannot be decoded (a cubemap, a missing asset). Stubbed
        # rather than left to fall through, which would send the suite at the real paks.
        DY._tex_image = lambda gr: None if gr == "Textures/T_Gone" else saved[2](gr)
        try:
            zp, ok = DY.texture_bundle("Materials/MI_X", size=16)
        finally:
            DY.M.read_material, DY.dye_slots, DY._tex_image = saved
            DY._IMCACHE.clear()
        with zipfile.ZipFile(zp) as z:
            names = z.namelist()
            manifest = z.read("SLOTS.txt").decode()
        assert sorted(ok) == ["BaseColor", "Normal", "ORM"], ok
        for s in slots:
            assert any(n.startswith(s + "__") for n in names), names
        # a slot that cannot be decoded is LISTED as unavailable, not silently dropped — otherwise
        # a missing normal map looks like a material that has none
        assert "Broken" in manifest and "unavailable" in manifest, manifest


def t_the_bundle_has_a_route_and_a_button():
    """A backend that nothing can reach is not a feature."""
    assert "/api/mat_textures_download" in read_text("atelier/web/routes.py")
    js = read_text("gui/app.js")
    assert "matTexturesDownload" in js and "Download all textures" in js


for t in (t_the_bundle_names_every_slot, t_the_bundle_has_a_route_and_a_button):
    check(t.__doc__.splitlines()[0].strip() if t.__doc__ else t.__name__, t)


def t_the_controls_render_what_they_promise():
    """Drive the real render paths under node (tests/dom_checks.js).

    Everything else about the front end here greps app.js, which only proves the code is present.
    This calls it: the blank control naming the format it cannot make transparent, the Marvel_LQ
    control explaining why it is off, an option switched off being REMOVED rather than stored
    false, the sidebar badge, and the dye-off toggle appearing on a material with no exposed
    parameters at all.
    """
    node = shutil.which("node")
    if not node:
        raise _Skip("node not installed; these paths are exercised in-app")
    r = subprocess.run([node, os.path.join(ROOT, "tests", "dom_smoke.js")],
                       capture_output=True, text=True, timeout=60, cwd=ROOT)
    assert r.returncode == 0, (r.stdout + r.stderr).strip()[-1500:]
    assert "all render paths OK" in r.stdout, r.stdout


check(t_the_controls_render_what_they_promise.__doc__.splitlines()[0].strip(),
      t_the_controls_render_what_they_promise)


# ══ #37 — the HQ texture DLC and the work cache ══════════════════════════════
section("#37  installing the high-res texture pack")

OPT_MOUNT = "../../../Marvel/Content/Marvel"


def t_a_uptnl_is_recorded_but_not_indexed_as_an_asset():
    """The DLC's containers hold only .uptnl files, and a .uptnl is not an asset.

    Indexing them as assets would put a browsable entry next to every texture; ignoring them
    entirely is what left no way to tell a pre-DLC work copy from a post-DLC one. They are
    recorded separately.
    """
    with sandbox() as sb:
        write_asset(sb.paks, "pakchunkUI-Windows.utoc", OPT_MOUNT, "UI", "T_A.uasset")
        write_asset(sb.paks, "pakchunkUIoptional-Windows.utoc", OPT_MOUNT, "UI", "T_A.uptnl")
        vps = sorted(vp for vp, _c, _p in IDX.ensure_index())
        assert vps == ["UI/T_A.uasset"], vps
        assert IDX.optional_mips() == {"ui/t_a"}, IDX.optional_mips()
        assert IDX.has_optional_mip("UI/T_A")
        assert IDX.has_optional_mip("UI/T_A.uasset")
        assert not IDX.has_optional_mip("UI/T_B")


def t_the_record_survives_the_index_cache():
    """It is persisted, or the first cached launch after the DLC forgets the whole thing."""
    with sandbox() as sb:
        write_asset(sb.paks, "pakchunkUI-Windows.utoc", OPT_MOUNT, "UI", "T_A.uasset")
        write_asset(sb.paks, "pakchunkUIoptional-Windows.utoc", OPT_MOUNT, "UI", "T_A.uptnl")
        IDX.ensure_index()
        IDX._INDEX, IDX._OPT_MIPS, IDX._LOOKUP = None, set(), None   # next launch, cache warm
        assert IDX.optional_mips() == {"ui/t_a"}, "the cached index dropped the optional mips"


def t_installing_the_dlc_invalidates_a_cached_copy():
    """THE bug: the .uasset's container never changes, so nothing else can see the copy is stale.

    Measured on a real install the moment the DLC finished downloading: 4 of 47 cached entries
    were already serving half-resolution textures, and would have gone on doing so forever.
    """
    with sandbox() as sb:
        write_asset(sb.paks, "pakchunkUI-Windows.utoc", OPT_MOUNT, "UI", "T_A.uasset")
        write_asset(sb.paks, "pakchunkUIoptional-Windows.utoc", OPT_MOUNT, "UI", "T_A.uptnl")
        wb = _fake_project_texture(sb, "UI/T_A")          # extracted before the DLC: no .uptnl
        assert TX.missing_optional_mip("UI/T_A", wb) is True
        # and ensure_work_base acts on it rather than handing the stale copy back
        calls = []
        saved = (TX.extract_via_retoc, TX.prefers_retoc, TX._purge_work)
        TX.prefers_retoc = lambda: True
        TX.extract_via_retoc = lambda grs: (calls.append(list(grs)) or {})
        TX._purge_work = lambda gr: calls.append("purged")
        try:
            TX.ensure_work_base("UI/T_A")
        finally:
            TX.extract_via_retoc, TX.prefers_retoc, TX._purge_work = saved
        assert "purged" in calls, calls
        assert ["UI/T_A"] in calls, "it did not re-extract"


def t_a_current_copy_is_left_alone():
    """Re-extracting on every call would undo the entire point of the work cache."""
    with sandbox() as sb:
        write_asset(sb.paks, "pakchunkUI-Windows.utoc", OPT_MOUNT, "UI", "T_A.uasset")
        write_asset(sb.paks, "pakchunkUIoptional-Windows.utoc", OPT_MOUNT, "UI", "T_A.uptnl")
        wb = _fake_project_texture(sb, "UI/T_A")
        open(wb + ".uptnl", "wb").write(b"\0" * 1024)     # extracted after the DLC
        assert TX.missing_optional_mip("UI/T_A", wb) is False
        saved = TX.extract_via_retoc
        TX.extract_via_retoc = lambda grs: (_ for _ in ()).throw(AssertionError("re-extracted"))
        try:
            assert TX.ensure_work_base("UI/T_A") == wb
        finally:
            TX.extract_via_retoc = saved


def t_uninstalling_the_dlc_never_throws_the_top_mip_away():
    """One-directional on purpose: the cached copy is then BETTER than the paks can hand back."""
    with sandbox() as sb:
        write_asset(sb.paks, "pakchunkUI-Windows.utoc", OPT_MOUNT, "UI", "T_A.uasset")
        wb = _fake_project_texture(sb, "UI/T_A")          # no optional container in these paks
        open(wb + ".uptnl", "wb").write(b"\0" * 1024)
        assert not IDX.has_optional_mip("UI/T_A")
        assert TX.missing_optional_mip("UI/T_A", wb) is False


def t_a_top_mips_size_is_readable_from_its_length_alone():
    """Exact, and without a UAssetTool call per texture just to ask "is this one bigger now".

    A .uptnl is one square block-compressed mip, so len == (d/4)^2 * bpb with d a power of two.
    The two block sizes cannot collide: (d/4)^2*16 == (d'/4)^2*8 gives d' = d*sqrt(2).
    """
    tmp = tempfile.mkdtemp()
    try:
        for n, want in ((2097152, 2048), (1048576, 1024), ((256 // 4) ** 2 * 8, 256), (12345, None)):
            f = os.path.join(tmp, str(n))
            open(f, "wb").write(b"\0" * n)
            assert TX.uptnl_dimension(f) == want, (n, TX.uptnl_dimension(f), want)
        assert TX.uptnl_dimension(os.path.join(tmp, "nope")) is None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def t_an_imported_png_that_is_now_too_small_is_reported():
    """The half the cache cannot fix: a project PNG is the user's artwork, not ours to overwrite.

    Measured off the PNG, not off cache state, so the answer does not flip depending on whether
    the work copy has been re-extracted yet.
    """
    from PIL import Image
    with sandbox() as sb:
        write_asset(sb.paks, "pakchunkUI-Windows.utoc", OPT_MOUNT, "UI", "T_A.uasset")
        write_asset(sb.paks, "pakchunkUIoptional-Windows.utoc", OPT_MOUNT, "UI", "T_A.uptnl")
        wb = _fake_project_texture(sb, "UI/T_A", size=(64, 64))      # decoded pre-DLC, small
        # not re-extracted yet: we know it is not current, but not yet by how much
        got = TX.stale_mip_imports(sb.project)
        assert [i["game_rel"] for i in got] == ["UI/T_A"], got
        assert got[0]["full"] == 0, got
        # after the re-extract the top mip is on disk and the gap is measurable
        open(wb + ".uptnl", "wb").write(b"\0" * ((256 // 4) ** 2 * 16))
        got = TX.stale_mip_imports(sb.project)
        assert got and got[0]["have"] == 64 and got[0]["full"] == 256, got
        # a PNG already at (or above) the full size is not reported
        Image.new("RGBA", (256, 256), (1, 2, 3, 255)).save(
            CFG.project_base("UI/T_A", sb.project) + ".png")
        assert TX.stale_mip_imports(sb.project) == [], TX.stale_mip_imports(sb.project)


def t_nothing_is_reported_without_the_dlc():
    """No optional containers means no claim to make — and no walk of the project either."""
    with sandbox() as sb:
        write_asset(sb.paks, "pakchunkUI-Windows.utoc", OPT_MOUNT, "UI", "T_A.uasset")
        _fake_project_texture(sb, "UI/T_A", size=(64, 64))
        assert TX.stale_mip_imports(sb.project) == []


def t_the_report_reaches_the_user():
    """A finding nobody sees is not a fix."""
    assert "/api/stale_mips" in read_text("atelier/web/routes.py")
    js = read_text("gui/app.js")
    assert "checkStaleMips" in js and "checkStaleMips();" in js


for t in (t_a_uptnl_is_recorded_but_not_indexed_as_an_asset, t_the_record_survives_the_index_cache,
          t_installing_the_dlc_invalidates_a_cached_copy, t_a_current_copy_is_left_alone,
          t_uninstalling_the_dlc_never_throws_the_top_mip_away,
          t_a_top_mips_size_is_readable_from_its_length_alone,
          t_an_imported_png_that_is_now_too_small_is_reported,
          t_nothing_is_reported_without_the_dlc, t_the_report_reaches_the_user):
    check(t.__doc__.splitlines()[0].strip() if t.__doc__ else t.__name__, t)


# ══ against the real tools, where they are installed ═════════════════════════
section("with the real UAssetTool + a real extracted texture")


def _real_texture():
    """A real extracted texture from the work cache, or a skip. Nothing here writes to the paks."""
    from atelier.tools import UAT
    from atelier import hostos
    if not (os.path.exists(UAT) or os.path.exists(hostos.native_tool(UAT) or "")):
        raise _Skip("UAssetTool not installed")
    if not CFG.USMAP or not os.path.exists(CFG.USMAP):
        raise _Skip("no usmap configured")
    root = os.path.join(CFG._CACHE, "import")
    for dirpath, _d, files in os.walk(root):
        for f in files:
            if f.lower().endswith(".uasset") and f.lower().startswith("t_"):
                base = os.path.join(dirpath, f)[:-7]
                if os.path.exists(base + ".ubulk"):
                    return base
    raise _Skip("no extracted texture in the work cache — import one first")


def t_the_group_edit_keeps_the_injected_mips():
    """The one thing that could go wrong silently: from_json writes .uasset/.uexp only.

    The mip data lives in the .ubulk beside them, so rewriting the LODGroup after injection has to
    leave that file alone AND still resolve. Injected, retargeted, then decoded back.
    """
    base = _real_texture()
    tmp = tempfile.mkdtemp()
    try:
        from PIL import Image as I
        png = os.path.join(tmp, "src.png")
        I.new("RGBA", (256, 256), (9, 9, 9, 255)).save(png)
        out = os.path.join(tmp, "out.uasset")
        TX.uat(["inject_texture", os.path.abspath(base + ".uasset"), os.path.abspath(png),
                os.path.abspath(out), "--usmap", CFG.USMAP])
        if not os.path.exists(out):
            raise _Skip("inject_texture produced nothing on this host")
        before = TX.texture_props(out[:-7]).get("lod_group")
        if not before:
            raise _Skip("this texture serialises no LODGroup")
        want = "TEXTUREGROUP_UI" if before != "TEXTUREGROUP_UI" else "TEXTUREGROUP_Character"
        assert TX.set_texture_group(out, want) is True
        assert TX.texture_props(out[:-7]).get("lod_group") == want
        back = os.path.join(tmp, "back.png")
        TX.uat(["extract_texture", os.path.abspath(out), os.path.abspath(back), "--usmap", CFG.USMAP])
        assert os.path.exists(back), "the retargeted texture no longer decodes"
        assert I.open(back).size == (256, 256), I.open(back).size
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def t_a_neutral_mask_survives_the_round_trip():
    """DXT5's alpha block is independent, so a uniform zero alpha has to come back exactly zero.

    If it drifted even one step a texel would land in region 1 and the "undyed" skin would have a
    dyed patch — the same class of damage decode_dds exists to avoid.
    """
    base = _real_texture()
    fmt = TX.texture_format(base)
    if not TX.format_has_alpha(fmt):
        raise _Skip(f"the cached texture is {fmt}, which has no alpha channel")
    tmp = tempfile.mkdtemp()
    try:
        src = DY.neutral_mask_png(os.path.join(tmp, "m", "n.png"), TX.texture_size("x", base))
        out = os.path.join(tmp, "out.uasset")
        TX.uat(["inject_texture", os.path.abspath(base + ".uasset"), os.path.abspath(src),
                os.path.abspath(out), "--usmap", CFG.USMAP])
        if not os.path.exists(out):
            raise _Skip("inject_texture produced nothing on this host")
        back = os.path.join(tmp, "back.png")
        TX.uat(["extract_texture", os.path.abspath(out), os.path.abspath(back), "--usmap", CFG.USMAP])
        a = np.asarray(Image.open(back).convert("RGBA"))
        reg = np.rint(a[..., 3].astype(np.float32) / DY.STEP).astype(np.int32)
        assert reg.max() == 0, f"alpha drifted off region 0: {np.unique(a[..., 3])[:8]}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


for t in (t_the_group_edit_keeps_the_injected_mips, t_a_neutral_mask_survives_the_round_trip):
    check(t.__doc__.splitlines()[0].strip() if t.__doc__ else t.__name__, t)


# ══ summary ══════════════════════════════════════════════════════════════════
print(f"\n{len(PASS)} passed, {len(FAIL)} failed" + (f", {len(SKIP)} skipped" if SKIP else ""))
for name, err in FAIL:
    print(f"  FAILED: {name}\n          {type(err).__name__}: {err}")
sys.exit(1 if FAIL else 0)
