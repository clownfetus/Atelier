"""Check local mod containers and write confirmed repairs as separate ZIPs."""
from collections import OrderedDict
from collections.abc import Callable
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, dataclass
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import secrets
import stat
import subprocess
import tempfile
import threading
from typing import BinaryIO
import zipfile
import zlib

from atelier import config, file_fixer, hostos, jobs
from atelier.handlers import modlock
from atelier.storage import atomic_json
from atelier.tools import container_retoc

_EXTENSIONS = (".utoc", ".ucas", ".pak")
_BLOCK = 1024 * 1024
_MAX_ARCHIVE_BYTES = 512 * _BLOCK
_MAX_ZIP_DIRECTORY = 2 * _BLOCK
_MAX_ZIP_BYTES = _MAX_ARCHIVE_BYTES + 2 * _MAX_ZIP_DIRECTORY
_MAX_ZIP_MEMBERS = 4096
_CACHE_VERSION = 1
_CACHE_LIMIT = 512
_CONFIRMATION_LIMIT = 1024
_WORK_LOCK = threading.Lock()
_RESERVED_NAMES = {"con", "prn", "aux", "nul", "conin$", "conout$"} | {
    stem + number for stem in ("com", "lpt") for number in "123456789¹²³"
}
_BAD_ARCHIVE = (zipfile.BadZipFile, EOFError, UnicodeError, zlib.error, NotImplementedError)
_STALE = "The source mod has changed. Check it again before saving."


class _SourceIssue(ValueError):
    def __init__(self, status, reason):
        super().__init__(reason)
        self.status = status


@dataclass
class _Bundle:
    utoc: bytes
    ucas: bytes
    fingerprint: str
    pair_digest: str
    expanded_bytes: int
    write_zip: Callable[[BinaryIO, bytes, bytes], None]


@dataclass(frozen=True)
class _Confirmation:
    source: Path
    fingerprint: str
    module: str
    scan: file_fixer.ScanResult


_confirmed: OrderedDict[str, _Confirmation] = OrderedDict()


def _component_is_safe(name):
    return (
        bool(name) and not name.endswith((" ", "."))
        and not any(c in '<>:"|?*\\/' or ord(c) < 32 or ord(c) == 127 for c in name)
        and name.split(".", 1)[0].rstrip(" ").casefold() not in _RESERVED_NAMES
    )


class _ZipReader:
    """Bound the ZIP directory read before zipfile allocates its member table."""

    def __init__(self, stream):
        self.stream = stream

    def __getattr__(self, name):
        return getattr(self.stream, name)

    def read(self, size=-1):
        if size < 0:
            position = self.stream.tell()
            size = self.stream.seek(0, os.SEEK_END) - position
            self.stream.seek(position)
        if size > _MAX_ZIP_DIRECTORY:
            raise _SourceIssue("review", "The ZIP directory exceeds the file repair limit.")
        return self.stream.read(size)


def _zip_members(archive):
    members = archive.infolist()
    if len(members) > _MAX_ZIP_MEMBERS or sum(info.file_size for info in members) > _MAX_ARCHIVE_BYTES:
        raise _SourceIssue("review", "The ZIP exceeds the file repair limit.")
    names = {}
    folded = {}
    for info in members:
        name = info.orig_filename.replace("\\", "/")
        is_dir = name.endswith("/")
        parts = name.removesuffix("/").split("/")
        key = name.removesuffix("/").casefold()
        kind = stat.S_IFMT(info.external_attr >> 16)
        if (
            not all(_component_is_safe(part) for part in parts) or key in folded
            or kind not in (0, stat.S_IFDIR if is_dir else stat.S_IFREG)
            or info.external_attr & stat.FILE_ATTRIBUTE_REPARSE_POINT
            or (is_dir and info.file_size)
        ):
            raise _SourceIssue("unreadable", "The ZIP contains unsafe or conflicting member names.")
        if info.flag_bits & 0x41:
            raise _SourceIssue("review", "The ZIP contains password-protected files.")
        if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            raise _SourceIssue("review", "The ZIP uses an unsupported compression method.")
        folded[key] = is_dir
        names[name] = info
    for key in folded:
        if any(folded.get(str(parent)) is False for parent in PurePosixPath(key).parents):
            raise _SourceIssue("unreadable", "The ZIP contains conflicting member names.")
    return names


def _pair_names(names):
    by_suffix = {suffix: [] for suffix in _EXTENSIONS}
    for name in names:
        suffix = PurePosixPath(name).suffix.lower()
        if not name.endswith("/") and suffix in by_suffix:
            by_suffix[suffix].append(name)
    tocs, data, paks = (by_suffix[suffix] for suffix in _EXTENSIONS)
    if not tocs or not data:
        raise _SourceIssue("review", "The mod needs a matching .utoc and .ucas pair.")
    if len(tocs) != 1 or len(data) != 1:
        raise _SourceIssue("review", "The mod contains more than one possible container pair.")
    stem = tocs[0].rsplit(".", 1)[0].casefold()
    if data[0].rsplit(".", 1)[0].casefold() != stem:
        raise _SourceIssue("review", "The .utoc and .ucas must share a name and folder.")
    companions = [pak for pak in paks if pak.rsplit(".", 1)[0].casefold() == stem]
    if len(companions) > 1:
        raise _SourceIssue("review", "The mod contains more than one matching .pak.")
    return tocs[0], data[0], companions[0] if companions else None


def _stamp(meta):
    common = (meta.st_dev, meta.st_ino, meta.st_mode, meta.st_size, meta.st_mtime_ns)
    # On Windows lstat and fstat can give different values for st_ctime on the same file.
    return common if os.name == "nt" else common + (meta.st_ctime_ns,)


def _reparse(meta):
    return bool(getattr(meta, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


@contextmanager
def _open_file(path):
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or _reparse(before):
        raise _SourceIssue("unreadable", "The mod must be a regular file.")
    stamp = _stamp(before)
    with path.open("rb") as stream:
        if _stamp(os.fstat(stream.fileno())) != stamp:
            raise _SourceIssue("unreadable", _STALE)
        yield stream, before.st_size
        if _stamp(os.fstat(stream.fileno())) != stamp or _stamp(path.lstat()) != stamp:
            raise _SourceIssue("unreadable", _STALE)


def _copy_stream(source, size, checkpoint, target=None):
    digest = hashlib.sha256()
    remaining = size
    while remaining:
        checkpoint()
        block = source.read(min(remaining, _BLOCK))
        if not block:
            raise _SourceIssue("unreadable", "A mod file ended before its declared size.")
        if target is not None:
            target.write(block)
        digest.update(block)
        remaining -= len(block)
    if source.read(1):
        raise _SourceIssue("unreadable", "A mod file exceeds its declared size.")
    return digest.digest()


def _read_payload(source, size, checkpoint):
    with io.BytesIO() as output:
        digest = _copy_stream(source, size, checkpoint, output)
        return output.getvalue(), digest


def _check_pair_size(toc_size, data_size):
    if not toc_size or not data_size:
        raise _SourceIssue("unreadable", "One of the mod's container files is empty.")
    if toc_size + data_size > file_fixer.MAX_INPUT_BYTES:
        raise _SourceIssue("review", "The container pair exceeds the file repair limit.")


def _check_legacy_lock(utoc, ucas):
    if modlock._scan_bytes(ucas) or modlock._scan_bytes(utoc):
        raise _SourceIssue("review", "This mod is password-protected. Unlock it in Repatch.")


@contextmanager
def _read_zip(path, checkpoint):
    with _open_file(path) as (stream, size):
        if size > _MAX_ZIP_BYTES:
            raise _SourceIssue("review", "The ZIP exceeds the file repair limit.")
        with zipfile.ZipFile(_ZipReader(stream)) as archive:
            members = _zip_members(archive)
            toc_name, data_name, _pak = _pair_names(members)
            toc_info, data_info = members[toc_name], members[data_name]
            _check_pair_size(toc_info.file_size, data_info.file_size)
            with archive.open(toc_info) as entry:
                utoc, toc_hash = _read_payload(entry, toc_info.file_size, checkpoint)
            with archive.open(data_info) as entry:
                ucas, data_hash = _read_payload(entry, data_info.file_size, checkpoint)
            _check_legacy_lock(utoc, ucas)
            stream.seek(0)
            fingerprint = _copy_stream(stream, size, checkpoint)

            def write_zip(target, new_utoc, new_ucas):
                replacements = {toc_name: new_utoc, data_name: new_ucas}
                with zipfile.ZipFile(target, "w") as output:
                    output.comment = archive.comment
                    for name, info in members.items():
                        checkpoint()
                        # Keeping the original extra fields can reintroduce alternate paths
                        # or old size information for replaced entries.
                        copied = zipfile.ZipInfo(name, info.date_time)
                        copied.create_system = info.create_system
                        copied.external_attr = info.external_attr
                        copied.compress_type = info.compress_type
                        copied.comment = info.comment
                        copied.file_size = len(replacements[name]) if name in replacements else info.file_size
                        with output.open(copied, "w") as destination:
                            if name in replacements:
                                _write_bytes(destination, replacements[name], checkpoint)
                            else:
                                with archive.open(info) as original:
                                    _copy_stream(original, info.file_size, checkpoint, destination)
                stream.seek(0)
                if _copy_stream(stream, size, checkpoint) != fingerprint:
                    raise _SourceIssue("unreadable", _STALE)

            expanded_bytes = sum(info.file_size for info in members.values())
            yield _Bundle(utoc, ucas, fingerprint.hex(), hashlib.sha256(toc_hash + data_hash).hexdigest(),
                          expanded_bytes, write_zip)


def _write_bytes(target, payload, checkpoint):
    view = memoryview(payload)
    for offset in range(0, len(view), _BLOCK):
        checkpoint()
        target.write(view[offset:offset + _BLOCK])


def _loose_names(source):
    names = [sibling.name for sibling in source.parent.iterdir()
             if sibling.stem.casefold() == source.stem.casefold() and sibling.suffix.lower() in _EXTENSIONS]
    match = _pair_names(names)
    if source not in [source.with_name(name) for name in match if name]:
        raise _SourceIssue("unreadable", "The selected mod file could not be found.")
    return match


@contextmanager
def _read_loose(path, checkpoint, names=None):
    toc_name, data_name, pak_name = names or _loose_names(path)
    if not all(_component_is_safe(name) for name in (toc_name, data_name, pak_name) if name):
        raise _SourceIssue("unreadable", "The mod has an unsafe container file name.")
    with ExitStack() as opened:
        toc, toc_size = opened.enter_context(_open_file(path.with_name(toc_name)))
        data, data_size = opened.enter_context(_open_file(path.with_name(data_name)))
        _check_pair_size(toc_size, data_size)
        utoc, toc_hash = _read_payload(toc, toc_size, checkpoint)
        ucas, data_hash = _read_payload(data, data_size, checkpoint)
        _check_legacy_lock(utoc, ucas)
        pak_hash = b""
        expanded_bytes = toc_size + data_size
        if pak_name:
            pak, size = opened.enter_context(_open_file(path.with_name(pak_name)))
            expanded_bytes += size
            if expanded_bytes > _MAX_ARCHIVE_BYTES:
                raise _SourceIssue("review", "The mod exceeds the file repair limit.")
            pak_hash = _copy_stream(pak, size, checkpoint)
        pair_hashes = toc_hash + data_hash
        fingerprint = hashlib.sha256(
            pair_hashes + pak_hash + "\0".join((toc_name, data_name, pak_name or "")).encode("utf-8")
        ).hexdigest()

        def write_zip(target, new_utoc, new_ucas):
            with zipfile.ZipFile(target, "w") as output:
                for name, payload in ((toc_name, new_utoc), (data_name, new_ucas)):
                    with output.open(name, "w") as entry:
                        _write_bytes(entry, payload, checkpoint)
                if pak_name:
                    pak.seek(0)
                    with output.open(pak_name, "w") as entry:
                        if _copy_stream(pak, size, checkpoint, entry) != pak_hash:
                            raise _SourceIssue("unreadable", _STALE)
            if _loose_names(path) != (toc_name, data_name, pak_name):
                raise _SourceIssue("unreadable", _STALE)

        yield _Bundle(utoc, ucas, fingerprint, hashlib.sha256(pair_hashes).hexdigest(),
                      expanded_bytes, write_zip)


def _read_source(path, checkpoint, names=None):
    if path.suffix.lower() == ".zip":
        return _read_zip(path, checkpoint)
    if path.suffix.lower() in _EXTENSIONS:
        return _read_loose(path, checkpoint, names)
    raise _SourceIssue("review", "Choose a mod ZIP or one of its .utoc, .ucas or .pak files.")


def _answer(path, verdict=None, *, status="unreadable", reason="", token=None):
    return {
        "ok": True, "name": path.name, "suggested_name": path.stem + "-repaired.zip",
        "status": verdict.status if verdict else status, "reason": verdict.reason if verdict else reason,
        "materials": verdict.materials if verdict else 0, "fixed": verdict.fixed if verdict else 0,
        "problems": verdict.problems if verdict else 0, "token": token,
    }


def _scan(path, module, checkpoint, *, names=None, cached=None):
    try:
        with _read_source(path, checkpoint, names) as bundle:
            verdict = cached.get(bundle.pair_digest) if cached is not None else None
            if verdict is None:
                checkpoint()
                verdict = file_fixer.scan_pair(bundle.utoc, bundle.ucas)
            checkpoint()
        if cached is not None:
            cached[bundle.pair_digest] = verdict
            cached.move_to_end(bundle.pair_digest)
        token = None
        if verdict.status == "repairable":
            token = secrets.token_urlsafe(18)
            _confirmed[token] = _Confirmation(path, bundle.fingerprint, module, verdict)
            while len(_confirmed) > _CONFIRMATION_LIMIT:
                _confirmed.popitem(last=False)
        return _answer(path, verdict, token=token)
    except _SourceIssue as error:
        return _answer(path, status=error.status, reason=str(error))
    except _BAD_ARCHIVE:
        return _answer(path, reason="The mod archive could not be read.")
    except (OSError, RuntimeError):
        return _answer(path, reason="The mod or file checker could not be read.")


def scan_source(source, *, checkpoint=jobs.checkpoint):
    """Check a chosen loose container or mod ZIP and confirm a repair candidate."""
    path = Path(os.path.abspath(source))
    with jobs.cancellable_lock(_WORK_LOCK):
        checkpoint()
        try:
            module = file_fixer.module_digest()
        except file_fixer.Unavailable:
            return _answer(path, reason="File repair is unavailable.")
        return _scan(path, module, checkpoint)


def _installed_sources(folder, checkpoint):
    for parent, dirs, files in os.walk(folder, followlinks=False):
        checkpoint()
        folder = Path(parent)
        dirs[:] = sorted(
            (name for name in dirs if not name.startswith(".") and not name.lower().endswith(".disabled")
             and not _is_link(folder / name)), key=str.casefold,
        )
        groups = {}
        for name in sorted(files, key=str.casefold):
            path = folder / name
            if path.suffix.lower() in _EXTENSIONS and not name.startswith("."):
                groups.setdefault(path.stem.casefold(), []).append(name)
        for group in groups.values():
            try:
                names = _pair_names(group)
            except _SourceIssue:
                continue
            if not any(_is_link(folder / name) for name in names if name):
                yield folder / names[0], names


def _is_link(path):
    try:
        meta = path.lstat()
        return stat.S_ISLNK(meta.st_mode) or _reparse(meta)
    except OSError:
        return True


def _cache_path():
    return Path(config._CACHE) / "file-repair-verdicts.json"


def _load_cache(module):
    cached = OrderedDict()
    try:
        with _cache_path().open("rb") as stream:
            data = json.loads(stream.read(_BLOCK))
        if data["version"] != _CACHE_VERSION or data["module"] != module:
            return cached
        for key, value in list(data["verdicts"].items())[-_CACHE_LIMIT:]:
            verdict = file_fixer.ScanResult(**value)
            if (verdict.status in {"repairable", "clean", "review", "unreadable"}
                    and isinstance(verdict.reason, str) and isinstance(verdict.input_digest, str)
                    and all(type(count) is int and count >= 0
                            for count in (verdict.materials, verdict.fixed, verdict.problems))
                    and (verdict.status != "repairable" or verdict.fixed > 0)):
                cached[key] = verdict
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        pass
    return cached


def scan_installed(mods_folder, *, checkpoint=jobs.checkpoint):
    """Check complete loose pairs in the configured folder, one at a time."""
    repairs = []
    result = {"ok": True, "checked": 0, "repairable": 0, "repairs": repairs}
    if not mods_folder:
        return result
    root = Path(os.path.abspath(mods_folder))
    if not root.is_dir():
        return result
    checkpoint()
    try:
        module = file_fixer.module_digest()
    except file_fixer.Unavailable:
        return result
    cached = _load_cache(module)
    for path, names in _installed_sources(root, checkpoint):
        with jobs.cancellable_lock(_WORK_LOCK):
            checkpoint()
            scan = _scan(path, module, checkpoint, names=names, cached=cached)
        result["checked"] += 1
        if scan["status"] == "repairable":
            repairs.append(scan)
        while len(cached) > _CACHE_LIMIT:
            cached.popitem(last=False)
    result["repairable"] = len(repairs)
    if cached:
        try:
            atomic_json(_cache_path(), {
                "version": _CACHE_VERSION, "module": module,
                "verdicts": {key: asdict(verdict) for key, verdict in cached.items()},
            })
        except OSError:
            pass
    return result


def _native_readback(original, repaired, checkpoint):
    reader = container_retoc()
    if not hostos.installed_tool(reader):
        return
    env = config.retoc_env()
    with tempfile.TemporaryDirectory(prefix="atelier-repair-readback-") as scratch:
        toc = Path(scratch) / "contents.utoc"

        def readable(pair):
            checkpoint()
            with toc.open("wb") as stream:
                _write_bytes(stream, pair[0], checkpoint)
            with toc.with_suffix(".ucas").open("wb") as stream:
                _write_bytes(stream, pair[1], checkpoint)
            try:
                result = hostos.run_exe([reader, "info", str(toc)], stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL, timeout=30, env=env)
            except (OSError, RuntimeError, subprocess.SubprocessError):
                return False
            return result.returncode == 0

        if readable(original) and not readable(repaired):
            raise _SourceIssue("unreadable", "The repaired mod could not be verified by the container reader.")


def _publish(staged, destination):
    if os.name == "nt":
        os.rename(staged, destination)  # Windows rename cannot replace an existing file.
    else:
        os.link(staged, destination)  # Publish the complete file without replacing another.


def save_repaired(token, destination, *, checkpoint=jobs.checkpoint):
    """Recheck a confirmed snapshot, verify its repaired form and publish a new ZIP."""
    path = Path(os.path.abspath(destination))
    if path.suffix.lower() != ".zip" or not _component_is_safe(path.name):
        return {"ok": False, "error": "Choose a new .zip file for the repaired mod."}
    if os.path.lexists(path):
        return {"ok": False, "error": "A file already exists at that destination."}
    staged = None
    try:
        with jobs.cancellable_lock(_WORK_LOCK):
            checkpoint()
            confirmation = _confirmed.get(token) if isinstance(token, str) else None
            if confirmation is None or file_fixer.module_digest() != confirmation.module:
                return {"ok": False, "error": "Check the mod again before saving a repaired copy."}
            with _read_source(confirmation.source, checkpoint) as bundle:
                if bundle.fingerprint != confirmation.fingerprint:
                    raise _SourceIssue("unreadable", _STALE)
                scan = file_fixer.scan_pair(bundle.utoc, bundle.ucas)
                if scan != confirmation.scan or scan.status != "repairable":
                    raise _SourceIssue("unreadable", _STALE)
                checkpoint()
                repaired = file_fixer.repair_pair(bundle.utoc, bundle.ucas, scan)
                checkpoint()
                toc_size, data_size = map(len, repaired)
                _check_pair_size(toc_size, data_size)
                unchanged_bytes = bundle.expanded_bytes - len(bundle.utoc) - len(bundle.ucas)
                if unchanged_bytes + toc_size + data_size > _MAX_ARCHIVE_BYTES:
                    raise _SourceIssue("review", "The repaired mod exceeds the file repair limit.")
                verified = file_fixer.scan_pair(*repaired)
                if verified.status != "clean" or verified.materials != scan.materials:
                    raise _SourceIssue("unreadable", "The repaired mod did not pass verification.")
                _native_readback((bundle.utoc, bundle.ucas), repaired, checkpoint)
                with tempfile.NamedTemporaryFile(prefix=".atelier-repair-", suffix=".tmp",
                                                 dir=path.parent, delete=False) as output:
                    staged = Path(output.name)
                    bundle.write_zip(output, *repaired)
                    output.flush()
                    os.fsync(output.fileno())
            checkpoint()
            jobs.begin_publication("Saving repaired copy…")
            _publish(staged, path)
        return {"ok": True, "status": "repaired", "name": path.name,
                "materials": scan.materials, "fixed": scan.fixed, "problems": scan.problems}
    except _SourceIssue as error:
        return {"ok": False, "error": str(error)}
    except file_fixer.Unavailable:
        return {"ok": False, "error": "File repair is unavailable."}
    except (file_fixer.RepairError, *_BAD_ARCHIVE):
        return {"ok": False, "error": "The source could not be read or the repair could not be verified."}
    except FileExistsError:
        return {"ok": False, "error": "A file already exists at that destination."}
    except (OSError, RuntimeError):
        return {"ok": False, "error": "The repaired copy could not be saved to that destination."}
    finally:
        if staged is not None:
            try:
                staged.unlink(missing_ok=True)
            except OSError:
                pass  # An external file lock can delay the cleanup of a staging file.
