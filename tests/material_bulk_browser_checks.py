"""Material-folder selection and real HTTP review/save jobs with synthetic cooked documents."""
import copy
import json
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from material_bulk_fixtures import material, BASE, NEW_PARENT, SOURCE


def run_material_bulk_checks(page, context, url, report, checks):
    from atelier import config as C
    from atelier.handlers import material as M

    assets = ["Fixture/BulkMaterials/MI_One", "Fixture/BulkMaterials/MI_Two", "Fixture/BulkMaterials/MI_NoOpacity"]
    project = Path(C.project_dir("Smoke A"))
    paths = [Path(C.project_base(gr, str(project)) + ".json") for gr in assets]
    docs = {gr: material(gr, opacity=None if gr == assets[-1] else .75) for gr in assets}
    # Cover both supported opacity spellings without choosing a different operation.
    entry = M._gn(M._ex_props(docs[assets[1]]["Exports"][0]), "ScalarParameterValues")["Value"][-1]
    M._gn(M._gn(entry["Value"], "ParameterInfo")["Value"], "Name")["Value"] = "OpacityMultiplier"
    docs.update({SOURCE: material(SOURCE), BASE: material(BASE, kind="Material"), NEW_PARENT: material(NEW_PARENT, kind="Material")})
    items = [dict(type="asset", file_type="material", name=gr.split("/")[-1], game_rel=gr) for gr in assets]
    items += [dict(type="asset", file_type="curve", name="C_Excluded", game_rel="Fixture/C_Excluded"),
              dict(type="folder", name="Nested", rel_path="Fixture/BulkMaterials/Nested", count=50)]
    tab = context.new_page()
    errors, searches, single_saves = [], [], []
    tab.on("pageerror", lambda error: errors.append(str(error)))
    def browse(route):
        route.fulfill(json=[{**item, "imported": Path(C.project_base(item["game_rel"], str(project)) + ".json").is_file()}
                            if item["type"] == "asset" else item for item in items])
    def search(route):
        query = parse_qs(urlparse(route.request.url).query)
        searches.append(query)
        parents = query.get("parents") == ["true"]
        term = query.get("q", [""])[0].casefold()
        route.fulfill(json={"ok": True, "materials": [gr for gr in docs if term in gr.casefold() and
                                                      (parents or gr.split("/")[-1].startswith("MI_"))]})
    tab.route("**/api/browse?*", browse)
    tab.route("**/api/material_sources?*", search)
    tab.route("**/api/dye_info?*", lambda route: route.fulfill(json={"ok": True, "dyeable": False}))
    tab.route("**/api/material_save", lambda route: (single_saves.append(route.request.post_data_json), route.continue_())[-1])
    def read(gr):
        return json.loads(Path(C.project_base(gr, str(project)) + ".json").read_text(encoding="utf-8"))
    def review():
        tab.locator("#bulk-preview").click()
        tab.wait_for_function("!document.getElementById('bulk-apply').disabled")
    def save(count):
        tab.locator("#bulk-apply").click()
        tab.wait_for_function("count => document.getElementById('bulk-status').textContent.startsWith('Saved ' + count)", arg=count)

    try:
        with patch.object(M, "_original_document", side_effect=lambda gr: copy.deepcopy(docs[gr])):
            tab.goto(url)
            tab.wait_for_function("window.AtelierBulkEdit && window.atelierProject?.() === 'Smoke A'")
            tab.evaluate("pushNav({path:'Fixture/BulkMaterials'})")
            tab.wait_for_function("_gridStatus === 'ready' && nav.path === 'Fixture/BulkMaterials'")
            assert tab.locator("#bulk-edit-open").is_hidden()
            assert tab.locator("#bulk-material-open").is_visible()
            tab.locator("#library-type").select_option("texture")
            assert tab.locator("#bulk-material-open").is_hidden()
            tab.locator("#library-type").select_option("all")
            tab.locator("#bulk-material-open").click()
            assert tab.locator("#bulk-source").input_value() == "folder"
            assert tab.locator("#bulk-list input").count() == 3
            assert tab.locator("#bulk-selection-count").inner_text() == "3 of 3 selected"
            tab.locator("#bulk-select-none").click()
            assert tab.locator("#bulk-preview").is_disabled()
            tab.locator("#bulk-select-all").click()
            tab.locator("#bulk-list input").last.uncheck()
            tab.locator(".bulk-modal").focus()
            tab.keyboard.press("Control+a")
            assert tab.locator("#bulk-list input:checked").count() == 3
            assert not any(path.exists() for path in paths)
            checks.append("A material folder opens a filtered batch with all materials selected; Select all, Clear selection and Ctrl+A exclude folders and other asset types")

            tab.locator("#bulk-value").fill("0")
            review()
            tab.mouse.move(20, 20)
            tab.wait_for_function("!document.querySelector('.toast')")
            assert not any(path.exists() for path in paths)
            assert "No existing scalar override" in tab.locator("#bulk-results").inner_text()
            assert "2 assets" in tab.locator("#bulk-status").inner_text()
            tab.locator("#bulk-value").fill("0.2")
            assert tab.locator("#bulk-apply").is_disabled()
            assert tab.locator("#bulk-results table").count() == 0
            tab.locator("#bulk-value").fill("0")
            review()
            for theme in ("dark", "light"):
                tab.locator("#settings-theme").select_option(theme, force=True)
                tab.screenshot(path=str(report / ("material-bulk-review-" + theme + ".png")))
            tab.set_viewport_size({"width": 1024, "height": 768})
            bounds = tab.locator(".bulk-modal").bounding_box()
            assert bounds["x"] >= 0 and bounds["y"] >= 0 and bounds["y"] + bounds["height"] <= 768
            tab.screenshot(path=str(report / "material-bulk-compact.png"))
            save(2)
            for gr in assets[:2]:
                assert M._mat_params(read(gr))[1][-1]["value"] == 0
            assert not paths[-1].exists()
            checks.append("Real HTTP jobs review without importing, save both opacity spellings to zero and report missing parameters; edited controls invalidate the review")

            tab.keyboard.press("Escape")
            assert tab.locator("#bulk-material-open").evaluate("node => node === document.activeElement")
            tab.set_viewport_size({"width": 1400, "height": 900})
            tab.evaluate("item => openMaterialEditor(item)", items[0])
            tab.wait_for_selector("#material-overlay #bulk-edit-open:not([hidden])")
            original_value = tab.locator("#msn0").input_value()
            tab.locator("#msn0").fill("9")
            tab.locator("#bulk-edit-open").click()
            assert not tab.locator("#bulk-overlay").evaluate("node => node.classList.contains('active')")
            assert tab.evaluate("materialDirtyCount()") > 0
            tab.locator("#msn0").fill(original_value)
            tab.locator("#bulk-edit-open").click()
            tab.locator(".bulk-modal").focus()
            tab.keyboard.press("Control+s")
            assert not single_saves
            assert tab.locator("#material-overlay").evaluate("node => node.classList.contains('active')")
            checks.append("Materials also expose a contextual batch action; unsaved drafts block entry and Ctrl+S inside the batch cannot save the underlying single-material editor")

            tab.locator("#bulk-source").select_option("folder")
            tab.locator("#bulk-operation").select_option("reparent")
            tab.locator("#bulk-material-source").fill("Alternate")
            tab.wait_for_selector("#bulk-source-results:not([hidden])")
            tab.locator("#bulk-source-results").select_option(NEW_PARENT)
            assert searches[-1]["parents"] == ["true"]
            before_params = [M._mat_params(read(gr)) if paths[i].exists() else M._mat_params(docs[gr]) for i, gr in enumerate(assets)]
            review()
            tab.mouse.move(20, 20)
            tab.wait_for_function("!document.querySelector('.toast')")
            tab.screenshot(path=str(report / "material-bulk-parent.png"))
            save(3)
            for i, gr in enumerate(assets):
                assert M._mat_surface(read(gr))["parent_path"] == NEW_PARENT
                assert M._mat_params(read(gr)) == before_params[i]
            tab.wait_for_function("parent => matEditor?.materialParent === parent", arg=NEW_PARENT)
            assert NEW_PARENT in tab.locator("#mat-replacement").text_content()
            checks.append("Parent search includes base materials; the reviewed three-material save preserves each target's colours, scalars and textures")

            tab.locator("#bulk-operation").select_option("replace_material")
            tab.locator("#bulk-material-source").fill("MI_Source")
            tab.wait_for_selector("#bulk-source-results:not([hidden])")
            tab.locator("#bulk-source-results").select_option(SOURCE)
            assert "parents" not in searches[-1]
            review()
            save(3)
            for gr in assets:
                saved = read(gr)
                assert saved[M._SOURCE_KEY] == SOURCE and M._PARENT_KEY not in saved
                assert M._mat_params(saved) == M._mat_params(docs[SOURCE])
            tab.wait_for_function("source => matEditor?.materialSource === source && !matEditor.materialParent", arg=SOURCE)
            assert "Parent override:" not in tab.locator("#mat-replacement").text_content()
            checks.append("Full material replacement searches instances and saves the donor's complete setup under every target's own identity")
            tab.locator("#bulk-close").click()
            tab.wait_for_function("!!matEditor && !document.getElementById('bulk-edit-open').hidden")
            tab.evaluate("closeMaterialEditor(true)")
            assert not errors, errors
    finally:
        tab.close()
