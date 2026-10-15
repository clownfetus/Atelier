"""Opt-in real material, painted texture and neutral-dye export/readback.

Requires a configured, isolated ATELIER_DATA_DIR. Writes a new disposable project
and a new report directory; installation is only into that report's test-mods.
This verifies stored data. Shader appearance still requires an in-game check.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def digest(path):
    with open(path, "rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def fingerprints(root):
    return {str(p.relative_to(root)): digest(p) for p in root.rglob("*") if p.is_file()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--material", default="Characters/1031/1031306/Materials/MI_1031306_Equip_01")
    args = parser.parse_args()
    if not os.environ.get("ATELIER_DATA_DIR"):
        parser.error("Set ATELIER_DATA_DIR to the isolated development directory.")
    from atelier import config as C, tools, jobs
    from atelier.handlers import material as M, texture as T
    from atelier.storage import publish_files, atomic_json
    from PIL import Image, ImageDraw, ImageChops

    data, report = Path(C.DATA_ROOT).resolve(), args.report_dir.resolve()
    if data == Path(C.ROOT).resolve() or report.exists():
        parser.error("Use isolated application data and a fresh report directory.")
    if report.is_relative_to(Path(C.PAKS).resolve()):
        parser.error("Report must be outside the game's Paks directory.")
    report.mkdir(parents=True)
    projects = Path(C.PROJECTS_ROOT)
    before = fingerprints(projects)
    name = "Material Dye Check " + time.strftime("%Y%m%d-%H%M%S")
    project = Path(C.project_dir(name))
    project.mkdir(parents=True)
    result = {"material": args.material, "project": str(project), "checks": [],
              "in_game_verified": False, "started": time.time()}
    try:
        with C.project_context(str(project)):
            original = M.read_material_original(args.material)
            mask_gr = original["textures"].get("DyeingTexture")
            base_gr = original["textures"].get("BaseColor")
            assert mask_gr and base_gr and original["colors"], "Choose a dyeable material with BaseColor"
            color_name = next((p["name"] for p in original["colors"] if p["name"] == "BaseTint"),
                              original["colors"][0]["name"])
            colors = {color_name: [0.16, 0.61, 0.37, 1.0]}
            scalars = {original["scalars"][0]["name"]: 0.625} if original["scalars"] else {}
            M.save_material(args.material, colors, scalars)
            T.ensure_work_base(base_gr)
            T.decode_flat([base_gr], str(project))
            png = Path(C.project_base(base_gr) + ".png")
            assert png.is_file(), "Texture decode failed"
            with Image.open(png) as image:
                painted = image.convert("RGBA")
                original_pixels = painted.copy()
            ImageDraw.Draw(painted).rectangle((0, 0, min(63, painted.width-1), min(63, painted.height-1)),
                                             fill=(35, 205, 95, 255))
            painted.save(png)
            project_before_build = fingerprints(project)
            mask_base = T.ensure_work_base(mask_gr)
            base_base = T.ensure_work_base(base_gr)
            mask_format, base_format = T.texture_format(mask_base), T.texture_format(base_base)
            mask_size = T.texture_size(mask_gr, mask_base)
            result.update(mask=mask_gr, texture=base_gr, expected_colors=colors, expected_scalars=scalars,
                          mask_format=mask_format, texture_format=base_format, mask_size=mask_size,
                          texture_size=painted.size)
            print("Building real material + painted texture + neutral dye mask…", flush=True)
            manager = jobs.JobManager(report / "jobs")
            def build(job):
                return T.build_mod("AtelierMaterialDyeCheck", [base_gr], [{"game_rel": args.material}],
                                   str(report / "exported"), asset_opts={args.material: {"dye_off": True}})
            record = manager.submit("export", "Native material/dye export", str(project), name, build)
            try:
                deadline = time.monotonic() + 3600
                while True:
                    record = manager.snapshot(record["id"], name)
                    if record["state"] not in jobs.ACTIVE:
                        break
                    assert time.monotonic() < deadline, "Native export exceeded the test deadline"
                    time.sleep(.1)
                assert record["state"] == "succeeded", record
                built = record["result"]
                result["managed_job"] = record
            finally:
                manager.shutdown(15)
            result["build"] = built
            assert built["ok"] and not built["skipped"], built
            assert any(s.startswith("mat ") for s in built["applied"]), built
            assert any(s.startswith("dye-off ") for s in built["applied"]), built
            installed = publish_files(built["artifacts"], str(report / "test-mods"))
            assert [digest(p) for p in installed] == [digest(p) for p in built["artifacts"]]
            result["checks"].append("complete container set and isolated installation hashes")
            result["checks"].append("tracked native export persists a successful terminal result through managed child-process execution")
            readback = report / "readback-paks"
            readback.mkdir()
            for source in built["artifacts"]:
                shutil.copy2(source, readback / Path(source).name)
            for source in Path(C.PAKS).glob("global.*"):
                shutil.copy2(source, readback / source.name)
            unpacked = report / "unpacked"
            proc = tools.uat(["extract_iostore_legacy", str(readback), str(unpacked)] +
                             T.uat_filter([args.material, base_gr, mask_gr]))
            def asset(gr):
                matches = list(unpacked.rglob(Path(gr).name + ".uasset"))
                assert len(matches) == 1, (gr, matches, (proc.stderr or proc.stdout)[-600:])
                return matches[0]
            material_file = asset(args.material)
            converted = report / "material-json"
            converted.mkdir()
            proc = tools.uat(["to_json", str(material_file), C.USMAP, str(converted)])
            assert proc.returncode == 0, proc.stderr
            exported = json.loads((converted / (material_file.stem + ".json")).read_text(encoding="utf-8-sig"))
            col, sc = M._mat_params(exported)
            actual_colors = {p["name"]: p["rgba"] for p in col}
            actual_scalars = {p["name"]: p["value"] for p in sc}
            for key, value in colors.items():
                assert all(abs(a-b) < 0.0001 for a, b in zip(actual_colors[key], value)), actual_colors[key]
            for key, value in scalars.items():
                assert abs(actual_scalars[key]-value) < 0.0001, actual_scalars[key]
            assert M._mat_textures(exported) == original["textures"], "Texture references changed"
            result["checks"].append("saved material colors/scalars and all texture references survive export")
            for label, gr, expected_size, expected_format in (
                ("mask", mask_gr, mask_size, mask_format),
                ("texture", base_gr, painted.size, base_format),
            ):
                base = str(asset(gr).with_suffix(""))
                T.decode_png(str(report / label), base)
                with Image.open(report / (label + ".png")) as image:
                    assert image.size == tuple(expected_size), (label, image.size, expected_size)
                    rgba = image.convert("RGBA")
                    if label == "mask":
                        assert rgba.getchannel("A").getextrema() == (0, 0), "Neutral mask alpha changed"
                    else:
                        assert ImageChops.difference(rgba.convert("RGB"), original_pixels.convert("RGB")).getbbox(), "Paint edit lost"
                        expected = painted.getpixel((16, 16))
                        actual = rgba.getpixel((16, 16))
                        assert max(abs(a-b) for a,b in zip(actual[:3], expected[:3])) < 35, (actual, expected)
                assert T.texture_format(base) == expected_format, (label, T.texture_format(base), expected_format)
            result["checks"].append("painted pixels, dimensions, formats and uniformly zero dye-mask alpha survive readback")
            assert fingerprints(project) == project_before_build, "Build changed project edits"
        after = fingerprints(projects)
        assert all(after.get(path) == value for path, value in before.items()), "An existing project changed"
        result["checks"].append("existing projects and new source edits preserved")
        result["artifacts"] = [{"path": p, "sha256": digest(p)} for p in built["artifacts"]]
        result["ok"] = True
        print("PASS " + "; ".join(result["checks"]), flush=True)
    except BaseException as exc:
        result.update(ok=False, error=str(exc))
        raise
    finally:
        result["elapsed_seconds"] = round(time.time()-result["started"], 2)
        atomic_json(str(report / "results.json"), result, indent=2)


if __name__ == "__main__":
    main()
