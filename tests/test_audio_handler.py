"""End-to-end tests for Audio & Voice Line Studio handler (scan, subtitles, DSP save, BNK repack, pak export)."""
from pathlib import Path
import struct
import tempfile
import unittest

import numpy as np

from atelier import legacy_pak
from atelier.handlers import audio, audio_dsp, audio_subtitles, wwise_bnk, wwise_pak, wwise_wem


def _sine_wav(freq: float = 440.0, seconds: float = 0.25, rate: int = 48000, amp: float = 0.25, channels: int = 2) -> bytes:
    t = np.arange(int(rate * seconds), dtype=np.float32) / float(rate)
    sig = (amp * np.sin(2.0 * np.pi * freq * t)).astype(np.float32)
    arr = np.repeat(sig[:, None], channels, axis=1)
    return audio_dsp.write_wav_pcm16(arr, rate)


def _synthetic_locres(entries: dict[str, dict[str, str]]) -> bytes:
    def fstr(s: str) -> bytes:
        raw = s.encode("utf-8") + b"\x00"
        return struct.pack("<i", len(raw)) + raw

    strings, idx_map = [], {}
    for m in entries.values():
        for txt in m.values():
            if txt not in idx_map:
                idx_map[txt] = len(strings)
                strings.append(txt)
    body = bytearray(struct.pack("<II", sum(len(m) for m in entries.values()), len(entries)))
    for ns, m in entries.items():
        body.extend(struct.pack("<I", 0) + fstr(ns) + struct.pack("<I", len(m)))
        for k, txt in m.items():
            body.extend(struct.pack("<I", 0) + fstr(k) + struct.pack("<Ii", 0, idx_map[txt]))
    str_off = 25 + len(body)
    st = bytearray(struct.pack("<I", len(strings)))
    for txt in strings:
        st.extend(fstr(txt) + struct.pack("<i", 1))
    return bytes(audio_subtitles._LOCRES_MAGIC + struct.pack("<Bq", 2, str_off) + body + st)


def _synthetic_bnk(media: dict[int, bytes]) -> bytes:
    bkhd = struct.pack("<II", 145, 999)
    didx, data = bytearray(), bytearray()
    for mid, wem in media.items():
        pad = (-len(data)) % 16
        if pad:
            data.extend(b"\x00" * pad)
        off = len(data)
        data.extend(wem)
        didx.extend(struct.pack("<III", mid, off, len(wem)))
    return wwise_bnk.serialize_chunks([
        wwise_bnk.BnkChunk(b"BKHD", bkhd),
        wwise_bnk.BnkChunk(b"DIDX", bytes(didx)),
        wwise_bnk.BnkChunk(b"DATA", bytes(data)),
    ])


class AudioHandlerEndToEndTests(unittest.TestCase):
    def test_scan_subtitle_resolution_save_and_pak_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paks = root / "Paks"
            proj = root / "ProjectA"
            out_dir = root / "Out"
            paks.mkdir()
            proj.mkdir()
            out_dir.mkdir()

            wem1 = wwise_wem.encode_wav_to_wem_pcm(_sine_wav(freq=330.0, amp=0.3))
            wem2 = wwise_wem.encode_wav_to_wem_pcm(_sine_wav(freq=660.0, amp=0.25))
            bnk = _synthetic_bnk({681577199: wem1, 681577200: wem2})
            sbi = """{"SoundBanksInfo":{"SoundBanks":[{"ShortName":"bnk_vo_1029","Events":[{"Name":"Play_VO_1029_Ult_01","MediaRefs":[{"Id":"681577199"}]}]}]}}""".encode("utf-8")
            loc = _synthetic_locres({"VO_1029": {"1029_Ult_01": "BEHOLD, DARKCHYLDE!"}})

            wwise_pak.write_loose_pak(paks / "pakchunkWwise-Windows.pak", {
                "Marvel/Content/WwiseAudio/Windows/bnk_vo_1029.bnk": bnk,
                "Marvel/Content/WwiseAudio/Windows/SoundbanksInfo.json": sbi,
                "Marvel/Content/Localization/Game/en/Game.locres": loc,
            })

            cat = audio.scan_audio_catalog(paks)
            self.assertEqual(len(cat["banks"]), 1)
            self.assertEqual(cat["banks"][0]["hero_id"], "1029")

            bank_res = audio.list_bank_clips("bnk_vo_1029", paks_dir=paks, project_dir=proj)
            self.assertEqual(bank_res["clip_count"], 2)
            ult = next(c for c in bank_res["clips"] if c["media_id"] == "681577199")
            self.assertEqual(ult["subtitle"], "BEHOLD, DARKCHYLDE!")
            self.assertFalse(ult["edited"])

            # Save a custom replacement WAV with LUFS matching + trim + fade.
            custom_wav = _sine_wav(freq=520.0, seconds=0.4, rate=44100, amp=0.08, channels=1)
            saved = audio.save_audio_edit(
                ult["game_rel"],
                wav_bytes=custom_wav,
                dsp={"match_lufs": True, "trim_start": 0.05, "trim_end": 0.30, "fade_out_ms": 20.0},
                label="Custom Darkchylde Ult",
                subtitle="BEHOLD, CUSTOM LINE!",
                paks_dir=paks,
                project_dir=proj,
            )
            self.assertTrue(saved["ok"])

            detail = audio.inspect_clip(ult["game_rel"], paks_dir=paks, project_dir=proj)
            self.assertTrue(detail["edited"])
            self.assertIsNotNone(detail["original_wave"])
            self.assertIsNotNone(detail["edited_wave"])
            self.assertEqual(detail["subtitle"], "BEHOLD, CUSTOM LINE!")

            # Export to a clean UE5 v11 .pak and verify round-trip unpacking.
            out_pak = out_dir / "DarkchyldeAudio_9999999_P.pak"
            built = audio.build_audio_pak([ult["game_rel"]], out_pak, paks_dir=paks, project_dir=proj)
            self.assertTrue(built["ok"])
            self.assertTrue(out_pak.is_file())

            names, problem = legacy_pak.check(str(out_pak))
            self.assertIsNone(problem)
            self.assertEqual(names, ["Marvel/Content/WwiseAudio/Windows/bnk_vo_1029.bnk"])

            repacked_bnk = wwise_pak.PakReader(out_pak).read_file(names[0])
            new_wem1 = wwise_bnk.extract_wem(repacked_bnk, 681577199)
            untouched_wem2 = wwise_bnk.extract_wem(repacked_bnk, 681577200)
            self.assertNotEqual(new_wem1, wem1)
            self.assertEqual(untouched_wem2, wem2)
            new_info = wwise_wem.inspect_wem(new_wem1)
            self.assertEqual(new_info["sample_rate"], 48000)
            self.assertEqual(new_info["channels"], 2)
            self.assertAlmostEqual(new_info["duration"], 0.25, places=2)


if __name__ == "__main__":
    unittest.main()
