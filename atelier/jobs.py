"""Tracked project work with cooperative cancellation and restart-safe status.

Only status/results are persisted. Inputs (notably mod passwords) stay in memory.
Cancellation stops owned native processes; publication is an uncancellable final
step so a request cannot leave half of a container set installed.
"""
from contextvars import ContextVar
from contextlib import contextmanager
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
import uuid

from atelier import operations
from atelier.storage import atomic_json

ACTIVE = {"queued", "running", "cancelling"}
_current = ContextVar("atelier_job", default=None)
_instance = None
_instance_lock = threading.Lock()


class Cancelled(BaseException):
    """Bypass legacy per-asset 'except Exception: skip' handlers."""


def current():
    return _current.get()


def checkpoint():
    job = current()
    if job:
        job.checkpoint()


@contextmanager
def cancellable_lock(lock):
    while not lock.acquire(timeout=0.1):
        checkpoint()
    try:
        checkpoint()
        yield
    finally:
        lock.release()


def progress(stage, current_count=None, total=None):
    job = current()
    if job:
        job.update(stage, current_count, total)


def begin_publication(stage="Publishing exported files…"):
    job = current()
    if job:
        job.begin_publication(stage)


def build_workspace(cache):
    job = current()
    parent = job.manager.workspace(job.id) if job else cache
    os.makedirs(parent, exist_ok=True)
    return tempfile.mkdtemp(prefix="build-", dir=parent)


class Job:
    def __init__(self, manager, record, root):
        self.manager, self.record, self.root = manager, record, root
        self.id = record["id"]
        self.cancelled = threading.Event()
        self.thread = None

    def checkpoint(self):
        if self.cancelled.is_set():
            raise Cancelled()

    def update(self, stage, current_count=None, total=None):
        self.checkpoint()
        with self.manager.lock:
            self.record["stage"] = stage
            if current_count is not None:
                self.record["current"] = current_count
            if total is not None:
                self.record["total"] = total
            self.manager.save(self.record)

    def begin_publication(self, stage):
        with self.manager.lock:
            self.checkpoint()
            self.record.update(can_cancel=False, stage=stage)
            self.manager.save(self.record)


class JobManager:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.records, self.live = {}, {}
        self.closing = False
        for path in self.directory.glob("*.json"):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
                if str(uuid.UUID(record["id"])) != path.stem:
                    continue
                if record["state"] in ACTIVE:
                    record.update(state="interrupted", can_cancel=False,
                                  error="Atelier closed before this job finished. Review the output before retrying.",
                                  stage="Interrupted by a previous shutdown")
                    self.save(record)
                self.records[record["id"]] = record
                self.cleanup(record["id"])
            except (OSError, ValueError, KeyError, TypeError):
                continue  # Retain unreadable status for diagnosis, never execute its contents.

    def save(self, record):
        record["updated"] = time.time()
        atomic_json(str(self.directory / (record["id"] + ".json")), record)

    def workspace(self, job_id):
        # A UUID-owned workspace is the only tree startup recovery may remove.
        name = str(uuid.UUID(job_id))
        path = self.directory / name / "work"
        if not path.resolve().is_relative_to(self.directory) or path.is_symlink():
            raise ValueError("Job workspace is outside application data")
        return str(path)

    def cleanup(self, job_id):
        path = self.workspace(job_id)
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)

    def submit(self, kind, label, root, project, work, on_finish=None):
        release = operations.reserve(root)
        try:
            with self.lock:
                if self.closing:
                    raise operations.BusyError("Atelier is closing; wait before starting another operation.")
                for job in self.live.values():
                    if os.path.normcase(job.root) == os.path.normcase(root):
                        raise operations.BusyError("This project already has a job in progress. View Activity to cancel or wait.")
                    if kind in ("export", "repatch") and job.record["kind"] in ("export", "repatch"):
                        raise operations.BusyError("Another mod build is in progress. View Activity to cancel or wait.")
                record = dict(id=str(uuid.uuid4()), kind=kind, label=label, project=project,
                              state="queued", stage="Waiting to start…", current=0, total=0,
                              can_cancel=True, created=time.time(), updated=time.time(),
                              error=None, result=None)
                job = Job(self, record, root)
                self.save(record)
                self.records[job.id] = record
                self.live[job.id] = job
                job.thread = threading.Thread(target=self._run, args=(job, work, release, on_finish),
                                              name="atelier-" + kind, daemon=True)
                try:
                    job.thread.start()
                except BaseException:
                    self.live.pop(job.id, None)
                    record.update(state="failed", error="Could not start the background worker", can_cancel=False)
                    self.save(record)
                    raise
                return self.snapshot(job.id, project)
        except BaseException:
            release()
            raise

    def _run(self, job, work, release, on_finish=None):
        from atelier import config
        token = _current.set(job)
        try:
            with operations.project_use(job.root, write=True), config.project_context(job.root):
                job.checkpoint()
                with self.lock:
                    job.record.update(state="running", stage="Starting…")
                    self.save(job.record)
                result = work(job)
                # A completed publication is never relabelled as cancelled.
                job.checkpoint()
                with self.lock:
                    job.record.update(state="succeeded" if result.get("ok") else "failed",
                                      result=result, error=result.get("error"), stage="Finished")
        except Cancelled:
            with self.lock:
                job.record.update(state="cancelled", stage="Cancelled", error="Cancelled by request.",
                                  result={"ok": False, "cancelled": True, "error": "Operation cancelled."})
        except Exception as exc:
            with self.lock:
                job.record.update(state="failed", stage="Failed", error=str(exc),
                                  result={"ok": False, "error": str(exc)})
        finally:
            try:
                with self.lock:
                    job.record["can_cancel"] = False
                    self.save(job.record)
            finally:
                try:
                    if on_finish:
                        on_finish()
                finally:
                    try:
                        self.cleanup(job.id)
                    finally:
                        _current.reset(token)
                        release()
                        with self.lock:
                            self.live.pop(job.id, None)

    def snapshot(self, job_id, project):
        with self.lock:
            record = self.records.get(job_id)
            if not record or record.get("project") != project:
                raise ValueError("Job not found in this project")
            return copy.deepcopy(record)

    def list(self, project):
        with self.lock:
            items = [copy.deepcopy(r) for r in self.records.values() if r.get("project") == project]
            return sorted(items, key=lambda r: r["created"], reverse=True)[:40]

    def cancel(self, job_id, project):
        with self.lock:
            self.snapshot(job_id, project)
            job = self.live.get(job_id)
            if not job or not job.record["can_cancel"]:
                return False
            job.cancelled.set()
            job.record.update(state="cancelling", stage="Stopping…")
            self.save(job.record)
            return True

    def shutdown(self, timeout=15):
        with self.lock:
            self.closing = True
            live = list(self.live.values())
            for job in live:
                self.cancel(job.id, job.record["project"])
        deadline = time.monotonic() + timeout
        for job in live:
            if job.thread is not threading.current_thread():
                job.thread.join(max(0, deadline - time.monotonic()))
        with self.lock:
            return not self.live


def manager():
    global _instance
    with _instance_lock:
        if _instance is None:
            from atelier.config import DATA_ROOT, ASSETS_MODS, get_mods_folder
            from atelier.storage import recover_destination
            for destination in {ASSETS_MODS, get_mods_folder()} - {None, ""}:
                recover_destination(destination)
            _instance = JobManager(os.path.join(DATA_ROOT, "_jobs"))
        return _instance


def shutdown(timeout=15):
    return _instance.shutdown(timeout) if _instance else True


def run_process(args, **kwargs):
    """subprocess.run semantics, with cancellation only for the current job's child."""
    if current() is None:
        return subprocess.run(args, **kwargs)
    checkpoint()
    timeout = kwargs.pop("timeout", None)
    check = kwargs.pop("check", False)
    input_data = kwargs.pop("input", None)
    if input_data is not None:
        kwargs["stdin"] = subprocess.PIPE
    if kwargs.pop("capture_output", False):
        kwargs.update(stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    started = time.monotonic()
    with subprocess.Popen(args, **kwargs) as process:
        try:
            first = True
            while True:
                checkpoint()
                if timeout is not None and time.monotonic() - started >= timeout:
                    raise subprocess.TimeoutExpired(args, timeout)
                try:
                    stdout, stderr = process.communicate(input_data if first else None, timeout=0.15)
                    break
                except subprocess.TimeoutExpired:
                    first = False
        except BaseException:
            process.kill()
            process.communicate()
            raise
        checkpoint()
        if check and process.returncode:
            raise subprocess.CalledProcessError(process.returncode, args, stdout, stderr)
        return subprocess.CompletedProcess(args, process.returncode, stdout, stderr)
