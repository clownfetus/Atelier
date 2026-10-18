"""Replacement picker, immediate saves, failure drafts and stale replies in real Chromium."""
from time import monotonic

TARGET = "Characters/1001/1001001/Materials/MI_Body"
SOURCE = "Characters/1002/1002001/Materials/MI_Galaxy"


def run_material_replacement_checks(page, context, url, report, checks):
    tab = context.new_page()
    errors, writes, searches, pending_writes = [], [], [], []
    tab.on("pageerror", lambda error: errors.append(str(error)))
    original = {"ok": True, "colors": [{"name": "Tint", "rgba": [.2, .3, .4, 1]}],
                "scalars": [{"name": "Roughness", "value": .4}], "textures": {}, "material_source": ""}
    donor = {"ok": True, "colors": [{"name": "GalaxyGlow", "rgba": [.8, .1, .9, 1]}],
             "scalars": [{"name": "StarSpeed", "value": 2}], "textures": {"Stars": "Characters/1002/T_Stars"},
             "material_source": SOURCE}
    state = {"current": original, "replace": "ok"}

    def search(route):
        if "delay" in route.request.url:
            searches.append(route)
        else:
            route.fulfill(json={"ok": True, "materials": [SOURCE], "more": False})

    def replace(route):
        writes.append({"body": route.request.post_data_json, "project": route.request.headers.get("x-atelier-project")})
        if state["replace"] == "delay":
            pending_writes.append(route)
        elif state["replace"] == "fail":
            route.fulfill(json={"ok": False, "error": "Fixture donor unavailable"})
        else:
            state["current"] = donor
            route.fulfill(json=donor)

    def reset(route):
        state["current"] = original
        route.fulfill(json=original)

    def open_editor(gr=TARGET):
        tab.evaluate("gr=>openMaterialEditor({name:gr.split('/').pop(),game_rel:gr})", gr)
        tab.wait_for_selector("#mat-replacement summary")
        if tab.locator("#mat-replacement").get_attribute("open") is None:
            tab.locator("#mat-replacement summary").click()

    def pending(routes):
        deadline = monotonic() + 5
        while not routes and monotonic() < deadline:
            tab.wait_for_timeout(10)
        assert routes, "Expected intercepted request"
        return routes.pop(0)

    tab.route("**/api/material_params?*", lambda route: route.fulfill(json=state["current"]))
    tab.route("**/api/material_sources?*", search)
    tab.route("**/api/material_replace", replace)
    tab.route("**/api/material_reset", reset)
    tab.route("**/api/dye_info?*", lambda route: route.fulfill(json={"dyeable": False}))
    tab.route("**/api/imported", lambda route: route.fulfill(json=[]))
    try:
        tab.goto(url)
        tab.wait_for_function("window.atelierProject?.()")
        open_editor()
        tab.locator("#mat-source-search").fill("galaxy")
        tab.wait_for_selector("#mat-source-results option")
        tab.locator("#mat-source-results").select_option(SOURCE)
        assert tab.locator("#mat-source-path").input_value() == SOURCE
        tab.locator("#mat-use-source").click()
        tab.locator("#atelier-confirm-cancel").click()
        assert not writes
        tab.locator("#mat-use-source").click()
        tab.locator("#atelier-confirm-ok").click()
        tab.wait_for_function("matEditor?.materialSource?.includes('MI_Galaxy')")
        assert tab.evaluate("matEditor.colors[0].name") == "GalaxyGlow"
        assert tab.evaluate("matEditor.scalars[0].name") == "StarSpeed"
        assert tab.evaluate("materialDirtyCount()") == 0
        assert writes[-1]["body"] == {"game_rel": TARGET, "source_game_rel": SOURCE}
        assert writes[-1]["project"] == "Smoke%20A"
        if tab.locator("#mat-replacement").get_attribute("open") is None:
            tab.locator("#mat-replacement summary").click()
        for theme in ("dark", "light"):
            tab.locator('#settings-theme').evaluate('(el,value)=>{el.value=value;el.dispatchEvent(new Event("change"));}', theme)
            tab.set_viewport_size({"width": 1024, "height": 768})
            assert tab.locator("#mat-source-path").evaluate("el => el.getBoundingClientRect().right <= innerWidth")
            tab.screenshot(path=str(report / ("material-replacement-" + theme + ".png")))
        checks.append("Material search/select, cancellation and immediate replacement retain donor controls and project identity")

        tab.locator("#mat-reset").click()
        tab.locator("#atelier-confirm-ok").click()
        tab.wait_for_function("!matEditor?.materialSource && matEditor?.colors?.[0]?.name === 'Tint'")
        assert tab.evaluate("materialDirtyCount()") == 0
        checks.append("Restore game defaults returns the original parameter schema after replacement")

        before = len(writes)
        for action in ("replaceMaterialFromSource", "resetMaterial"):
            tab.locator("#mat-source-path").fill(SOURCE)
            tab.evaluate("action => { window.confirmation = window[action](); }", action)
            tab.wait_for_selector("#atelier-confirm-ok")
            tab.evaluate("closeMaterialEditor(true)")
            tab.evaluate("openMaterialEditor({name:'Other material',game_rel:'Fixture/MI_ConfirmOther'})")
            tab.locator("#atelier-confirm-ok").click()
            tab.wait_for_timeout(80)
            assert tab.evaluate("matEditor.game_rel") == "Fixture/MI_ConfirmOther"
            assert len(writes) == before
            tab.evaluate("closeMaterialEditor(true)")
            open_editor()
        checks.append("A confirmation for a closed material cannot replace or reset a subsequently opened editor")

        state["replace"] = "fail"
        tab.locator("#msn0").fill(".8")
        tab.locator("#msn0").dispatch_event("input")
        tab.locator("#mat-source-path").fill(SOURCE)
        tab.locator("#mat-use-source").click()
        tab.locator("#atelier-confirm-ok").click()
        tab.wait_for_function("document.getElementById('mat-status').textContent.includes('donor unavailable')")
        assert tab.locator("#msn0").input_value() == ".8"
        assert tab.evaluate("materialDirtyCount()") == 1
        assert not tab.locator("#mat-body").evaluate("el=>el.inert")
        checks.append("A failed replacement retains unsaved parameters and re-enables the editor")

        tab.locator("#mat-source-search").fill("delay")
        old_search = pending(searches)
        tab.locator("#mat-source-search").fill("galaxy")
        tab.wait_for_selector("#mat-source-results option")
        old_search.fulfill(json={"ok": True, "materials": ["Fixture/MI_Stale"], "more": False})
        tab.wait_for_timeout(100)
        assert tab.locator("#mat-source-results option").all_text_contents() == [SOURCE]

        state["replace"] = "delay"
        tab.locator("#mat-use-source").click()
        tab.locator("#atelier-confirm-ok").click()
        old_write = pending(pending_writes)
        assert tab.locator("#mat-body").evaluate("el=>el.inert")
        tab.evaluate("closeMaterialEditor(true)")
        open_editor("Fixture/MI_Other")
        old_write.fulfill(json=donor)
        tab.wait_for_timeout(150)
        assert tab.evaluate("matEditor.game_rel") == "Fixture/MI_Other"
        assert not tab.locator("#mat-body").evaluate("el=>el.inert")
        checks.append("Stale search and replacement replies cannot overwrite a newer choice or another editor")
        assert not errors, errors
    finally:
        tab.close()
