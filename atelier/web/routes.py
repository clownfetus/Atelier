import os, sys, json, re, math, shutil, threading, queue, subprocess, tempfile, time, urllib.request, uuid
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from bottle import request, response, static_file

from atelier.web.app import app
from atelier import hostos
from atelier import operations
from atelier import jobs
from atelier import preview
from atelier import import_server
from atelier import changelog
from atelier.storage import publish_files, container_files, PublicationRecoveryError
from contextlib import ExitStack
from functools import wraps
from urllib.parse import unquote, urlencode
import atelier.config as _c   # module handle: several routes rewrite config globals in place
from atelier.config import (ROOT, ASSETS, IMPORT_ROOT, PROJECTS_ROOT, WORK_IMPORT_ROOT, ASSETS_MODS, PAKS,
                            CNW,
                            GUI_DIR, VERSION_FILE, _CACHE, CACHE_3DVIEW, get_prereq_status, CONFIG_HAS_PAKS, paks_suggestion,
                            save_paks_config, save_setup_config, save_usmap_config,
                            get_usmap_checked_at, save_usmap_checked_at,
                            get_import_root, get_active_project, set_active_project,
                            project_base, project_base_legacy, project_game_rel,
                            get_mods_folder, save_mods_folder,
                            get_export_password, save_export_password,
                            save_blender_path)

_USMAP_PATTERN = re.compile(r'^5\.3\.2-\d+\+\+\+depot_marvel\+S\d+\.\d+_release-Marvel\.usmap$')
_THREE_DAYS    = 3 * 24 * 3600

def _fetch_github_usmap_list():
    url = "https://api.github.com/repos/SpaceDepot/rivals-depot/contents/usmap"
    req = urllib.request.Request(url, headers={"User-Agent": "Atelier/1.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())

def _get_latest_usmap_from_github():
    files = _fetch_github_usmap_list()
    matching = [f for f in files if f.get("type") == "file" and _USMAP_PATTERN.match(f["name"])]
    if not matching:
        return None
    matching.sort(key=lambda x: x["name"])
    return matching[-1]

def _download_usmap_file(download_url, dest_path):
    req = urllib.request.Request(download_url, headers={"User-Agent": "Atelier/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    with open(dest_path, "wb") as f:
        f.write(data)

THUMBS_DIR = os.path.join(_CACHE, "thumbs")
from atelier.tools import uat
from atelier.handlers.texture import (decode_batch, decode_flat, decode_png, stage_inject, build_mod,
                                      decode_thumb, extract_info, find_extracted,
                                      ensure_work_base, extract_many)
import atelier.asset_cache as _asset_cache
from atelier.handlers.pak_thumb import decode_thumb_from_pak
import atelier.handlers.pak_thumb as _pak_thumb_mod
import io_lib as _io_lib_mod
if CONFIG_HAS_PAKS and _io_lib_mod.AES_KEY:
    _pak_thumb_mod.start_warmup()
from atelier.handlers.material import mat_json, is_material, read_material, read_material_original, save_material, reset_material
import atelier.handlers.material as _material_mod
import atelier.handlers.custom_texture as _custom_tex
from atelier.handlers.vfx import read_vfx, is_vfx, save_vfx, reset_vfx, stage_vfx
from atelier.handlers.curve import read_curve, save_curve, reset_curve, is_curve, stage_curve
from atelier.handlers.world import is_world
from atelier.handlers.text import is_text
from atelier.paths import game_rel_for_skin, pak_game_path
from atelier.web.browse import (browse_dispatch, token, game_rel_from_token, all_imported)
import atelier.project_meta as _project_meta
from atelier import project_trash
import atelier.web.browse as _browse_mod


class _ProjectScopePlugin:
    name, api = "project_scope", 2

    def apply(self, callback, route):
        if not route.rule.startswith("/api/") or route.rule in ("/api/events", "/api/showcase_webp"):
            return callback

        @wraps(callback)
        def scoped(*args, **kwargs):
            try:
                body = request.json if request.content_type.startswith("application/json") else {}
                body = body or {}
                if not isinstance(body, dict):
                    raise ValueError("request body must be an object")
                # Cancellation must reach a load even while that load holds the project lock.
                if route.rule == '/api/viewport_cancel':
                    return callback(*args, **kwargs)
                # Validate asset paths before they can reach any cache/project join.
                gr = body.get("game_rel") or request.query.get("game_rel") or request.forms.get("game_rel")
                if gr:
                    _c.validate_game_rel(gr)
                asset_lists = [body.get(k, []) for k in ("game_rels", "items")]
                if any(not isinstance(items, list) for items in asset_lists):
                    raise ValueError("asset lists must be arrays")
                for item in asset_lists[0] + asset_lists[1]:
                    gr = item.get("game_rel") if isinstance(item, dict) else item
                    if gr:
                        _c.validate_game_rel(gr)
                if route.rule in ("/api/reset_data", "/api/save_paks"):
                    with operations.change_all():
                        return callback(*args, **kwargs)
                if route.rule in ("/api/project/create", "/api/project/rename",
                                  "/api/project/delete", "/api/project/duplicate"):
                    names = [body[k] for k in ("name", "old_name", "new_name") if body.get(k)]
                    roots = [_c.project_dir(n, PROJECTS_ROOT) for n in names]
                    with operations.change_projects(*roots):
                        return callback(*args, **kwargs)
                if route.rule == "/api/project/select":
                    root = _c.project_dir(body.get("name", ""), PROJECTS_ROOT)
                    with operations.project_use(root):
                        return callback(*args, **kwargs)
                if route.rule in ("/api/projects", "/api/project/export",
                                  "/api/changelog", "/api/changelog/acknowledge"):
                    return callback(*args, **kwargs)
                header = request.get_header("X-Atelier-Project")
                name = (unquote(header) if header is not None else
                        request.query.get("_project", get_active_project()))
                root = _c.project_dir(name, PROJECTS_ROOT) if name else IMPORT_ROOT
                preview_id = request.get_header('X-Atelier-Preview')
                with preview.scope(name, preview_id), operations.project_use(root, write=request.method == "POST" and
                                            not route.rule.startswith("/api/jobs")), _c.project_context(root):
                    if name and not os.path.isdir(root):
                        raise ValueError("project not found")
                    from atelier.storage import recover_project_writes
                    recover_project_writes(root)
                    jobs.checkpoint()
                    return callback(*args, **kwargs)
            except jobs.Cancelled:
                response.status = 409
                return {'ok': False, 'cancelled': True}
            except (ValueError, operations.BusyError, PublicationRecoveryError) as e:
                response.status = 400 if isinstance(e, ValueError) else 409
                response.content_type = "application/json"
                return json.dumps({"ok": False, "error": str(e)})
        return scoped


app.install(_ProjectScopePlugin())


@app.get('/api/app_info')
def api_app_info():
    """Local build identity for client-only captures; no release/network check."""
    try:
        with open(VERSION_FILE,encoding='utf-8') as source:
            version=source.read(100).strip()
        if not re.fullmatch(r'\d+(?:\.\d+){1,3}',version):
            version='development'
    except OSError:
        version='development'
    return {'version':version}


@app.get('/api/changelog')
def api_changelog():
    return changelog.status(VERSION_FILE)


@app.post('/api/changelog/acknowledge')
def api_changelog_acknowledge():
    return changelog.acknowledge(VERSION_FILE, (request.json or {}).get('version'))


@app.get("/api/jobs")
def api_jobs():
    return {"ok": True, "jobs": jobs.manager().list(get_active_project_for_request())}


def get_active_project_for_request():
    header = request.get_header("X-Atelier-Project")
    return unquote(header) if header is not None else request.query.get("_project", get_active_project())


@app.post('/api/viewport_cancel')
def api_viewport_cancel():
    preview.cancel(get_active_project_for_request(), (request.json or {}).get('id'))
    return {'ok': True}


@app.get("/api/jobs/<job_id>")
def api_job_status(job_id):
    return {"ok": True, "job": jobs.manager().snapshot(job_id, get_active_project_for_request())}


@app.post("/api/jobs/<job_id>/cancel")
def api_job_cancel(job_id):
    project = get_active_project_for_request()
    accepted = jobs.manager().cancel(job_id, project)
    return {"ok": accepted, "job": jobs.manager().snapshot(job_id, project),
            "error": None if accepted else "This job has finished or is publishing its files; cancellation is unavailable."}


def _submit_job(kind, label, work, on_finish=None):
    job = jobs.manager().submit(kind, label, get_import_root(), get_active_project_for_request(), work, on_finish)
    return {"ok": True, "job_id": job["id"], "job": job}


@app.post("/api/bulk/preview")
def api_bulk_preview():
    from atelier import bulk
    body = request.json or {}
    if body.get("background"):
        return _submit_job("bulk-preview", "Review batch edits",
                           lambda job: bulk.preview(body.get("items"), body.get("edit")))
    return bulk.preview(body.get("items"), body.get("edit"))


@app.post("/api/bulk/apply")
def api_bulk_apply():
    from atelier import bulk
    body = request.json or {}
    if body.get("background"):
        return _submit_job("bulk-save", "Save batch edits",
                           lambda job: bulk.apply(body.get("preview_id")))
    return bulk.apply(body.get("preview_id"))

# ── extraction helpers ────────────────────────────────────────────────────────

@app.post('/api/s_maps/plan')
def api_s_maps_plan():
    from atelier import s_maps
    body = request.json or {}
    if body.get('background'):
        return _submit_job('s-map-plan', 'Find D/S texture pairs', lambda job: s_maps.plan())
    return s_maps.plan()


@app.post('/api/s_maps/process')
def api_s_maps_process():
    from atelier import s_maps
    body = request.json or {}
    work = lambda job: s_maps.process(body.get('plan_id'), body.get('choices'))
    if body.get('background'):
        return _submit_job('s-map-process', 'Process S maps', work)
    return work(None)

def _import_base(game_rel):
    """Full disk path (no ext) for a game_rel's project file, subfolder-mirrored by game_rel so
    same-named assets under different skins never collide. Prefers whichever layout already holds a
    file (new subfolder, then legacy flat) for back-compat; defaults to the new layout for writes.
    Callers that WRITE must os.makedirs(os.path.dirname(...)) since the subfolder may not exist yet."""
    new = project_base(game_rel)
    if any(os.path.exists(new + e) for e in (".png", ".json")):
        return new
    legacy = project_base_legacy(game_rel)
    if any(os.path.exists(legacy + e) for e in (".png", ".json")):
        return legacy
    return new

def _cache_import_base(game_rel):
    """Extracted cache path (no ext) for a game_rel in _cache/import, via asset_cache."""
    return _asset_cache.cache_base(game_rel)

# ── static ────────────────────────────────────────────────────────────────────
from atelier.catalogue import catalogue
from atelier.hero_artwork import hero_artwork


@app.get('/api/catalogue/status')
def catalogue_status():
    catalogue.start_update()
    with catalogue.lock:
        hero_artwork.start_update(dict(catalogue.data.get('entries', {})))
    response.content_type = 'application/json'
    status = catalogue.status()
    status['hero_artwork'] = hero_artwork.status()
    status['updating'] = status['updating'] or status['hero_artwork']['updating']
    return json.dumps(status)


@app.get('/api/catalogue/hero/<cid>/<kind>')
def catalogue_hero_artwork(cid, kind):
    path = hero_artwork.image(cid, kind)
    if not path:
        response.status = 404
        response.set_header('Cache-Control', 'no-store')
        return b''
    result = static_file(path.name, root=str(path.parent), mimetype='image/webp')
    result.headers['Cache-Control'] = 'no-cache'
    if kind == 'story':
        result.headers['X-Atelier-Upscale'] = 'ready' if path.stem.endswith('-x4') else 'pending'
    return result


@app.get('/api/catalogue/icon/<key>')
def catalogue_icon(key):
    return catalogue_thumbnail(key, kind='icon')


@app.get('/api/catalogue/banner/<key>')
def catalogue_banner(key):
    return catalogue_thumbnail(key, kind='banner', sharp=request.query.get('sharp') == '1')


@app.get('/api/catalogue/badge/<key>')
def catalogue_badge(key):
    return catalogue_thumbnail(key, kind='badge')


@app.get('/api/catalogue/thumbnail/<key>')
def catalogue_thumbnail(key, kind='thumbnail', sharp=False):
    path = catalogue.banner(key, sharp=sharp) if kind == 'banner' else getattr(catalogue, kind)(key)
    if path is None:
        response.status = 404
        response.set_header('Cache-Control', 'no-store')
        return ''
    result = static_file(path.name, root=str(path.parent), mimetype='image/webp')
    result.set_header('Cache-Control', 'no-cache' if sharp else 'private, max-age=86400')
    if kind == 'banner' and sharp:
        result.set_header('X-Atelier-Upscale', 'ready' if path.stem.endswith('-x4') else 'pending')
    return result

@app.route("/")
def index():
    r = static_file("index.html", root=GUI_DIR)
    r.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return r

@app.route("/static/<path:path>")
def static(path):
    r = static_file(path, root=GUI_DIR)
    r.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return r

# ── 3D viewport (mesh -> glTF via AtelierNative / CUE4Parse) ──────────────────
from atelier.tools import atelier_mesh
from atelier.paths import skin_entries, skin_rel

_MESH_SKIP = re.compile(r"skeleton|physics|collision|shell|_lobby|lobby_|_vfx|vfxmesh|_lod", re.I)

@app.get("/api/skin_meshes")
def api_skin_meshes():
    """List the skin's renderable skeletal meshes (game_rels) for the viewport to compose."""
    skin_id = request.query.get("skin_id", "")
    response.content_type = "application/json"
    if not skin_id:
        return json.dumps([])
    from atelier.handlers.meshstudio import skin_meshes
    return json.dumps(skin_meshes(skin_id))

@app.get("/api/browse_material_dirs")
def api_browse_material_dirs():
    """Browse the pak tree for folders that contain MI_ materials — the viewport's "materials from"
    picker.

    NO CONVENTION IS ASSUMED, deliberately. Chromas/recolours have no mesh of their own, but there
    is no rule for finding them: some ship a full mesh set, some are textures-only, some materials-
    only, sibling ids under a character aren't necessarily variants of each other, and the folder
    schema isn't even consistently a skin id (`Characters/1060/1060CommonMaterial`). Every attempt to
    infer the relationship gets it wrong. So: the user navigates, we just report what's actually
    there, and they point at the material set they want applied to the loaded mesh.

    `path` = a virtual folder prefix ('' = roots). Returns its immediate child folders with recursive
    MI_/SK_ counts, so a chroma reads as "materials, no mesh" without us having to call it one.
    Reads the cached pak index — a dict walk, not a scan.
    """
    from atelier.index import ensure_index
    response.content_type = "application/json"
    path = (request.query.get("path") or "").strip("/")
    depth = len(path.split("/")) if path else 0
    pfx = (path.lower() + "/") if path else ""
    from atelier.index import prefix_entries
    acc = {}
    for p, _c, _x in prefix_entries(pfx):
        pl = p.lower()
        if not pl.endswith(".uasset"):
            continue
        parts = p.split("/")
        if len(parts) <= depth + 1:      # a file sitting directly in `path`, not a child folder
            continue
        child = parts[depth]
        e = acc.setdefault(child, {"name": child, "path": (path + "/" + child) if path else child,
                                   "materials": 0, "meshes": 0})
        b = os.path.basename(pl)
        if b.startswith("mi_"):
            e["materials"] += 1
        elif b.startswith("sk_") and not _MESH_SKIP.search(b[:-7]):
            e["meshes"] += 1
    out = [v for v in acc.values() if v["materials"] or v["meshes"]]
    try:
        from atelier.handlers.skinnames import label_for
        from atelier.catalogue import catalogue
        for v in out:
            display = catalogue.decorate({'type': 'folder', 'name': v['name'], 'rel_path': path.rstrip('/') + '/' + v['name']})
            v["label"] = ' · '.join(filter(None, (display.get('context_label'), display.get('display_name')))) or label_for(v["name"])
    except Exception:
        pass
    out.sort(key=lambda v: v["name"])
    return json.dumps({"path": path,
                       "up": "/".join(path.split("/")[:-1]) if path else None,
                       "dirs": out})

def _decoded_elsewhere(out_dir, name, since):
    """A <name>.glb the decoder wrote during this run somewhere other than the expected path (a
    different mount prefix or letter case), newest first — or None."""
    want, hits = (name + ".glb").lower(), []
    for dirpath, _dirs, files in os.walk(out_dir):
        for f in files:
            p = os.path.join(dirpath, f)
            if f.lower() == want and os.path.getmtime(p) >= since - 1:
                hits.append(p)
    return max(hits, key=os.path.getmtime) if hits else None

def _model_glb(game_rel):
    """Decode (cached) a mesh game_rel to a .glb and return its path, or raise saying why there is
    no model. The decoder's failure used to be dropped and the route answered a bare 404, which
    the viewer could only show as 'fetch ... responded with 404: Not Found'."""
    if os.path.isfile(project_base(game_rel)+'.blend') or os.path.isfile(project_base(game_rel)+'.asset.json'):
        from atelier.handlers.meshreplace import preview as edited_mesh_preview
        return edited_mesh_preview(game_rel)
    if import_server.available():
        return import_server.mesh(game_rel)
    asset   = pak_game_path(game_rel)                        # Marvel/Content/Marvel/.../SK_...
    out_dir = os.path.join(_CACHE, "gltf")
    glb     = os.path.join(out_dir, *asset.split("/")) + ".glb"
    if os.path.exists(glb):
        return glb
    name = os.path.basename(game_rel)
    from atelier.index import index_lookup
    if (game_rel.lower() + ".uasset") not in index_lookup():
        raise LookupError(f"{name} is not in the game files Atelier has indexed ({game_rel}), "
                          f"so there is no model to decode.")
    os.makedirs(out_dir, exist_ok=True)
    started = time.time()
    r = atelier_mesh(asset, out_dir)
    if os.path.exists(glb):
        return glb
    elsewhere = _decoded_elsewhere(out_dir, name, started)
    if elsewhere:
        return elsewhere
    detail = "\n".join(l for l in ((r.stderr or "") + (r.stdout or "")).splitlines() if l.strip())[-600:]
    message = (f"Atelier could not decode {name} (exit code {r.returncode})"
               + (f":\n{detail}" if detail else ", and it gave no reason."))
    # The decoder's own reason is often just "export failed". When it could also see installed
    # mods, a mod that overrides this mesh is the likeliest cause, and the user can test that.
    mods_note = getattr(r, "mods_note", None)
    if mods_note:
        message += (f"\n\nInstalled mods may be the cause: {mods_note}. If one of them changes "
                    f"{name}, move it out of the mods folder for now and reopen this model.")
    print(f"[model_gltf] {message}", file=sys.stderr, flush=True)
    raise RuntimeError(message)

@app.get("/api/model_gltf")
def api_model_gltf():
    gr = request.query.get("game_rel", "")
    if not gr:
        response.status = 400
        return b""
    try:
        glb = _model_glb(gr)
    except Exception as e:
        response.status = 404 if isinstance(e, LookupError) else 500
        response.content_type = "application/json"
        return json.dumps({"error": str(e)})
    if glb and os.path.exists(glb):
        result=static_file(os.path.basename(glb), root=os.path.dirname(glb),mimetype="model/gltf-binary")
        result.headers['Cache-Control']='no-store'
        return result
    response.status = 404
    response.content_type = "application/json"
    return json.dumps({"error": f"No model is available for {os.path.basename(gr)}."})

@app.post("/api/skin_materials")
def api_skin_materials():
    """Read the skin's MI materials, keyed by name (matches the glTF slot names), so the viewport
    can tint each mesh part and offer live recolor. Pass `names` (the mesh's slot names) to only
    read materials actually on the model; empty/omitted reads every MI under the skin folder."""
    body    = request.json or {}
    skin_id = body.get("skin_id", "")
    want    = set(str(n).lower() for n in (body.get("names") or []))
    response.content_type = "application/json"
    if not skin_id and not body.get('meshes'):
        return json.dumps({"ok": False, "error": "missing skin_id"})
    if body.get('meshes'):
        from atelier.handlers.meshstudio import material_bindings
        from atelier.handlers.texture import prefetch_exact
        bindings = list(material_bindings(skin_id, body['meshes']))
        # A cold character preview can reference dozens of materials. Extract
        # them together instead of rescanning the game containers for each one.
        try:
            if not import_server.available():
                prefetch_exact([binding.get('game_rel') for binding in bindings])
        except jobs.Cancelled:
            raise
        except Exception as exc:
            print(f'[skin_materials] material prefetch failed: {exc}', file=sys.stderr, flush=True)
        def read(gr):
            try:
                jobs.checkpoint()
                return _viewport_material_payload(gr, read_material(gr, cache_only=True))
            except jobs.Cancelled:
                raise
            except Exception as exc:
                return {'colors': [], 'scalars': [], 'textures': {}, 'material_error': str(exc)}
        paths = list(dict.fromkeys(binding.get('game_rel') for binding in bindings if binding.get('game_rel')))
        # Bound native conversions and preserve both project selection and preview
        # cancellation in every worker. Repeated slots share a single conversion.
        with ThreadPoolExecutor(max_workers=min(4, max(1, len(paths)))) as pool:
            pending = {gr: pool.submit(copy_context().run, read, gr) for gr in paths}
            materials = {gr: future.result() for gr, future in pending.items()}
        # The viewer needs only these channels. Extract them together before its
        # parallel PNG requests, avoiding a whole container scan per cold image.
        textures = []
        for params in materials.values():
            roles = params.get('texture_roles', {})
            custom = params.get('texture_urls', {})
            textures.extend(path for role, path in roles.items() if role in ('basecolor', 'emissive', 'opacity', 'iris', 'sclera') and role not in custom)
            if params.get('dyeable'):
                textures.extend(params.get('textures', {}).get(slot) for slot in ('BaseColor', 'DyeingTexture'))
        if any(textures) and not import_server.available():
            try:
                prefetch_exact(list(dict.fromkeys(path for path in textures if path)))
            except jobs.Cancelled:
                raise
            except Exception as exc:
                print(f'[skin_materials] texture prefetch failed: {exc}', file=sys.stderr, flush=True)
        empty = {'colors': [], 'scalars': [], 'textures': {}}
        out = {binding['key']: {**materials.get(binding.get('game_rel'), empty), **binding} for binding in bindings}
        return json.dumps({'ok': True, 'materials': out})
    out, seen = {}, set()
    for p, _c in skin_entries(skin_id):
        jobs.checkpoint()
        nm = os.path.basename(p)
        if not nm.upper().startswith("MI_") or not nm.lower().endswith(".uasset"):
            continue
        base = nm[:-7]
        if base in seen or (want and base.lower() not in want):
            continue
        seen.add(base)
        gr = game_rel_for_skin(skin_id, skin_rel(p, skin_id))
        try:
            params = read_material(gr, cache_only=True)
            jobs.checkpoint()
            # Dyeing materials must render the COMPOSITE, not the raw diffuse. Chromas differ only in
            # their "Region N" colours over the same mask+diffuse, so handing three.js the BaseColor
            # renders every chroma identically. Free to detect — the slot is already in `textures`.
            out[base] = _viewport_material_payload(gr, params)
        except Exception as e:
            print(f"[skin_materials] {base}: {e}", file=sys.stderr, flush=True)
    return json.dumps({"ok": True, "materials": out})


def _preview_surface(params, original=False):
    from atelier.handlers.material_preview import inherited_opacity, effect_surface, eye_layers
    from atelier.index import by_basename
    read = read_material_original if original else lambda path: read_material(path, cache_only=True)
    return eye_layers(effect_surface(inherited_opacity(params, read, by_basename), read, by_basename), by_basename)


def _viewport_material_payload(gr, params):
    import hashlib
    from atelier.handlers.meshmat import texture_role
    from atelier.handlers.material_preview import eye_material
    params = _preview_surface(params)
    texs = params.get('textures', {}) or {}
    roles, texture_urls, texture_sources = {}, {}, []
    custom = _custom_tex.assignments(gr) if gr else {}
    versions = {g: _tex_version(g) for g in texs.values()}
    for name, path in texs.items():
        role = texture_role(name)
        assignment = custom.get(name)
        source_path = _custom_tex.package_game_rel(gr, name, assignment['name'], assignment.get('folder')) if assignment else path
        source_url = '/api/material_custom_texture/preview?' + urlencode({
            'game_rel': gr, 'slot': name, 'v': assignment['file']}) if assignment else '/api/texture_png?' + urlencode({
                'game_rel': path, 'v': versions[path]})
        texture_sources.append({'slot': name, 'game_rel': source_path, 'role': role,
                                'preview_role': role if role and role not in roles else None,
                                'texture_class': assignment.get('texture_class', 'Texture2D') if assignment else (params.get('texture_classes') or {}).get(name),
                                'url': source_url, 'custom': bool(assignment),
                                'inferred': name in params.get('eye_defaults', [])})
        if role and role not in roles:
            roles[role] = path
            if name in custom:
                texture_urls[role] = '/api/material_custom_texture/preview?' + urlencode({
                    'game_rel': gr, 'slot': name, 'v': custom[name]['file']})
    dyeable = 'DyeingTexture' in texs
    eye = eye_material(params)
    eye_version = hashlib.sha256(json.dumps([versions, params.get('colors'), params.get('scalars'), custom], sort_keys=True).encode()).hexdigest() if eye else '0'
    return {'game_rel': gr, 'token': token(gr) if gr else None, **params, 'texture_roles': roles, 'texture_urls': texture_urls,
            'texture_sources': texture_sources,
            'tex_ver': versions, 'dyeable': dyeable,
            'dye_ver': _dye_version(gr, texs) if dyeable else '0', 'eye_preview': eye, 'eye_ver': eye_version}


@app.post('/api/assembly_references')
def api_assembly_references():
    from atelier.handlers.assembly import references
    body = request.json or {}
    response.content_type = 'application/json'
    return json.dumps(references(body.get('mesh_game_rel', ''), body.get('material_game_rel', '')))


@app.get('/api/assembly_thumbnail')
def api_assembly_thumbnail():
    from io import BytesIO
    from PIL import Image
    gr = request.query.get('game_rel', '')
    _c.validate_game_rel(gr)
    slot = request.query.getunicode('slot') or ''
    path = _custom_tex.image_path(gr, slot) if slot else _texture_png(gr)
    if not path or not os.path.isfile(path):
        response.status = 404
        return ''
    with Image.open(path) as source:
        source.thumbnail((160, 160), Image.Resampling.LANCZOS)
        image = source.convert('RGBA')
        output = BytesIO()
        image.save(output, 'PNG')
    response.content_type = 'image/png'
    response.set_header('Cache-Control', 'no-store')
    return output.getvalue()


@app.post('/api/mesh_visibility')
def api_mesh_visibility():
    from atelier.handlers.meshvisibility import set_hidden
    body = request.json or {}
    return set_hidden(body.get('game_rel', ''), body.get('slot_index'), body.get('slot_name'), body.get('hidden'))


@app.get("/api/idle_animations")
def api_idle_animations():
    from atelier.handlers.animation import idle_candidates
    try:
        return {"ok": True, "animations": idle_candidates(request.query.get('game_rel', ''))}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@app.post("/api/idle_animation")
def api_idle_animation():
    from atelier.handlers.animation import decode_idle
    body = request.json or {}
    try:
        return {"ok": True, **decode_idle(body.get('game_rel', ''), body.get('animation_rel', ''))}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

def _tex_version(game_rel):
    """Cache-busting stamp for a texture: mtime of the user's edited PNG if one exists, else '0'
    (vanilla). The viewport keys its GPU-texture cache on this, so edits invalidate while vanilla
    textures stay cached across opens."""
    edited = _import_base(game_rel) + ".png"
    try:
        return str(os.stat(edited).st_mtime_ns) if os.path.exists(edited) else import_server.source_version() if import_server.available() else "0"
    except OSError:
        return "0"

def _dye_version(game_rel, texs):
    """Cache-busting stamp for a dyed composite. It changes when the Region colours are re-saved
    (the material's project JSON) OR when the mask/diffuse are edited — those are its three inputs."""
    parts = []
    jp = project_base(game_rel) + ".json"
    try:
        parts.append(str(os.stat(jp).st_mtime_ns) if os.path.exists(jp) else "0")
    except OSError:
        parts.append("0")
    for slot in ("DyeingTexture", "BaseColor"):
        g = (texs or {}).get(slot)
        if g:
            parts.append(_tex_version(g))
        parts.append((_custom_tex.assignments(game_rel).get(slot) or {}).get('file', '0'))
    return "-".join(parts)

def _texture_png(game_rel, original=False):
    """PNG path for a texture game_rel. Prefers the user's EDITED/imported PNG in the active project
    (so viewport shows their edits); otherwise extracts + decodes the vanilla texture from the paks
    (cached in CACHE_3DVIEW). Returns a path or None."""
    edited = _import_base(game_rel) + ".png"
    if not original and os.path.exists(edited):
        return edited
    if import_server.available():
        try:
            return import_server.texture(game_rel)
        except import_server.ImportError as exc:
            print(f'[import] texture compatibility fallback for {game_rel}: {exc}', file=sys.stderr, flush=True)
    out_dir = CACHE_3DVIEW
    base    = project_base(game_rel, out_dir)   # no ext, subfolder-mirrored (no basename collisions)
    out_png = base + ".png"
    if os.path.exists(out_png):
        return out_png
    # Everything below extracts + decodes (a UAssetTool cold-start + a full-res texture in RAM). The
    # viewport fires these ~2N-at-once, so gate the heavy work behind tex_semaphore to cap concurrent
    # processes/memory — that swarm is what crashes the viewport on big skins. Re-check the cache
    # inside the gate: a sibling request for the same texture may have finished while we waited.
    from atelier.tools import tex_semaphore
    with jobs.cancellable_lock(tex_semaphore):
        if os.path.exists(out_png):
            return out_png
        cb = ensure_work_base(game_rel,prefer_exact=True)  # exact container/path first; bounded fallback when needed
        jobs.checkpoint()
        if not cb or not os.path.exists(cb + ".uasset"):
            return None
        return _decode_texture_png(game_rel, base, out_png, cb)

def _decode_texture_png(game_rel, base, out_png, cb):
    # MR strips the top mip on big textures; decode_png (UAssetTool) then falls back to the 4x4 tail
    # and the viewport shows a solid smear. decode_to_png recovers the largest SHIPPED mip from the
    # .uptnl/.ubulk and only falls back to UAssetTool when there's no recoverable block data.
    from atelier.handlers.texture import decode_to_png
    from PIL import Image
    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.viewport-texture-', dir=os.path.dirname(out_png)) as scratch:
        decoded = decode_to_png(os.path.join(scratch, os.path.basename(base)), cb)
        if not decoded:
            return None
        with Image.open(decoded) as image:
            image.verify()
        jobs.checkpoint()
        os.replace(decoded, out_png)
    return out_png

@app.get("/api/texture_png")
def api_texture_png():
    """Decode a texture game_rel to PNG and serve it (for the viewport to apply as a mesh map)."""
    gr = request.query.get("game_rel", "")
    if not gr:
        response.status = 400
        return b""
    try:
        png = _texture_png(gr, original=True) if request.query.get("original") == "1" else _texture_png(gr)
    except Exception as e:
        response.status = 500
        response.content_type = "application/json"
        return json.dumps({"error": str(e)})
    if png and os.path.exists(png):
        return static_file(os.path.basename(png), root=os.path.dirname(png), mimetype="image/png")
    response.status = 404
    return b""

@app.get('/api/eye_texture')
@app.post('/api/eye_preview')
def api_eye_texture():
    from atelier.handlers.material_preview import eye_image, eye_material
    from PIL import Image
    import hashlib
    body = (request.json or {}) if request.method == 'POST' else {}
    if not isinstance(body, dict):
        response.status = 400
        return {'ok': False, 'error': 'Invalid eye preview request'}
    gr = body.get('game_rel') or request.query.get('game_rel', '')
    original = request.query.get('original') == '1'
    try:
        _c.validate_game_rel(gr)
        params = _preview_surface(read_material_original(gr) if original else read_material(gr, cache_only=True), original=original)
        if not eye_material(params):
            raise ValueError('This material has no iris and sclera colour layers')
        overrides = {} if original else body.get('overrides') or {}
        if not isinstance(overrides, dict) or len(overrides) > 256:
            raise ValueError('Invalid eye colour overrides')
        if overrides:
            colors = []
            for color in params.get('colors', []):
                rgba = overrides.get(color['name'], color['rgba'])
                if not isinstance(rgba, list) or len(rgba) != 4 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in rgba):
                    raise ValueError('Invalid eye colour override')
                colors.append({**color, 'rgba': rgba})
            params = {**params, 'colors': colors}
        images = []
        for slot in ('IrisBaseColor', 'ScleraBaseColor'):
            path = None if original else _custom_tex.image_path(gr, slot)
            path = path or _texture_png(params['textures'][slot], original=original)
            if not path or not os.path.isfile(path):
                raise ValueError('An eye colour texture is unavailable')
            images.append(path)
        stamp = [(os.path.realpath(path), os.stat(path).st_mtime_ns, os.path.getsize(path)) for path in images]
        identity = hashlib.sha256(json.dumps(['eye-v1', stamp, params.get('colors', []), params.get('scalars', [])], sort_keys=True).encode()).hexdigest()
        directory = os.path.join(CACHE_3DVIEW, 'eyes')
        os.makedirs(directory, exist_ok=True)
        target = os.path.join(directory, identity + '.png')
        if not os.path.isfile(target):
            with Image.open(images[0]) as iris, Image.open(images[1]) as sclera:
                image = eye_image(iris, sclera, params)
            with tempfile.TemporaryDirectory(prefix='.eye-', dir=directory) as scratch:
                temporary = os.path.join(scratch, 'eye.png')
                image.save(temporary, 'PNG')
                jobs.checkpoint()
                os.replace(temporary, target)
        result = static_file(os.path.basename(target), root=directory, mimetype='image/png')
        result.headers['Cache-Control'] = 'no-store'
        return result
    except (ValueError, OSError) as error:
        response.status = 400
        return {'ok': False, 'error': str(error)}

@app.post("/api/showcase_webp")
def api_showcase_webp():
    from atelier.web.showcase import MAX_CAPTURE_BYTES, encode_turntable, capture_frames
    if request.content_length > MAX_CAPTURE_BYTES:
        response.status = 413
        return {"ok": False, "error": "Capture exceeds 24 MB"}
    try:
        data = encode_turntable(capture_frames(request.body))
    except (ValueError, OSError) as exc:
        response.status = 400
        return {"ok": False, "error": str(exc)}
    response.content_type = "image/webp"
    response.set_header("Content-Disposition", 'attachment; filename="showcase.webp"')
    return data


# ── dyeing / ID-mask preview ──────────────────────────────────────────────────
@app.get("/api/dye_texture")
def api_dye_texture():
    """The dyed albedo for a dyeing MI, as a plain GET so the viewport's TextureLoader can take it
    like any other map. `v` is only a cache-buster (see _dye_version)."""
    gr = request.query.get("game_rel", "")
    if not gr:
        response.status = 400
        return b""
    try:
        from atelier.handlers.dye import dye_preview
        png = dye_preview(gr, size=int(request.query.get("size") or 1024),
                          dye_off=request.query.get("dye_off") == "1",
                          original=request.query.get("original") == "1")
    except Exception as e:
        print(f"[dye_texture] {gr}: {e}", file=sys.stderr, flush=True)
        response.status = 404
        return b""
    if png and os.path.exists(png):
        return static_file(os.path.basename(png), root=os.path.dirname(png), mimetype="image/png")
    response.status = 404
    return b""

@app.get("/api/dye_overlay")
def api_dye_overlay():
    """The ID-mask region map: the same ColorID mask the dye preview composites, but coloured BY
    REGION INDEX and numbered, so "which colour do I edit for this part" is a picture instead of
    trial and error. Preview only — this never ships into a mod."""
    gr = request.query.get("game_rel", "")
    if not gr:
        response.status = 400
        return b""
    try:
        from atelier.handlers.dye import region_overlay
        png = region_overlay(gr, size=int(request.query.get("size") or 1024))
    except Exception as e:
        print(f"[dye_overlay] {gr}: {e}", file=sys.stderr, flush=True)
        response.status = 404
        return b""
    if png and os.path.exists(png):
        return static_file(os.path.basename(png), root=os.path.dirname(png), mimetype="image/png")
    response.status = 404
    return b""

@app.get("/api/dye_info")
def api_dye_info():
    """Regions + current colours for a dyeing material, and which regions the mask actually uses."""
    gr = request.query.get("game_rel", "")
    response.content_type = "application/json"
    if not gr:
        response.status = 400
        return json.dumps({"error": "game_rel required"})
    try:
        from atelier.handlers.dye import dye_info
        return json.dumps(dye_info(gr))
    except Exception as e:
        response.status = 500
        return json.dumps({"error": str(e)})

def _dye_png(gr, overrides, size, dye_off=False):
    from atelier.handlers.dye import dye_preview
    return dye_preview(gr, overrides=overrides, size=size, dye_off=dye_off)

@app.post("/api/dye_preview")
def api_dye_preview():
    """Composite a dye preview and serve it. Body may carry unsaved {region: {param: rgba}} so a
    colour pick previews before it's saved."""
    try:
        body = request.json or {}
    except Exception:
        body = {}
    gr = body.get("game_rel", "")
    if not gr:
        response.status = 400
        response.content_type = "application/json"
        return json.dumps({"error": "game_rel required"})
    try:
        png = _dye_png(gr, body.get("overrides") or None, int(body.get("size") or 1024),
                       bool(body.get("dye_off")))
    except Exception as e:
        response.status = 500
        response.content_type = "application/json"
        return json.dumps({"error": str(e)})
    if png and os.path.exists(png):
        return static_file(os.path.basename(png), root=os.path.dirname(png), mimetype="image/png")
    response.status = 404
    return b""

@app.post("/api/dye_download")
def api_dye_download():
    """QoL: bake the dyed result to a full-res PNG the user can take into an image editor as a
    starting point. Same composite as the preview, just at the mask's native size and served as an
    attachment."""
    try:
        body = request.json or {}
    except Exception:
        body = {}
    gr = body.get("game_rel", "")
    if not gr:
        response.status = 400
        response.content_type = "application/json"
        return json.dumps({"error": "game_rel required"})
    try:
        png = _dye_png(gr, body.get("overrides") or None, int(body.get("size") or 2048),
                       bool(body.get("dye_off")))
    except Exception as e:
        response.status = 500
        response.content_type = "application/json"
        return json.dumps({"error": str(e)})
    if png and os.path.exists(png):
        name = os.path.basename(gr) + "_dyed.png"
        return static_file(os.path.basename(png), root=os.path.dirname(png),
                           mimetype="image/png", download=name)
    response.status = 404
    return b""

@app.post("/api/mat_textures_download")
def api_mat_textures_download():
    """Every texture this material uses, zipped, at native size, with a manifest naming the slots.

    chopthememegod asked for the dyed download to cover the other texture types and was told
    "noted". One dyed BaseColor is not a starting point on its own — repainting needs the normal,
    the ORM and the ColorID next to it, and needs to say which file is which slot."""
    try:
        body = request.json or {}
    except Exception:
        body = {}
    gr = body.get("game_rel", "")
    if not gr:
        response.status = 400
        response.content_type = "application/json"
        return json.dumps({"error": "game_rel required"})
    try:
        from atelier.handlers.dye import texture_bundle
        zp, _slots = texture_bundle(gr, overrides=body.get("overrides") or None,
                                    size=int(body.get("size") or 2048),
                                    dye_off=bool(body.get("dye_off")))
    except Exception as e:
        response.status = 500
        response.content_type = "application/json"
        return json.dumps({"error": str(e)})
    return static_file(os.path.basename(zp), root=os.path.dirname(zp),
                       mimetype="application/zip", download=os.path.basename(gr) + "_textures.zip")

# ── prereqs ───────────────────────────────────────────────────────────────────

@app.get("/api/index_warnings")
def api_index_warnings():
    """Pak containers that failed to parse during the last index build.

    A failed container is invisible in the asset browser — every asset inside it simply is not
    there. Surfacing this turns "Atelier shows nothing / material not found" into a report that
    names the container and points at the AES key."""
    response.content_type = "application/json"
    try:
        import atelier.index as _idx
        return json.dumps({"ok": True, "failed": _idx.index_warnings()})
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e), "failed": []})


@app.get("/api/content_mounts")
def api_content_mounts():
    """Which content mounts the index actually read, and whether Marvel_LQ is one of them.

    "More asset roots (UI/Textures, Marvel_LQ)" was closed with "it should be fixed now" and then
    reopened by fawnls, who still had no Marvel_LQ node — with no way to tell a hidden root from an
    absent one. Both answers are now facts the app can show, and they are different sentences."""
    response.content_type = "application/json"
    try:
        from atelier.index import content_mounts, _LQ_PREFIX
        mounts = content_mounts()
        return json.dumps({"ok": True,
                           "mounts": [{"mount": k, "assets": v} for k, v in sorted(mounts.items())],
                           "has_lq": _LQ_PREFIX in mounts})
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e), "mounts": [], "has_lq": False})

@app.get("/api/stale_mips")
def api_stale_mips():
    """Imported textures now below the resolution the paks can give — the HQ texture DLC arriving
    after they were imported.

    The work cache fixes itself; a project PNG cannot be fixed for the user, because it is their
    artwork and re-importing an edited texture means redoing the edit at the larger size. So this
    reports and lets them decide."""
    response.content_type = "application/json"
    try:
        from atelier.handlers.texture import stale_mip_imports
        items = stale_mip_imports()
        return json.dumps({"ok": True, "items": items, "count": len(items)})
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e), "items": [], "count": 0})

@app.post('/api/refresh_texture_mips')
def api_refresh_texture_mips():
    from atelier.handlers.texturerefresh import repair
    return _submit_job('texture-refresh','Refresh high-resolution textures',lambda job:repair())


@app.post('/api/revert_imported')
def api_revert_imported():
    from atelier.handlers.projectedit import revert
    game_rel=(request.json or {}).get('game_rel','')
    _c.validate_game_rel(game_rel)
    return _submit_job('asset-revert','Revert '+os.path.basename(game_rel),lambda job:revert(game_rel))


@app.get("/api/prereqs")
def api_prereqs():
    response.content_type = "application/json"
    return json.dumps(get_prereq_status())

# ── first-run setup ───────────────────────────────────────────────────────────

def _find_mr_root(path):
    """Find the game root by walking up path until */MarvelGame/Marvel/Content/Paks exists."""
    norm  = path.replace("\\", "/").rstrip("/")
    parts = norm.split("/")
    for i in range(len(parts), 0, -1):
        candidate = "/".join(parts[:i])
        if os.path.isdir(candidate + "/MarvelGame/Marvel/Content/Paks"):
            return candidate
    return None

def _mr_root_to_display(paks_path):
    """Given a stored Paks path, return the game root for display in the frontend."""
    mr = _find_mr_root(paks_path)
    if mr:
        return mr
    # Fallback: strip the known paks suffix if present
    norm = paks_path.replace("\\", "/").rstrip("/")
    suffix = "/marvelgame/marvel/content/paks"
    if norm.lower().endswith(suffix):
        return norm[:-len(suffix)]
    return norm

@app.get("/api/setup_status")
def api_setup_status():
    cfg  = _c._load_config()
    paks = cfg.get("paks", "")
    aes  = cfg.get("aes_key", "")
    configured = bool(paks) and bool(aes) and bool(_c.USMAP)
    if paks:
        mr_prefill = _mr_root_to_display(paks)
    else:
        suggestion = _c.paks_suggestion()
        mr_prefill = _mr_root_to_display(suggestion) if suggestion else ""
    aes_prefill  = ("0x" + aes) if aes else ""
    usmap_prefill = (_c.USMAP or "").replace("\\", "/")
    from atelier.handlers.meshedit import blender_path_suggestion
    response.content_type = "application/json"
    return json.dumps({"configured": configured,
                       "paks_prefill":  mr_prefill,
                       "aes_prefill":   aes_prefill,
                       "usmap_prefill": usmap_prefill,
                       "mods_prefill":  get_mods_folder(),
                       "password_prefill": get_export_password(),
                       "blender_prefill": blender_path_suggestion()})

@app.post("/api/pick_folder")
def api_pick_folder():
    body    = request.json or {}
    initial = body.get("initial") or ""
    raw_pick = bool(body.get("raw"))   # raw=True returns the chosen folder as-is (e.g. mods folder,
                                       # which can be named anything); default resolves the MR root.
    desc    = (body.get("desc") or ("Select a folder:" if raw_pick else "Select your MarvelRivals folder:"))
    response.content_type = "application/json"
    try:
        raw = hostos.pick_folder(initial, desc)
        path = raw if raw_pick else ((_find_mr_root(raw) if raw else "") or raw)
        return json.dumps({"ok": True, "path": path})
    except Exception as e:
        return json.dumps({"ok": False, "path": "", "error": str(e)})

@app.get("/api/validate_paks")
def api_validate_paks():
    path = request.query.get("path", "").strip()
    response.content_type = "application/json"
    if not path:
        return json.dumps({"status": "empty"})
    mr = _find_mr_root(path)
    if not mr:
        return json.dumps({"status": "wrong_folder"})
    if not os.path.isdir(mr):
        return json.dumps({"status": "missing"})
    # The live validator behind the green tick in Settings. It goes through the SAME check as the
    # save handler and the prereq screen: this is the field that told users "every path is valid"
    # while the app refused to start, because it tested for one literal filename and the prereq
    # check globbed for containers.
    return json.dumps({"status": "wrong_folder" if _validate_and_build_paks(path)[1] else "ok"})

@app.get("/api/validate_mods_folder")
def api_validate_mods_folder():
    """Live validation for the Settings mods-folder input. Any folder that exists (or whose parent
    exists, since Install Mod creates it via makedirs) is fine — only an existing non-folder path
    is actually invalid."""
    path = request.query.get("path", "").strip()
    response.content_type = "application/json"
    if not path:
        return json.dumps({"status": "empty"})
    p = path.replace("\\", "/").rstrip("/")
    if os.path.isfile(p):
        return json.dumps({"status": "invalid"})
    parent = os.path.dirname(p) or p
    if os.path.isdir(p) or os.path.isdir(parent):
        return json.dumps({"status": "ok"})
    return json.dumps({"status": "missing"})

@app.get("/api/validate_blender")
def api_validate_blender():
    from atelier.handlers.meshedit import BLENDER_NAMES
    path = request.query.get("path", "").strip()
    response.content_type = "application/json"
    if not path:
        return json.dumps({"status": "empty"})
    if os.path.basename(path).lower() not in {name.lower() for name in BLENDER_NAMES}:
        return json.dumps({"status": "invalid"})
    if not os.path.exists(path):
        return json.dumps({"status": "missing"})
    return json.dumps({"status": "ok"})

@app.post("/api/pick_blender_file")
def api_pick_blender_file():
    from atelier.handlers.meshedit import BLENDER_NAMES
    body    = request.json or {}
    initial = body.get("initial") or ""
    response.content_type = "application/json"
    try:
        title = "Select blender.exe" if hostos.IS_WINDOWS else "Select the blender executable"
        return json.dumps({"ok": True, "path": hostos.pick_file(
            title, BLENDER_NAMES, initial)})
    except Exception as e:
        return json.dumps({"ok": False, "path": "", "error": str(e)})

@app.get("/api/blender_status")
def api_blender_status():
    """Cheap pre-flight for anything about to shell out to Blender. Frontend calls this before
    an extract/open so it can toast immediately instead of after the slow extraction runs."""
    from atelier.handlers.meshedit import find_blender
    response.content_type = "application/json"
    try:
        return json.dumps({"ok": True, "path": find_blender()})
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)})

def _validate_and_build_paks(path):
    """Validate user-supplied path (game root or subfolder) and return (paks_path, error).

    Defers to config.has_pak_files for the "is this really a paks folder" half. This used to test
    for a literal pakchunkCharacter-Windows.ucas while the prereq check globbed pakchunk*.utoc, so
    a path containing glob metacharacters (D:/[Steam]/...) passed here and failed there — Settings
    said every path was valid while the app said "No pak files found"."""
    mr = _find_mr_root(path)
    if not mr:
        return None, "MarvelGame/Marvel/Content/Paks not found in path"
    paks = mr + "/MarvelGame/Marvel/Content/Paks"
    if not _c.has_pak_files(paks):
        return None, f"no pakchunk*.utoc containers found in {paks} — wrong folder"
    return paks, None

def _path_under(child, parent):
    """True when child is parent or inside it (case- and separator-insensitive on Windows)."""
    if not child or not parent:
        return False
    try:
        c = os.path.normcase(os.path.normpath(child))
        p = os.path.normcase(os.path.normpath(parent))
        return c == p or c.startswith(p + os.sep)
    except Exception:
        return False

@app.post("/api/save_paks")
def api_save_paks():
    body       = request.json or {}
    path       = body.get("path", "").strip()
    aes_key    = body.get("aes_key", "").strip()  # stored without 0x prefix
    usmap_path = body.get("usmap_path", "").strip()
    has_mods   = "mods_folder" in body            # only touch mods config when the field was sent
    mods_folder = (body.get("mods_folder") or "").strip()
    has_pw     = "export_password" in body        # only touch password config when the field was sent
    export_password = (body.get("export_password") or "").strip()
    has_blender = "blender_path" in body           # only touch blender config when the field was sent
    blender_path = (body.get("blender_path") or "").strip()
    if not path:
        response.content_type = "application/json"
        return json.dumps({"ok": False, "error": "no path provided"})
    if not aes_key:
        response.content_type = "application/json"
        return json.dumps({"ok": False, "error": "no AES key provided"})
    try:
        aes_key = _c.normalize_aes_key(aes_key)
    except ValueError as e:
        # Reject a malformed key HERE. Saved unchecked, it used to be written out and only show up
        # later as an empty asset browser with nothing pointing back at the typo.
        response.content_type = "application/json"
        return json.dumps({"ok": False, "error": str(e)})
    from atelier.handlers.meshedit import BLENDER_NAMES, is_blender_executable
    if has_blender and blender_path and not is_blender_executable(blender_path):
        # Every Blender step launches this path unprompted; checked before anything is saved.
        response.content_type = "application/json"
        return json.dumps({"ok": False, "error":
                           f"The Blender path must be an existing {BLENDER_NAMES[0]} file."})
    paks_path, err = _validate_and_build_paks(path)
    if err:
        response.content_type = "application/json"
        return json.dumps({"ok": False, "error": err})
    try:
        save_setup_config(paks_path, aes_key,
                          usmap_path if (usmap_path and os.path.exists(usmap_path)) else None)
        mods_now = mods_folder if has_mods else get_mods_folder()
        mods_reset = False
        if has_mods and mods_folder == "":
            save_mods_folder("")   # empty string clears it
        else:
            # The game only loads mods from under its own Paks dir. A folder anywhere else (e.g. a
            # path carried over from another machine or an old install) can never have worked, so
            # re-point it to this game's ~mods and tell the user. Nothing configured yet is the
            # initial-setup case: default there too, so "Copy to ~mods/" works without Settings.
            if _path_under(mods_now, paks_path):
                target = mods_now
            else:
                target = paks_path + "/~mods"
                mods_reset = bool(mods_now)
            try:
                os.makedirs(target, exist_ok=True)
            except OSError:
                pass
            save_mods_folder(target)
        if has_pw:
            save_export_password(export_password)   # empty string clears it
        if has_blender:
            save_blender_path(blender_path)          # empty string clears it

        # One call writes AES_KEY.txt (for UAssetTool), io_lib.AES_KEY (for our own pak reader)
        # and drops the in-memory index. The DISK index cache needs no special handling: its key
        # includes an AES fingerprint, so the build made under the old key can no longer match.
        # That is the fix for "entered the correct key and the tree is still empty".
        _c.set_aes_key(aes_key)

        _c.PAKS = paks_path
        _c.CONFIG_HAS_PAKS = True
        global PAKS
        PAKS = paks_path

        import atelier.index as _idx
        _idx.PAKS = paks_path
        _idx._INDEX = None  # force re-index with new path

        _pak_thumb_mod.PAKS = paks_path
        with _pak_thumb_mod._toc_lock:  _pak_thumb_mod._toc_cache.clear()
        with _pak_thumb_mod._gr_map_lock: _pak_thumb_mod._gr_to_cont.clear()
        _pak_thumb_mod._gr_map_ready = False
        _pak_thumb_mod.start_warmup()

        if usmap_path and os.path.exists(usmap_path):
            _c.USMAP = usmap_path
            import atelier.handlers.texture as _tex
            import atelier.handlers.material as _mat
            import atelier.handlers.vfx     as _vfx
            _tex.USMAP = usmap_path
            _mat.USMAP = usmap_path
            _vfx.USMAP = usmap_path

        response.content_type = "application/json"
        return json.dumps({"ok": True, "mods_folder": get_mods_folder(),
                           "mods_folder_reset": mods_reset,
                           "export_password": get_export_password()})
    except Exception as e:
        response.content_type = "application/json"
        return json.dumps({"ok": False, "error": str(e)})

@app.get("/api/open_discord_key")
def api_open_discord_key():
    url = "https://discord.com/channels/1419106202511609958/1485413590310584374/1485417747834863616"
    try: hostos.open_path(url)
    except Exception: pass
    response.content_type = "application/json"
    return json.dumps({"ok": True})

# ── auto-update ───────────────────────────────────────────────────────────────

_update_cache      = None   # {"tag": str, "download_url": str} set by update_check
_update_state      = "idle" # idle | downloading | error
_update_state_lock = threading.Lock()
_update_progress   = {"pct": 0, "bytes": 0, "total": 0}


@app.get("/api/update_check")
def api_update_check():
    global _update_cache
    response.content_type = "application/json"

    try:
        with open(VERSION_FILE, "r") as f:
            current = tuple(int(x) for x in f.read().strip().split("."))
        print(f"[update] current version: {current}")
    except Exception as e:
        print(f"[update] failed to read version: {e}")
        return json.dumps({"available": False})

    try:
        req = urllib.request.Request(
            "https://api.github.com/repos/clownfetus/Atelier/releases/latest",
            headers={"User-Agent": "Atelier-Updater"},
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read().decode())
        if not data or "tag_name" not in data:
            return json.dumps({"available": False})
    except Exception as e:
        print(f"[update] GitHub request failed: {e}")
        return json.dumps({"available": False})

    tag = data.get("tag_name", "")
    try:
        remote = tuple(int(x) for x in tag.lstrip("v").split("."))
    except Exception:
        return json.dumps({"available": False})

    if remote <= current:
        print(f"[update] up to date ({current} >= {remote})")
        return json.dumps({"available": False})

    release_url = data.get("html_url") or f"https://github.com/clownfetus/Atelier/releases/tag/{tag}"

    # Only Windows updates in place (Inno Setup installer). Elsewhere the same prompt sends the
    # user to the release page to grab the new AppImage by hand.
    if not hostos.IS_WINDOWS:
        _update_cache = {"tag": tag, "download_url": None, "release_url": release_url}
        print(f"[update] update available: {current} -> {remote} (manual, via release page)")
        return json.dumps({"available": True, "tag": tag, "manual": True})

    download_url = None
    for asset in data.get("assets", []):
        if asset["name"] == "AtelierSetup.exe":
            download_url = asset["browser_download_url"]
            break
    if not download_url:
        print("[update] AtelierSetup.exe not found in release assets")
        return json.dumps({"available": False})

    _update_cache = {"tag": tag, "download_url": download_url, "release_url": release_url}
    print(f"[update] update available: {current} -> {remote}")
    return json.dumps({"available": True, "tag": tag})


# ── native tool updates (Settings > Tools) ─────────────────────────────────────
# Game patches break container tools long before an Atelier release can ship. These routes install
# reviewed, hash-pinned tool builds from the update channel (atelier/tool_updates.py).
@app.get("/api/tools_status")
def api_tools_status():
    from atelier import tool_updates
    response.content_type = "application/json"
    return json.dumps(tool_updates.status(check=request.query.get("check") == "1"))


@app.post("/api/tools_update")
def api_tools_update():
    from atelier import tool_updates
    response.content_type = "application/json"
    name = (request.json or {}).get("name")
    try:
        if name:
            return json.dumps({"ok": True, "updated": [name], "tool": tool_updates.install(name)})
        return json.dumps(tool_updates.update_all())
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)})


@app.post("/api/tools_repair")
def api_tools_repair():
    from atelier import tool_updates
    response.content_type = "application/json"
    try:
        return json.dumps(tool_updates.repair())
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)})


@app.post("/api/tools_rollback")
def api_tools_rollback():
    from atelier import tool_updates
    response.content_type = "application/json"
    try:
        return json.dumps({"ok": True, "tool": tool_updates.rollback((request.json or {}).get("name", ""))})
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)})


@app.post("/api/update_open_release")
def api_update_open_release():
    response.content_type = "application/json"
    if not _update_cache:
        return json.dumps({"ok": False})
    try: hostos.open_path(_update_cache["release_url"])
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)})
    return json.dumps({"ok": True})


@app.post("/api/update_download")
def api_update_download():
    global _update_state
    response.content_type = "application/json"
    if not _update_cache:
        return json.dumps({"ok": False, "error": "no update info cached"})
    with _update_state_lock:
        if _update_state == "downloading":
            return json.dumps({"ok": True})
        _update_state = "downloading"
    threading.Thread(target=_do_update_download, args=(_update_cache["download_url"],), daemon=True).start()
    return json.dumps({"ok": True})


@app.get("/api/update_status")
def api_update_status():
    response.content_type = "application/json"
    return json.dumps({"state": _update_state})


@app.get("/api/update_progress")
def api_update_progress():
    response.content_type = "application/json"
    return json.dumps(_update_progress)


def _do_update_download(download_url):
    """Downloads and runs the Inno Setup installer. Windows-only by construction — releases ship
    an .exe installer, and on Linux update_check offers the release page instead."""
    global _update_state, _update_progress
    if not hostos.IS_WINDOWS:
        print("[update] in-app update is Windows-only; download the new release from the release page")
        with _update_state_lock:
            _update_state = "error"
        return
    tmp_path = os.path.join(tempfile.gettempdir(), "AtelierSetup.exe")

    def _reporthook(block_num, block_size, total_size):
        global _update_progress
        if total_size > 0:
            downloaded = min(block_num * block_size, total_size)
            _update_progress = {
                "pct":   int(downloaded * 100 / total_size),
                "bytes": downloaded,
                "total": total_size,
            }

    try:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        print(f"[update] downloading to {tmp_path}...")
        urllib.request.urlretrieve(download_url, tmp_path, reporthook=_reporthook)
        print("[update] download complete, launching installer...")
    except Exception as e:
        print(f"[update] download failed: {e}")
        with _update_state_lock:
            _update_state = "error"
        return
    subprocess.Popen(
        [tmp_path, "/SILENT"],
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        close_fds=True,
    )
    print("[update] installer launched, exiting...")
    os._exit(0)


# ── USMAP management ──────────────────────────────────────────────────────────

@app.get("/api/validate_usmap")
def api_validate_usmap():
    path = request.query.get("path", "").strip()
    response.content_type = "application/json"
    if not path:
        return json.dumps({"status": "empty"})
    if not path.lower().endswith(".usmap"):
        return json.dumps({"status": "invalid"})
    if not os.path.exists(path):
        return json.dumps({"status": "missing"})
    return json.dumps({"status": "ok"})

@app.post("/api/pick_usmap_file")
def api_pick_usmap_file():
    body    = request.json or {}
    initial = (body.get("initial") or "").replace("/", "\\")
    response.content_type = "application/json"
    try:
        return json.dumps({"ok": True, "path": hostos.pick_file(
            "Select USMAP mapping file", ("*.usmap",), initial)})
    except Exception as e:
        return json.dumps({"ok": False, "path": "", "error": str(e)})

@app.post("/api/download_usmap")
def api_download_usmap():
    try:
        latest = _get_latest_usmap_from_github()
        if not latest:
            response.content_type = "application/json"
            return json.dumps({"ok": False, "error": "No matching USMAP found on GitHub"})
        mappings_dir = os.path.join(_c.TOOLS, "Mappings")
        dest_path    = os.path.join(mappings_dir, latest["name"])
        if not os.path.exists(dest_path):
            _download_usmap_file(latest["download_url"], dest_path)
        response.content_type = "application/json"
        return json.dumps({"ok": True, "path": dest_path.replace("\\", "/"), "name": latest["name"]})
    except Exception as e:
        response.content_type = "application/json"
        return json.dumps({"ok": False, "error": str(e)})

_usmap_check_running = False
_usmap_check_lock    = threading.Lock()

@app.get("/api/usmap_update_check")
def api_usmap_update_check():
    global _usmap_check_running
    last = _c.get_usmap_checked_at()
    if time.time() - last < _THREE_DAYS:
        response.content_type = "application/json"
        return json.dumps({"ok": True, "updated": False})
    with _usmap_check_lock:
        if _usmap_check_running:
            response.content_type = "application/json"
            return json.dumps({"ok": True, "checking": True})
        _usmap_check_running = True

    def _check():
        global _usmap_check_running
        try:
            latest = _get_latest_usmap_from_github()
            if not latest:
                return
            latest_name  = latest["name"]
            current_name = os.path.basename(_c.USMAP) if _c.USMAP else ""
            _c.save_usmap_checked_at(time.time())
            if latest_name == current_name:
                return
            mappings_dir = os.path.join(_c.TOOLS, "Mappings")
            dest_path    = os.path.join(mappings_dir, latest_name)
            _download_usmap_file(latest["download_url"], dest_path)
            # Consumers imported USMAP at startup. Keep that file and active value until restart;
            # only pin the downloaded mapping for the next launch, as the non-blocking notice says.
            _c.save_usmap_config(dest_path)
            _push_sse({"usmap_updated": True, "name": latest_name})
        except Exception:
            pass  # silent fail — will retry on next launch
        finally:
            with _usmap_check_lock:
                _usmap_check_running = False

    threading.Thread(target=_check, daemon=True).start()
    response.content_type = "application/json"
    return json.dumps({"ok": True, "checking": True})

# ── browse (unified) ──────────────────────────────────────────────────────────

@app.get('/api/startup_progress')
def api_startup_progress():
    from atelier.index import index_progress
    response.content_type = 'application/json'
    return json.dumps(index_progress())


@app.get('/api/catalogue/library')
def api_catalogue_library():
    from atelier.catalogue import catalogue
    with catalogue.lock:
        entries = dict(catalogue.data.get('entries', {}))
    def describe(key, entry):
        path = 'Characters/' + (key if len(key) == 4 else key[:4] + '/' + key)
        return {'name': entry.get('name') or key, 'path': path,
                'thumbnail': '/api/catalogue/thumbnail/' + key, 'hero_fallback': entry.get('hero_fallback', False)}
    heroes = []
    for key, entry in entries.items():
        if not re.fullmatch(r'10\d{2}', key) or entry.get('kind') != 'hero' or not entry.get('image'):
            continue
        hero = describe(key, entry)
        hero['avatar'] = '/api/catalogue/hero/' + key + '/avatar'
        hero['logo'] = '/api/catalogue/hero/' + key + '/logo'
        hero['banner'] = '/api/catalogue/banner/' + key if entry.get('banner') else None
        hero['lord'] = '/api/catalogue/hero/' + key + '/lord'
        hero['kill'] = '/api/catalogue/hero/' + key + '/kill'
        hero['skins'] = [{**describe(sid, skin), **({} if skin.get('hero_fallback') else {'icon': '/api/catalogue/icon/' + sid}),
                          **({'banner': '/api/catalogue/banner/' + sid} if skin.get('banner') and not skin.get('hero_fallback') else {}),
                          **({'badge': '/api/catalogue/badge/' + sid} if skin.get('badge') and not skin.get('hero_fallback') else {})}
                         for sid, skin in entries.items()
                         if re.fullmatch(r'\d{7}', sid) and skin.get('hero') == key and skin.get('image')]
        heroes.append(hero)
    response.content_type = 'application/json'
    return json.dumps({'heroes': sorted(heroes, key=lambda hero: hero['name'].casefold()),
                       'identities': catalogue.identity_entries()})

@app.get("/api/browse")
def api_browse():
    path = request.query.get("path", "")
    try:
        items = browse_dispatch(path)
    except Exception as e:
        response.content_type = "application/json"
        return json.dumps({"error": str(e)})
    response.content_type = "application/json"
    return json.dumps(items)

# ── preview image ─────────────────────────────────────────────────────────────

@app.get("/api/preview")
def api_preview():
    gr = request.query.get("game_rel", "")
    if gr:
        png = _import_base(gr) + ".png"
        if os.path.exists(png):
            response.content_type = "image/png"
            with open(png, "rb") as f: return f.read()
    tok = request.query.get("token", "")
    if tok:
        gr = game_rel_from_token(tok)
        if gr:
            png = _import_base(gr) + ".png"
            if os.path.exists(png):
                response.content_type = "image/png"
                with open(png, "rb") as f: return f.read()
    response.status = 404
    return b""

# ── thumbnail (low-mip preview, no import required) ──────────────────────────

_thumb_lock = threading.RLock()
_thumb_states = {}  # cache path -> {state, error, updated}; independent of browser/project navigation
_thumb_files = {}   # verified PNG path -> (mtime_ns, size)
_thumb_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="atelier-thumbs")
_THUMB_RETRY_SECONDS = 30


def _thumb_path(game_rel):
    return project_base(game_rel, THUMBS_DIR) + ".png"


def _thumb_key(game_rel):
    return os.path.normcase(_thumb_path(game_rel))


def _valid_thumb(path):
    """Do not announce an incomplete/invalid old cache file as ready. Verify once per version."""
    try:
        stat = os.stat(path)
        stamp = (stat.st_mtime_ns, stat.st_size)
        with _thumb_lock:
            if _thumb_files.get(path) == stamp:
                return True
        from PIL import Image
        with Image.open(path) as image:
            if image.format != "PNG":
                return False
            image.verify()
        with _thumb_lock:
            _thumb_files[path] = stamp
        return True
    except Exception:
        return False


def _thumb_source(game_rel):
    # Keep existing priority and legacy project-layout support. Workers never read project state.
    thumb = _thumb_path(game_rel)
    if _valid_thumb(thumb):
        return thumb
    full_png = _import_base(game_rel) + ".png"
    return full_png if os.path.isfile(full_png) else None


@app.get("/api/thumb")
def api_thumb():
    game_rel = request.query.get("game_rel", "")
    if not game_rel:
        response.status = 404; return b""
    source = _thumb_source(game_rel)
    if source:
        response.content_type = "image/png"
        with open(source, "rb") as f: return f.read()
    response.status = 404
    response.set_header("Cache-Control", "no-store")
    return b""


def _requested_thumbs(body):
    return list(dict.fromkeys("/".join(_c.validate_game_rel(gr))
                             for gr in body.get("game_rels", []) if gr))


def _thumb_snapshot(game_rels):
    result = {"ok": True, "cached": [], "pending": [], "failed": [], "missing": [], "errors": {}}
    for gr in game_rels:
        if _thumb_source(gr):
            result["cached"].append(gr)
            continue
        with _thumb_lock:
            job = _thumb_states.get(_thumb_key(gr), {}).copy()
        # Publication may complete between the first file check and this state read.
        # Recheck a ready job before classifying it as a removed/missing cache file.
        if job.get("state") == "ready" and _thumb_source(gr):
            result["cached"].append(gr)
        elif job.get("state") == "pending":
            result["pending"].append(gr)
        elif job.get("state") == "failed":
            result["failed"].append(gr)
            result["errors"][gr] = job["error"]
        else:
            # Includes never queued, server restart, and a ready file removed from the cache.
            result["missing"].append(gr)
    result["count"] = len(result["pending"])
    return result


@app.post("/api/thumb_status")
def api_thumb_status():
    """Read-only recovery for clients that missed an SSE or rebuilt their grid."""
    response.content_type = "application/json"
    response.set_header("Cache-Control", "no-store")
    return json.dumps(_thumb_snapshot(_requested_thumbs(request.json or {})))


def _finish_thumb(gr, error=None, run=None):
    with _thumb_lock:
        if run is not None and _thumb_states.get(_thumb_key(gr), {}).get("run") is not run:
            return
        _thumb_states[_thumb_key(gr)] = {"state": "failed" if error else "ready",
                                       "error": str(error or ""), "updated": time.monotonic(), "run": run}
    event = {"game_rel": gr, "thumb_failed" if error else "thumb_ready": True}
    if error:
        event["error"] = str(error)
    # Delivery is best effort. /api/thumb_status remains authoritative if a client disconnects.
    try: _push_sse(event)
    except Exception: pass


def _publish_thumb(gr, source):
    """Decode/resize privately, then expose a complete PNG with one atomic replacement."""
    import io
    from PIL import Image
    target = _thumb_path(gr)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    fd, staged = tempfile.mkstemp(prefix=".thumb-", suffix=".png", dir=os.path.dirname(target))
    os.close(fd)
    try:
        with Image.open(io.BytesIO(source) if isinstance(source, bytes) else source) as image:
            image.load()
            image.thumbnail((128, 128), Image.Resampling.LANCZOS)
            image.convert("RGBA").save(staged, "PNG", optimize=False)
        os.replace(staged, target)
    finally:
        if os.path.exists(staged): os.remove(staged)


def _decode_cached_thumb(gr, stem, run):
    try:
        if not stem or not os.path.isfile(stem + ".uasset"):
            raise ValueError("Texture data could not be extracted for this preview.")
        os.makedirs(THUMBS_DIR, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".decode-", dir=THUMBS_DIR) as scratch:
            decoded = os.path.join(scratch, "preview.png")
            if not decode_thumb(stem + ".uasset", decoded) or not os.path.isfile(decoded):
                raise ValueError("This texture could not be decoded for preview.")
            _publish_thumb(gr, decoded)
        _finish_thumb(gr, run=run)
    except Exception as error:
        _finish_thumb(gr, error, run)


def _run_thumb_batch(pending, release, run):
    try:
        fallback = []
        for gr in pending:
            try:
                if _valid_thumb(_thumb_path(gr)):
                    _finish_thumb(gr, run=run)
                    continue
                try:
                    png = decode_thumb_from_pak(gr)
                    if png:
                        _publish_thumb(gr, png)
                        _finish_thumb(gr, run=run)
                        continue
                except Exception as error:
                    print(f"[PREFETCH] pak preview failed for {gr}: {error}", file=sys.stderr, flush=True)
                stem = _asset_cache.cache_base(gr)
                if stem and os.path.isfile(stem + ".uasset"):
                    _decode_cached_thumb(gr, stem, run)
                else:
                    fallback.append(gr)
            except Exception as error:
                _finish_thumb(gr, error, run)
        if fallback:
            # Preserve one native extraction per batch/container, rather than one per tile.
            try:
                found = extract_many(fallback)
            except Exception as error:
                for gr in fallback: _finish_thumb(gr, error, run)
            else:
                with ThreadPoolExecutor(max_workers=4) as executor:
                    list(executor.map(lambda gr: _decode_cached_thumb(gr, found.get(gr) or
                                      _asset_cache.cache_base(gr), run), fallback))
    finally:
        # Unexpected batch errors must not strand any remaining assets in pending.
        for gr in pending:
            with _thumb_lock:
                job = _thumb_states.get(_thumb_key(gr), {})
                unfinished = job.get("run") is run and job.get("state") == "pending"
            if unfinished: _finish_thumb(gr, "Thumbnail generation did not complete. Retry preview.", run)
        release()


@app.post("/api/prefetch_thumbs")
def api_prefetch_thumbs():
    body = request.json or {}
    game_rels = _requested_thumbs(body)
    candidates = [gr for gr in game_rels if not _thumb_source(gr)]
    with _thumb_lock:
        now = time.monotonic()
        pending = []
        for gr in candidates:
            job = _thumb_states.get(_thumb_key(gr), {})
            if job.get("state") == "pending": continue
            if (job.get("state") == "failed" and not body.get("retry") and
                    now - job["updated"] < _THUMB_RETRY_SECONDS): continue
            pending.append(gr)
        if pending:
            # Shared-cache jobs outlive this HTTP request; Reset Data must wait for them too.
            release = operations.reserve(_CACHE)
            run = object()
            for gr in pending:
                _thumb_states[_thumb_key(gr)] = {"state": "pending", "updated": now, "run": run}
            try:
                _thumb_executor.submit(_run_thumb_batch, pending, release, run)
            except Exception as error:
                release()
                for gr in pending: _finish_thumb(gr, error, run)
    response.content_type = "application/json"
    return json.dumps(_thumb_snapshot(game_rels))

# ── imported list ─────────────────────────────────────────────────────────────

@app.get("/api/imported")
def api_imported():
    response.content_type = "application/json"
    items = all_imported()
    from atelier.ui_preview import saved_preview
    for item in items:
        item['modified'] = item['mtime']
        hidden = item.get('opts', {}).get('hidden_sections') or []
        if item['file_type'] == 'mesh' and hidden:
            item['name'] += f" · {len(hidden)} hidden section{'s' if len(hidden) != 1 else ''}"
        preview = saved_preview(item['game_rel'], item['file_type'])
        if preview: item['ui_preview'] = preview
    return json.dumps(items)


@app.get('/api/search')
def api_search():
    from atelier.search import search
    response.content_type = 'application/json'
    return json.dumps(search(request.query.getunicode('q', ''), request.query.get('limit', '50')))

@app.get('/api/assets/browse')
def api_assets_browse():
    from atelier import added_assets
    return added_assets.browse(request.query.get('path', ''), request.query.get('file_type') or None)


@app.post('/api/assets/add')
def api_assets_add():
    from atelier import added_assets
    if request.content_type.startswith('application/json'):
        body = request.json or {}
        files = []
        upload = None
    else:
        body = dict(request.forms)
        upload = tempfile.TemporaryDirectory(prefix='atelier-asset-upload-')
        files, seen, total = [], set(), 0
        try:
            for entry in request.files.getall('files'):
                name = os.path.basename(entry.filename.replace('\\', '/'))
                extension = os.path.splitext(name)[1].lower()
                if (extension not in set(added_assets.PACKAGE_EXTS) | added_assets.IMAGE_EXTS or
                        name.casefold() in seen):
                    raise ValueError('Choose an image or cooked Unreal asset files with unique filenames.')
                seen.add(name.casefold())
                target = os.path.join(upload.name, name)
                with open(target, 'wb') as output:
                    while chunk := entry.file.read(1024 * 1024):
                        total += len(chunk)
                        if total > 2 * 1024**3:
                            raise ValueError('Asset files exceed 2 GB.')
                        output.write(chunk)
                files.append(target)
        except BaseException:
            upload.cleanup()
            raise
    def work(job):
        return added_assets.add(body.get('file_type'), body.get('folder', ''), body.get('name', ''),
                                body.get('source', ''), files)
    try:
        return _submit_job('asset-add', 'Add ' + str(body.get('name') or 'asset'), work,
                           upload.cleanup if upload else None)
    except BaseException:
        if upload:
            upload.cleanup()
        raise


# ── single import (texture) ────────────────────────────────────────────────────

@app.post("/api/import_texture")
def api_import_texture():
    body    = request.json or {}
    skin_id = body.get("skin_id", "")
    rel     = body.get("rel_path", "")
    gr_in   = body.get("game_rel", "")
    if skin_id and rel:
        gr = game_rel_for_skin(skin_id, rel)   # skin flow (unchanged)
    elif gr_in:
        gr = gr_in                             # non-skin flow (e.g. VFX tree) — import by game_rel
    else:
        response.content_type = "application/json"
        return json.dumps({"ok": False, "error": "missing skin_id/rel_path or game_rel"})
    try:
        os.makedirs(get_import_root(), exist_ok=True)
        cb = ensure_work_base(gr)           # retoc or UAssetTool per host; caches the result
        print(f"[import] {gr}: {'extracted -> ' + cb if cb else 'NOT FOUND anywhere'}",
              file=sys.stderr, flush=True)
        dst_base  = _import_base(gr)
        work_base = _cache_import_base(gr)
        print(f"[import] {gr}: work_base={work_base!r} exists={bool(work_base) and os.path.exists(work_base + '.uasset')}", file=sys.stderr, flush=True)
        # Don't re-decode if the PNG already exists — would overwrite user's edited version.
        if work_base and os.path.exists(work_base + ".uasset") and not os.path.exists(dst_base + ".png"):
            os.makedirs(os.path.dirname(dst_base), exist_ok=True)
            decode_png(dst_base, work_base)
        png_exists    = os.path.exists(dst_base + ".png")
        uasset_exists = bool(work_base) and os.path.exists(work_base + ".uasset")
        if not png_exists:
            msg = "decode failed — PNG not created" if uasset_exists else "extraction failed — asset not found in pak"
            response.content_type = "application/json"
            return json.dumps({"ok": False, "error": msg, "game_rel": gr})
        response.content_type = "application/json"
        return json.dumps({"ok": True, "token": token(gr), "game_rel": gr})
    except Exception as e:
        response.content_type = "application/json"
        return json.dumps({"ok": False, "error": str(e)})

# ── vfx import ────────────────────────────────────────────────────────────────

@app.post("/api/import_vfx")
def api_import_vfx():
    body = request.json or {}
    gr   = body.get("game_rel", "") or (game_rel_for_skin(body["skin_id"], body["rel_path"])
                                        if body.get("skin_id") and body.get("rel_path") else "")
    response.content_type = "application/json"
    if not gr:
        return json.dumps({"ok": False, "error": "missing game_rel"})
    try:
        read_vfx(gr)   # extract + validate the Niagara asset is readable
        return json.dumps({"ok": True, "token": token(gr), "game_rel": gr})
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)})

# ── vfx parameters (read / save / reset: Niagara colour-curve group edits) ────

@app.get("/api/vfx_params")
def api_vfx_params():
    gr = request.query.get("game_rel", "")
    response.content_type = "application/json"
    if not gr:
        return json.dumps({"ok": False, "error": "missing game_rel"})
    try:
        p = read_vfx(gr)
        return json.dumps({"game_rel": gr, "token": token(gr), "inten": _get_inten(gr), **p})
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)})

@app.post("/api/vfx_save")
def api_vfx_save():
    body = request.json or {}
    gr   = body.get("game_rel", "")
    response.content_type = "application/json"
    if not gr:
        return json.dumps({"ok": False, "error": "missing game_rel"})
    try:
        # groups = Niagara curve groups; scalars/vectors = an MPC's global parameters (vfx.save_mpc)
        p = save_vfx(gr, body.get("groups", []),
                     scalars=body.get("scalars"), vectors=body.get("vectors"))
        inten = _put_inten(gr, body.get("inten"))
        return json.dumps({"game_rel": gr, "token": token(gr), "inten": inten,
                           "inten_saved": inten == _clean_inten(body.get("inten")), **p})
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)})

@app.post("/api/vfx_reset")
def api_vfx_reset():
    body = request.json or {}
    gr   = body.get("game_rel", "")
    response.content_type = "application/json"
    if not gr:
        return json.dumps({"ok": False, "error": "missing game_rel"})
    try:
        p = reset_vfx(gr)
        _put_inten(gr, {})
        return json.dumps({"game_rel": gr, "token": token(gr), "inten": {}, **p})
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)})

# ── curve parameters (read / save / reset: CurveLinearColor R/G/B/A key edits) ─

@app.get("/api/curve_params")
def api_curve_params():
    gr = request.query.get("game_rel", "")
    response.content_type = "application/json"
    if not gr:
        return json.dumps({"ok": False, "error": "missing game_rel"})
    try:
        p = read_curve(gr)
        return json.dumps({"game_rel": gr, "token": token(gr), **p})
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)})

@app.post("/api/curve_save")
def api_curve_save():
    body = request.json or {}
    gr   = body.get("game_rel", "")
    response.content_type = "application/json"
    if not gr:
        return json.dumps({"ok": False, "error": "missing game_rel"})
    try:
        p = save_curve(gr, body.get("edits", {}))
        return json.dumps({"game_rel": gr, "token": token(gr), **p})
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)})

@app.post("/api/curve_reset")
def api_curve_reset():
    body = request.json or {}
    gr   = body.get("game_rel", "")
    response.content_type = "application/json"
    if not gr:
        return json.dumps({"ok": False, "error": "missing game_rel"})
    try:
        p = reset_curve(gr)
        return json.dumps({"game_rel": gr, "token": token(gr), **p})
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)})

# ── material import ───────────────────────────────────────────────────────────

@app.post("/api/import_material")
def api_import_material():
    body    = request.json or {}
    skin_id = body.get("skin_id", "")
    rel     = body.get("rel_path", "")
    if not skin_id or not rel:
        response.content_type = "application/json"
        return json.dumps({"ok": False, "error": "missing skin_id or rel_path"})
    try:
        gr = game_rel_for_skin(skin_id, rel)
        mat_json(gr)
        response.content_type = "application/json"
        return json.dumps({"ok": True, "token": token(gr), "game_rel": gr})
    except Exception as e:
        response.content_type = "application/json"
        return json.dumps({"ok": False, "error": str(e)})

# ── colour intensity split (persisted) ───────────────────────────────────────
# A colour parameter's "intensity" is the HDR multiplier the editor shows beside the swatch: the
# stored value is swatch x intensity. It used to be DERIVED on every read as max(rgb, 1), which
# does not survive a round-trip — set a colour under intensity 1.2 and the product's max falls
# below 1, so the next read derives 1 and shows the colour 1.2x brighter than the one that was
# typed (the "it doubles when I save" report). The split the user actually worked with is theirs,
# so it is stored per asset and handed back on read; absent still means "derive it", which is the
# correct reading for every material edited before this existed.

def _clean_inten(v):
    """Sanitise a {param: intensity} map off the wire — finite positive floats under named keys."""
    out = {}
    if not isinstance(v, dict):
        return out
    for k, x in v.items():
        if not isinstance(k, str) or not k:
            continue
        try:
            f = float(x)
        except (TypeError, ValueError):
            continue
        if math.isfinite(f) and f > 0:
            out[k] = round(f, 5)
    return out

def _get_inten(gr):
    """The stored {param: intensity} for one asset, or {} to mean "derive it from the value"."""
    try:
        v = _project_meta.get_asset_opts(get_import_root(), gr).get("color_inten")
        return v if isinstance(v, dict) else {}
    except Exception:
        return {}

def _put_inten(gr, v):
    """Store one asset's colour intensity split. Returns what is now stored, so the client can see
    whether it landed — an editor that cannot persist the split must say so rather than let the
    user find out at the next open."""
    clean = _clean_inten(v)
    try:
        # `or None` because set_asset_opts treats None as "remove", and an empty map is the same
        # state as never having stored one — it must not be written as {}.
        _project_meta.set_asset_opts(get_import_root(), gr, {"color_inten": clean or None})
        return clean
    except Exception:
        return {}

# ── material parameters (read / save / reset) ────────────────────────────────

@app.get("/api/material_params")
def api_material_params():
    gr = request.query.get("game_rel", "")
    if not gr:
        response.content_type = "application/json"
        return json.dumps({"ok": False, "error": "missing game_rel"})
    try:
        p = read_material(gr)
        response.content_type = "application/json"
        return json.dumps({"ok": True, "game_rel": gr, "token": token(gr),
                           "inten": _get_inten(gr), "custom_textures": _custom_tex.public(gr), **p})
    except Exception as e:
        response.content_type = "application/json"
        return json.dumps({"ok": False, "error": str(e)})

@app.get("/api/material_original")
def api_material_original():
    """Comparison data from the game, never from the current project's saved edits."""
    response.content_type = "application/json"
    gr = request.query.get("game_rel", "")
    if not gr:
        return json.dumps({"ok": False, "error": "missing game_rel"})
    try:
        from atelier.handlers.material_preview import eye_material
        params = _preview_surface(read_material_original(gr), original=True)
        return json.dumps({"ok": True, "game_rel": gr, **params, 'eye_preview': eye_material(params)})
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)})

@app.post("/api/material_save")
def api_material_save():
    body = request.json or {}
    gr   = body.get("game_rel", "")
    if not gr:
        response.content_type = "application/json"
        return json.dumps({"ok": False, "error": "missing game_rel"})
    try:
        p = save_material(gr, body.get("colors", {}), body.get("scalars", {}))
        inten = _put_inten(gr, body.get("inten"))
        response.content_type = "application/json"
        return json.dumps({"ok": True, "game_rel": gr, "token": token(gr),
                           "inten": inten, "inten_saved": inten == _clean_inten(body.get("inten")),
                           **p})
    except Exception as e:
        response.content_type = "application/json"
        return json.dumps({"ok": False, "error": str(e)})

@app.post("/api/material_reset")
def api_material_reset():
    body = request.json or {}
    gr   = body.get("game_rel", "")
    if not gr:
        response.content_type = "application/json"
        return json.dumps({"ok": False, "error": "missing game_rel"})
    try:
        p = reset_material(gr)
        try:
            _custom_tex.prune()
        except OSError:
            pass  # Unreferenced images can be collected at the next assignment.
        custom = _custom_tex.public(gr)
        response.content_type = "application/json"
        return json.dumps({"ok": True, "game_rel": gr, "token": token(gr), "inten": {},
                           "custom_textures": custom, **p})
    except Exception as e:
        response.content_type = "application/json"
        return json.dumps({"ok": False, "error": str(e)})


@app.get("/api/material_sources")
def api_material_sources():
    """Search installed MI paths without importing any materials into the project."""
    from atelier.index import ensure_index
    from atelier.handlers.skinnames import char_name, skin_name
    from atelier.catalogue import catalogue
    response.content_type = "application/json"
    query = (request.query.getunicode("q") or "").strip().casefold()
    parents = request.query.get("parents") == "true"
    if len(query) < 2:
        return {"ok": True, "materials": [], "more": False}
    words = query.split()
    matches = {}
    for path, _container, mount in ensure_index():
        if mount.rstrip("/") != "Marvel/Content/Marvel" or not path.lower().endswith(".uasset"):
            continue
        if not (is_material(path) or parents and os.path.basename(path).upper().startswith("M_")):
            continue
        parts = path.split("/")
        label = ""
        identity = catalogue.identity(path)
        if identity:
            label = " · ".join(n for n in (identity['char_name'], identity['skin_name']) if n)
        if not label and len(parts) > 3 and parts[0] == "Characters":
            label = " · ".join(n for n in (char_name(parts[1]), skin_name(parts[2])) if n)
        if all(word in (path + " " + label).casefold() for word in words):
            matches[path[:-7]] = label
    paths = sorted(matches, key=str.casefold)
    return {"ok": True, "materials": paths[:80], "labels": {p: matches[p] for p in paths[:80]}, "more": len(paths) > 80}


@app.post("/api/material_replace")
def api_material_replace():
    response.content_type = "application/json"
    body = request.json or {}
    try:
        gr = body.get("game_rel", "")
        p = _material_mod.replace_material(gr, body.get("source_game_rel", ""))
        try:
            _custom_tex.prune()
        except OSError:
            pass
        custom = _custom_tex.public(gr)
        return {"ok": True, "game_rel": gr, "token": token(gr), "inten": {},
                "custom_textures": custom, **p}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# ── custom textures: the user's own image as a NEW texture for one material slot ─────────────
# See handlers/custom_texture.py. Assigned on upload, like dye-off: it is an export option on the
# material, not one of the parameter edits the editor's Save writes into the material JSON.

def _custom_tex_slot(gr, slot, with_class=False):
    """The slot's current game texture, or ValueError naming why it cannot take a custom one."""
    if not is_material(gr):
        raise ValueError("custom textures can only be assigned to a material (MI_…)")
    with open(mat_json(gr), encoding="utf-8-sig") as stream:
        slots = _material_mod.texture_slots(json.load(stream))
    if slot not in slots:
        raise ValueError(f"this material has no texture slot named {slot!r}")
    if slots[slot]["class"] not in ("Texture2D", "TextureCube"):
        raise ValueError(f"{slot} holds a {slots[slot]['class'] or 'non-texture'} asset; "
                         f"only Texture2D and TextureCube slots can use your own image")
    return (slots[slot]['game_rel'], slots[slot]['class']) if with_class else slots[slot]["game_rel"]

@app.post("/api/material_custom_texture")
def api_material_custom_texture():
    response.content_type = "application/json"
    gr     = request.forms.get("game_rel", "").strip()
    slot   = (request.forms.getunicode("slot") or "").strip()
    upload = request.files.get("file")
    if not gr or not slot or not upload:
        return json.dumps({"ok": False, "error": "missing game_rel, slot or file"})
    try:
        template, texture_class = _custom_tex_slot(gr, slot, with_class=True)
        custom = _custom_tex.assign(gr, slot, upload.raw_filename or upload.filename,
                                    upload.file.read(), template, name=request.forms.getunicode('name'),
                                    folder=request.forms.getunicode('folder'), texture_class=texture_class)
        return json.dumps({"ok": True, "game_rel": gr, "custom_textures": custom})
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)})

@app.post("/api/material_custom_texture/location")
def api_material_custom_texture_location():
    response.content_type = 'application/json'
    body = request.json or {}
    gr, slot = body.get('game_rel', ''), body.get('slot', '')
    try:
        if not isinstance(gr, str) or not gr or not isinstance(slot, str) or not slot:
            raise ValueError('missing game_rel or slot')
        _custom_tex_slot(gr, slot)
        custom = _custom_tex.set_location(gr, slot, body.get('name'), body.get('folder'))
        return json.dumps({'ok': True, 'game_rel': gr, 'custom_textures': custom})
    except Exception as exc:
        return json.dumps({'ok': False, 'error': str(exc)})


@app.post("/api/material_custom_texture/clear")
def api_material_custom_texture_clear():
    response.content_type = "application/json"
    body = request.json or {}
    gr, slot = body.get("game_rel", ""), body.get("slot", "")
    if not gr or not isinstance(slot, str) or not slot:
        return json.dumps({"ok": False, "error": "missing game_rel or slot"})
    try:
        return json.dumps({"ok": True, "game_rel": gr, "custom_textures": _custom_tex.clear(gr, slot)})
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)})

@app.get("/api/material_custom_texture/preview")
def api_material_custom_texture_preview():
    gr, slot = request.query.get("game_rel", ""), request.query.getunicode("slot") or ""
    path = _custom_tex.image_path(gr, slot) if gr and slot else None
    if not path or not os.path.isfile(path):
        response.status = 404
        return ""
    result = static_file(os.path.basename(path), root=os.path.dirname(path), mimetype="image/png")
    result.set_header("Cache-Control", "no-store")
    return result

# ── bulk import (job) ─────────────────────────────────────────────────────────

_job      = {"running": False, "current": 0, "total": 0, "name": "",
             "done": False, "error": None, "results": []}
_job_lock = threading.Lock()
_sse_queues: list[queue.Queue] = []
_sse_lock   = threading.Lock()

def _push_sse(data: dict):
    with _sse_lock:
        dead = []
        for q in _sse_queues:
            try: q.put_nowait(data)
            except queue.Full: dead.append(q)
        for q in dead: _sse_queues.remove(q)

_browse_mod._update_callback = _push_sse

def _run_import_job(items, project_root=None, release=None):
    root = project_root or get_import_root()
    try:
        with operations.project_use(root, write=True), _c.project_context(root):
            _run_import_job_in_project(items)
    finally:
        if release:
            release()


def _run_import_job_in_project(items):
    """items: [{skin_id, rel_path, game_rel, name}] — extract+decode all via UAssetTool."""
    with _job_lock:
        _job.update(running=True, current=0, total=len(items), name="", done=False, error=None, results=[])
    try:
        jobs.progress("Extracting textures…", 0, len(items))
        _push_sse({"current": 0, "total": len(items), "name": "Extracting from game…", "done": False})
        os.makedirs(get_import_root(), exist_ok=True)
        extract_many([it["game_rel"] for it in items])   # one retoc call per container, or UAT on Windows
        # extract_many records every extracted asset itself.

        _push_sse({"current": 0, "total": len(items), "name": "Decoding…", "done": False})
        decode_flat([it["game_rel"] for it in items], get_import_root())

        results = []; current = 0
        for it in items:
            jobs.checkpoint()
            dst_base = _import_base(it["game_rel"])
            current += 1
            jobs.progress("Importing " + it["name"], current, len(items))
            if os.path.exists(dst_base + ".png"):
                results.append({"name": it["name"], "token": token(it["game_rel"]),
                                 "game_rel": it["game_rel"]})
            with _job_lock:
                _job.update(current=current, name=it["name"])
            _push_sse({"current": current, "total": len(items), "name": it["name"], "done": False,
                       "game_rel": it['game_rel'], "ok": os.path.exists(dst_base + '.png')})
    except Exception as e:
        with _job_lock:
            _job.update(running=False, done=True, error=str(e))
        _push_sse({"done": True, "error": str(e), "results": []})
        return

    with _job_lock:
        missing = len(items) - len(results)
        error = f"{missing} texture(s) could not be imported" if missing else None
        _job.update(running=False, done=True, results=results, error=error)
    _push_sse({"current": current, "total": len(items), "name": "", "done": True,
               "results": results, "error": error})

@app.post("/api/import_all")
def api_import_all():
    body  = request.json or {}
    items = body.get("items", [])
    if not items:
        response.content_type = "application/json"
        return json.dumps({"ok": False, "error": "no items"})
    if body.get("background"):
        owner = uuid.uuid4().hex
        with _job_lock:
            if _job["running"]:
                return {"ok": False, "error": "job already running"}
            _job.update(running=True, current=0, total=len(items), done=False, error=None, results=[], owner=owner)
        def run(job):
            try:
                _run_import_job_in_project(items)
                with _job_lock:
                    return {"ok": not _job["error"], **_job}
            finally:
                with _job_lock:
                    if _job["running"] and _job.get("owner") == owner:
                        _job.update(running=False, done=True, error="Import cancelled; completed assets are retained.")
                        _push_sse(dict(_job))
        try:
            def settled():
                with _job_lock:
                    if _job["running"] and _job.get("owner") == owner:
                        _job.update(running=False, done=True, error="Import cancelled; completed assets are retained.")
                        _push_sse(dict(_job))
            return _submit_job("import", "Import textures", run, settled)
        except BaseException:
            with _job_lock:
                _job.update(running=False, done=True)
            raise
    with _job_lock:
        if _job["running"]:
            response.content_type = "application/json"
            return json.dumps({"ok": False, "error": "job already running"})
        root = get_import_root()
        release = operations.reserve(root)
        # Claim before starting the thread: a second HTTP request must see it immediately.
        _job.update(running=True, current=0, total=len(items), done=False, error=None, results=[], owner=None)
    try:
        threading.Thread(target=_run_import_job, args=(items, root, release), daemon=True).start()
    except Exception:
        release()
        with _job_lock:
            _job.update(running=False, done=True, error="Could not start import worker")
        raise
    response.content_type = "application/json"
    return json.dumps({"ok": True, "total": len(items)})

@app.get("/api/import_status")
def api_import_status():
    with _job_lock:
        snap = dict(_job)
    response.content_type = "application/json"
    return json.dumps(snap)

# ── SSE stream (import progress + file changes) ───────────────────────────────

@app.get("/api/events")
def api_events():
    q = queue.Queue(maxsize=128)
    with _sse_lock:
        _sse_queues.append(q)

    def generate():
        yield "retry: 1000\n\n"
        try:
            while True:
                try:
                    data = q.get(timeout=20)
                    yield f"data: {json.dumps(data)}\n\n"
                except queue.Empty:
                    yield ": keepalive\n\n"
        except GeneratorExit:
            with _sse_lock:
                try: _sse_queues.remove(q)
                except ValueError: pass

    response.content_type = "text/event-stream"
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    return generate()

# ── file change watcher ───────────────────────────────────────────────────────

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class _PNGHandler(FileSystemEventHandler):
    _last: dict = {}

    def on_modified(self, event):
        if not event.is_directory and event.src_path.endswith(".png"):
            if project_trash.DIRECTORY in event.src_path.replace('\\', '/').split('/'):
                return
            import_root = get_import_root().replace("\\", "/")
            evt_path    = event.src_path.replace("\\", "/")
            if not evt_path.startswith(import_root + "/"):
                return
            now = time.monotonic()
            if now - self._last.get(event.src_path, 0) < 0.5:
                return
            self._last[event.src_path] = now
            # Derive game_rel from the subfolder-mirrored path; legacy flat files resolve via cache.
            gr = project_game_rel(event.src_path, get_import_root())
            if "/" not in gr:
                gr = _asset_cache.by_name(gr) or gr
            _push_sse({"file_changed": True, "token": token(gr), "game_rel": gr})

    def on_created(self, event):
        self.on_modified(event)

    def on_deleted(self, event):
        # Any edited-asset file (texture/material/curve/vfx json, mesh .blend) removed from the
        # active project externally (e.g. deleted in Explorer) — tell the sidebar to reconcile.
        if event.is_directory:
            return
        p = event.src_path
        if project_trash.DIRECTORY in p.replace('\\', '/').split('/'):
            return
        if p.endswith(".blend.mat.json") or not p.endswith((".png", ".json", ".blend")):
            return
        import_root = get_import_root().replace("\\", "/")
        evt_path    = p.replace("\\", "/")
        if not evt_path.startswith(import_root + "/"):
            return
        _push_sse({"asset_removed": True})

def _migrate_legacy_imports():
    """Move files from assets/imported/ to projects/Default/ on first use of projects."""
    if not os.path.isdir(IMPORT_ROOT):
        return
    files = [f for f in os.listdir(IMPORT_ROOT) if os.path.isfile(os.path.join(IMPORT_ROOT, f))]
    if not files:
        return
    if os.path.isdir(PROJECTS_ROOT) and any(
        os.path.isdir(os.path.join(PROJECTS_ROOT, d)) for d in os.listdir(PROJECTS_ROOT)
    ):
        return
    new_root = os.path.join(PROJECTS_ROOT, "Default")
    os.makedirs(new_root, exist_ok=True)
    for fname in files:
        src = os.path.join(IMPORT_ROOT, fname)
        dst = os.path.join(new_root, fname)
        if not os.path.exists(dst):
            shutil.move(src, dst)
    print(f"[migrate] moved {len(files)} files from imported/ to projects/Default/", flush=True)

_migrate_legacy_imports()
os.makedirs(PROJECTS_ROOT, exist_ok=True)
_observer = Observer()
_observer.schedule(_PNGHandler(), PROJECTS_ROOT, recursive=True)
_observer.start()

# ── projects ─────────────────────────────────────────────────────────────────

def _list_projects():
    if not os.path.isdir(PROJECTS_ROOT):
        return []
    projects = []
    for name in os.listdir(PROJECTS_ROOT):
        path = os.path.join(PROJECTS_ROOT, name)
        if not os.path.isdir(path):
            continue
        mtime       = 0
        asset_count = 0
        try:
            # Project files are subfolder-mirrored by game_rel, so walk (not just listdir).
            for dirpath, _dirs, files in os.walk(path):
                _dirs[:] = [d for d in _dirs if d not in ('.atelier', project_trash.DIRECTORY)]
                for fname in files:
                    fp = os.path.join(dirpath, fname)
                    mt = os.path.getmtime(fp)
                    if mt > mtime:
                        mtime = mt
                    if fname.endswith(".png") or fname.endswith(".json"):
                        asset_count += 1
        except Exception:
            pass
        if not mtime:
            try: mtime = os.path.getmtime(path)
            except Exception: pass
        projects.append({"name": name, "mtime": int(mtime), "asset_count": asset_count})
    projects.sort(key=lambda p: p["mtime"], reverse=True)
    return projects

@app.get("/api/projects")
def api_projects():
    response.content_type = "application/json"
    active = get_active_project()
    if active:
        root = _c.project_dir(active, PROJECTS_ROOT)
        with operations.project_use(root, write=True):
            project_trash.purge(root)
    return json.dumps({"ok": True, "projects": _list_projects(), "active": get_active_project()})

@app.post("/api/project/select")
def api_project_select():
    body = request.json or {}
    name = body.get("name", "").strip()
    if not name:
        response.content_type = "application/json"
        return json.dumps({"ok": False, "error": "no name"})
    project_dir = _c.project_dir(name, PROJECTS_ROOT)
    if not os.path.isdir(project_dir):
        response.content_type = "application/json"
        return json.dumps({"ok": False, "error": "project not found"})
    with operations.project_use(project_dir, write=True):
        project_trash.purge(project_dir)
    set_active_project(name)
    response.content_type = "application/json"
    return json.dumps({"ok": True})

@app.post("/api/project/create")
def api_project_create():
    body = request.json or {}
    name = body.get("name", "").strip()
    if not name or any(c in name for c in r'/\:*?"<>|'):
        response.content_type = "application/json"
        return json.dumps({"ok": False, "error": "invalid project name"})
    project_dir = _c.project_dir(name, PROJECTS_ROOT)
    if os.path.exists(project_dir):
        response.content_type = "application/json"
        return json.dumps({"ok": False, "error": "project already exists"})
    os.makedirs(project_dir, exist_ok=True)
    _project_meta.stamp_new(project_dir)   # only here: an existing folder's provenance is not ours to claim
    set_active_project(name)
    response.content_type = "application/json"
    return json.dumps({"ok": True})

@app.post("/api/project/rename")
def api_project_rename():
    body     = request.json or {}
    old_name = body.get("old_name", "").strip()
    new_name = body.get("new_name", "").strip()
    if not old_name or not new_name or any(c in new_name for c in r'/\:*?"<>|'):
        response.content_type = "application/json"
        return json.dumps({"ok": False, "error": "invalid name"})
    old_dir = _c.project_dir(old_name, PROJECTS_ROOT)
    new_dir = _c.project_dir(new_name, PROJECTS_ROOT)
    response.content_type = "application/json"
    if not os.path.isdir(old_dir):
        return json.dumps({"ok": False, "error": "project not found"})
    if os.path.exists(new_dir) and old_name.lower() != new_name.lower():
        return json.dumps({"ok": False, "error": "name already taken"})
    try:
        os.rename(old_dir, new_dir)
    except OSError as e:
        return json.dumps({"ok": False, "error": str(e)})
    if get_active_project() == old_name:
        set_active_project(new_name)
    return json.dumps({"ok": True})

@app.post("/api/project/duplicate")
def api_project_duplicate():
    body     = request.json or {}
    src_name = body.get("name", "").strip()
    new_name = body.get("new_name", "").strip()
    if not src_name or not new_name or any(c in new_name for c in r'/\:*?"<>|'):
        response.content_type = "application/json"
        return json.dumps({"ok": False, "error": "invalid name"})
    src_dir = _c.project_dir(src_name, PROJECTS_ROOT)
    dst_dir = _c.project_dir(new_name, PROJECTS_ROOT)
    if not os.path.isdir(src_dir):
        response.content_type = "application/json"
        return json.dumps({"ok": False, "error": "source project not found"})
    if os.path.exists(dst_dir):
        response.content_type = "application/json"
        return json.dumps({"ok": False, "error": "name already taken"})
    shutil.copytree(src_dir, dst_dir)
    response.content_type = "application/json"
    return json.dumps({"ok": True})

@app.post("/api/project/asset_selection")
def api_project_asset_selection():
    """Persist which edited assets are switched OFF for export in the active project, so the
    sidebar comes back the way the user left it. Stores the deselected set (see project_meta)."""
    body = request.json or {}
    response.content_type = "application/json"
    deselected = body.get("deselected")
    if not isinstance(deselected, list):
        return json.dumps({"ok": False, "error": "deselected must be a list"})
    import_root = get_import_root()
    if not os.path.isdir(import_root):
        return json.dumps({"ok": False, "error": "no active project"})
    _project_meta.set_deselected(import_root, deselected)
    return json.dumps({"ok": True})

@app.post("/api/project/delete")
def api_project_delete():
    body = request.json or {}
    name = body.get("name", "").strip()
    if not name:
        response.content_type = "application/json"
        return json.dumps({"ok": False, "error": "no name"})
    project_dir = _c.project_dir(name, PROJECTS_ROOT)
    if not os.path.isdir(project_dir):
        response.content_type = "application/json"
        return json.dumps({"ok": False, "error": "project not found"})
    shutil.rmtree(project_dir)
    if get_active_project() == name:
        set_active_project("")
    response.content_type = "application/json"
    return json.dumps({"ok": True})

def _safe_project_dir(name):
    """The folder for `name`, or None when the name is not a plain project name sitting directly
    in PROJECTS_ROOT. Export is the one project route that takes a list, so a bad entry must fail
    the request rather than quietly resolve somewhere else on disk."""
    try:
        return _c.project_dir(name, PROJECTS_ROOT, must_exist=True)
    except ValueError:
        return None

def _build_project_zip(names):
    with ExitStack() as stack:
        # Reserve all source projects before reading any files. An unrelated active
        # project is immaterial to a multi-project archive.
        # A stable order also prevents two reversed multi-project exports deadlocking.
        roots = sorted({_c.project_dir(name, PROJECTS_ROOT, must_exist=True) for name in names})
        for root in roots:
            stack.enter_context(operations.project_use(root, write=True))
        return _build_project_zip_reserved(names)


def _build_project_zip_reserved(names):
    """Pack the named projects into one .zip under the cache and return its path.

    One project zips its own contents at the root, so unzipping gives the project back as-is;
    several are each placed in a folder named after the project, so one archive can be handed over
    whole. Nothing on disk is touched — export is a copy, not a move. Raises ValueError naming the
    offender when a name is not a project sitting in PROJECTS_ROOT."""
    import zipfile
    dirs = []
    for name in names:
        d = _safe_project_dir(name)
        if not d:
            raise ValueError(f"project not found: {name}")
        dirs.append((name, d))
    if not dirs:
        raise ValueError("no projects given")

    out_dir = os.path.join(_CACHE, "project_export")
    os.makedirs(out_dir, exist_ok=True)
    out_dir = tempfile.mkdtemp(prefix="archive-", dir=out_dir)
    stem = dirs[0][0] if len(dirs) == 1 else f"atelier_projects_{len(dirs)}"
    zip_path = os.path.join(out_dir, stem + ".zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, d in dirs:
            prefix = "" if len(dirs) == 1 else name + "/"
            for root, _subdirs, files in os.walk(d):
                _subdirs[:] = [part for part in _subdirs if part != project_trash.DIRECTORY]
                rel_root = os.path.relpath(root, d)
                if not files and rel_root != ".":
                    z.writestr(prefix + rel_root.replace(os.sep, "/") + "/", b"")
                for fname in files:
                    arc = os.path.join(rel_root, fname) if rel_root != "." else fname
                    z.write(os.path.join(root, fname), prefix + arc.replace(os.sep, "/"))
    return zip_path

@app.post("/api/project/export")
def api_project_export():
    """Download one or more projects as a .zip. Errors come back as JSON so the picker can say why."""
    body  = request.json or {}
    names = body.get("names")
    if not isinstance(names, list):
        names = [body.get("name")] if body.get("name") else []
    names = [n for n in ((n or "").strip() for n in names) if n]
    if not names:
        response.status = 400
        response.content_type = "application/json"
        return json.dumps({"error": "no projects given"})
    try:
        zip_path = _build_project_zip(names)
    except ValueError as e:
        response.status = 404
        response.content_type = "application/json"
        return json.dumps({"error": str(e)})
    except OSError as e:
        response.status = 500
        response.content_type = "application/json"
        return json.dumps({"error": str(e)})
    return static_file(os.path.basename(zip_path), root=os.path.dirname(zip_path),
                       mimetype="application/zip", download=os.path.basename(zip_path))

@app.get("/api/project/thumb")
def api_project_thumb():
    project = request.query.get("project", "")
    if not project:
        response.status = 404; return b""
    project_dir = _c.project_dir(project, PROJECTS_ROOT)
    if not os.path.isdir(project_dir):
        response.status = 404; return b""
    best_file  = None
    best_mtime = 0
    try:
        for fname in os.listdir(project_dir):
            if not fname.endswith(".png"):
                continue
            fp = os.path.join(project_dir, fname)
            mt = os.path.getmtime(fp)
            if mt > best_mtime:
                best_mtime = mt
                best_file  = fp
    except Exception:
        pass
    if not best_file:
        response.status = 404; return b""
    response.content_type = "image/png"
    with open(best_file, "rb") as f:
        return f.read()

# ── reveal in file manager ────────────────────────────────────────────────────

@app.get("/api/open_explorer")
def api_open_explorer():
    """Reveal a file in the desktop file manager.

    Reports failure instead of returning ok:true after doing nothing. The old version silently
    no-opped whenever the target did not exist yet — which is the normal state for a texture that
    has not been imported — so the UI showed no error and nothing opened, and it was reported as
    "Open in Explorer does nothing" more than once."""
    path = request.query.get("path", "")
    gr   = request.query.get("game_rel", "")
    response.content_type = "application/json"
    if gr:
        path = _import_base(gr) + ".png"
    if not path:
        return json.dumps({"ok": False, "error": "No path given."})

    abs_path = os.path.abspath(path)
    if os.path.exists(abs_path):
        target, select = abs_path, True
    elif os.path.isdir(os.path.dirname(abs_path)):
        target, select = os.path.dirname(abs_path), False
    else:
        return json.dumps({"ok": False, "error":
                           f"Nothing to show yet at {abs_path} — import or export this asset first."})
    try:
        hostos.reveal(target, select=select)
    except Exception as e:
        return json.dumps({"ok": False, "error": f"Could not open the file manager: {e}"})
    return json.dumps({"ok": True, "path": target})


@app.post("/api/reset_data")
def api_reset_data():
    paths_to_remove = [
        _c.ASSETS,
        _c._CACHE,
        os.path.join(_c.DATA_ROOT, "_logs"),
        os.path.join(_c.TOOLS, "Mappings"),
        _c.AES_KEY_FILE,
    ]
    for p in paths_to_remove:
        try:
            if os.path.isdir(p):   shutil.rmtree(p)
            elif os.path.isfile(p): os.remove(p)
        except Exception as e:
            print(f"[reset] failed to remove {p}: {e}")
    try:
        with open(_c.CONFIG_FILE, "w", encoding="utf-8") as _f:
            json.dump({}, _f)
    except Exception as e:
        print(f"[reset] failed to clear config: {e}")
    # Reset in-memory state
    _c.CONFIG_HAS_PAKS = False
    _c._active_project = ""
    try: _io_lib_mod.AES_KEY = b""
    except Exception: pass
    try:
        import atelier.index as _idx_mod; _idx_mod._INDEX = None
    except Exception: pass
    try: _asset_cache.clear()
    except Exception: pass
    try:
        with _pak_thumb_mod._toc_lock:   _pak_thumb_mod._toc_cache.clear()
        with _pak_thumb_mod._gr_map_lock: _pak_thumb_mod._gr_to_cont.clear()
        _pak_thumb_mod._gr_map_ready = False
    except Exception: pass
    # Recreate projects root so the watchdog observer doesn't error
    try: os.makedirs(PROJECTS_ROOT, exist_ok=True)
    except Exception: pass
    response.content_type = "application/json"
    return json.dumps({"ok": True})


@app.get("/api/open_projects_folder")
def api_open_projects_folder():
    active = get_active_project()
    if active:
        target = os.path.join(PROJECTS_ROOT, active)
        if os.path.isdir(target):
            hostos.reveal(target, select=True)
            response.content_type = "application/json"
            return json.dumps({"ok": True})
    hostos.reveal(PROJECTS_ROOT, select=False)
    response.content_type = "application/json"
    return json.dumps({"ok": True})


@app.post("/api/replace_texture")
def api_replace_texture():
    from PIL import Image
    import io
    response.content_type = 'application/json'
    gr     = request.forms.get("game_rel", "").strip()
    upload = request.files.get("file")
    if not gr or not upload:
        response.content_type = "application/json"
        return json.dumps({"ok": False, "error": "missing game_rel or file"})
    dst = _import_base(gr) + ".png"
    if not os.path.exists(dst):
        response.content_type = "application/json"
        return json.dumps({"ok": False, "error": "asset not imported — edit it first"})
    try:
        from atelier.handlers import hdr_texture
        payload = upload.file.read(hdr_texture.MAX_BYTES + 1)
        if len(payload) > hdr_texture.MAX_BYTES:
            raise ValueError('Choose a replacement texture up to 512 MB.')
        extension = os.path.splitext(upload.raw_filename or upload.filename)[1].lower()
        cube_dds = payload[:4] == b'DDS ' and len(payload) >= 128 and int.from_bytes(payload[112:116], 'little') & 0x200
        if extension == '.hdr' or extension == '.dds' and (cube_dds or hdr_texture.project_info(dst[:-4])):
            info = hdr_texture.replace_project(gr, upload.raw_filename or upload.filename, payload)
            thumb = os.path.join(THUMBS_DIR, *gr.split('/')) + '.png'
            try:
                if os.path.isfile(thumb): os.remove(thumb)
            except OSError:
                pass
            return json.dumps({'ok': True, 'token': token(gr), 'game_rel': gr, **info})
        if hdr_texture.project_info(dst[:-4]):
            raise ValueError('Replace this TextureCube with an HDR .hdr image or cubemap DDS. Its PNG is a tone-mapped preview.')
        if extension == '.dds' and payload[84:88] == b'DX10' and len(payload) >= 148 and int.from_bytes(payload[128:132], 'little') in hdr_texture.FORMATS:
            raise ValueError('Use a TextureCube template for HDR replacements. HDR Texture2D replacement is not supported.')
        img = Image.open(io.BytesIO(payload)).convert("RGBA")
        img.save(dst, "PNG")
        thumb = os.path.join(THUMBS_DIR, *gr.split("/")) + ".png"
        try:
            if os.path.exists(thumb): os.remove(thumb)
        except Exception:
            pass
        response.content_type = "application/json"
        return json.dumps({"ok": True, "token": token(gr), "game_rel": gr})
    except Exception as e:
        response.content_type = "application/json"
        return json.dumps({"ok": False, "error": str(e)})


@app.get("/api/open_with")
def api_open_with():
    path = request.query.get("path", "")
    gr   = request.query.get("game_rel", "")
    if gr:
        path = _import_base(gr) + ".png"
        from atelier.handlers.hdr_texture import project_info as hdr_project_info
        if hdr_project_info(_import_base(gr)):
            path = _import_base(gr) + '.dds'
    if path:
        abs_path = os.path.abspath(path)
        if os.path.exists(abs_path):
            hostos.open_with(abs_path)
    response.content_type = "application/json"
    return json.dumps({"ok": True})

# ── Blender mesh editing ──────────────────────────────────────────────────────

@app.post('/api/mesh_add')
def api_mesh_add():
    from atelier.handlers.meshreplace import add
    return add((request.json or {}).get('game_rel',''))


@app.post('/api/model_blender_export')
def api_model_blender_export():
    from atelier.handlers.meshport import export
    body=request.json or {}
    return _submit_job('blender-export','Export model to Blender',lambda job:export(body.get('game_rel',''),body.get('weapons',[])))


@app.post('/api/model_blender_send')
def api_model_blender_send():
    from atelier.handlers.meshport import send_to_blender
    body = request.json or {}
    return _submit_job('blender-send', 'Send model to running Blender',
                       lambda job: send_to_blender(body.get('game_rel', ''), body.get('weapons', [])))


@app.get('/api/blender_extension')
def api_blender_extension():
    """Download only the bundled extension; installation remains explicit in Blender."""
    import sys
    from pathlib import Path
    if getattr(sys, 'frozen', False):
        archive = Path(sys._MEIPASS) / 'extensions' / 'Atelier-Live-Bridge.zip'
        payload = archive.read_bytes()
    else:
        from atelier.blender_extension import archive_bytes
        payload = archive_bytes()
    response.content_type = 'application/zip'
    response.set_header('Content-Disposition', 'attachment; filename="Atelier-Live-Bridge.zip"')
    return payload


@app.post('/api/model_blender_open')
def api_model_blender_open():
    from atelier.handlers.meshport import destination
    from atelier.handlers.meshedit import find_blender
    target=destination((request.json or {}).get('game_rel',''))
    if not target.is_file():raise ValueError('Export this model to Blender first')
    subprocess.Popen([find_blender(),str(target)],creationflags=CNW)
    return {'ok':True}


@app.post('/api/mesh_replace')
def api_mesh_replace():
    from atelier.handlers.meshreplace import prepare,import_options,MODEL_EXTENSIONS,COMPANIONS
    game_rel=request.forms.get('game_rel','')
    files=request.files.getall('files')
    if not game_rel or not files:return {'ok':False,'error':'Choose a mesh and replacement files'}
    import tempfile
    upload=tempfile.TemporaryDirectory(prefix='atelier-model-upload-')
    try:
        options=import_options(json.loads(request.forms.get('options','{}')))
        sources=[];companions=[];seen=set();total=0
        if len(files)>32:raise ValueError('Choose one model and at most 31 companion files')
        for entry in files:
            name=os.path.basename(entry.filename.replace('\\','/'));extension=os.path.splitext(name)[1].lower()
            from atelier.config import validate_game_rel
            validate_game_rel(name)
            if extension not in MODEL_EXTENSIONS|COMPANIONS or name.lower() in seen:raise ValueError('Unexpected or duplicate replacement file')
            seen.add(name.lower());target=os.path.join(upload.name,name)
            with open(target,'wb') as output:
                while chunk:=entry.file.read(1024*1024):
                    total+=len(chunk)
                    if total>2*1024**3:raise ValueError('Replacement files exceed 2 GB')
                    output.write(chunk)
            if extension in MODEL_EXTENSIONS:sources.append(target)
            else:companions.append(target)
        if len(sources)!=1:raise ValueError('Choose one model file, plus its material JSON, PNG textures or cooked companions')
        def run(job):return prepare(game_rel,sources[0],options,companions)
        return _submit_job('mesh-replace','Replace '+os.path.basename(game_rel),run,upload.cleanup)
    except BaseException:
        upload.cleanup();raise

@app.post("/api/mesh_blend_extract")
def api_mesh_blend_extract():
    """Decode a SkeletalMesh into an editable .blend in the active project, with its materials'
    textures staged alongside and wired into the shader nodes.

    Refuses up front on a mesh format the rebuilder can't pack (the survey's preflight), because
    the expensive thing a user spends here is the sculpting between extract and build. The reply
    carries can_force so the UI can offer inspect-anyway."""
    body  = request.json or {}
    gr    = (body.get("game_rel") or "").strip()
    force = bool(body.get("force"))
    response.content_type = "application/json"
    if not gr:
        return json.dumps({"ok": False, "error": "no game_rel"})
    try:
        from atelier.handlers import meshedit, meshsurvey
        base = meshedit._resolve_base(gr)
        report = meshsurvey.probe(base)
        if report["status"] != "ok" and not force:
            return json.dumps({"ok": False, "can_force": True, "error": meshsurvey.verdict_text(report)})
        r = meshedit.extract_blend(gr, base_path=base, force=True, project_textures=body.get('project_textures', True))
        # probe() reports warnings as bare keys ("morphs"); expand them so the UI shows the
        # sentence rather than the code.
        warnings = [meshsurvey.WARNINGS.get(w, w) for w in r["warnings"]]
        return json.dumps({"ok": True, "blend": r["blend"].replace("\\", "/"),
                           "preflight": r["preflight"], "warnings": warnings,
                           "textures": r["textures"], "materials": r["materials"],
                           "project_textures": r.get('project_textures', True),
                           "info": r["info"]})
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)})

@app.get("/api/open_blend")
def api_open_blend():
    """Open a project .blend in Blender (falls back to the shell association)."""
    gr = request.query.get("game_rel", "")
    response.content_type = "application/json"
    path = os.path.abspath(project_base(gr) + ".blend") if gr else ""
    if not path or not os.path.exists(path):
        return json.dumps({"ok": False, "error": "no .blend for this mesh yet"})
    try:
        from atelier.handlers.meshedit import find_blender
        subprocess.Popen([find_blender(), path], creationflags=CNW)
    except Exception:
        try: hostos.open_path(path)
        except Exception as e: return json.dumps({"ok": False, "error": str(e)})
    return json.dumps({"ok": True})

# ── export ────────────────────────────────────────────────────────────────────

def _is_mesh_item(game_rel):
    """A mesh edit: its edits live in a .blend, not a PNG, so it must not fall into tex_items."""
    return _browse_mod._classify_file(os.path.basename(game_rel)) == "mesh"

def _split_export_items(items):
    """Partition selected game_rels into build_mod's buckets (edits already live on disk / sidecar)."""
    tex_items   = [gr for gr in items if not is_material(gr) and not is_curve(gr)
                   and not is_vfx(gr) and not is_world(gr) and not is_text(gr)
                   and not _is_mesh_item(gr)]
    mat_items   = [{"game_rel": gr, "colors": {}, "scalars": {}} for gr in items if is_material(gr)]
    curve_items = [{"game_rel": gr, "edits": {}} for gr in items if is_curve(gr)]   # edits already on disk
    vfx_items   = [gr for gr in items if is_vfx(gr)]                                 # edits from sidecar
    world_items = [gr for gr in items if is_world(gr)]                               # edits from sidecar
    text_items  = [gr for gr in items if is_text(gr)]                                # edits from sidecar
    mesh_items  = [gr for gr in items if _is_mesh_item(gr)]                          # edits from the .blend
    return tex_items, mat_items, curve_items, vfx_items, world_items, text_items, mesh_items

def _install_to_mods(mod_name, export_dir, artifacts=None):
    """Copy a freshly-built mod's .pak/.ucas/.utoc from export_dir into the configured mods folder,
    with verification and rollback of replacements. Returns (ok, error, dest_dir)."""
    mods = get_mods_folder()
    if not mods:
        return False, "No mods folder set — configure one in Menu → Settings.", None
    stem = f"{mod_name}_9999999_P"
    try:
        os.makedirs(mods, exist_ok=True)
    except Exception as e:
        return False, f"Mods folder not usable: {e}", None
    try:
        sources = artifacts or container_files(os.path.join(export_dir, stem))
        publish_files(sources, mods)
        return True, None, mods
    except Exception as e:
        return False, f"Could not install mod: {e}", None

def _mod_stem(mod_name):
    """Filesystem-safe stem for a mod name.

    Strips the Windows-illegal set AND the glob metacharacters [ ] — legal in filenames, so they
    survived into _cache/build_stage/<name> and the output filenames, where every later glob over
    those paths (modlock, repatch, the packed-output scan) matched nothing and quietly did no work.
    A mod called "[WIP] Recolor" could not be locked or repatched, with no error anywhere."""
    return re.sub(r'[/\\:*?"<>|.\[\]]', '', (mod_name or "Mod").strip()) or "Mod"

@app.get("/api/check_mod_conflict")
def api_check_mod_conflict():
    """Whether installing this mod name would overwrite an existing file, in the default export
    folder and/or the configured mods folder — so the frontend can raise a single confirm popup
    covering both destinations at once instead of one per destination."""
    mod_name     = _mod_stem(request.query.get("mod_name", ""))
    copy_to_mods = request.query.get("copy_to_mods") == "1"
    stem = f"{mod_name}_9999999_P"
    default_exists = any(os.path.exists(os.path.join(ASSETS_MODS, stem + ext))
                         for ext in (".pak", ".ucas", ".utoc"))
    mods_exists = False
    if copy_to_mods:
        mods = get_mods_folder()
        if mods:
            mods_exists = any(os.path.exists(os.path.join(mods, stem + ext))
                              for ext in (".pak", ".ucas", ".utoc"))
    response.content_type = "application/json"
    return json.dumps({"default": default_exists, "mods": mods_exists})

@app.post("/api/install_mod")
def api_install_mod():
    """Build the selected edits into a mod in the default export folder, then — when copy_to_mods
    is set — also copy it into the configured mods folder, replacing any previous version there.
    Single entry point behind the "Install Mod" button, regardless of toggle state."""
    body = request.json or {}
    if body.get("background"):
        return _submit_job("export", "Export " + _mod_stem(body.get("mod_name")),
                           lambda job: _install_mod_payload(body))
    response.content_type = "application/json"
    return json.dumps(_install_mod_payload(body))


def _install_mod_payload(body):
    mod_name     = _mod_stem(body.get("mod_name"))
    items        = body.get("items", [])
    copy_to_mods = bool(body.get("copy_to_mods"))
    password     = (body.get("password") or "").strip() or None
    if not items:
        return {"ok": False, "error": "no items selected"}
    if copy_to_mods and not get_mods_folder():
        return {"ok": False, "error": "No mods folder set — configure one in Menu → Settings.",
                "need_mods_folder": True}
    out_dir = ASSETS_MODS
    os.makedirs(out_dir, exist_ok=True)
    try:
        tex_items, mat_items, curve_items, vfx_items, world_items, text_items, mesh_items = \
            _split_export_items(items)
        result = build_mod(mod_name, tex_items, mat_items, out_dir, force=True,
                           curve_items=curve_items, vfx_items=vfx_items, world_items=world_items,
                           text_items=text_items, password=password, mesh_items=mesh_items,
                           asset_opts=_project_meta.get_asset_opts(get_import_root()),
                           allow_unsafe_world=bool(body.get("allow_unsafe_world")))
        if not result.get("ok"):
            return {"ok": False, "error": result.get("error", "build failed")}
        pak = result.get("pak")
        # applied/skipped were computed and then dropped on the floor here. A per-item failure --
        # a dye-off whose ColorID would not extract, a texture group that could not be set -- left
        # build_mod with ok:true and the user with "Installed", no hint that part of the mod is
        # missing. That is indistinguishable from the game ignoring the edit, which is exactly the
        # confusion the whole diagnostics phase exists to remove.
        resp = {"ok": bool(pak), "pak_path": pak.replace("\\", "/") if pak else None,
                "applied": result.get("applied") or [], "skipped": result.get("skipped") or [],
                "artifacts": result.get("artifacts") or []}
        if copy_to_mods:
            ok, err, dest = _install_to_mods(mod_name, out_dir, result.get("artifacts"))
            if not ok:
                return {**resp, "ok": False, "built": True, "error": err}
            resp["installed_dir"] = dest.replace("\\", "/")
        return resp
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.get("/api/skin_swapper/status")
def api_skin_swapper_status():
    """Whether Project Galacta Skin Swapper export is available (template installed, not revoked)."""
    from atelier import skin_swapper
    skin_swapper.refresh_flag_async()
    response.content_type = "application/json"
    return json.dumps(skin_swapper.status())


@app.post("/api/skin_swapper/plan")
def api_skin_swapper_plan():
    """Validate a Skin Swapper export without building it: IDs, package names and every problem."""
    from atelier import skin_swapper
    body = request.json or {}
    response.content_type = "application/json"
    result = skin_swapper.plan(body.get("mod_name"), body.get("meshes") or [],
                               body.get("skin_name"), body.get("author"))
    return json.dumps({"ok": True, **result, "status": skin_swapper.status()})


@app.post("/api/skin_swapper/build")
def api_skin_swapper_build():
    """Build a Skin Swapper mod: the edited meshes and their Galacta configs in one container."""
    body = request.json or {}
    if body.get("background"):
        return _submit_job("export", "Skin Swapper export " + str(body.get("mod_name") or ""),
                           lambda job: _skin_swapper_payload(body))
    response.content_type = "application/json"
    return json.dumps(_skin_swapper_payload(body))


def _skin_swapper_payload(body):
    from atelier import skin_swapper
    mod_name = body.get("mod_name")
    copy_to_mods = bool(body.get("copy_to_mods"))
    password = (body.get("password") or "").strip() or None
    if copy_to_mods and not get_mods_folder():
        return {"ok": False, "error": "No mods folder set — configure one in Menu → Settings.",
                "need_mods_folder": True}
    out_dir = ASSETS_MODS
    os.makedirs(out_dir, exist_ok=True)
    try:
        result = skin_swapper.build(mod_name, body.get("meshes") or [], body.get("skin_name"),
                                    body.get("author"), out_dir, password)
        if not result.get("ok"):
            return {"ok": False, "error": result.get("error", "build failed"),
                    "problems": result.get("problems") or []}
        pak = result.get("pak")
        resp = {"ok": True, "pak_path": pak.replace("\\", "/"), "applied": result.get("applied") or [],
                "skipped": [], "artifacts": result.get("artifacts") or [], "galacta_folder": result.get("folder")}
        if copy_to_mods:
            ok, err, dest = _install_to_mods(mod_name, out_dir, result.get("artifacts"))
            if not ok:
                return {**resp, "ok": False, "built": True, "error": err}
            resp["installed_dir"] = dest.replace("\\", "/")
        return resp
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/pick_mod_file")
def api_pick_mod_file():
    """Native picker for a mod to repatch (.zip / .pak / .utoc). Reports if it's password-locked."""
    response.content_type = "application/json"
    try:
        path = hostos.pick_file("Select a mod to repatch", ("*.zip", "*.pak", "*.utoc"))
        locked = False
        if path:
            from atelier.handlers import modlock
            locked = modlock.is_locked(path)
        return json.dumps({"ok": True, "path": path, "locked": locked})
    except Exception as e:
        return json.dumps({"ok": False, "path": "", "error": str(e)})

@app.post("/api/repatch")
def api_repatch():
    """Repatch a picked mod for the current patch. body: {path, unlock, stage_as_project, password}."""
    body = request.json or {}
    if body.get("background"):
        return _submit_job("repatch", "Repatch mod", lambda job: _repatch_payload(body))
    response.content_type = "application/json"
    return json.dumps(_repatch_payload(body))


def _repatch_payload(body):
    src  = (body.get("path") or "").strip()
    if not src or not os.path.exists(src):
        return {"ok": False, "error": "Pick a mod file first."}
    from atelier.handlers.repatch import repatch_mod
    from atelier.handlers.texture import _build_lock
    if not _build_lock.acquire(blocking=False):
        return {"ok": False, "error": "Another mod build is in progress; wait before repatching."}
    name = re.sub(r'[/\\:*?"<>|.]', '', os.path.splitext(os.path.basename(src))[0])[:60] or "Mod"
    work = None
    try:
        os.makedirs(_CACHE, exist_ok=True)
        work = jobs.build_workspace(_CACHE)
        out_base = os.path.join(work, f"{name}_Repatched_9999999_P")
        if body.get("stage_as_project"):
            # This legacy option writes each decoded asset into the project.
            # Once it starts, finish it during shutdown rather than cancelling
            # halfway through a set of project writes.
            jobs.begin_publication("Repatching and importing project assets…")
        r = repatch_mod(src, out_base,
                        unlock=(body.get("unlock") or None),
                        stage_as_project=bool(body.get("stage_as_project")),
                        relock=((body.get("password") or "").strip() or None),
                        work_dir=os.path.join(work, "repatch"))
        if r.get("locked"):
            return {"ok": False, "locked": True, "error": r.get("error")}
        if not r.get("ok"):
            return {"ok": False, "error": r.get("error", "repatch failed"), "manifest": r.get("manifest")}
        jobs.begin_publication("Publishing repatched files…")
        artifacts = publish_files(container_files(out_base), ASSETS_MODS)
        pak = next(p for p in artifacts if p.endswith(".pak"))
        return {"ok": True, "manifest": r.get("manifest"), "skipped": r.get("skipped"),
                "pak": pak.replace("\\", "/"), "artifacts": artifacts, "mod": f"{name}_Repatched_9999999_P"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        if work:
            shutil.rmtree(work, ignore_errors=True)
        _build_lock.release()

@app.get("/api/open_export_folder")
def api_open_export_folder():
    """Open the app's export folder (assets/exported), selecting a specific pak when given."""
    os.makedirs(ASSETS_MODS, exist_ok=True)
    sel = request.query.get("select", "")
    if sel:
        abs_sel = os.path.abspath(sel)
        if os.path.exists(abs_sel):
            hostos.reveal(abs_sel, select=True)
            response.content_type = "application/json"
            return json.dumps({"ok": True})
    hostos.reveal(ASSETS_MODS, select=False)
    response.content_type = "application/json"
    return json.dumps({"ok": True})

# ── delete imported ───────────────────────────────────────────────────────────

# Every on-disk form a project edit can take. A mesh's edit is a .blend (plus Blender's .blend1
# backup and the texture manifest beside it), so deleting one has to clear those too -- otherwise
# the asset returns on the next sidebar refresh and "Delete" looks like it did nothing.
_EDIT_EXTS = project_trash.EDIT_EXTS

def _delete_imported(grs):
    """Move edits to the project trash. A move that fails rolls back and is reported, not raised."""
    try:
        return project_trash.remove(get_import_root(), grs)
    except project_trash.Interrupted as error:
        return {"ok": False, "error": str(error)}
    except OSError as error:
        # Usually a Windows sharing violation: another program has one of the files open.
        name = os.path.basename(error.filename or "") or "A file"
        hint = " Close any program using it and try again." if isinstance(error, PermissionError) else ""
        return {"ok": False, "error": f"{name} could not be moved to the project trash "
                                      f"({error.strerror or error}).{hint}"}

def _delete_one_imported(gr):
    """Compatibility entry point; a batch request uses one shared trash entry instead."""
    return _delete_imported([gr])

@app.post("/api/delete_imported")
def api_delete_imported():
    """Delete one edited asset (`game_rel`) or several (`game_rels`) — the multi-select delete in
    the sidebar sends the list, so clearing 30 assets is one request and one refresh instead of 30."""
    body = request.json or {}
    grs  = [g for g in (body.get("game_rels") or []) if g] or \
           ([body["game_rel"]] if body.get("game_rel") else [])
    response.content_type = "application/json"
    if not grs:
        return json.dumps({"ok": False, "error": "missing game_rel"})
    return json.dumps(_delete_imported(grs))

@app.post("/api/delete_all_imported")
def api_delete_all_imported():
    items = all_imported()
    response.content_type = "application/json"
    return json.dumps(_delete_imported([item['game_rel'] for item in items]))


@app.post('/api/restore_imported')
def api_restore_imported():
    response.content_type = 'application/json'
    return json.dumps(project_trash.restore(get_import_root(), (request.json or {}).get('entry')))

@app.get("/api/asset_info")
def api_asset_info():
    """Return pak source + game path for a game_rel (for sidebar tooltips)."""
    gr = request.query.get("game_rel", "")
    response.content_type = "application/json"
    if not gr:
        return json.dumps({"ok": False, "error": "missing game_rel"})
    info = _asset_cache.get(gr)
    if not info:
        return json.dumps({"ok": False})
    pak       = os.path.basename(info.get("pak", ""))
    pfx       = info.get("pfx", "")
    # mount_join, not concatenation: a plugin game_rel carries a synthetic 'Plugins/<Name>' root
    # that names its mount, so pasting it after the mount would show a path that exists nowhere.
    from atelier.index import mount_join
    game_path = mount_join(pfx, gr) if pfx else gr
    return json.dumps({"ok": True, "pak": pak, "game_path": game_path})


# ── per-asset export options (#12 dye-off · #20 mips/group · #21 LQ twin · #22 blank) ──

@app.get("/api/asset_opts")
def api_asset_opts():
    """One asset's export options, plus everything the panel needs to render the controls:
    the texture groups on offer, the group this texture actually declares, and whether the two
    options that depend on the install (a Marvel_LQ mount, a dyeing material) apply at all."""
    gr = request.query.get("game_rel", "")
    response.content_type = "application/json"
    if not gr:
        return json.dumps({"ok": False, "error": "missing game_rel"})
    from atelier.handlers.texture import (TEXTURE_GROUPS, texture_props, texture_format,
                                          format_has_alpha)
    out = {"ok": True, "game_rel": gr,
           "opts": _project_meta.effective_asset_opts(_project_meta.get_asset_opts(get_import_root(), gr), gr),
           "groups": list(TEXTURE_GROUPS), "current_group": "", "has_lq": False,
           "dyeable": False, "mask": "", "format": "", "blank_alpha": True}
    try:
        from atelier.index import has_lq_mount
        out["has_lq"] = has_lq_mount()
    except Exception:
        pass
    if is_material(gr):
        try:
            from atelier.handlers.dye import dye_off_target
            out["mask"] = dye_off_target(gr) or ""
            out["dyeable"] = bool(out["mask"])
        except Exception as e:
            out["dye_error"] = str(e)
        return json.dumps(out)
    # Textures only from here: reading the declared LODGroup costs a to_json, so it is not done
    # for asset kinds that have none.
    try:
        wb = _cache_import_base(gr)
        if wb and os.path.exists(wb + ".uasset"):
            out["current_group"] = texture_props(wb).get("lod_group") or ""
            # Whether "blank" can mean invisible or only black, for THIS texture — the control has
            # to say so before it is used, not in the export log afterwards.
            out["format"]      = texture_format(wb)
            out["blank_alpha"] = format_has_alpha(out["format"])
    except Exception as e:
        out["group_error"] = str(e)
    return json.dumps(out)

@app.post("/api/asset_opts")
def api_asset_opts_save():
    """Merge export options into one asset. Options are per PROJECT, not global: two projects can
    ship the same texture with and without mips, and neither is a setting on the app."""
    body = request.json or {}
    gr   = body.get("game_rel", "")
    response.content_type = "application/json"
    if not gr:
        return json.dumps({"ok": False, "error": "missing game_rel"})
    opts = body.get("opts")
    if not isinstance(opts, dict):
        return json.dumps({"ok": False, "error": "opts must be an object"})
    from atelier.handlers.texture import TEXTURE_GROUPS
    clean = {}
    for k in ("no_mips", "blank", "dye_off", "lq_twin"):
        if k in opts:
            clean[k] = bool(opts[k])
    if "lod_group" in opts:
        g = opts["lod_group"] or ""
        if g and g not in TEXTURE_GROUPS:
            return json.dumps({"ok": False, "error": "unknown texture group: " + str(g)})
        clean["lod_group"] = g
    try:
        cur = _project_meta.set_asset_opts(get_import_root(), gr, clean)
        return json.dumps({"ok": True, "opts": _project_meta.effective_asset_opts(cur, gr)})
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)})

# ── Shader Studio ─────────────────────────────────────────────────────────────────
import atelier.handlers.shaders as _shaders

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

# Shader EDITING is permanently disabled — Shader Studio ships as a read-only viewer so it can't be
# used to build cheat shaders. Browsing/disassembly (status, build index, list, disasm) stay open.
_SHADER_EDIT_DISABLED = json.dumps(
    {"ok": False, "error": "Shader editing is disabled — Shader Studio is a read-only viewer."})

@app.get("/api/shaders/constants")
@app.post("/api/shaders/build_mod")
@app.get("/api/shaders/ir")
@app.post("/api/shaders/build_mod_ir")
def api_shaders_edit_disabled():
    response.content_type = "application/json"
    return _SHADER_EDIT_DISABLED


# ── World: edit level (.umap) lighting / components / fog / grade (bundles into the unified mod) ──
from atelier.handlers.world import read_world, save_world, reset_world

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


# ── Text: edit StringTable strings (bundles into the unified mod) ────────────────
from atelier.handlers.text import read_text, save_text, reset_text

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


def shutdown(timeout=15):
    """Stop admission, drain managed jobs, then release native worker/watchers."""
    if not jobs.shutdown(timeout):
        return False
    import_server.shutdown()
    _thumb_executor.shutdown(wait=False, cancel_futures=True)
    _observer.stop()
    _observer.join(timeout=5)
    from atelier.tools import _shutdown
    _shutdown()
    return True
