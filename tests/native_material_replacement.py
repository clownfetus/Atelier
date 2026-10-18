"""Opt-in cross-character material export/readback using isolated project and output folders."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--target", default="Characters/1015/1015502/Materials/MI_1015502_Equip_01")
    parser.add_argument("--source", default="Characters/1031/1031306/Materials/MI_1031306_Equip_01")
    args = parser.parse_args()
    if not os.environ.get("ATELIER_DATA_DIR"):
        parser.error("Set ATELIER_DATA_DIR to configured isolated development data")
    from atelier import config as C, tools
    from atelier.handlers import material as M, texture as T
    report = args.report_dir.resolve()
    if report.exists() or report.is_relative_to(Path(C.PAKS).resolve()):
        parser.error("Use a new report directory outside the game's Paks folder")
    report.mkdir(parents=True)
    project = report / "project"
    project.mkdir()
    result = {"target": args.target, "source": args.source, "in_game_verified": False, "checks": []}
    try:
        with C.project_context(str(project)):
            donor = M._original_document(args.source)
            M.replace_material(args.target, args.source)
            print("Building cross-character material containers…", flush=True)
            built = T.build_mod("AtelierMaterialReplacementCheck", [], [{"game_rel": args.target}],
                                str(report / "exported"))
            result["build"] = built
            assert built["ok"] and not built["skipped"], built
            readback = report / "readback-paks"
            readback.mkdir()
            for source in built["artifacts"]:
                shutil.copy2(source, readback / Path(source).name)
            for source in Path(C.PAKS).glob("global.*"):
                shutil.copy2(source, readback / source.name)
            unpacked = report / "unpacked"
            proc = tools.uat(["extract_iostore_legacy", str(readback), str(unpacked)] + T.uat_filter([args.target]))
            assets = list(unpacked.rglob(Path(args.target).name + ".uasset"))
            assert len(assets) == 1, (assets, (proc.stderr or proc.stdout)[-600:])
            converted = report / "readback-json"
            converted.mkdir()
            proc = tools.uat(["to_json", str(assets[0]), C.USMAP, str(converted)])
            assert proc.returncode == 0, proc.stderr
            actual = json.loads((converted / (Path(args.target).name + ".json")).read_text(encoding="utf-8-sig"))
            expected = M._retarget_material(donor, args.source, args.target)
            assert actual["Exports"][0]["ObjectName"] == Path(args.target).name
            assert M._mat_params(actual) == M._mat_params(expected)
            assert M._mat_textures(actual) == M._mat_textures(expected)
            # The complete graph (parent and all texture imports), plus static switches
            # and opaque cooked shader payload, must survive actual IoStore conversion.
            def graph(doc):
                # Only the mod and global scripts are present during readback. UAssetTool
                # labels absent base-game exports Export_N/Object, while retaining their
                # package identity and FPackageIndex links. Compare those stable links.
                return [(i.get("ObjectName") if i.get("ClassName") == "Package" else None,
                         i.get("OuterIndex")) for i in doc["Imports"]]
            assert graph(actual) == graph(expected), "Parent/texture import graph changed"
            for name in ("Parent", "StaticParametersRuntime", "bHasStaticPermutationResource"):
                assert M._gn(M._ex_props(actual["Exports"][0]), name) == M._gn(M._ex_props(expected["Exports"][0]), name), name
            assert actual["Exports"][0].get("Extras") == expected["Exports"][0].get("Extras"), "Cooked shader payload changed"
            assert M._SOURCE_KEY not in actual
            result["checks"] += ["target package and export identity", "donor parent and complete import graph",
                                  "donor textures, colors and scalars", "static switches and opaque cooked shader payload",
                                  "complete pak/utoc/ucas build and native readback"]
            result["artifacts"] = [{"name": Path(p).name, "sha256": hashlib.sha256(Path(p).read_bytes()).hexdigest()}
                                   for p in built["artifacts"]]
            M.reset_material(args.target)
            assert not M.read_material(args.target)["material_source"]
            result["checks"].append("restore original target defaults after replacement")
        result["ok"] = True
    finally:
        (report / "results.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
