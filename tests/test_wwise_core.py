"""Unit tests for pure-Python Wwise .bnk parser/repacker and .wem codec engine."""
from io import BytesIO
import struct
import unittest
import wave

from atelier.handlers import wwise_bnk, wwise_wem


def _make_wav(frames: int = 4800, rate: int = 48000, channels: int = 2) -> bytes:
    buf = BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(b"\x10\x02" * frames * channels)
    return buf.getvalue()


def _make_bnk(media_map: dict[int, bytes], *, include_hirc: bool = True) -> bytes:
    bkhd = struct.pack("<II", 145, 0x12345678)
    didx = bytearray()
    data = bytearray()
    hirc_objs = bytearray()
    for mid, payload in media_map.items():
        pad = (-len(data)) % 16
        if pad:
            data.extend(b"\x00" * pad)
        off = len(data)
        data.extend(payload)
        didx.extend(struct.pack("<III", mid, off, len(payload)))
        if include_hirc:
            # Minimal CAkSound (type=2): object_id + plugin_id + stream_type(0) + source_id + media_size
            body = struct.pack("<IIBII", mid ^ 0xFF, 0x00040001, 0, mid, len(payload))
            hirc_objs.extend(struct.pack("<BI", 2, len(body)) + body)

    chunks = [
        wwise_bnk.BnkChunk(b"BKHD", bkhd),
        wwise_bnk.BnkChunk(b"DIDX", bytes(didx)),
        wwise_bnk.BnkChunk(b"DATA", bytes(data)),
    ]
    if include_hirc:
        chunks.append(wwise_bnk.BnkChunk(b"HIRC", struct.pack("<I", len(media_map)) + bytes(hirc_objs)))
    chunks.append(wwise_bnk.BnkChunk(b"STID", b"\x01\x00\x00\x00"))
    return wwise_bnk.serialize_chunks(chunks)


class WwiseCoreTests(unittest.TestCase):
    def test_wem_pcm_roundtrip_and_inspect(self):
        wav = _make_wav(frames=2400, rate=48000, channels=2)
        wem, codec = wwise_wem.encode_wav_to_wem(wav, prefer_vorbis=False)
        self.assertEqual(codec, "Wwise PCM")

        info = wwise_wem.inspect_wem(wem)
        self.assertEqual(info["format_tag"], 0xFFFE)
        self.assertEqual(info["channels"], 2)
        self.assertEqual(info["sample_rate"], 48000)
        self.assertEqual(info["bits_per_sample"], 16)
        self.assertAlmostEqual(info["duration"], 0.05, places=3)

        decoded = wwise_wem.decode_wem_to_wav(wem)
        with wave.open(BytesIO(decoded), "rb") as wf:
            self.assertEqual(wf.getnchannels(), 2)
            self.assertEqual(wf.getframerate(), 48000)
            self.assertEqual(wf.getnframes(), 2400)

    def test_bnk_parse_extract_repack_updates_alignment_and_hirc_size(self):
        wem1 = wwise_wem.encode_wav_to_wem_pcm(_make_wav(frames=1000, channels=1))
        wem2 = wwise_wem.encode_wav_to_wem_pcm(_make_wav(frames=1200, channels=2))
        bnk = _make_bnk({111111: wem1, 222222: wem2})

        parsed = wwise_bnk.parse_bnk(bnk)
        self.assertEqual(parsed["version"], 145)
        self.assertEqual([m["media_id"] for m in parsed["media"]], [111111, 222222])
        self.assertEqual(wwise_bnk.extract_wem(bnk, 111111), wem1)
        self.assertEqual(wwise_bnk.extract_wem(bnk, 222222), wem2)

        replacement = wwise_wem.encode_wav_to_wem_pcm(_make_wav(frames=3333, channels=2))
        repacked = wwise_bnk.repack_bnk(bnk, {111111: replacement})
        reparsed = wwise_bnk.parse_bnk(repacked)
        self.assertEqual(wwise_bnk.extract_wem(repacked, 111111), replacement)
        self.assertEqual(wwise_bnk.extract_wem(repacked, 222222), wem2)
        # Second entry must remain 16-byte aligned in DATA.
        self.assertEqual(reparsed["media"][1]["offset"] % 16, 0)
        # Untouched trailing STID chunk must be preserved verbatim.
        self.assertIn("STID", reparsed["chunks"])
        # HIRC CAkSound embedded media size must match replacement length.
        hirc_chunk = next(c.payload for c in wwise_bnk.parse_chunks(repacked) if c.tag == b"HIRC")
        self.assertIn(struct.pack("<II", 111111, len(replacement)), hirc_chunk)


if __name__ == "__main__":
    unittest.main()
