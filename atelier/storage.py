"""Atomic sidecar writes and recoverable publication of complete mod file sets."""
import hashlib
import json
import os
import shutil
import tempfile
import threading

_publish_lock = threading.RLock()
_PREFIX = ".atelier-publish-"


class PublicationRecoveryError(RuntimeError):
    """A replacement could not be rolled back; callers must not reuse its output."""


def atomic_json(path, data, **kwargs):
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".atelier-write-", dir=parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, **kwargs)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def _digest(path):
    with open(path, "rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def container_files(base):
    """Require every member before replacing any previous mod."""
    files = [base + ext for ext in (".pak", ".ucas", ".utoc")]
    missing = [os.path.basename(p) for p in files if not os.path.isfile(p) or not os.path.getsize(p)]
    if missing:
        raise RuntimeError("Incomplete mod output: " + ", ".join(missing))
    return files


def _plain_name(name):
    return (isinstance(name, str) and name not in ("", ".", "..")
            and os.path.basename(name) == name
            and not any(c in name for c in '/\\:'))


def _rollback(folder, destination, entries):
    # Backups are copied, not consumed: an interrupted rollback can be retried.
    for entry in entries:
        name = entry["name"]
        if not _plain_name(name):
            raise RuntimeError("Invalid publication journal")
        target = os.path.join(destination, name)
        if entry["had_old"]:
            backup = os.path.join(folder, "backup", name)
            if not os.path.isfile(backup):
                raise RuntimeError("Missing publication backup: " + name)
            restore = os.path.join(folder, "new", name)
            shutil.copy2(backup, restore)
            os.replace(restore, target)
        elif os.path.exists(target):
            os.remove(target)


def recover_publications(destination):
    """Recover interrupted publications before another write to this destination.

    Caller must hold the publication lock. Unknown/incomplete journals are retained
    for inspection; no path supplied by a journal is trusted outside its directory.
    """
    if not os.path.isdir(destination):
        return
    for name in os.listdir(destination):
        if not name.startswith(_PREFIX):
            continue
        folder = os.path.join(destination, name)
        if not os.path.isdir(folder) or os.path.islink(folder):
            continue
        journal = os.path.join(folder, "journal.json")
        if not os.path.isfile(journal):
            continue  # preparation had not reached the point where any output could change
        with open(journal, encoding="utf-8") as f:
            data = json.load(f)
        if data["state"] != "committed":
            _rollback(folder, destination, data["entries"])
        shutil.rmtree(folder)


def publish_files(sources, destination):
    """Copy, verify, back up, then replace. Restore previous files on any failure.

    A multi-file mod is not an atomic filesystem object. A durable journal and
    backups allow the next publication to recover after process interruption.
    No game files outside the explicit artifact set are touched.
    """
    sources = [os.path.abspath(p) for p in sources]
    names = [os.path.basename(p) for p in sources]
    if not sources or len(set(n.lower() for n in names)) != len(names):
        raise ValueError("Empty or duplicate mod artifact set")
    if any(not _plain_name(n) for n in names):
        raise ValueError("Invalid mod artifact name")
    for p in sources:
        if not os.path.isfile(p) or not os.path.getsize(p):
            raise RuntimeError("Missing or empty mod artifact: " + os.path.basename(p))
    destination = os.path.abspath(destination)
    with _publish_lock:
        os.makedirs(destination, exist_ok=True)
        recover_publications(destination)
        folder = tempfile.mkdtemp(prefix=_PREFIX, dir=destination)
        os.makedirs(os.path.join(folder, "new"))
        os.makedirs(os.path.join(folder, "backup"))
        entries, publishing = [], False
        try:
            for src, name in zip(sources, names):
                staged = os.path.join(folder, "new", name)
                shutil.copy2(src, staged)
                if _digest(src) != _digest(staged):
                    raise RuntimeError("Artifact copy failed verification: " + name)
                target = os.path.join(destination, name)
                had_old = os.path.exists(target)
                if had_old:
                    shutil.copy2(target, os.path.join(folder, "backup", name))
                entries.append({"name": name, "had_old": had_old})
            journal = os.path.join(folder, "journal.json")
            atomic_json(journal, {"state": "publishing", "entries": entries})
            publishing = True
            for name in names:
                os.replace(os.path.join(folder, "new", name), os.path.join(destination, name))
            atomic_json(journal, {"state": "committed", "entries": entries})
        except Exception as error:
            if publishing:
                try:
                    _rollback(folder, destination, entries)
                except Exception as rollback_error:
                    raise PublicationRecoveryError(
                        f"Publication failed ({error}); recovery pending at {folder}: "
                        f"{rollback_error}") from error
            shutil.rmtree(folder, ignore_errors=True)
            raise
        # A cleanup failure after commit must not turn a successful publication into a failure.
        shutil.rmtree(folder, ignore_errors=True)
    return [os.path.join(destination, n) for n in names]


def recover_destination(destination):
    with _publish_lock:
        recover_publications(destination)


def _project_target(root, relative):
    from atelier.config import project_base
    return os.path.realpath(project_base(relative, root))


def recover_project_writes(root):
    """Roll back an interrupted bulk save before serving project data again."""
    with _publish_lock:
        base = _project_target(root, ".atelier/transactions")
        if not os.path.isdir(base):
            return
        for name in os.listdir(base):
            if not _plain_name(name):
                continue
            folder = os.path.join(base, name)
            journal = os.path.join(folder, "journal.json")
            if not os.path.isfile(journal) or os.path.islink(folder):
                continue
            with open(journal, encoding="utf-8") as stream:
                data = json.load(stream)
            if data["state"] != "committed":
                for i, entry in enumerate(data["entries"]):
                    target = _project_target(root, entry["path"])
                    if entry["had_old"]:
                        backup = os.path.join(folder, str(i) + ".bak")
                        with open(backup, "rb") as stream:
                            payload = stream.read()
                        _atomic_bytes(target, payload)
                    elif os.path.exists(target):
                        os.remove(target)
            shutil.rmtree(folder)


def _atomic_bytes(path, payload):
    parent = os.path.dirname(path)
    os.makedirs(parent, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".atelier-write-", dir=parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def publish_project_json(root, changes):
    """Compare all previews first, then persist JSON as one recoverable batch.

    changes: [{path: project-relative path, before: SHA256 or None, data: JSON}].
    A failure restores every previous byte, including files absent before the batch.
    """
    return _publish_project_changes(root, changes,
                                    lambda target, change: atomic_json(target, change["data"], allow_nan=False))


def publish_project_files(root, changes):
    """Recoverably publish staged project files, checking previous hashes before any write."""
    def write(target, change):
        with open(change["source"], "rb") as stream:
            _atomic_bytes(target, stream.read())
    return _publish_project_changes(root, changes, write)


def _publish_project_changes(root, changes, write):
    import uuid
    with _publish_lock:
        recover_project_writes(root)
        targets = [_project_target(root, c["path"]) for c in changes]
        if len(set(os.path.normcase(p) for p in targets)) != len(targets):
            raise ValueError("Duplicate bulk save target")
        for target, change in zip(targets, changes):
            actual = _digest(target) if os.path.isfile(target) else None
            if actual != change["before"]:
                raise RuntimeError("An asset changed after preview. Review the batch again before saving.")
        folder = os.path.join(root, ".atelier", "transactions", str(uuid.uuid4()))
        os.makedirs(folder)
        entries = []
        try:
            for i, (target, change) in enumerate(zip(targets, changes)):
                had_old = os.path.isfile(target)
                if had_old:
                    shutil.copy2(target, os.path.join(folder, str(i) + ".bak"))
                entries.append({"path": change["path"], "had_old": had_old})
            journal = os.path.join(folder, "journal.json")
            atomic_json(journal, {"state": "publishing", "entries": entries})
            for target, change in zip(targets, changes):
                write(target, change)
            atomic_json(journal, {"state": "committed", "entries": entries})
        except Exception as error:
            try:
                recover_project_writes(root)
            except Exception as rollback_error:
                raise PublicationRecoveryError(
                    f"Bulk save failed ({error}); recovery pending at {folder}: {rollback_error}") from error
            raise
        shutil.rmtree(folder, ignore_errors=True)
