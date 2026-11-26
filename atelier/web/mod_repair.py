"""HTTP entry points for checking installed mods and saving a repaired copy."""
from pathlib import Path
import re
import threading

from bottle import request, response

from atelier import config, hostos, jobs, operations
from atelier.handlers import file_repair


_startup_lock = threading.Lock()
_startup_job = None
_active_stages = {"queued", "running"}


def _scan_installed():
    global _startup_job

    folder = config.get_mods_folder()
    if not folder or not Path(folder).is_dir():
        return {"ok": True, "checked": 0, "repairs": []}

    with _startup_lock:
        manager = jobs.manager()
        if _startup_job and _startup_job[0] == folder:
            previous = manager.snapshot(_startup_job[1], "")
            if previous and previous["state"] in _active_stages:
                return {"ok": True, "job_id": previous["id"], "job": previous}
        try:
            job = manager.submit(
                "installed-mod-check", "Check installed mods",
                str(Path(config._CACHE) / "installed-mod-check"), "",
                lambda job: file_repair.scan_installed(folder),
            )
        except operations.BusyError as exc:
            return {"ok": False, "error": str(exc)}
        _startup_job = (folder, job["id"])
        return {"ok": True, "job_id": job["id"], "job": job}


def _repaired_destination(folder, name):
    # The folder comes from the desktop picker. Only the basename may come from the view.
    stem = name[:-4][:180]
    root = Path(folder)
    for index in range(1, 101):
        suffix = f"-{index}" if index > 1 else ""
        destination = root / f"{stem}{suffix}.zip"
        if not destination.exists() and not destination.is_symlink():
            return destination
    return None


def register(app, submit_job):
    @app.get("/api/mod_repair/installed", skip=["project_scope"])
    def api_mod_repair_installed():
        response.set_header("Cache-Control", "no-store")
        return _scan_installed()

    @app.post("/api/mod_repair/scan")
    def api_mod_repair_scan():
        body = request.json or {}
        path = body.get("path")
        if not isinstance(path, str) or not path or "\x00" in path:
            return {"ok": False, "error": "Choose a mod file first."}
        if body.get("background"):
            return submit_job("mod-check", "Check for material issues",
                              lambda job: file_repair.scan_source(path))
        return file_repair.scan_source(path)

    @app.post("/api/mod_repair/save")
    def api_mod_repair_save():
        body = request.json or {}
        token, name = body.get("token"), body.get("suggested_name")
        if not isinstance(token, str) or not token:
            return {"ok": False, "error": "Check this mod again before saving a repaired copy."}
        if not isinstance(name, str) or not re.fullmatch(r'[^<>:"/\\|?*\x00-\x1f]+\.zip', name, re.I):
            return {"ok": False, "error": "Choose a valid ZIP filename for the repaired copy."}
        try:
            folder = hostos.pick_folder(title="Choose where to save the repaired copy")
            if not folder:
                return {"ok": False, "cancelled": True}
            destination = _repaired_destination(folder, name)
        except (OSError, RuntimeError) as exc:
            return {"ok": False, "error": str(exc)}
        if destination is None:
            return {"ok": False, "error": "Choose another folder for the repaired copy."}
        if body.get("background"):
            return submit_job("mod-repair", "Save repaired copy",
                              lambda job: file_repair.save_repaired(token, destination))
        return file_repair.save_repaired(token, destination)
