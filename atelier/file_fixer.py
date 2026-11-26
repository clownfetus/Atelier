"""Run version 1 of the bundled material repair module on a pair of local buffers."""
import atexit
from dataclasses import dataclass
from functools import lru_cache
import hashlib
from pathlib import Path
import struct
import threading

from atelier import jobs


_WASM = Path(__file__).with_name("vendor") / "file_fixer" / "file_fixer.wasm"
_SHA256 = "e07785e7db844e02bf4f4de9c41145e06191f90504cd5dcf6f5b5148d87322a3"
MAX_INPUT_BYTES = 128 * 1024 * 1024
_MAX_OUTPUT_BYTES = 192 * 1024 * 1024
_MAX_MEMORY_BYTES = 512 * 1024 * 1024
_MAX_FUEL = 12_000_000_000
_RESULT = struct.Struct("<10I")
_RUN_LOCK = threading.Lock()


class Unavailable(RuntimeError):
    """The app's pinned repair dependency cannot be loaded."""


class RepairError(ValueError):
    """The selected input or returned repair data was invalid."""


@dataclass(frozen=True)
class ScanResult:
    status: str
    materials: int
    fixed: int
    problems: int
    reason: str
    input_digest: str


@dataclass(frozen=True)
class _GuestResult:
    status: int
    message: str
    materials: int
    fixed: int
    problems: int
    pair: tuple[bytes, bytes] | None


@lru_cache(maxsize=1)
def _runtime():
    try:
        import wasmtime
        with _WASM.open("rb") as source:
            blob = source.read(2 * 1024 * 1024 + 1)
    except (OSError, ImportError) as exc:
        raise Unavailable("Material repair is unavailable in this installation.") from exc
    if hashlib.sha256(blob).hexdigest() != _SHA256:
        raise Unavailable("The bundled repair file failed its integrity check.")

    try:
        config = wasmtime.Config()
        config.consume_fuel = True
        config.wasm_gc = False
        config.wasm_exceptions = False
        config.wasm_threads = False
        config.wasm_memory64 = False
        config.wasm_multi_memory = False
        engine = wasmtime.Engine(config)
        module = wasmtime.Module(engine, blob)
    except wasmtime.WasmtimeError as exc:
        raise Unavailable("The bundled repair file could not be loaded.") from exc

    exports = {export.name: export.type for export in module.exports}
    if module.imports or not isinstance(exports.get("memory"), wasmtime.MemoryType):
        raise Unavailable("The bundled repair file has an incompatible interface.")
    for name, parameters, results in (("alloc", 1, 1), ("dealloc", 2, 0), ("fix_mod", 6, 1)):
        function = exports.get(name)
        if (not isinstance(function, wasmtime.FuncType)
                or list(map(str, function.params)) != ["i32"] * parameters
                or list(map(str, function.results)) != ["i32"] * results):
            raise Unavailable("The bundled repair file has an incompatible interface.")
    return engine, module


# Release native handles before Python tears down Wasmtime's FFI module.
atexit.register(_runtime.cache_clear)


def module_digest():
    _runtime()
    return _SHA256


def _input_digest(utoc, ucas):
    if not utoc or not ucas:
        raise RepairError("Both the .utoc and .ucas files are required.")
    if len(utoc) + len(ucas) > MAX_INPUT_BYTES:
        raise RepairError("This mod exceeds the material repair size limit.")
    digest = hashlib.sha256()
    digest.update(len(utoc).to_bytes(8, "little"))
    digest.update(utoc)
    digest.update(ucas)
    return digest.hexdigest()


def _bounds(memory, store, pointer, length):
    size = memory.data_len(store)
    if pointer <= 0 or pointer > size or length > size - pointer:
        raise RepairError("The repair tool returned an invalid buffer.")


def _read(memory, store, pointer, length):
    if not length:
        return b""
    _bounds(memory, store, pointer, length)
    return bytes(memory.read(store, pointer, pointer + length))


def _invoke(utoc, ucas, *, assume_old, check_only):
    with jobs.cancellable_lock(_RUN_LOCK):
        engine, module = _runtime()
        import wasmtime

        try:
            with wasmtime.Store(engine) as store:
                store.set_limits(memory_size=_MAX_MEMORY_BYTES, table_elements=4096,
                                 instances=1, tables=1, memories=1)
                # Recompression needs more instructions than decoding a candidate for a check.
                # Keep separate floors so small Oodle-compressed packages can be repaired.
                floor, scale = (100_000_000, 512) if check_only else (1_250_000_000, 2048)
                fuel = min(_MAX_FUEL, max(floor, (len(utoc) + len(ucas)) * scale))
                store.set_fuel(fuel)
                exports = wasmtime.Instance(store, module, []).exports(store)
                memory, alloc = exports["memory"], exports["alloc"]

                def write(blob):
                    pointer = alloc(store, len(blob)) & 0xFFFFFFFF
                    _bounds(memory, store, pointer, len(blob))
                    memory.write(store, blob, pointer)
                    return pointer

                result = exports["fix_mod"](
                    store, write(utoc), len(utoc), write(ucas), len(ucas),
                    int(assume_old), int(check_only),
                ) & 0xFFFFFFFF
                jobs.checkpoint()
                (status, msg_ptr, msg_len, materials, fixed, toc_ptr, toc_len,
                 cas_ptr, cas_len, problems) = _RESULT.unpack(
                     _read(memory, store, result, _RESULT.size))
                if (status not in (0, 1) or fixed > materials or msg_len > 16 * 1024
                        or toc_len + cas_len > _MAX_OUTPUT_BYTES):
                    raise RepairError("The repair tool returned an invalid result.")
                expect_output = not (check_only or status or problems) and fixed > 0
                if bool(toc_len) != expect_output or bool(cas_len) != expect_output:
                    raise RepairError("The repair tool returned an incomplete result.")
                message = _read(memory, store, msg_ptr, msg_len).decode("utf-8", errors="replace")
                pair = None
                if expect_output:
                    _bounds(memory, store, toc_ptr, toc_len)
                    _bounds(memory, store, cas_ptr, cas_len)
                    pair = (_read(memory, store, toc_ptr, toc_len),
                            _read(memory, store, cas_ptr, cas_len))
                # The guest owns its output buffers. Closing the store releases them and both inputs.
                return _GuestResult(status, message, materials, fixed, problems, pair)
        except wasmtime.Trap as exc:
            if exc.trap_code == wasmtime.TrapCode.OUT_OF_FUEL:
                raise RepairError("This mod exceeds the material repair work limit.") from exc
            raise RepairError("Could not read this mod's container data.") from exc
        except wasmtime.WasmtimeError as exc:
            raise RepairError("Could not process this mod within the repair limits.") from exc


def scan_pair(utoc: bytes, ucas: bytes) -> ScanResult:
    """Only confirm a repair when both check-only scans agree."""
    digest = ""
    try:
        digest = _input_digest(utoc, ucas)
        strict = _invoke(utoc, ucas, assume_old=False, check_only=True)
        if strict.status:
            raise RepairError(strict.message or "Could not read this mod.")
        probe = _invoke(utoc, ucas, assume_old=True, check_only=True)
    except RepairError as exc:
        return ScanResult("unreadable", 0, 0, 0, str(exc), digest)

    problems = max(strict.problems, probe.problems)
    if probe.status or problems or (strict.materials, strict.fixed) != (probe.materials, probe.fixed):
        reason = strict.message or probe.message or "Some materials match both layouts."
        return ScanResult("review", strict.materials, strict.fixed, problems, reason, digest)
    if strict.fixed:
        return ScanResult("repairable", strict.materials, strict.fixed, 0, "", digest)
    return ScanResult("clean", strict.materials, 0, 0, "", digest)


def repair_pair(utoc: bytes, ucas: bytes, scan: ScanResult) -> tuple[bytes, bytes]:
    """Repair the exact bytes covered by a confirmed scan."""
    if scan.status != "repairable" or not scan.fixed or scan.input_digest != _input_digest(utoc, ucas):
        raise RepairError("Check this mod again before saving a repaired copy.")
    result = _invoke(utoc, ucas, assume_old=False, check_only=False)
    if result.status or result.problems or result.fixed != scan.fixed or result.pair is None:
        raise RepairError(result.message or "The repair tool did not return a complete mod.")
    return result.pair
