"""Real DXIL editing via the DXC COM API (dxcompiler.dll + dxil.dll).

Compiled shaders can't be byte-patched (DXIL bitstream-encodes constants), but DXC round-trips
cleanly: DXBC container -> LLVM IR text (editable) -> DXBC container. IDxcAssembler assembles the
edited IR and IDxcValidator (dxil.dll) signs it, producing a valid shader the game will accept.

  disassemble(dxbc)      -> LLVM IR text (bytes)      [edit this]
  assemble_and_sign(ir)  -> signed DXBC container     [ready to splice back]
"""
import ctypes, uuid, os
from ctypes import (c_void_p, c_int32, c_uint32, c_uint64, POINTER, byref, cast,
                    Structure, c_ubyte, c_ushort, c_ulong)

_TOOLS = os.path.join(os.environ.get("MR_TOOLS", ""), "shaders")


class _GUID(Structure):
    _fields_ = [("D1", c_ulong), ("D2", c_ushort), ("D3", c_ushort), ("D4", c_ubyte * 8)]


def _guid(s):
    u = uuid.UUID(s)
    g = _GUID(); g.D1 = u.time_low; g.D2 = u.time_mid; g.D3 = u.time_hi_version
    for i, b in enumerate(u.bytes[8:]):
        g.D4[i] = b
    return g


def _call(obj, idx, restype, argtypes, *args):
    vt = cast(obj, POINTER(c_void_p))[0]
    fp = cast(vt, POINTER(c_void_p))[idx]
    return ctypes.WINFUNCTYPE(restype, c_void_p, *argtypes)(fp)(obj, *args)


# CLSIDs / IIDs from dxcapi.h
_CLSID_UTILS = "6245D6AF-66E0-48FD-80B4-4D271796748C"
_IID_UTILS = "4605C4CB-2019-492A-ADA4-65F20BB7D67F"
_CLSID_COMPILER = "73E22D93-E6CE-47F3-B5BF-F0664F39C1B0"
_IID_COMPILER = "8C210BF3-011F-4422-8D70-6F9ACB8DB617"
_CLSID_ASSEMBLER = "D728DB68-F903-4F80-94CD-DCCF76EC7151"
_IID_ASSEMBLER = "091F7A26-1C1F-4948-904B-E6E3A8A771D5"
_CLSID_VALIDATOR = "8CA3E215-F728-4CF3-8CDF-88D0F92B6E7A"
_IID_VALIDATOR = "A6E82BD2-1FD7-4826-9811-2857E797F49A"

_dxc = None
_dxil = None


def _load():
    global _dxc, _dxil
    if _dxc is None:
        try:
            os.add_dll_directory(_TOOLS)                       # let dxcompiler find dxil.dll
        except Exception:
            pass
        try:
            ctypes.windll.ole32.CoInitializeEx(None, 0)
        except Exception:
            pass
        _dxc = ctypes.WinDLL(os.path.join(_TOOLS, "dxcompiler.dll"))
        _dxc.DxcCreateInstance.restype = c_int32
        _dxc.DxcCreateInstance.argtypes = [POINTER(_GUID), POINTER(_GUID), POINTER(c_void_p)]
        try:
            _dxil = ctypes.WinDLL(os.path.join(_TOOLS, "dxil.dll"))
            _dxil.DxcCreateInstance.restype = c_int32
            _dxil.DxcCreateInstance.argtypes = [POINTER(_GUID), POINTER(_GUID), POINTER(c_void_p)]
        except Exception:
            _dxil = None


def _create(dll, clsid, iid):
    p = c_void_p()
    hr = dll.DxcCreateInstance(byref(_guid(clsid)), byref(_guid(iid)), byref(p))
    if hr != 0 or not p.value:
        raise RuntimeError(f"DxcCreateInstance({clsid}) failed hr={hr & 0xffffffff:#x}")
    return p


def _blob(utils, data):
    """IDxcUtils::CreateBlobFromPinned (idx 4) — a blob backed by a pinned mutable buffer."""
    buf = (c_ubyte * len(data)).from_buffer(bytearray(data))
    out = c_void_p()
    hr = _call(utils, 4, c_int32, [c_void_p, c_uint32, c_uint32, POINTER(c_void_p)],
               cast(buf, c_void_p), len(data), 0, byref(out))
    if hr != 0 or not out.value:
        raise RuntimeError(f"CreateBlobFromPinned hr={hr & 0xffffffff:#x}")
    return out, buf


def _bytes(blob):
    p = _call(blob, 3, c_void_p, [])       # GetBufferPointer
    n = _call(blob, 4, c_uint64, [])       # GetBufferSize
    return ctypes.string_at(p, n)


def disassemble(dxbc):
    """DXBC container bytes -> editable LLVM IR text (bytes)."""
    _load()
    utils = _create(_dxc, _CLSID_UTILS, _IID_UTILS)
    comp = _create(_dxc, _CLSID_COMPILER, _IID_COMPILER)
    blob, _keep = _blob(utils, dxbc)
    dis = c_void_p()
    hr = _call(comp, 5, c_int32, [c_void_p, POINTER(c_void_p)], blob, byref(dis))  # Disassemble
    if hr != 0 or not dis.value:
        raise RuntimeError(f"Disassemble hr={hr & 0xffffffff:#x}")
    return _bytes(dis)


def _try_sign(container):
    """Best-effort: sign the container in place via the DXIL validator. Returns (bytes, signed_bool).
    This dxil.dll build may not expose the validator (REGDB_E_CLASSNOTREG) — then we return unsigned
    and the caller flags it for the user to test in-game."""
    try:
        utils = _create(_dxc, _CLSID_UTILS, _IID_UTILS)
        val = _create(_dxil, _CLSID_VALIDATOR, _IID_VALIDATOR)
        sblob, sbuf = _blob(utils, bytes(container))
        vres = c_void_p()
        _call(val, 3, c_int32, [c_void_p, c_uint32, POINTER(c_void_p)], sblob, 1, byref(vres))
        signed = bytes(bytearray(sbuf))
        return signed, any(signed[4:20])
    except Exception:
        return bytes(container), False


def assemble(ir):
    """Edited LLVM IR text -> assembled DXBC container. Returns (container_bytes, signed_bool)."""
    _load()
    utils = _create(_dxc, _CLSID_UTILS, _IID_UTILS)
    asm = _create(_dxc, _CLSID_ASSEMBLER, _IID_ASSEMBLER)
    src, _k1 = _blob(utils, ir)
    res = c_void_p()
    hr = _call(asm, 3, c_int32, [c_void_p, POINTER(c_void_p)], src, byref(res))  # AssembleToContainer
    if hr != 0 or not res.value:
        raise RuntimeError(f"AssembleToContainer hr={hr & 0xffffffff:#x}")
    st = c_int32()
    _call(res, 3, c_int32, [POINTER(c_int32)], byref(st))                        # GetStatus
    if st.value != 0:
        errb = c_void_p()
        _call(res, 5, c_int32, [POINTER(c_void_p)], byref(errb))                 # GetErrorBuffer
        msg = _bytes(errb).decode("utf-8", "replace") if errb.value else ""
        raise RuntimeError("assemble failed: " + (msg.strip() or f"status {st.value:#x}"))
    outb = c_void_p()
    _call(res, 4, c_int32, [POINTER(c_void_p)], byref(outb))                     # GetResult
    return _try_sign(bytearray(_bytes(outb)))


if __name__ == "__main__":
    # Self-test: round-trip a real shader and confirm the reassembled container is signed.
    import subprocess, struct, sys
    os.environ.setdefault("MR_TOOLS", os.path.dirname(_TOOLS))
    retoc = os.path.join(_TOOLS, "retoc-rivals-cli.exe")
    paks = r"C:/Program Files (x86)/Steam/steamapps/common/MarvelRivals/MarvelGame/Marvel/Content/Paks"
    out = os.path.abspath("_cache/irtest.bin")
    os.makedirs("_cache", exist_ok=True)
    subprocess.run([retoc, "extract-shader", paks + "/pakchunkShaderAsset-Windows.utoc",
                    paks + "/global.utoc", "-l", "ShaderArchive-Global-PCD3D_SM6-PCD3D_SM6",
                    "-s", "20", "-o", out], cwd=_TOOLS, capture_output=True)
    b = open(out, "rb").read()
    pos = b.find(b"DXBC"); size = struct.unpack_from("<I", b, pos + 24)[0]
    dxbc = b[pos:pos + size]
    ir = disassemble(dxbc)
    print("IR bytes:", len(ir))
    cont, signed = assemble(ir)
    print("reassembled:", len(cont), "hash:", cont[4:20].hex(), "signed:", signed)
