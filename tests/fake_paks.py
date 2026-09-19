"""Synthetic UE5 IoStore containers, just real enough for io_lib to parse (or fail) on.

Lets the index / thumbnail / error-message paths be exercised with no game installed.
"""
import os, struct

MAGIC = b"-==--==--==--==-"


def _header(dir_index_size, version=3, flags=0, enc_guid=b"\x00" * 16):
    """144-byte TOC header with every count zeroed, so off_dirindex lands exactly at 144."""
    h = bytearray(144)
    h[0:16] = MAGIC
    h[16] = version
    b = 20
    struct.pack_into("<I", h, b + 0,  144)              # hdr_size
    struct.pack_into("<I", h, b + 4,  0)                # entry_count
    struct.pack_into("<I", h, b + 8,  0)                # cblk_count
    struct.pack_into("<I", h, b + 12, 12)               # cblk_entry_size
    struct.pack_into("<I", h, b + 16, 0)                # cm_name_count
    struct.pack_into("<I", h, b + 20, 32)               # cm_name_len
    struct.pack_into("<I", h, b + 24, 65536)            # cblk_size
    struct.pack_into("<I", h, b + 28, dir_index_size)   # dir_index_size
    struct.pack_into("<I", h, b + 32, 1)                # partition_count
    struct.pack_into("<Q", h, b + 36, 1234)             # container_id
    h[b + 44:b + 60] = enc_guid                         # enc_guid (which key this wants)
    h[b + 60] = flags                                   # bit 2 = encrypted, bit 4 = signed
    struct.pack_into("<I", h, b + 64, 0)                # phash_seed_count
    struct.pack_into("<Q", h, b + 68, 0xFFFFFFFFFFFFFFFF)
    struct.pack_into("<I", h, b + 76, 0)                # chunks_wo_phash
    return bytes(h)


def clean_blob():
    """mount="" , 0 dirs, 0 files, 0 strings -> parse_dir_index returns []."""
    return struct.pack("<iIII", 0, 0, 0, 0)


def garbage_blob_overflow():
    """A huge positive FString length -> the offset runs past the buffer.

    Reproduces `unpack_from requires a buffer of at least N bytes`, the shape seen in the field
    when a container is decrypted with the wrong AES key.
    """
    return struct.pack("<i", 0x7FFFFFF0) + b"\x00" * 12


def garbage_blob_utf16():
    """A negative FString length over bytes that are not valid UTF-16.

    Reproduces `'utf-16-le' codec can't decode bytes ... illegal UTF-16 surrogate`.
    """
    return struct.pack("<i", -3) + b"\x00\xd8\x00\x00\x00\x00"


def write(path, blob, extra_flags=0, enc_guid=b"\x00" * 16):
    """A container holding `blob` as its directory index. An empty blob means no directory index
    at all (flags keep bit 8 clear) — the shape global.utoc really has on every install."""
    flags = (8 if blob else 0) | extra_flags        # bit 8 = Indexed
    data = _header(len(blob), flags=flags, enc_guid=enc_guid) + blob
    with open(path, "wb") as f:
        f.write(data)
    open(path[:-5] + ".ucas", "wb").close()   # every .utoc has a sibling .ucas
    return path


# ── real AES-encrypted containers ───────────────────────────────────────────────────────────
# The wrong-key failure is the single largest cluster in the bug corpus, so reproducing it needs
# a container that is ACTUALLY encrypted: AES-ECB with the wrong key does not fail, it returns
# garbage, and only the parse downstream notices. Everything above this line is plaintext.
INV = 0xFFFFFFFF


def dir_index_blob(mount="../../../Marvel/Content/Marvel", folder="Characters",
                   name="T_Test.uasset"):
    """A real directory index: mount/<folder>/<name>, one directory, one file."""
    def fstr(x):
        return struct.pack("<i", len(x) + 1) + x.encode("latin1") + b"\x00"
    out  = fstr(mount)
    out += struct.pack("<I", 2)                                     # 2 dirs
    out += struct.pack("<IIII", INV, 1, INV, INV)                   # root -> child 1
    out += struct.pack("<IIII", 0, INV, INV, 0)                     # <folder>, first file 0
    out += struct.pack("<I", 1)                                     # 1 file
    out += struct.pack("<III", 1, INV, 0)                           # name=strings[1], no next
    out += struct.pack("<I", 2) + fstr(folder) + fstr(name)         # 2 strings
    return out


def aes_encrypt(blob, key_hex):
    """AES-256-ECB, zero-padded to a block boundary — what parse_dir_index expects to undo."""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    pad = (-len(blob)) % 16
    enc = Cipher(algorithms.AES(bytes.fromhex(key_hex)), modes.ECB()).encryptor()
    return enc.update(blob + b"\x00" * pad) + enc.finalize()


def write_encrypted(path, key_hex, blob=None, enc_guid=b"\x11" * 16, **kw):
    """An encrypted container readable ONLY with key_hex. Any other key yields garbage."""
    return write(path, aes_encrypt(blob if blob is not None else dir_index_blob(**kw), key_hex),
                 extra_flags=2, enc_guid=enc_guid)


def make_dir(tmp, clean=1, overflow=0, utf16=0):
    """Populate tmp with N clean + N broken containers. Returns the directory."""
    os.makedirs(tmp, exist_ok=True)
    for i in range(clean):
        write(os.path.join(tmp, f"pakchunkClean{i}-Windows.utoc"), clean_blob())
    for i in range(overflow):
        write(os.path.join(tmp, f"pakchunkOverflow{i}-Windows.utoc"), garbage_blob_overflow())
    for i in range(utf16):
        write(os.path.join(tmp, f"pakchunkUtf16{i}-Windows.utoc"), garbage_blob_utf16())
    return tmp


# ── test isolation ──────────────────────────────────────────────────────────────────────────────
def settle_background_index():
    """Wait out the warmup thread `import atelier.web.routes` starts, before sandboxing the index.

    routes.py calls pak_thumb.start_warmup() AT IMPORT when the config has paks and a key, and that
    thread calls ensure_index() against the REAL install. Stubbing start_warmup inside the test is
    too late — the import already launched it. If it then finishes after a sandbox has set
    IDX._INDEX = None, the module global is quietly repopulated with the real 546k-entry index and
    the next assertion sees a full tree where the test built an empty one.

    It only bites once the real index is cached (a cold build takes minutes and always loses the
    race, a warm one wins it sometimes), which is why this reads as flakiness on a developer machine
    and never in a fresh checkout. Joining the thread makes the order deterministic either way.
    """
    import threading
    for th in threading.enumerate():
        if th.name == "pak_thumb_warmup":
            th.join(timeout=180)
