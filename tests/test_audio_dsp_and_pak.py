"""Unit tests for audio_dsp (LUFS/trim/fade/waveform), wwise_pak (UE5 v11 pak R/W), and audio_subtitles (.locres)."""
from pathlib import Path
import struct
import tempfile
import unittest

import numpy as np

from atelier import legacy_pak
from atelier.handlers import audio_dsp, audio_subtitles, wwise_pak


def _sine_wav(freq: float = 440.0, seconds: float = 0.4, rate: int = 48000, amp: float = 0.2, channels: int = 2) -> bytes:
    t = np.arange(int(rate * seconds), dtype=np.float32) / float(rate)
    sig = (amp * np.sin(2.0 * np.pi * freq * t)).astype(np.float32)
    arr = np.repeat(sig[:, None], channels, axis=1)
    return audio_dsp.write_wav_pcm16(arr, rate)


def _build_synthetic_locres(entries: dict[str, dict[str, str]]) -> bytes:
    """Build a valid binary UE5 .locres v2 buffer for roundtrip parser testing."""
    def fstr(s: str) -> bytes:
        raw = s.encode("utf-8") + b"\x00"
        return struct.pack("<i", len(raw)) + raw

    strings: list[str] = []
    str_idx_map: dict[str, int] = {}
    for ns_map in entries.values():
        for txt in ns_map.values():
            if txt not in str_idx_map:
                str_idx_map[txt] = len(strings)
                strings.append(txt)

    body = bytearray()
    total_entries = sum(len(m) for m in entries.values())
    body.extend(struct.pack("<II", total_entries, len(entries)))
    for ns, ns_map in entries.items():
        body.extend(struct.pack("<I", 0))
        body.extend(fstr(ns))
        body.extend(struct.pack("<I", len(ns_map)))
        for k, txt in ns_map.items():
            body.extend(struct.pack("<I", 0))
            body.extend(fstr(k))
            body.extend(struct.pack("<Ii", 0, str_idx_map[txt]))

    str_table_offset = 25 + len(body)
    str_table = bytearray()
    str_table.extend(struct.pack("<I", len(strings)))
    for txt in strings:
        str_table.extend(fstr(txt))
        str_table.extend(struct.pack("<i", 1))

    header = audio_subtitles._LOCRES_MAGIC + struct.pack("<Bq", 2, str_table_offset)
    return bytes(header + body + str_table)


class AudioDspPakSubtitleTests(unittest.TestCase):
    def test_lufs_matching_trim_fade_and_peak_safety(self):
        quiet = _sine_wav(amp=0.05, seconds=0.5, rate=44100, channels=1)
        loud = _sine_wav(amp=0.45, seconds=0.5, rate=48000, channels=2)

        loud_info = audio_dsp.waveform_peaks(loud, bars=64)
        self.assertEqual(len(loud_info["peaks"]), 64)
        self.assertGreater(loud_info["lufs"], -20.0)

        processed, meta = audio_dsp.process_audio(
            quiet,
            target_rate=48000,
            target_channels=2,
            trim_start=0.05,
            trim_end=0.35,
            fade_in_ms=20,
            fade_out_ms=20,
            match_lufs=loud_info["lufs"],
        )
        self.assertEqual(meta["sample_rate"], 48000)
        self.assertEqual(meta["channels"], 2)
        self.assertAlmostEqual(meta["duration"], 0.30, places=2)
        # Matched LUFS should move much closer to the target and never exceed -0.95 dBFS peak ceiling.
        self.assertGreater(meta["lufs_after"], meta["lufs_before"] + 6.0)
        self.assertLessEqual(meta["peak_dbfs"], -0.95)
        self.assertTrue(processed.startswith(b"RIFF"))

    def test_ue5_pak_v11_write_and_read_roundtrip_with_legacy_pak_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            pak_path = Path(tmp) / "AudioMod_P.pak"
            files = {
                "Marvel/Content/WwiseAudio/Windows/bnk_vo_1029.bnk": b"BKHD" + b"\x01\x02\x03\x04" * 20,
                "Marvel/Content/WwiseAudio/Windows/681577199.wem": b"RIFF" + b"\x05\x06\x07\x08" * 10,
            }
            wwise_pak.write_loose_pak(pak_path, files)

            # Verify Atelier's existing legacy_pak.Pak & safety checker accept it!
            names, problem = legacy_pak.check(str(pak_path))
            self.assertIsNone(problem)
            self.assertEqual(sorted(names), sorted(files.keys()))

            # Verify PakReader extracts every byte verbatim.
            reader = wwise_pak.PakReader(pak_path)
            for rel, expected in files.items():
                self.assertEqual(reader.read_file(rel), expected)

    def test_locres_parser_and_soundbanks_info_subtitle_resolution(self):
        loc_bytes = _build_synthetic_locres({
            "VO_Subtitles": {
                "1029_Ult_01": "BEHOLD, DARKCHYLDE!",
                "1029_Greeting_01": "Limbo waits for no one.",
            },
        })
        tables = audio_subtitles.parse_locres(loc_bytes)
        self.assertEqual(tables["VO_Subtitles"]["1029_Ult_01"], "BEHOLD, DARKCHYLDE!")

        sbi_json = """{
          "SoundBanksInfo": {
            "SoundBanks": [{
              "ShortName": "bnk_vo_1029",
              "Language": "English(US)",
              "Media": [{"Id": "681577199", "ShortName": "VO_1029_Ult_01.wav"}],
              "Events": [{"Name": "Play_VO_1029_Ult_01", "MediaRefs": [{"Id": "681577199"}]}]
            }]
          }
        }"""
        bank_info = audio_subtitles.parse_soundbanks_info_json(sbi_json)
        idx = audio_subtitles.SubtitleIndex(tables, bank_info)
        hit = idx.resolve(681577199)
        self.assertEqual(hit["subtitle"], "BEHOLD, DARKCHYLDE!")
        self.assertEqual(hit["source"], "locres")

        hero_hits = idx.hero_subtitles("1029", query="limbo")
        self.assertEqual(len(hero_hits), 1)
        self.assertIn("Limbo", hero_hits[0]["text"])

        csv_map = audio_subtitles.parse_subtitle_map("media_id,subtitle,label\n999999,\"Maximum Pulse!\",Ult\n", "subs.csv")
        self.assertEqual(csv_map["999999"]["subtitle"], "Maximum Pulse!")


if __name__ == "__main__":
    unittest.main()
