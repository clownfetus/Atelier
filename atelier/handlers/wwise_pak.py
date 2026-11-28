"""Pure-Python UE5 Pak (v8–v11) loose-file extractor and v11 Pak writer for Wwise audio mods.

Marvel Rivals stores Wwise SoundBanks (.bnk), streamed media (.wem), SoundbanksInfo metadata,
and localization resources (.locres) inside legacy .pak archives (alongside IoStore containers).
This module:
  1. Reads & extracts entries from encrypted/unencrypted UE5 .pak archives (uncompressed, zlib,
     and Oodle via io_lib) reusing Atelier's verified word-swapped AES logic in legacy_pak.py.
  2. Writes clean, uncompressed UE5 v11 .pak archives for modified .bnk / .wem files so audio
     mods package directly from Atelier without external repak binaries.
"""
import hashlib
import os
from pathlib import Path
import struct
import zlib

import io_lib
from atelier import legacy_pak

_MAGIC = 0x5A6F12E1
_PAK_VERSION_11 = 11
_COMPRESSION_NAMES_COUNT = 5


def _fnv1a_64_path_hash(path_str: str, seed: int) -> int:
    """UE5 FNV1a-64 lowercase UTF-16LE path hash used in PathHashIndex."""
    h = (0xCBF29CE484222325 ^ (seed & 0xFFFFFFFFFFFFFFFF)) & 0xFFFFFFFFFFFFFFFF
    raw = path_str.lower().encode("utf-16-le")
    for b in raw:
        h ^= b
        h = (h * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return h


def _pack_fstring(text: str) -> bytes:
    if not text:
        return struct.pack("<i", 0)
    try:
        raw = text.encode("ascii") + b"\x00"
        return struct.pack("<i", len(raw)) + raw
    except UnicodeEncodeError:
        raw = text.encode("utf-16-le") + b"\x00\x00"
        return struct.pack("<i", -(len(raw) // 2)) + raw


def _read_u32(buf: bytes, off: int) -> tuple[int, int]:
    return struct.unpack_from("<I", buf, off)[0], off + 4


def _read_u64(buf: bytes, off: int) -> tuple[int, int]:
    return struct.unpack_from("<Q", buf, off)[0], off + 8


def _decode_encoded_entry(encoded: bytes, offset: int) -> dict:
    """Decode one UE5 bit-packed FPakEntry from ``encoded_pak_entries``."""
    flags, pos = _read_u32(encoded, offset)
    comp_method = (flags >> 23) & 0x3F
    is_encrypted = bool((flags >> 22) & 1)
    comp_blocks_count = (flags >> 6) & 0xFFFF
    comp_block_size = (flags & 0x3F) << 11

    if flags & (1 << 31):
        data_offset, pos = _read_u32(encoded, pos)
    else:
        data_offset, pos = _read_u64(encoded, pos)

    if flags & (1 << 30):
        uncomp_size, pos = _read_u32(encoded, pos)
    else:
        uncomp_size, pos = _read_u64(encoded, pos)

    if comp_method != 0:
        if flags & (1 << 29):
            comp_size, pos = _read_u32(encoded, pos)
        else:
            comp_size, pos = _read_u64(encoded, pos)
    else:
        comp_size = uncomp_size

    if comp_blocks_count == 1 and not is_encrypted:
        comp_block_size = uncomp_size

    blocks = []
    if comp_method != 0:
        if comp_blocks_count == 1:
            blocks.append((0, comp_size))
        else:
            cur = 0
            for _ in range(comp_blocks_count):
                blk_sz, pos = _read_u32(encoded, pos)
                blocks.append((cur, cur + blk_sz))
                cur += blk_sz

    return {
        "offset": data_offset,
        "uncomp_size": uncomp_size,
        "comp_size": comp_size,
        "comp_method": comp_method,
        "encrypted": is_encrypted,
        "comp_block_size": comp_block_size,
        "blocks": blocks,
    }


def _read_unencoded_entry(buf: bytes, off: int) -> dict:
    """Read a full non-encoded FPakEntry record (used for entries with negative directory offsets)."""
    data_offset, comp_size, uncomp_size, comp_method = struct.unpack_from("<QQQI", buf, off)
    pos = off + 28 + 20  # skip 20-byte SHA1 hash
    blocks = []
    if comp_method != 0:
        (n_blocks,) = struct.unpack_from("<I", buf, pos)
        pos += 4
        for _ in range(n_blocks):
            b_start, b_end = struct.unpack_from("<QQ", buf, pos)
            blocks.append((b_start, b_end))
            pos += 16
    flags_byte = buf[pos]
    (comp_block_size,) = struct.unpack_from("<I", buf, pos + 1)
    return {
        "offset": data_offset,
        "uncomp_size": uncomp_size,
        "comp_size": comp_size,
        "comp_method": comp_method,
        "encrypted": bool(flags_byte & 1),
        "comp_block_size": comp_block_size,
        "blocks": blocks,
    }


def _entry_header_size(version: int, comp_method: int, blocks_count: int) -> int:
    # Inline FPakEntry stored right before each file payload in v8–v11:
    # Offset(8=0) + Size(8) + UncompSize(8) + Method(4) + Hash(20) + [Blocks] + Flags(1) + CompBlockSize(4)
    size = 8 + 8 + 8 + 4 + 20 + 1 + 4
    if comp_method != 0:
        size += 4 + blocks_count * 16
    return size


class PakReader:
    """Read file listings and extract arbitrary entries from a UE5 v8–v11 ``.pak`` archive."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        self.size = os.path.getsize(self.path)
        with open(self.path, "rb") as stream:
            stream.seek(max(0, self.size - legacy_pak._FOOTER - 64))
            tail = stream.read()
        at = tail.rfind(struct.pack("<I", _MAGIC))
        if at < 17:
            raise legacy_pak.PakError("Not a readable UE5 .pak file.")
        self.encrypted_index = tail[at - 1] != 0
        self.version, idx_off, idx_size = struct.unpack_from("<iqq", tail, at + 4)
        if not 8 <= self.version <= 11:
            raise legacy_pak.PakError(f"Unsupported pak version {self.version}.")

        # Read compression method names from footer (5 x 32-byte ASCII strings after the 20-byte index hash).
        comp_table_off = at + 4 + 4 + 8 + 8 + 20
        self.compression_methods = ["None"]
        for i in range(_COMPRESSION_NAMES_COUNT):
            raw = tail[comp_table_off + i * 32:comp_table_off + (i + 1) * 32]
            name = raw.split(b"\x00", 1)[0].decode("ascii", "ignore").strip()
            self.compression_methods.append(name or "None")

        self.cipher = "plain"
        data = self._read_index_block(idx_off, idx_size)
        if self.encrypted_index and not legacy_pak._mount_reads(data):
            self.cipher = "swapped"
            data = self._read_index_block(idx_off, idx_size)
            if not legacy_pak._mount_reads(data):
                raise legacy_pak.PakError("Pak index could not be decrypted with the current AES key.")

        reader = legacy_pak._Reader(data)
        self.mount = reader.fstring()
        self.count = reader.i32()
        reader.take(8)  # path_hash_seed
        if reader.u32():
            reader.take(8 + 8 + 20)  # PathHashIndex offset, size, sha1
        dir_off = dir_size = 0
        if reader.u32():
            dir_off, dir_size = struct.unpack("<qq", reader.take(16))
            reader.take(20)  # FullDirectoryIndex sha1

        enc_size = reader.i32()
        self._encoded = reader.take(enc_size) if enc_size > 0 else b""
        unenc_count = reader.i32()
        self._unencoded_blob = data[reader.at:] if unenc_count > 0 else b""

        self.entries: dict[str, int] = {}
        if dir_size > 0:
            dir_reader = legacy_pak._Reader(self._read_index_block(dir_off, dir_size))
            for _ in range(dir_reader.i32()):
                folder = dir_reader.fstring()
                for _ in range(dir_reader.i32()):
                    fname = dir_reader.fstring()
                    entry_loc = dir_reader.i32()
                    rel = (folder + fname).lstrip("/")
                    self.entries[rel] = entry_loc

    def _read_index_block(self, offset: int, size: int) -> bytes:
        with open(self.path, "rb") as stream:
            stream.seek(offset)
            data = stream.read(legacy_pak._align(size) if self.encrypted_index else size)
        if self.encrypted_index:
            data = legacy_pak._CIPHERS[self.cipher](data)
        return data[:size]

    @property
    def names(self) -> list[str]:
        return list(self.entries.keys())

    def read_file(self, name: str) -> bytes:
        clean = name.lstrip("/")
        if clean not in self.entries:
            low = clean.casefold()
            match = next((k for k in self.entries if k.casefold() == low), None)
            if match is None:
                raise KeyError(f"{name} not found in {os.path.basename(self.path)}")
            clean = match
        loc = self.entries[clean]
        if loc >= 0:
            meta = _decode_encoded_entry(self._encoded, loc)
        else:
            raise legacy_pak.PakError("Unencoded pak directory entries are not supported yet.")

        hdr_size = _entry_header_size(self.version, meta["comp_method"], len(meta["blocks"]))
        method_name = (
            self.compression_methods[meta["comp_method"]]
            if 0 <= meta["comp_method"] < len(self.compression_methods)
            else "None"
        ).lower()

        with open(self.path, "rb") as stream:
            if meta["comp_method"] == 0 or method_name == "none":
                stream.seek(meta["offset"] + hdr_size)
                raw_len = legacy_pak._align(meta["comp_size"]) if meta["encrypted"] else meta["comp_size"]
                raw = stream.read(raw_len)
                if meta["encrypted"]:
                    raw = legacy_pak._CIPHERS[self.cipher](raw)
                return raw[:meta["uncomp_size"]]

            out = bytearray()
            remaining = meta["uncomp_size"]
            block_uncomp = meta["comp_block_size"] or meta["uncomp_size"]
            for b_start, b_end in meta["blocks"]:
                b_len = b_end - b_start
                # In UE5 encoded entries, block offsets are relative to the entry's file header end.
                stream.seek(meta["offset"] + hdr_size + b_start)
                read_len = legacy_pak._align(b_len) if meta["encrypted"] else b_len
                chunk = stream.read(read_len)
                if meta["encrypted"]:
                    chunk = legacy_pak._CIPHERS[self.cipher](chunk)
                chunk = chunk[:b_len]
                want = min(block_uncomp, remaining)
                if method_name == "zlib":
                    out.extend(zlib.decompress(chunk))
                elif method_name == "oodle":
                    out.extend(io_lib.oodle_decompress(chunk, want))
                else:
                    raise legacy_pak.PakError(f"Unsupported pak compression method: {method_name}")
                remaining -= want
            return bytes(out[:meta["uncomp_size"]])


def write_loose_pak(out_pak: str | Path, files: dict[str, bytes], *, mount: str = "../../../") -> str:
    """Write an uncompressed, unencrypted UE5 v11 ``.pak`` containing ``{rel_path: bytes}``.

    Produces valid PathHashIndex, FullDirectoryIndex, encoded FPakEntries, and SHA-1 hashes
    readable by Unreal Engine 5, Atelier's ``legacy_pak.Pak`` and ``PakReader``.
    """
    if not files:
        raise ValueError("Cannot write an empty pak archive.")

    out_path = Path(out_pak)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")

    # Sort deterministically and normalise paths.
    ordered = sorted((k.replace("\\", "/").lstrip("/"), bytes(v)) for k, v in files.items())
    path_hash_seed = 0x5A17000012345678

    encoded_entries = bytearray()
    dir_map: dict[str, list[tuple[str, int]]] = {}
    path_hashes: list[tuple[int, int]] = []

    with open(tmp_path, "wb") as stream:
        for rel, payload in ordered:
            entry_offset = stream.tell()
            size = len(payload)
            sha1 = hashlib.sha1(payload).digest()

            # Write inline FPakEntry header (Offset is 0 inline, Size, UncompSize, Method=0, SHA1, Flags=0, BlockSize=0)
            inline_hdr = struct.pack("<QQQI", 0, size, size, 0) + sha1 + struct.pack("<BI", 0, 0)
            stream.write(inline_hdr)
            stream.write(payload)

            # Encode bit-packed directory entry in encoded_pak_entries
            enc_pos = len(encoded_entries)
            offset_32 = entry_offset <= 0xFFFFFFFF
            size_32 = size <= 0xFFFFFFFF
            flags = (1 << 31 if offset_32 else 0) | (1 << 30 if size_32 else 0)
            encoded_entries.extend(struct.pack("<I", flags))
            encoded_entries.extend(struct.pack("<I" if offset_32 else "<Q", entry_offset))
            encoded_entries.extend(struct.pack("<I" if size_32 else "<Q", size))

            if "/" in rel:
                folder_part, fname = rel.rsplit("/", 1)
                folder_key = folder_part + "/"
            else:
                folder_key, fname = "/", rel
            dir_map.setdefault(folder_key, []).append((fname, enc_pos))
            path_hashes.append((_fnv1a_64_path_hash(rel, path_hash_seed), enc_pos))

        # Write PathHashIndex
        phi_offset = stream.tell()
        phi_buf = bytearray()
        phi_buf.extend(struct.pack("<i", len(path_hashes)))
        for ph, loc in path_hashes:
            phi_buf.extend(struct.pack("<Qi", ph, loc))
        stream.write(phi_buf)
        phi_hash = hashlib.sha1(phi_buf).digest()

        # Write FullDirectoryIndex
        fdi_offset = stream.tell()
        fdi_buf = bytearray()
        fdi_buf.extend(struct.pack("<i", len(dir_map)))
        for folder_key, items in sorted(dir_map.items()):
            fdi_buf.extend(_pack_fstring(folder_key))
            fdi_buf.extend(struct.pack("<i", len(items)))
            for fname, loc in items:
                fdi_buf.extend(_pack_fstring(fname))
                fdi_buf.extend(struct.pack("<i", loc))
        stream.write(fdi_buf)
        fdi_hash = hashlib.sha1(fdi_buf).digest()

        # Write Primary Index
        primary_offset = stream.tell()
        primary = bytearray()
        primary.extend(_pack_fstring(mount))
        primary.extend(struct.pack("<i", len(ordered)))
        primary.extend(struct.pack("<Q", path_hash_seed))
        primary.extend(struct.pack("<Iqq", 1, phi_offset, len(phi_buf)) + phi_hash)
        primary.extend(struct.pack("<Iqq", 1, fdi_offset, len(fdi_buf)) + fdi_hash)
        primary.extend(struct.pack("<i", len(encoded_entries)))
        primary.extend(encoded_entries)
        primary.extend(struct.pack("<i", 0))  # 0 unencoded entries
        stream.write(primary)
        primary_hash = hashlib.sha1(primary).digest()

        # Write UE5 v11 Footer (16-byte encryption GUID + 1-byte encrypted_index + magic + version +
        # index_offset + index_size + 20-byte index_hash + 5x32-byte compression method names)
        footer = (
            b"\x00" * 16
            + b"\x00"
            + struct.pack("<Iiqq", _MAGIC, _PAK_VERSION_11, primary_offset, len(primary))
            + primary_hash
            + (b"\x00" * (32 * _COMPRESSION_NAMES_COUNT))
        )
        stream.write(footer)

    os.replace(tmp_path, out_path)
    return str(out_path).replace("\\", "/")
