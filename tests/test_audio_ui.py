"""Node-backed unit tests for Audio & Voice Line Studio client helpers and UI wiring."""
import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class AudioStudioUiTests(unittest.TestCase):
    def test_wav_encoder_peaks_and_subtitle_filters(self):
        script = r"""
const assert = require('node:assert/strict');
const studio = require('./gui/audio-studio.js');

// 1. PCM 16-bit WAV encoder produces valid RIFF/WAVE header and clamps samples
const sr = 48000;
const n = 480; // 10ms
const left = new Float32Array(n);
const right = new Float32Array(n);
for (let i = 0; i < n; i++) {
  left[i] = i === 0 ? 1.5 : Math.sin((2 * Math.PI * 440 * i) / sr) * 0.5;
  right[i] = i === 0 ? -1.5 : -Math.sin((2 * Math.PI * 440 * i) / sr) * 0.5;
}
const wav = studio.encodePcm16Wav([left, right], sr);
assert.equal(wav.length, 44 + n * 2 * 2);
const dv = new DataView(wav.buffer, wav.byteOffset, wav.byteLength);
assert.equal(String.fromCharCode(...wav.slice(0, 4)), 'RIFF');
assert.equal(String.fromCharCode(...wav.slice(8, 12)), 'WAVE');
assert.equal(dv.getUint16(20, true), 1); // PCM
assert.equal(dv.getUint16(22, true), 2); // Stereo
assert.equal(dv.getUint32(24, true), sr);
assert.equal(dv.getUint16(34, true), 16); // 16-bit
assert.equal(dv.getInt16(44, true), 32767); // clamped +1.5
assert.equal(dv.getInt16(46, true), -32768); // clamped -1.5

// Base64 roundtrip
const b64 = studio.uint8ToBase64(wav);
assert.deepEqual(Buffer.from(b64, 'base64'), Buffer.from(wav));

// 2. Waveform peaks helper
const peaks = studio.peaksFromChannels([left, right], sr, 60);
assert.equal(peaks.peaks.length, 60);
assert.ok(peaks.duration > 0.009 && peaks.duration < 0.011);
assert.ok(peaks.peaks[0] >= 0.99);

// 3. Time formatter
assert.equal(studio.formatTime(0), '0:00.00');
assert.equal(studio.formatTime(65.42), '1:05.42');

// 4. Subtitle-aware clip and bank filters
const clips = [
  { media_id: '111', subtitle: 'BEHOLD, DARKCHYLDE!', label: 'Ultimate', codec: 'Vorbis' },
  { media_id: '222', subtitle: 'Time to swing!', label: 'Movement', codec: 'PCM' },
];
assert.equal(studio.filterClips(clips, 'darkchylde').length, 1);
assert.equal(studio.filterClips(clips, '222 pcm').length, 1);
assert.equal(studio.filterClips(clips, 'missing').length, 0);

const banks = [
  { bank_rel: 'b1.bnk', stem: 'Hero_1029_VO', group_label: 'Magik (1029)', hero_id: '1029', category: 'heroes' },
  { bank_rel: 'b2.bnk', stem: 'UI_Announcer', group_label: 'UI & Announcer', hero_id: '', category: 'ui' },
];
assert.equal(studio.filterBanks(banks, 'darkchylde', 'all', { 'b1.bnk': clips }).length, 1);
assert.equal(studio.filterBanks(banks, '', 'ui', {}).length, 1);

console.log(JSON.stringify({ ok: true }));
"""
        proc = subprocess.run(
            ["node", "-e", script],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, f"stdout={proc.stdout}\nstderr={proc.stderr}")
        self.assertTrue(json.loads(proc.stdout.strip())["ok"])

    def test_frontend_wiring_and_vendored_icons(self):
        html = (ROOT / "gui" / "index.html").read_text(encoding="utf-8")
        self.assertIn("/static/audio-studio.css", html)
        self.assertIn("/static/audio-studio.js", html)

        app_js = (ROOT / "gui" / "app.js").read_text(encoding="utf-8")
        self.assertIn('case "audio":', app_js)
        self.assertIn("AtelierAudioStudio", app_js)
        self.assertIn('"audio"', app_js)

        sources = json.loads((ROOT / "gui" / "vendor" / "material-symbols" / "sources.json").read_text(encoding="utf-8"))
        valid_icons = set(sources["mapping"].keys())
        audio_js = (ROOT / "gui" / "audio-studio.js").read_text(encoding="utf-8")
        import re
        used = set(re.findall(r'data-lucide="([^"]+)"', audio_js))
        self.assertTrue(used, "Expected Audio Studio to reference vendored icons")
        missing = used - valid_icons
        self.assertEqual(missing, set(), f"Unvendored icon names found in audio-studio.js: {missing}")


if __name__ == "__main__":
    unittest.main()
