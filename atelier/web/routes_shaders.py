"""Shader Studio, World (.umap), and StringTable (.uasset) HTTP routes."""
import json
from bottle import request, response

import atelier.handlers.shaders as _shaders
from atelier.handlers.text import read_text, reset_text, save_text
from atelier.handlers.world import read_world, reset_world, save_world

_SHADER_EDIT_DISABLED = json.dumps(
    {"ok": False, "error": "Shader editing is disabled — Shader Studio is a read-only viewer."}
)


def register(app):
    @app.get("/api/shaders/status")
    def api_shaders_status():
        response.content_type = "application/json"
        try:
            return json.dumps({"ok": True, **_shaders.status()})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @app.post("/api/shaders/build")
    def api_shaders_build():
        response.content_type = "application/json"
        if not _shaders.tools_ok():
            return json.dumps({"ok": False, "error": "shader tools missing under Tools/shaders"})
        return json.dumps(_shaders.build_index_async())

    @app.get("/api/shaders/list")
    def api_shaders_list():
        response.content_type = "application/json"
        q = request.query
        try:
            return json.dumps({"ok": True, **_shaders.list_shaders(
                lib=q.get("lib", ""), freq=q.get("freq", ""), q=q.get("q", ""),
                page=int(q.get("page", 0) or 0), page_size=min(500, int(q.get("page_size", 200) or 200)))})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @app.get("/api/shaders/disasm")
    def api_shaders_disasm():
        response.content_type = "application/json"
        q = request.query
        lib = q.get("lib", ""); idx = q.get("idx", "")
        if not lib or idx == "":
            return json.dumps({"ok": False, "error": "missing lib/idx"})
        try:
            return json.dumps(_shaders.disasm(lib, int(idx)))
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @app.get("/api/shaders/constants")
    @app.post("/api/shaders/build_mod")
    @app.get("/api/shaders/ir")
    @app.post("/api/shaders/build_mod_ir")
    def api_shaders_edit_disabled():
        response.content_type = "application/json"
        return _SHADER_EDIT_DISABLED

    @app.get("/api/world_params")
    def api_world_params():
        response.content_type = "application/json"
        try:
            return json.dumps(read_world(request.query.get("game_rel", "")))
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @app.post("/api/world_save")
    def api_world_save():
        response.content_type = "application/json"
        try:
            b = request.json or {}
            return json.dumps(save_world(b.get("game_rel", ""), b.get("edits") or {}))
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @app.post("/api/world_reset")
    def api_world_reset():
        response.content_type = "application/json"
        try:
            return json.dumps(reset_world((request.json or {}).get("game_rel", "")))
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @app.get("/api/text_params")
    def api_text_params():
        response.content_type = "application/json"
        try:
            return json.dumps(read_text(request.query.get("game_rel", "")))
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @app.post("/api/text_save")
    def api_text_save():
        response.content_type = "application/json"
        try:
            b = request.json or {}
            return json.dumps(save_text(b.get("game_rel", ""), b.get("edits") or {}))
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @app.post("/api/text_reset")
    def api_text_reset():
        response.content_type = "application/json"
        try:
            return json.dumps(reset_text((request.json or {}).get("game_rel", "")))
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    return {
        "_shaders": _shaders,
        "_SHADER_EDIT_DISABLED": _SHADER_EDIT_DISABLED,
        "api_shaders_status": api_shaders_status,
        "api_shaders_build": api_shaders_build,
        "api_shaders_list": api_shaders_list,
        "api_shaders_disasm": api_shaders_disasm,
        "api_shaders_edit_disabled": api_shaders_edit_disabled,
        "api_world_params": api_world_params,
        "api_world_save": api_world_save,
        "api_world_reset": api_world_reset,
        "api_text_params": api_text_params,
        "api_text_save": api_text_save,
        "api_text_reset": api_text_reset,
    }
