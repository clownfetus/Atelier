"""Phase 3 — in-app features. Run: .venv/bin/python tests/test_phase3.py

No game install required, and no Windows tools: every UAssetTool call these paths make is either
avoided (the index / browse / overlay work is pure Python) or replaced with a stub that asserts the
ARGUMENTS, which is the part Atelier is responsible for. What a real UAssetTool does with those
arguments, and whether the result looks right on a real skin, is the in-app check PHASES.md asks for
and can only be done on a machine with the paks.

Covered here:
  #11  the ID-mask / colour-region overlay renders, is keyed to the legend, and never ships
  #14  all three nameplate paths are surfaced, including the ones the paks don't have
  #15  plugin content (MarvelGAS) gets its own root and rebuilds to a real pak path
  #16  projects-screen search  ) front-end; asserted through gui/app.js + index.html, and through
  #17  hex / 255 / float toggle) the colour-notation parser run under node when it is available
  #18  multi-select delete: the batch endpoint deletes exactly the assets it was given
  #19  MPC (global parameter collection) read / edit / persist / stage
"""
import os, re, sys, json, shutil, tempfile, traceback, contextlib, subprocess

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fake_paks

PASS, FAIL, SKIP = [], [], []
GOOD_KEY = "ab" * 32
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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


class _Skip(Exception):
    pass


def section(t):
    print(f"\n\033[1m{t}\033[0m" if sys.stdout.isatty() else f"\n{t}")


import io_lib
import atelier.config as CFG
import atelier.index as IDX


@contextlib.contextmanager
def sandbox():
    """Same isolation as the Phase 2 suite: nothing here may touch the developer's own install."""
    tmp   = tempfile.mkdtemp()
    tools = os.path.join(tmp, "Tools"); os.makedirs(tools)
    paks  = os.path.join(tmp, "Paks");  os.makedirs(paks)
    proj  = os.path.join(tmp, "project"); os.makedirs(proj)
    saved = (CFG.CONFIG_FILE, CFG.TOOLS, CFG.AES_KEY_FILE, CFG.PAKS, CFG.IMPORT_ROOT,
             CFG._active_project, IDX.PAKS, IDX._CACHE_FILE, IDX._INDEX, IDX._FAILED, io_lib.AES_KEY)
    CFG.CONFIG_FILE  = os.path.join(tmp, "mr_config.json")
    CFG.TOOLS        = tools
    CFG.AES_KEY_FILE = os.path.join(tools, "AES_KEY.txt")
    CFG.PAKS = IDX.PAKS = paks
    CFG.IMPORT_ROOT  = proj
    CFG._active_project = ""
    IDX._CACHE_FILE  = os.path.join(tmp, "cli_index_cache.json")
    IDX._INDEX, IDX._FAILED = None, []
    io_lib.AES_KEY = bytes.fromhex(GOOD_KEY)
    try:
        yield type("Sandbox", (), {"root": tmp, "tools": tools, "paks": paks, "project": proj})
    finally:
        (CFG.CONFIG_FILE, CFG.TOOLS, CFG.AES_KEY_FILE, CFG.PAKS, CFG.IMPORT_ROOT,
         CFG._active_project, IDX.PAKS, IDX._CACHE_FILE, IDX._INDEX, IDX._FAILED, io_lib.AES_KEY) = saved
        shutil.rmtree(tmp, ignore_errors=True)


def write_asset(paks_dir, container, mount, folder, name):
    """One encrypted container holding exactly one asset at mount/folder/name."""
    fake_paks.write_encrypted(os.path.join(paks_dir, container), GOOD_KEY,
                              blob=fake_paks.dir_index_blob(mount=mount, folder=folder, name=name))


def read_text(rel):
    return open(os.path.join(ROOT, rel), encoding="utf-8").read()


# ══ #15 — plugin content (MarvelGAS ability icons) ═══════════════════════════
section("#15  the Plugins mount")

PLUGIN_MOUNT = "Marvel/Plugins/MarvelGAS/Content/"


def t_plugin_paths_get_their_own_root():
    """MarvelGAS content must not be flattened into the main tree.

    Its subpaths collide with Marvel/Content/Marvel's own (UI/Common/Textures/AbilityIcon exists in
    both), and as bare subpaths the dedup in ensure_index kept one and dropped the other — which is
    why the team-up ability icons were unreachable and why the ones that showed up answered to a
    different path than FModel's.
    """
    vp, pfx = IDX._virtual_path("../../../Marvel/Plugins/MarvelGAS/Content/UI/Common/Textures/AbilityIcon/T_X.uasset")
    assert vp == "Plugins/MarvelGAS/UI/Common/Textures/AbilityIcon/T_X.uasset", vp
    assert pfx == PLUGIN_MOUNT, pfx


def t_plugin_path_rebuilds_to_a_real_pak_path():
    """The whole point of the prefix: pfx + virtual has to land back on the real path.

    The old prefix was 'MarvelGAS/Content/' — it had lost the 'Marvel/Plugins/' it lives under, so
    every path rebuilt from it pointed nowhere and anything staged there overrode nothing.
    """
    vp, pfx = IDX._virtual_path("../../../Marvel/Plugins/MarvelGAS/Content/UI/T_X.uasset")
    assert IDX.mount_join(pfx, vp) == "Marvel/Plugins/MarvelGAS/Content/UI/T_X.uasset", IDX.mount_join(pfx, vp)


def t_non_plugin_mounts_are_unchanged():
    """Engine/Content and the two Marvel mounts must behave exactly as before."""
    vp, pfx = IDX._virtual_path("../../../Engine/Content/MapTemplates/Sky/T_Sky_Stars.uasset")
    assert (vp, pfx) == ("MapTemplates/Sky/T_Sky_Stars.uasset", "Engine/Content/"), (vp, pfx)
    assert IDX.mount_join(pfx, vp) == "Engine/Content/MapTemplates/Sky/T_Sky_Stars.uasset"
    vp, pfx = IDX._virtual_path("../../../Marvel/Content/Marvel/UI/T_X.uasset")
    assert (vp, pfx) == ("UI/T_X.uasset", "Marvel/Content/Marvel/"), (vp, pfx)


def t_a_plugin_asset_no_longer_shadows_its_twin():
    """THE repro, with containers: the same subpath in both mounts must yield TWO browsable assets."""
    with sandbox() as sb:
        write_asset(sb.paks, "pakchunkMain-Windows.utoc", "../../../Marvel/Content/Marvel", "UI", "T_Icon.uasset")
        write_asset(sb.paks, "pakchunkPlugin-Windows.utoc", "../../../Marvel/Plugins/MarvelGAS/Content", "UI", "T_Icon.uasset")
        vps = sorted(vp for vp, _c, _p in IDX.ensure_index())
        assert vps == ["Plugins/MarvelGAS/UI/T_Icon.uasset", "UI/T_Icon.uasset"], vps


def t_pak_game_path_round_trips_through_the_index():
    """What the extract/stage paths actually call."""
    with sandbox() as sb:
        write_asset(sb.paks, "pakchunkPlugin-Windows.utoc", "../../../Marvel/Plugins/MarvelGAS/Content", "UI", "T_Icon.uasset")
        from atelier.paths import pak_game_path
        got = pak_game_path("Plugins/MarvelGAS/UI/T_Icon")
        assert got == "Marvel/Plugins/MarvelGAS/Content/UI/T_Icon", got


def t_the_plugins_folder_is_browsable_and_pinned():
    """The mount shows up as its own pinned root, named the way FModel names it."""
    with sandbox() as sb:
        write_asset(sb.paks, "pakchunkPlugin-Windows.utoc", "../../../Marvel/Plugins/MarvelGAS/Content", "UI", "T_Icon.uasset")
        import atelier.web.browse as B
        root = B.browse_dispatch("")
        plugins = [r for r in root if r["name"] == "Plugins"]
        assert plugins, [r["name"] for r in root]
        assert "plugins" in B.ROOT_PINNED
        assert "MarvelGAS" in plugins[0]["label"], plugins[0]["label"]
        inner = B.browse_dispatch("Plugins")
        assert [r["name"] for r in inner] == ["MarvelGAS"], inner
        leaf = B.browse_dispatch("Plugins/MarvelGAS/UI")
        assert [(r["name"], r["file_type"]) for r in leaf] == [("T_Icon", "texture")], leaf


def t_extraction_predicts_the_real_on_disk_path():
    """extract_info must not paste the synthetic root onto the extractor's output directory."""
    with sandbox() as sb:
        write_asset(sb.paks, "pakchunkPlugin-Windows.utoc", "../../../Marvel/Plugins/MarvelGAS/Content", "UI", "T_Icon.uasset")
        import atelier.handlers.texture as TX
        cp, _pak, pfx = TX.extract_info("Plugins/MarvelGAS/UI/T_Icon")
        assert cp is not None, "the asset is in the index but extract_info found nothing"
        tail = cp.replace("\\", "/").split("/work_import/")[-1] if "work_import" in cp.replace("\\", "/") else cp
        assert "Plugins/MarvelGAS/Content/UI/T_Icon" in cp.replace("\\", "/"), cp
        assert "Content/Plugins" not in cp.replace("\\", "/"), "the synthetic root leaked into the path: " + cp
        assert pfx == PLUGIN_MOUNT, pfx


def t_plugin_assets_extract_by_full_path():
    """A basename filter cannot tell MarvelGAS's T_Icon from the main mount's T_Icon, so a plugin
    asset must go through retoc's full-path unpack (text.py documents UAssetTool writing one
    asset's bytes to the other's path when the name is ambiguous)."""
    import atelier.handlers.texture as TX
    assert TX.is_plugin_asset("Plugins/MarvelGAS/UI/T_Icon")
    assert not TX.is_plugin_asset("UI/T_Icon")
    src = read_text("atelier/handlers/texture.py")
    assert "prefers_retoc() or is_plugin_asset(game_rel)" in src, \
        "ensure_work_base no longer routes plugin assets through the full-path extractor"


for t in (t_plugin_paths_get_their_own_root, t_plugin_path_rebuilds_to_a_real_pak_path,
          t_non_plugin_mounts_are_unchanged, t_a_plugin_asset_no_longer_shadows_its_twin,
          t_pak_game_path_round_trips_through_the_index, t_the_plugins_folder_is_browsable_and_pinned,
          t_extraction_predicts_the_real_on_disk_path, t_plugin_assets_extract_by_full_path):
    check(t.__doc__.splitlines()[0].strip() if t.__doc__ else t.__name__, t)


# ══ #14 — the three nameplate paths ══════════════════════════════════════════
section("#14  nameplates")


def t_all_three_nameplate_paths_are_listed():
    """One plate is three assets; changing one and not the others is the reported failure."""
    with sandbox() as sb:
        write_asset(sb.paks, "pakchunkMain-Windows.utoc", "../../../Marvel/Content/Marvel",
                    "UI", "T_Unrelated.uasset")
        import atelier.web.browse as B
        rows = B.browse_dispatch("Nameplates")
        paths = [r["rel_path"] for r in rows]
        assert paths == [p for p, _d in B.NAMEPLATE_PATHS], paths
        assert all(r["type"] == "folder" for r in rows), rows
        # each one says WHICH plate it is — that is the part shafsta had to type out by hand
        assert any("Cropped icon" in r["label"] for r in rows), rows


def t_the_section_is_pinned_at_the_root():
    """Nameplates is where someone looking for nameplates would look: the root."""
    with sandbox() as sb:
        write_asset(sb.paks, "pakchunkMain-Windows.utoc", "../../../Marvel/Content/Marvel", "UI", "T_X.uasset")
        import atelier.web.browse as B
        root = B.browse_dispatch("")
        assert [r for r in root if r["rel_path"] == "Nameplates"], [r["name"] for r in root]


def t_a_missing_nameplate_path_says_so():
    """An empty node with no explanation is exactly what winterwintour reported. If the paks do not
    have the path, the row still appears and admits it — that IS the answer to the question."""
    with sandbox() as sb:
        write_asset(sb.paks, "pakchunkMain-Windows.utoc", "../../../Marvel/Content/Marvel",
                    "UI", "T_Unrelated.uasset")
        import atelier.web.browse as B
        rows = B.browse_dispatch("Nameplates")
        assert all("not in your paks" in r["label"] for r in rows), rows


def t_a_present_nameplate_path_is_not_marked_missing():
    """A path the paks DO have must not be slandered as absent."""
    with sandbox() as sb:
        # Textures/Show/NameplateFrame under the UI root, as the real paks ship it
        fake_paks.write_encrypted(
            os.path.join(sb.paks, "pakchunkUI-Windows.utoc"), GOOD_KEY,
            blob=fake_paks.dir_index_blob(mount="../../../Marvel/Content/Marvel/UI/Textures/Show",
                                          folder="NameplateFrame", name="T_Frame_01.uasset"))
        import atelier.web.browse as B
        rows = {r["rel_path"]: r["label"] for r in B.browse_dispatch("Nameplates")}
        assert "not in your paks" not in rows["UI/Textures/Show/NameplateFrame"], rows
        assert "not in your paks" in rows["UI/Textures/Item/NameplateFrame"], rows


for t in (t_all_three_nameplate_paths_are_listed, t_the_section_is_pinned_at_the_root,
          t_a_missing_nameplate_path_says_so, t_a_present_nameplate_path_is_not_marked_missing):
    check(t.__doc__.splitlines()[0].strip() if t.__doc__ else t.__name__, t)


# ══ #11 — the ID-mask / colour-region overlay ════════════════════════════════
section("#11  ID-mask region overlay")

import numpy as np
from PIL import Image
import atelier.handlers.dye as DYE


@contextlib.contextmanager
def fake_dye(regions=(0, 1, 3, 7), size=256):
    """A synthetic ColorID mask: vertical bands whose ALPHA is the region index × STEP, exactly as
    the real masks encode it, over a noisy diffuse."""
    a = np.zeros((size, size, 4), dtype=np.uint8); a[..., 0:3] = 120
    w = size // len(regions)
    for i, r in enumerate(regions):
        a[:, i * w:(i + 1) * w, 3] = round(r * DYE.STEP)
    mask = Image.fromarray(a, "RGBA")
    rng  = np.random.default_rng(7)
    diff = Image.fromarray((rng.random((size, size, 3)) * 255).astype(np.uint8), "RGB")
    saved = (DYE.dye_slots, DYE._tex_image, DYE.dye_regions)
    DYE.dye_slots   = lambda gr: ("mask", "diff")
    DYE._tex_image  = lambda gr: mask if gr == "mask" else diff
    DYE.dye_regions = lambda gr: {r: {"ColorA": [1.0, 0.2, 0.2, 1.0], "ColorB": [0.2, 0.2, 1.0, 1.0]}
                                  for r in regions if r}
    try:
        yield type("Fake", (), {"regions": regions, "width": w, "size": size})
    finally:
        DYE.dye_slots, DYE._tex_image, DYE.dye_regions = saved


def t_every_region_renders_in_its_legend_colour():
    """The map is only an answer if the colour on it matches the swatch in the legend."""
    with fake_dye() as f:
        out = os.path.join(tempfile.mkdtemp(), "regions.png")
        DYE.region_overlay("Characters/1060/1060300/MI_Test", size=f.size, out_path=out, numbers=False)
        arr = np.asarray(Image.open(out)).astype(float)
        for i, r in enumerate(f.regions):
            if r == 0:
                continue
            band = arr[:, i * f.width + 4: (i + 1) * f.width - 4]
            want = np.array(DYE.REGION_COLORS[r], dtype=float)
            # shading keeps each texel between OVERLAY_MIX and 1.0 of the region colour
            ratio = band.reshape(-1, 3).max(axis=1) / max(want.max(), 1)
            assert ratio.min() > DYE.OVERLAY_MIX - 0.05, (r, ratio.min())
            hue = band.reshape(-1, 3).mean(axis=0)
            assert np.argmax(hue) == np.argmax(want), (r, hue, want)


def t_undyed_texels_are_grey_and_dim():
    """Region 0 takes no Region colour at all — the other half of the answer people are missing."""
    with fake_dye() as f:
        out = os.path.join(tempfile.mkdtemp(), "regions.png")
        DYE.region_overlay("X/MI_Test", size=f.size, out_path=out, numbers=False)
        arr = np.asarray(Image.open(out)).astype(float)
        band = arr[:, 4:f.width - 4].reshape(-1, 3)
        assert band.max() < 110, band.max()                       # dimmer than any real region
        # grey, not a hue: the palette's undyed entry is a hair blue (142,142,147) on purpose, so
        # allow that much channel spread and no more — a real region would be far wider apart.
        spread = band.max(axis=1) - band.min(axis=1)
        assert spread.max() <= 6, spread.max()


def t_the_region_number_is_drawn_inside_its_own_region():
    """A centroid can fall outside a C-shaped region and label the neighbour instead."""
    with fake_dye() as f:
        d = os.path.join(tempfile.mkdtemp())
        plain    = np.asarray(Image.open(DYE.region_overlay("X/MI_T", size=f.size, out_path=os.path.join(d, "a.png"), numbers=False))).astype(int)
        numbered = np.asarray(Image.open(DYE.region_overlay("X/MI_T", size=f.size, out_path=os.path.join(d, "b.png"), numbers=True))).astype(int)
        diff = np.abs(plain - numbered).sum(axis=2) > 12
        assert diff.any(), "no numbers were drawn"
        for i, r in enumerate(f.regions):
            if r == 0:
                continue
            xs = np.nonzero(diff.any(axis=0))[0]
            band_hits = ((xs >= i * f.width) & (xs < (i + 1) * f.width)).sum()
            assert band_hits > 0, f"region {r} got no number"
        # and nothing was drawn over the undyed band
        assert not diff[:, 0:f.width].any(), "the undyed region must not be numbered"


def t_interleaved_regions_do_not_stack_their_numbers():
    """Two regions woven through each other share a centroid area — on White Fox 1060300 Equip_01
    (regions 3 and 4, a leaf pattern) the naive anchor put their numbers 5px apart and the second
    one drawn hid the first. Each number must land on its own region, far enough from the others."""
    n = 256
    a = np.zeros((n, n, 4), dtype=np.uint8); a[..., 0:3] = 120
    # interleaved stripes: region 3 and region 4 alternate across the same patch
    for y in range(n):
        a[y, :, 3] = round((3 if (y // 8) % 2 == 0 else 4) * DYE.STEP)
    a[:, :n // 4, 3] = 0                                   # plus an undyed margin
    mask = Image.fromarray(a, "RGBA")
    diff = Image.new("RGB", (n, n), (128, 128, 128))
    saved = (DYE.dye_slots, DYE._tex_image)
    DYE.dye_slots  = lambda gr: ("m", "d")
    DYE._tex_image = lambda gr: mask if gr == "m" else diff
    try:
        reg = np.rint(np.asarray(mask)[..., 3].astype(np.float32) / DYE.STEP).astype(np.int32)
        placed = []
        for idx in (3, 4):
            spot = DYE._label_anchor(reg, idx, placed)
            assert spot is not None, idx
            x, y = spot
            assert reg[y, x] == idx, f"region {idx}'s number landed on region {reg[y, x]}"
            placed.append((x, y))
        (x1, y1), (x2, y2) = placed
        assert (x1 - x2) ** 2 + (y1 - y2) ** 2 >= DYE._LABEL_MIN_GAP ** 2, placed
    finally:
        DYE.dye_slots, DYE._tex_image = saved


def t_dye_info_carries_the_legend():
    """One call feeds the whole panel: which colour each index is drawn in, and its coverage."""
    with fake_dye() as f:
        info = DYE.dye_info("X/MI_T")
        assert info["dyeable"] is True
        assert info["overlay"]["1"] == DYE.region_hex(1), info["overlay"]
        assert set(info["coverage"]) == set(info["used"]), info
        total = sum(float(v) for v in info["coverage"].values())
        assert abs(total - 100.0) < 0.5, total


def t_the_overlay_is_preview_only():
    """Nothing in the dye module may reach the export stage — it is a picture, not an asset."""
    src = read_text("atelier/handlers/dye.py")
    assert "def stage_" not in src, "dye.py grew a staging path"
    routes = read_text("atelier/web/routes.py")
    assert "/api/dye_overlay" in routes
    assert "region_overlay" not in read_text("atelier/handlers/texture.py")


for t in (t_every_region_renders_in_its_legend_colour, t_undyed_texels_are_grey_and_dim,
          t_the_region_number_is_drawn_inside_its_own_region,
          t_interleaved_regions_do_not_stack_their_numbers, t_dye_info_carries_the_legend,
          t_the_overlay_is_preview_only):
    check(t.__doc__.splitlines()[0].strip() if t.__doc__ else t.__name__, t)


# ══ #19 — MPC global parameters in the VFX editor ════════════════════════════
section("#19  global parameter collections (MPC)")

import atelier.handlers.vfx as VFX


def _mpc_doc(scalars=(("GlowStrength", 2.5),), vectors=(("IceGlow", [1.0, 0.8, 0.1, 1.0]),)):
    """A MaterialParameterCollection as UAssetAPI serialises one."""
    def sc(name, val):
        return {"$type": "StructPropertyData", "StructType": "CollectionScalarParameter",
                "Value": [{"Name": "DefaultValue", "Value": val},
                          {"Name": "ParameterName", "Value": name},
                          {"Name": "Id", "Value": "{0}"}]}
    def vec(name, rgba):
        return {"$type": "StructPropertyData", "StructType": "CollectionVectorParameter",
                "Value": [{"Name": "DefaultValue", "StructType": "LinearColor",
                           "Value": [{"$type": "FLinearColor",
                                      "R": rgba[0], "G": rgba[1], "B": rgba[2], "A": rgba[3]}]},
                          {"Name": "ParameterName", "Value": name},
                          {"Name": "Id", "Value": "{0}"}]}
    return {"Exports": [{"Data": [
        {"$type": "ArrayPropertyData", "Name": "ScalarParameters", "Value": [sc(n, v) for n, v in scalars]},
        {"$type": "ArrayPropertyData", "Name": "VectorParameters", "Value": [vec(n, v) for n, v in vectors]},
    ]}]}


@contextlib.contextmanager
def fake_mpc(doc=None):
    tmp = tempfile.mkdtemp()
    jp  = os.path.join(tmp, "MPC_Test.json")
    json.dump(doc or _mpc_doc(), open(jp, "w"))
    saved = VFX.mpc_json
    VFX.mpc_json = lambda gr: jp
    try:
        yield jp
    finally:
        VFX.mpc_json = saved
        shutil.rmtree(tmp, ignore_errors=True)


def t_an_mpc_is_classified_and_editable():
    """MPC_* used to classify as 'other', so it never appeared in the browser at all — which is
    why searching 1031306 for the glow colour returned nothing."""
    import atelier.web.browse as B
    assert B._classify_file("MPC_Ice_Params.uasset") == "vfx"
    assert VFX.is_mpc("VFX/MPC_Ice_Params") and VFX.is_vfx("VFX/MPC_Ice_Params")
    assert not VFX.is_mpc("VFX/NS_Something")
    assert "vfx" in B.JSON_EDIT_TYPES and "vfx" in B.LISTED_FILE_TYPES


def t_global_parameters_are_read_out():
    """The collection's scalars and colours, shaped for the editor."""
    with fake_mpc():
        r = VFX.read_vfx("VFX/MPC_Test")          # dispatches to read_mpc
        assert r["kind"] == "mpc" and r["groups"] == []
        assert r["scalars"] == [{"name": "GlowStrength", "value": 2.5}], r["scalars"]
        assert r["vectors"] == [{"name": "IceGlow", "rgba": [1.0, 0.8, 0.1, 1.0]}], r["vectors"]


def t_an_edit_persists_into_the_project_json():
    """Same edit model as materials: the project JSON IS the edit, so it survives a restart and the
    sidebar sees the asset as imported."""
    with fake_mpc() as jp:
        out = VFX.save_vfx("VFX/MPC_Test", [], scalars={"GlowStrength": 0.0},
                           vectors={"IceGlow": [0.0, 0.0, 0.0, 1.0]})
        assert out["vectors"][0]["rgba"] == [0.0, 0.0, 0.0, 1.0], out
        assert out["scalars"][0]["value"] == 0.0, out
        on_disk = json.load(open(jp, encoding="utf-8"))
        lc = on_disk["Exports"][0]["Data"][1]["Value"][0]["Value"][0]["Value"][0]
        assert (lc["R"], lc["G"], lc["B"]) == (0.0, 0.0, 0.0), lc


def t_an_unknown_parameter_name_is_ignored():
    """A stale sidecar naming a parameter the collection no longer has must not raise."""
    with fake_mpc():
        out = VFX.save_vfx("VFX/MPC_Test", [], scalars={"Gone": 1.0}, vectors={"AlsoGone": [1, 1, 1, 1]})
        assert out["vectors"][0]["rgba"] == [1.0, 0.8, 0.1, 1.0], out


def t_staging_writes_to_the_real_pak_path():
    """The export path has to be the collection's own game path, or the mod overrides nothing."""
    with sandbox() as sb:
        fake_paks.write_encrypted(
            os.path.join(sb.paks, "pakchunkVFX-Windows.utoc"), GOOD_KEY,
            blob=fake_paks.dir_index_blob(mount="../../../Marvel/Content/Marvel/VFX",
                                          folder="Params", name="MPC_Test.uasset"))
        with fake_mpc():
            calls = []
            saved = VFX.uat
            def fake_uat(args, **kw):
                calls.append(args)
                if args[0] == "from_json":
                    open(args[2], "w").write("uasset")     # stand in for the real writer
                return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})
            VFX.uat = fake_uat
            try:
                stage = os.path.join(sb.root, "stage")
                VFX.stage_vfx(stage, "VFX/Params/MPC_Test")   # dispatches to stage_mpc
            finally:
                VFX.uat = saved
            assert calls and calls[0][0] == "from_json", calls
            written = calls[0][2].replace("\\", "/")
            assert written.endswith("Marvel/Content/Marvel/VFX/Params/MPC_Test.uasset"), written
            assert "niagara_edit" not in [c[0] for c in calls], "an MPC has no Niagara LUTs"


def t_niagara_assets_still_take_the_curve_path():
    """The dispatch must not swallow ordinary VFX."""
    src = read_text("atelier/handlers/vfx.py")
    assert src.count("if is_mpc(game_rel):") >= 4, "read/save/reset/stage must all dispatch"
    assert "niagara_details" in src and "niagara_edit" in src


for t in (t_an_mpc_is_classified_and_editable, t_global_parameters_are_read_out,
          t_an_edit_persists_into_the_project_json, t_an_unknown_parameter_name_is_ignored,
          t_staging_writes_to_the_real_pak_path, t_niagara_assets_still_take_the_curve_path):
    check(t.__doc__.splitlines()[0].strip() if t.__doc__ else t.__name__, t)


# ══ #18 — multi-select delete ════════════════════════════════════════════════
section("#18  multi-select delete")

import atelier.web.routes as RT
fake_paks.settle_background_index()   # the import starts a real-index warmup thread


def t_the_batch_delete_removes_exactly_what_it_was_given():
    """One request, one refresh — and the assets that were NOT marked must survive it."""
    with sandbox() as sb:
        CFG._active_project = ""
        keep, drop = "UI/T_Keep", "UI/T_Drop"
        for gr in (keep, drop):
            base = CFG.project_base(gr, sb.project)
            os.makedirs(os.path.dirname(base), exist_ok=True)
            open(base + ".png", "w").write("x")
        saved = (RT.project_base, RT.project_base_legacy, RT._cache_import_base, RT._asset_cache.remove)
        RT.project_base        = lambda gr: CFG.project_base(gr, sb.project)
        RT.project_base_legacy = lambda gr: CFG.project_base_legacy(gr, sb.project)
        RT._cache_import_base  = lambda gr: None
        RT._asset_cache.remove = lambda gr: None
        try:
            RT._delete_one_imported(drop)
        finally:
            (RT.project_base, RT.project_base_legacy, RT._cache_import_base, RT._asset_cache.remove) = saved
        assert not os.path.exists(CFG.project_base(drop, sb.project) + ".png"), "the marked asset survived"
        assert os.path.exists(CFG.project_base(keep, sb.project) + ".png"), "an unmarked asset was deleted"


def t_the_endpoint_accepts_a_list_and_stays_compatible():
    """A list deletes many; a single game_rel still deletes one."""
    src = read_text("atelier/web/routes.py")
    assert 'body.get("game_rels")' in src, "the endpoint takes no list"
    assert 'body.get("game_rel")' in src, "the single-asset form was dropped"
    app = read_text("gui/app.js")
    assert "game_rels: items.map(i => i.game_rel)" in app, "the sidebar still deletes one at a time"


def t_marking_is_separate_from_the_export_checkbox():
    """The checkbox means 'include in the mod'; marking means 'act on these'. Conflating them would
    silently drop assets from the next export."""
    app = read_text("gui/app.js")
    assert "_sbMarked" in app and "sbDeleteMarked" in app
    assert "if (e.ctrlKey || e.metaKey || (e.shiftKey && _sbLastTok))" in app, "no multi-select gesture"
    # the bulk path must never touch i.selected
    body = app[app.index("function _sbMarkClick"): app.index("function renderSidebar")]
    assert ".selected" not in body, body


for t in (t_the_batch_delete_removes_exactly_what_it_was_given,
          t_the_endpoint_accepts_a_list_and_stays_compatible,
          t_marking_is_separate_from_the_export_checkbox):
    check(t.__doc__.splitlines()[0].strip() if t.__doc__ else t.__name__, t)


# ══ #16 / #17 — projects search, and the colour notation that sticks ═════════
section("#16/#17  projects search · colour notation")


def t_the_projects_screen_has_a_search_box():
    """shafsta's ask: find a project without reading every card."""
    html = read_text("gui/index.html")
    assert 'id="proj-search"' in html, "no search input in the project picker"
    app = read_text("gui/app.js")
    assert "function projSearch()" in app and "_projAll" in app
    # it filters the cached list rather than re-asking the server
    assert "_renderProjectPicker(_projAll, true)" in app


def t_the_colour_notation_is_remembered():
    """The notation is the setting; forgetting it was the complaint."""
    app = read_text("gui/app.js")
    assert 'localStorage.setItem("atelier.colorMode"' in app, "the choice is not persisted"
    assert 'localStorage.getItem("atelier.colorMode")' in app, "the choice is not read back"
    assert "COLOR_MODES  = [\"hex\", \"255\", \"float\"]" in app
    # and it is offered everywhere a colour is typed
    assert app.count("colorModeSeg()") >= 2, "only one editor offers the notation switch"


def t_the_colour_parser_round_trips():
    """Run the real parser under node: a pasted value has to survive whichever notation is showing.

    Narrower than the DOM run below and worth keeping separate: this pins the exact notations and
    the rejection of junk, which is where a "helpful" parser would otherwise start guessing.
    """
    node = shutil.which("node")
    if not node:
        raise _Skip("node not installed; the parser is exercised in-app")
    app = read_text("gui/app.js")
    start = app.index("const COLOR_MODES")
    end   = app.index("function _seedColors")
    src   = ("const localStorage = { getItem: () => null, setItem: () => {} };\n"
             'function _hx2(c){return ("0"+Math.round(Math.min(255,Math.max(0,c*255))).toString(16)).slice(-2);}\n'
             + app[start:end] + """
const out = [];
out.push(JSON.stringify(parseColor01("#ff8000")));
out.push(JSON.stringify(parseColor01("ff8000")));
out.push(JSON.stringify(parseColor01("255, 128, 0")));
out.push(JSON.stringify(parseColor01("1.0 0.502 0.0")));
out.push(JSON.stringify(parseColor01("not a colour")));
out.push(JSON.stringify(parseColor01("12, 34")));
_colorMode = "hex";   out.push(fmtColor01(1, 0.5019607843, 0));
_colorMode = "255";   out.push(fmtColor01(1, 0.5019607843, 0));
_colorMode = "float"; out.push(fmtColor01(1, 0.5019607843, 0));
console.log(out.join("\\n"));
""")
    tmp = os.path.join(tempfile.mkdtemp(), "t.js")
    open(tmp, "w").write(src)
    got = subprocess.run([node, tmp], capture_output=True, text=True, timeout=30)
    assert got.returncode == 0, got.stderr
    lines = got.stdout.strip().splitlines()
    hexed, bare, c255, cflt, bad, short = lines[0:6]
    assert json.loads(hexed) == json.loads(bare), (hexed, bare)
    assert abs(json.loads(hexed)[1] - 0.502) < 0.01, hexed
    assert json.loads(c255) == json.loads(hexed), (c255, hexed)      # 0-255 recognised
    assert abs(json.loads(cflt)[1] - 0.502) < 0.01, cflt             # float recognised
    assert bad == "null" and short == "null", (bad, short)           # junk is rejected, not guessed
    assert lines[6] == "#ff8000", lines[6]
    assert lines[7] == "255, 128, 0", lines[7]
    assert lines[8] == "1.000, 0.502, 0.000", lines[8]


def t_the_editors_render_what_they_promise():
    """Drive the real render paths under node (tests/dom_smoke.js).

    Everything else in this section greps gui/app.js, which only proves the code is still there.
    This loads it against a stub DOM and calls it: the region map switch and its legend, the
    notation switch rewriting every colour field, a pasted colour surviving an HDR intensity, the
    MPC panel, shift-range marking leaving the export checkboxes alone, and the projects filter.
    """
    node = shutil.which("node")
    if not node:
        raise _Skip("node not installed; these paths are exercised in-app")
    r = subprocess.run([node, os.path.join(ROOT, "tests", "dom_smoke.js")],
                       capture_output=True, text=True, timeout=60, cwd=ROOT)
    assert r.returncode == 0, (r.stdout + r.stderr).strip()[-1500:]
    assert "all render paths OK" in r.stdout, r.stdout


for t in (t_the_projects_screen_has_a_search_box, t_the_colour_notation_is_remembered,
          t_the_colour_parser_round_trips, t_the_editors_render_what_they_promise):
    check(t.__doc__.splitlines()[0].strip() if t.__doc__ else t.__name__, t)


# ══ summary ══════════════════════════════════════════════════════════════════
print(f"\n{len(PASS)} passed, {len(FAIL)} failed" + (f", {len(SKIP)} skipped" if SKIP else ""))
for name, err in FAIL:
    print(f"  FAILED: {name}\n          {type(err).__name__}: {err}")
sys.exit(1 if FAIL else 0)
