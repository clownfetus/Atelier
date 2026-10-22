"""Opt-in material batch reparent/replacement build and readback, without installing a mod."""
import argparse
import copy
import json
import math
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--targets", nargs="+", default=[
        "Characters/1015/1015502/Materials/Lobby/MI_1015502_Equip_01",
        "Characters/1015/1015502/Materials/Lobby/MI_1015502_Equip_02"])
    parser.add_argument("--source", default="Characters/1031/1031306/Materials/Lobby/MI_1031306_Equip_01")
    args = parser.parse_args()
    if not os.environ.get("ATELIER_DATA_DIR"):
        parser.error("Set ATELIER_DATA_DIR to configured isolated development data")
    from atelier import bulk, config as C, hostos, tools
    from atelier.handlers import material as M, texture as T
    from atelier.handlers.world import RETOC
    from atelier.unreal_refs import imported_package

    report = args.report_dir.resolve()
    if report.exists() or report.is_relative_to(Path(C.PAKS).resolve()) or Path(C.DATA_ROOT).resolve() == Path(C.ROOT).resolve():
        parser.error("Use isolated application data and a fresh report directory outside the game Paks directory")
    project = report / "project"
    project.mkdir(parents=True)
    result = {"ok": False, "targets": args.targets, "source": args.source,
              "in_game_verified": False, "checks": [], "builds": {}}

    def read(gr):
        return json.loads(Path(C.project_base(gr) + ".json").read_text(encoding="utf-8-sig"))

    def build_and_readback(phase, expected):
        print("Building and reading back " + phase + "…", flush=True)
        built = T.build_mod("AtelierMaterialBatchCheck", [], [{"game_rel": gr} for gr in args.targets],
                            str(report / phase / "exported"))
        result["builds"][phase] = built
        assert built["ok"] and not built["skipped"], built
        utoc = next(p for p in built["artifacts"] if p.endswith(".utoc"))
        unpacked = report / phase / "unpacked"
        proc = hostos.run_exe([RETOC, "unpack", utoc, "--game-paks-dir", C.PAKS, "-o", str(unpacked)],
                             env=C.retoc_env(), capture_output=True, text=True, timeout=120)
        assert proc.returncode == 0, proc.stderr
        for gr, document in expected.items():
            candidates = list(unpacked.rglob(Path(gr).name + ".uasset"))
            assert len(candidates) == 1, (gr, candidates)
            out = report / phase / "json" / Path(gr).name
            out.mkdir(parents=True)
            proc = tools.uat(["to_json", str(candidates[0]), C.USMAP, str(out)])
            assert proc.returncode == 0, proc.stderr
            actual = json.loads((out / (Path(gr).name + ".json")).read_text(encoding="utf-8-sig"))
            ex = actual["Exports"][0]
            assert ex["ObjectName"] == Path(gr).name
            parent_index = M._gn(M._ex_props(ex), "Parent")["Value"]
            parent = imported_package(actual, parent_index)
            expected_parent = M._mat_surface(document)["parent_path"]
            assert parent and parent[1] == expected_parent, (gr, parent, expected_parent)
            assert M._mat_textures(actual) == M._mat_textures(document), "Texture reference changed"
            for got, want in zip(M._mat_params(actual), M._mat_params(document)):
                assert len(got) == len(want)
                for a, b in zip(got, want):
                    assert a["name"] == b["name"]
                    av, bv = (a["rgba"], b["rgba"]) if "rgba" in a else ([a["value"]], [b["value"]])
                    assert all(math.isclose(x, y, rel_tol=2e-5, abs_tol=1e-5) for x, y in zip(av, bv)), (gr, a, b)
            assert ex.get("Extras") == document["Exports"][0].get("Extras"), "Cooked shader payload changed"
            assert M._SOURCE_KEY not in actual and M._PARENT_KEY not in actual
            if phase == "parent":
                assert any(parent_index in ex.get(field, []) for field in (
                    "CreateBeforeSerializationDependencies", "SerializationBeforeSerializationDependencies",
                    "SerializationBeforeCreateDependencies", "CreateBeforeCreateDependencies")), "New parent lost its load-order dependency"
        result["checks"].append(phase + ": target identity, parent path, texture paths, parameter values and cooked shader payload survive native IoStore readback")

    try:
        with C.project_context(str(project)):
            originals = {gr: M._original_document(gr) for gr in args.targets}
            donor = M._original_document(args.source)
            parent = M._mat_surface(donor)["parent_path"]
            preview = bulk.preview(args.targets, {"operation": "reparent", "source": parent})
            assert preview["changed_assets"] == len(args.targets), preview
            assert not list(project.rglob("*.json")), "Review wrote project edits"
            bulk.apply(preview["preview_id"])
            for gr, original in originals.items():
                assert M._mat_params(read(gr)) == M._mat_params(original)
                assert M._mat_textures(read(gr)) == M._mat_textures(original)
            common = set.intersection(*({s["name"] for s in M._mat_params(d)[1]} for d in originals.values()))
            assert common, "Choose materials with a shared scalar override"
            scalar = "AOIntensity" if "AOIntensity" in common else sorted(common)[0]
            preview = bulk.preview(args.targets, {"operation": "set_scalar", "parameter": scalar, "value": .314159})
            assert preview["changed_assets"] == len(args.targets)
            bulk.apply(preview["preview_id"])
            result["checks"].append("Parent review writes no project edits; batch reparent preserves parameters/textures; a shared scalar saves across both materials")
            build_and_readback("parent", {gr: read(gr) for gr in args.targets})
            preview = bulk.preview(args.targets, {"operation": "replace_material", "source": args.source})
            assert preview["changed_assets"] == len(args.targets)
            bulk.apply(preview["preview_id"])
            expected = {gr: M._retarget_material(copy.deepcopy(donor), args.source, gr) for gr in args.targets}
            build_and_readback("replacement", expected)
        result["ok"] = True
    finally:
        (report / "results.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"ok": result["ok"], "checks": result["checks"], "in_game_verified": False}, indent=2))


if __name__ == "__main__":
    main()
