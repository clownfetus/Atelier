"""Opt-in real-tool checks for #41 and #45, entirely in fresh report-local data.

Reads tools/game configuration from an existing isolated development directory.
Never installs a mod or modifies that directory, existing projects or game paks.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tools-data-dir", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--material", default="Characters/1031/1031306/Materials/MI_1031306_Equip_01")
    args = parser.parse_args()
    report, source = args.report_dir.resolve(), args.tools_data_dir.resolve()
    cfg = json.loads((source / "mr_config.json").read_text(encoding="utf-8"))
    paks = Path(cfg["paks"]).resolve()
    if report.exists() or report.is_relative_to(source) or report.is_relative_to(paks):
        parser.error("Use a fresh report directory outside game paks and the source data directory")
    data = report / "app-data"
    data.mkdir(parents=True)
    # Only read paths; keep keys and user configuration out of reports.
    config = {key: cfg[key] for key in ("paks", "usmap") if cfg.get(key)}
    config["tools"] = cfg.get("tools") or str(source / "Tools")
    (data / "mr_config.json").write_text(json.dumps(config), encoding="utf-8")
    os.environ["ATELIER_DATA_DIR"] = str(data)
    from atelier import config as C, tools
    from atelier.handlers import material as M, texture as T
    from PIL import Image
    result = {"ok": False, "checks": [], "in_game_verified": False}
    try:
        project = data / "fixture-project"
        project.mkdir()
        with C.project_context(str(project)):
            # Corrupt only an isolated project's old package import, leaving its
            # saved parameter data valid. Old full-document export would carry it.
            jp = Path(M.mat_json(args.material))
            vanilla = json.loads(jp.read_text(encoding="utf-8-sig"))
            colors, scalars = M._mat_params(vanilla)
            assert colors or scalars, "Fixture material has no editable parameters"
            cd = {colors[0]["name"]: [.16, .61, .37, 1]} if colors else {}
            sd = {scalars[0]["name"]: .625} if scalars else {}
            M.save_material(args.material, cd, sd)
            stale = json.loads(jp.read_text(encoding="utf-8-sig"))
            assert stale.get("Imports"), "Choose a fixture with material imports"
            stale["Imports"][0]["ObjectName"] = "__OLD_PATCH_IMPORT__"
            jp.write_text(json.dumps(stale), encoding="utf-8")
            before = digest(jp)
            print("Checking current-vanilla material rebuild with a stale project import…", flush=True)
            stage = report / "material-stage"
            M.stage_material(str(stage), args.material, {}, {})
            built = list(stage.rglob(Path(args.material).name + ".uasset"))
            assert len(built) == 1, built
            decoded = report / "material-readback"
            decoded.mkdir()
            converted = tools.uat(["to_json", str(built[0]), C.USMAP, str(decoded)])
            assert converted.returncode == 0, converted.stderr
            output = json.loads((decoded / (built[0].stem + ".json")).read_text(encoding="utf-8-sig"))
            assert "__OLD_PATCH_IMPORT__" not in json.dumps(output)
            assert M._mat_textures(output) == M._mat_textures(vanilla)
            actual_colors, actual_scalars = M._mat_params(output)
            actual_cd = {c["name"]: c["rgba"] for c in actual_colors}
            actual_sd = {s["name"]: s["value"] for s in actual_scalars}
            for name, value in cd.items():
                assert all(abs(a-b) < .0001 for a, b in zip(actual_cd[name], value))
            for name, value in sd.items():
                assert abs(actual_sd[name] - value) < .0001
            assert digest(jp) == before, "Export changed saved project JSON"
            result["checks"].append("material native serialization/readback preserves edits and current texture references, discards old import, preserves source JSON")
            print("PASS material rebase and native readback", flush=True)

            gr = "UI/Textures/img_empty"
            base = T.ensure_work_base(gr)
            assert base
            png_base = C.project_base(gr)
            T.decode_png(png_base, base)
            png = Path(png_base + ".png")
            with Image.open(png) as image:
                painted = image.convert("RGBA")
            painted.putpixel((0, 0), (190, 50, 100, 255))
            painted.save(png)
            before = digest(png)
            stem = Path(base).resolve()
            assert stem.is_relative_to(data), "Refusing to clear anything outside new fixture data"
            for ext in T._WORK_EXTS:
                stem.with_suffix(ext).unlink(missing_ok=True)
            assert not stem.with_suffix(".uasset").exists()
            print("Checking texture export after deleting its isolated extracted base…", flush=True)
            tex_stage = report / "texture-stage"
            T.stage_inject(str(tex_stage), gr, {"no_mips": True})
            assert stem.with_suffix(".uasset").is_file(), "Base was not recovered"
            injected = list(tex_stage.rglob("img_empty.uasset"))
            assert len(injected) == 1
            T.decode_png(str(report / "texture-readback"), str(injected[0].with_suffix("")))
            with Image.open(report / "texture-readback.png") as image:
                assert image.size == painted.size
                actual = image.convert("RGBA").getpixel((0, 0))
                assert max(abs(a-b) for a, b in zip(actual[:3], (190, 50, 100))) < 35, actual
            assert digest(png) == before, "Base recovery replaced authored PNG"
            result["checks"].append("deleted texture base re-extracted; injected pixels and dimensions survive native readback; authored PNG hash unchanged")
            print("PASS texture missing-base recovery and native readback", flush=True)
        result["ok"] = True
    except BaseException as error:
        result["error"] = str(error)
        raise
    finally:
        (report / "results.json").write_text(json.dumps(result, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
