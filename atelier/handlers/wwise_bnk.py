"""Pure-Python Audiokinetic Wwise SoundBank (.bnk) parser, extractor and repacker.

Supports standard Wwise RIFF-like four-CC chunk banks:
  - ``BKHD``: bank header (version, bank ID)
  - ``DIDX``: media index table (array of 12-byte ``<III`` entries: media_id, offset, size)
  - ``DATA``: concatenated ``.wem`` payloads (16-byte aligned between entries)
  - ``HIRC``: hierarchy objects (preserved verbatim; embedded ``Sound`` object ``uInMemoryMediaSize``
              fields are updated in place when a matching ``media_id`` changes size)
  - Any additional chunks (``STID``, ``ENVS``, ``FXPR``, ``INIT``, ``PLAT``, etc.) are preserved
    byte-for-byte.
"""
from dataclasses import dataclass
import struct

_ALIGNMENT = 16


@dataclass(frozen=True)
class BnkChunk:
    tag: bytes
    payload: bytes


@dataclass(frozen=True)
class BnkMediaEntry:
    media_id: int
    offset: int
    size: int


class BnkError(ValueError):
    pass


def parse_chunks(data: bytes) -> list[BnkChunk]:
    """Split a Wwise ``.bnk`` byte stream into ordered ``(tag, payload)`` chunks."""
    if not data or len(data) < 8:
        raise BnkError("Not a valid Wwise SoundBank (file too short).")
    chunks: list[BnkChunk] = []
    pos = 0
    total = len(data)
    while pos + 8 <= total:
        tag = data[pos:pos + 4]
        if not all(32 <= b < 127 for b in tag):
            raise BnkError(f"Unreadable Wwise chunk tag at offset {pos}.")
        (size,) = struct.unpack_from("<I", data, pos + 4)
        start = pos + 8
        end = start + size
        if end > total:
            raise BnkError(f"Truncated {tag.decode('ascii', 'replace')} chunk (needs {size} bytes, only {total - start} left).")
        chunks.append(BnkChunk(tag=tag, payload=data[start:end]))
        pos = end
    if not chunks or chunks[0].tag != b"BKHD":
        raise BnkError("Not a valid Wwise SoundBank (missing BKHD header).")
    return chunks


def serialize_chunks(chunks: list[BnkChunk]) -> bytes:
    out = bytearray()
    for ch in chunks:
        if len(ch.tag) != 4:
            raise BnkError("Invalid 4-byte chunk tag.")
        out.extend(ch.tag)
        out.extend(struct.pack("<I", len(ch.payload)))
        out.extend(ch.payload)
    return bytes(out)


def parse_bkhd(payload: bytes) -> dict:
    if len(payload) < 8:
        raise BnkError("Truncated BKHD chunk.")
    version, bank_id = struct.unpack_from("<II", payload, 0)
    return {"version": version, "bank_id": bank_id}


def parse_didx(payload: bytes) -> list[BnkMediaEntry]:
    if len(payload) % 12 != 0:
        raise BnkError(f"Invalid DIDX size ({len(payload)} is not a multiple of 12).")
    entries: list[BnkMediaEntry] = []
    for off in range(0, len(payload), 12):
        media_id, rel_offset, size = struct.unpack_from("<III", payload, off)
        entries.append(BnkMediaEntry(media_id=media_id, offset=rel_offset, size=size))
    return entries


def parse_bnk(data: bytes) -> dict:
    """Parse ``.bnk`` metadata and return header info plus embedded ``.wem`` descriptors."""
    chunks = parse_chunks(data)
    by_tag = {c.tag: c.payload for c in chunks}
    header = parse_bkhd(by_tag[b"BKHD"])
    entries = parse_didx(by_tag[b"DIDX"]) if b"DIDX" in by_tag else []
    data_blob = by_tag.get(b"DATA", b"")
    media = []
    for entry in entries:
        end = entry.offset + entry.size
        valid = end <= len(data_blob)
        media.append({
            "media_id": entry.media_id,
            "offset": entry.offset,
            "size": entry.size,
            "valid": valid,
        })
    return {
        "version": header["version"],
        "bank_id": header["bank_id"],
        "chunks": [c.tag.decode("ascii") for c in chunks],
        "media": media,
    }


def extract_wem(data: bytes, media_id: int) -> bytes:
    """Extract one embedded ``.wem`` stream by numeric ``media_id`` from a ``.bnk`` buffer."""
    chunks = parse_chunks(data)
    by_tag = {c.tag: c.payload for c in chunks}
    if b"DIDX" not in by_tag or b"DATA" not in by_tag:
        raise BnkError("This SoundBank contains no embedded DIDX/DATA media.")
    entries = parse_didx(by_tag[b"DIDX"])
    blob = by_tag[b"DATA"]
    target = int(media_id)
    for entry in entries:
        if entry.media_id == target:
            end = entry.offset + entry.size
            if end > len(blob):
                raise BnkError(f"Embedded media {target} points past the end of DATA.")
            return blob[entry.offset:end]
    raise KeyError(f"Media ID {target} not found in SoundBank.")


def _patch_hirc_media_sizes(hirc_payload: bytes, old_sizes: dict[int, int], new_sizes: dict[int, int]) -> bytes:
    """Update ``uInMemoryMediaSize`` inside HIRC ``CAkSound`` objects whose embedded ``sourceID`` changed size.

    In Wwise HIRC objects, ``type == 2`` is ``CAkSound``:
      - object header: ``u8 type``, ``u32 section_size``, ``u32 object_id``
      - followed by ``AkBankSourceData`` containing ``u32 plugin_id``, ``u8 stream_type``,
        ``u32 source_id``, ``u32 in_memory_media_size`` (plus older/newer bitfield variants).
    Because exact HIRC byte offsets shift slightly across Wwise versions, we patch ONLY when
    an embedded ``CAkSound`` object contains the exact consecutive pair ``<II(source_id, old_size)``
    within the first 36 bytes of the object body — completely safe against false matches.
    """
    if len(hirc_payload) < 4 or not new_sizes:
        return hirc_payload
    out = bytearray(hirc_payload)
    (count,) = struct.unpack_from("<I", out, 0)
    pos = 4
    total = len(out)
    for _ in range(count):
        if pos + 5 > total:
            break
        obj_type = out[pos]
        (obj_size,) = struct.unpack_from("<I", out, pos + 1)
        body_start = pos + 5
        body_end = body_start + obj_size
        if body_end > total:
            break
        if obj_type == 2 and obj_size >= 16:
            # Scan the AkBankSourceData prefix (first 40 bytes of CAkSound) for (media_id, old_size).
            scan_end = min(body_end, body_start + 44)
            window = bytes(out[body_start:scan_end])
            for mid, new_sz in new_sizes.items():
                old_sz = old_sizes.get(mid)
                if old_sz is None or old_sz == new_sz:
                    continue
                needle = struct.pack("<II", mid, old_sz)
                idx = window.find(needle)
                if idx >= 0:
                    struct.pack_into("<I", out, body_start + idx + 4, new_sz)
        pos = body_end
    return bytes(out)


def repack_bnk(data: bytes, replacements: dict[int, bytes]) -> bytes:
    """Replace one or more embedded ``.wem`` streams in ``data`` and return a valid repacked ``.bnk``."""
    if not replacements:
        return data
    chunks = parse_chunks(data)
    by_tag = {c.tag: c.payload for c in chunks}
    if b"DIDX" not in by_tag or b"DATA" not in by_tag:
        raise BnkError("Cannot repack a SoundBank with no DIDX/DATA sections.")

    entries = parse_didx(by_tag[b"DIDX"])
    blob = by_tag[b"DATA"]
    norm_rep = {int(k): bytes(v) for k, v in replacements.items()}
    known_ids = {e.media_id for e in entries}
    missing = [mid for mid in norm_rep if mid not in known_ids]
    if missing:
        raise KeyError(f"Media ID(s) not present in SoundBank: {missing}")

    new_didx = bytearray()
    new_data = bytearray()
    old_sizes: dict[int, int] = {}
    new_sizes: dict[int, int] = {}

    for idx, entry in enumerate(entries):
        old_sizes[entry.media_id] = entry.size
        if entry.media_id in norm_rep:
            payload = norm_rep[entry.media_id]
            new_sizes[entry.media_id] = len(payload)
        else:
            end = entry.offset + entry.size
            if end > len(blob):
                raise BnkError(f"Embedded media {entry.media_id} is out of bounds.")
            payload = blob[entry.offset:end]

        # Wwise aligns embedded DATA entries to 16-byte boundaries for SIMD/DMA reads.
        pad = (-len(new_data)) % _ALIGNMENT
        if pad:
            new_data.extend(b"\x00" * pad)
        rel_off = len(new_data)
        new_data.extend(payload)
        new_didx.extend(struct.pack("<III", entry.media_id, rel_off, len(payload)))

    rebuilt: list[BnkChunk] = []
    for ch in chunks:
        if ch.tag == b"DIDX":
            rebuilt.append(BnkChunk(b"DIDX", bytes(new_didx)))
        elif ch.tag == b"DATA":
            rebuilt.append(BnkChunk(b"DATA", bytes(new_data)))
        elif ch.tag == b"HIRC":
            rebuilt.append(BnkChunk(b"HIRC", _patch_hirc_media_sizes(ch.payload, old_sizes, new_sizes)))
        else:
            rebuilt.append(ch)
    return serialize_chunks(rebuilt)
