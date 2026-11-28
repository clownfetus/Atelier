"""Pure-NumPy audio DSP: WAV I/O, resampling, ITU-R BS.1770 LUFS loudness matching, trim/fade & waveform."""
from io import BytesIO
import math
import struct
import wave

import numpy as np


def read_wav_float(wav_bytes: bytes) -> tuple[np.ndarray, int]:
    """Read PCM WAV (8/16/24/32-bit int or 32-bit IEEE float) into ``(samples[N, C] float32, sample_rate)``."""
    if not wav_bytes or len(wav_bytes) < 44 or wav_bytes[:4] != b"RIFF" or wav_bytes[8:12] != b"WAVE":
        raise ValueError("Input is not a valid RIFF/WAVE file.")

    # Parse chunks manually so IEEE float (format tag 3) and extensible (0xFFFE) WAVs also decode cleanly.
    pos = 12
    total = len(wav_bytes)
    fmt = None
    raw_data = b""
    while pos + 8 <= total:
        tag = wav_bytes[pos:pos + 4]
        (size,) = struct.unpack_from("<I", wav_bytes, pos + 4)
        start = pos + 8
        end = min(total, start + size)
        if tag == b"fmt " and end - start >= 16:
            fmt = struct.unpack_from("<HHIIHH", wav_bytes, start)
            if fmt[0] == 0xFFFE and end - start >= 40:
                sub_tag = struct.unpack_from("<H", wav_bytes, start + 24)[0]
                fmt = (sub_tag, fmt[1], fmt[2], fmt[3], fmt[4], fmt[5])
        elif tag == b"data":
            raw_data = wav_bytes[start:end]
        pos = start + size + (size & 1)

    if fmt is None or not raw_data:
        raise ValueError("WAV file is missing fmt or data chunk.")

    fmt_tag, channels, sample_rate, _, _, bits = fmt
    if channels < 1 or channels > 8 or sample_rate <= 0:
        raise ValueError("Unsupported WAV channel count or sample rate.")

    if fmt_tag == 3 and bits == 32:
        n_vals = (len(raw_data) // 4 // channels) * channels
        samples = np.frombuffer(raw_data[:n_vals * 4], dtype="<f4").astype(np.float32)
    elif fmt_tag == 1 and bits == 16:
        n_vals = (len(raw_data) // 2 // channels) * channels
        samples = np.frombuffer(raw_data[:n_vals * 2], dtype="<i2").astype(np.float32) / 32768.0
    elif fmt_tag == 1 and bits == 8:
        n_vals = (len(raw_data) // channels) * channels
        samples = (np.frombuffer(raw_data[:n_vals], dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif fmt_tag == 1 and bits == 24:
        frame_bytes = 3 * channels
        n_frames = len(raw_data) // frame_bytes
        raw = np.frombuffer(raw_data[:n_frames * frame_bytes], dtype=np.uint8).reshape(n_frames * channels, 3)
        ints = (
            raw[:, 0].astype(np.int32)
            | (raw[:, 1].astype(np.int32) << 8)
            | (raw[:, 2].astype(np.int32) << 16)
        )
        ints = np.where(ints & 0x800000, ints - 0x1000000, ints)
        samples = ints.astype(np.float32) / 8388608.0
    elif fmt_tag == 1 and bits == 32:
        n_vals = (len(raw_data) // 4 // channels) * channels
        samples = np.frombuffer(raw_data[:n_vals * 4], dtype="<i4").astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f"Unsupported WAV format (tag={fmt_tag}, bits={bits}).")

    samples = samples.reshape(-1, channels)
    return np.clip(samples, -1.0, 1.0), int(sample_rate)


def write_wav_pcm16(samples: np.ndarray, sample_rate: int) -> bytes:
    """Encode ``samples[N, C]`` float32 in ``[-1, 1]`` to 16-bit PCM WAV bytes."""
    arr = np.asarray(samples, dtype=np.float32)
    if arr.ndim == 1:
        arr = arr[:, None]
    clipped = np.clip(arr, -1.0, 1.0)
    pcm = np.round(clipped * 32767.0).astype("<i2")
    buf = BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(int(pcm.shape[1]))
        wf.setsampwidth(2)
        wf.setframerate(int(sample_rate))
        wf.writeframes(pcm.tobytes())
    return buf.getvalue()


def match_channels(samples: np.ndarray, target_channels: int) -> np.ndarray:
    """Convert mono <-> stereo cleanly to match the target Wwise stream channel count."""
    arr = np.asarray(samples, dtype=np.float32)
    if arr.ndim == 1:
        arr = arr[:, None]
    cur = arr.shape[1]
    if cur == target_channels or target_channels < 1:
        return arr
    if target_channels == 1:
        return np.mean(arr, axis=1, keepdims=True).astype(np.float32)
    if cur == 1:
        return np.repeat(arr, target_channels, axis=1).astype(np.float32)
    if cur > target_channels:
        return arr[:, :target_channels].astype(np.float32)
    pad = np.zeros((arr.shape[0], target_channels - cur), dtype=np.float32)
    return np.concatenate([arr, pad], axis=1)


def resample_audio(samples: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    """Resample ``samples[N, C]`` from ``src_rate`` to ``dst_rate`` using smooth linear interpolation."""
    if src_rate == dst_rate or len(samples) < 2 or dst_rate <= 0:
        return samples
    n_in = samples.shape[0]
    n_out = max(1, int(round(n_in * (dst_rate / float(src_rate)))))
    x_old = np.linspace(0.0, 1.0, n_in, dtype=np.float64)
    x_new = np.linspace(0.0, 1.0, n_out, dtype=np.float64)
    out = np.empty((n_out, samples.shape[1]), dtype=np.float32)
    for ch in range(samples.shape[1]):
        out[:, ch] = np.interp(x_new, x_old, samples[:, ch]).astype(np.float32)
    return out


def _biquad_filter(x: np.ndarray, b0: float, b1: float, b2: float, a1: float, a2: float) -> np.ndarray:
    """Direct Form II Transposed biquad over a 1D float64 signal."""
    # Vectorized over channels when called per-channel; fast enough for game clips (< 15s) or FFT fallback.
    n = len(x)
    if n == 0:
        return x
    # Frequency-domain exact IIR application via rfft (orders of magnitude faster in pure NumPy than Python loops).
    n_fft = 1 << int(math.ceil(math.log2(max(256, n + 512))))
    freqs = np.fft.rfftfreq(n_fft, d=1.0)
    z_inv = np.exp(-2j * np.pi * freqs)
    z_inv2 = z_inv * z_inv
    H = (b0 + b1 * z_inv + b2 * z_inv2) / (1.0 + a1 * z_inv + a2 * z_inv2)
    X = np.fft.rfft(x, n=n_fft)
    return np.fft.irfft(X * H, n=n_fft)[:n]


def measure_lufs(samples: np.ndarray, sample_rate: int) -> float:
    """Measure integrated ITU-R BS.1770-4 K-weighted loudness (LUFS). Returns -70.0 for silence."""
    arr = np.asarray(samples, dtype=np.float64)
    if arr.ndim == 1:
        arr = arr[:, None]
    if arr.shape[0] == 0:
        return -70.0

    # Stage 1: K-weighting high-shelf pre-filter (+4 dB above ~1.68 kHz, bilinear transform for sample_rate).
    fs = float(sample_rate)
    db = 3.999843853973347
    f0 = 1681.974450955533
    q = 0.7071752369554196
    K = math.tan(math.pi * f0 / fs)
    Vh = 10.0 ** (db / 20.0)
    Vb = Vh ** 0.4996667741545416
    a0 = 1.0 + K / q + K * K
    b0_1 = (Vh + Vb * K / q + K * K) / a0
    b1_1 = 2.0 * (K * K - Vh) / a0
    b2_1 = (Vh - Vb * K / q + K * K) / a0
    a1_1 = 2.0 * (K * K - 1.0) / a0
    a2_1 = (1.0 - K / q + K * K) / a0

    # Stage 2: RLB high-pass filter (~38 Hz).
    f0_hp = 38.13547087602444
    q_hp = 0.5003270373238773
    K2 = math.tan(math.pi * f0_hp / fs)
    a0_2 = 1.0 + K2 / q_hp + K2 * K2
    b0_2 = 1.0 / a0_2
    b1_2 = -2.0 / a0_2
    b2_2 = 1.0 / a0_2
    a1_2 = 2.0 * (K2 * K2 - 1.0) / a0_2
    a2_2 = (1.0 - K2 / q_hp + K2 * K2) / a0_2

    ch_weights = [1.0, 1.0, 1.0, 0.0, 1.41, 1.41]  # L, R, C, LFE(ignored), Ls, Rs
    weighted_energy = 0.0
    total_active = 0
    for ch in range(arr.shape[1]):
        w = ch_weights[ch] if ch < len(ch_weights) else 1.0
        if w == 0.0:
            continue
        y = _biquad_filter(arr[:, ch], b0_1, b1_1, b2_1, a1_1, a2_1)
        y = _biquad_filter(y, b0_2, b1_2, b2_2, a1_2, a2_2)
        # Gate out leading/trailing silence (< -65 dBFS) so short voice barks measure accurately.
        sq = y * y
        if len(sq) > 0:
            active = sq[sq > 1e-7]
            if len(active) > 0:
                weighted_energy += w * float(np.mean(active))
                total_active += 1

    if total_active == 0 or weighted_energy <= 1e-12:
        return -70.0
    return round(float(-0.691 + 10.0 * math.log10(weighted_energy)), 2)


def soft_limit(samples: np.ndarray, ceiling_db: float = -1.0) -> np.ndarray:
    """Prevent digital clipping with a transparent soft-knee peak ceiling (default -1.0 dBFS)."""
    ceiling = 10.0 ** (ceiling_db / 20.0)
    peak = float(np.max(np.abs(samples))) if samples.size else 0.0
    if peak <= ceiling:
        return samples.astype(np.float32)
    # Soft tanh saturation above 85% of ceiling, hard-clamped at ceiling.
    knee = ceiling * 0.85
    abs_s = np.abs(samples)
    over = abs_s > knee
    out = samples.astype(np.float32).copy()
    if np.any(over):
        excess = (abs_s[over] - knee) / max(1e-6, ceiling - knee)
        shaped = knee + (ceiling - knee) * np.tanh(excess)
        out[over] = np.sign(samples[over]) * shaped
    return np.clip(out, -ceiling, ceiling).astype(np.float32)


def process_audio(
    wav_bytes: bytes,
    *,
    target_rate: int | None = None,
    target_channels: int | None = None,
    trim_start: float = 0.0,
    trim_end: float = 0.0,
    fade_in_ms: float = 0.0,
    fade_out_ms: float = 0.0,
    match_lufs: float | None = None,
    gain_db: float = 0.0,
) -> tuple[bytes, dict]:
    """Apply trim, fade, resampling, optional LUFS loudness match, gain and peak limiting."""
    samples, rate = read_wav_float(wav_bytes)
    n_total = samples.shape[0]

    start_idx = max(0, min(n_total, int(round(max(0.0, float(trim_start)) * rate))))
    end_idx = n_total if (not trim_end or trim_end <= 0.0) else max(start_idx + 1, min(n_total, int(round(float(trim_end) * rate))))
    samples = samples[start_idx:end_idx]
    if samples.shape[0] == 0:
        raise ValueError("Trim range leaves no audio samples.")

    if target_channels and target_channels > 0:
        samples = match_channels(samples, int(target_channels))
    if target_rate and target_rate > 0 and target_rate != rate:
        samples = resample_audio(samples, rate, int(target_rate))
        rate = int(target_rate)

    # Smooth cosine fades
    n_cur = samples.shape[0]
    fi = min(n_cur // 2, int(round(max(0.0, float(fade_in_ms)) * rate / 1000.0)))
    if fi > 1:
        ramp = 0.5 * (1.0 - np.cos(np.linspace(0.0, math.pi, fi, dtype=np.float32)))
        samples = samples.copy()
        samples[:fi] *= ramp[:, None]
    fo = min(n_cur // 2, int(round(max(0.0, float(fade_out_ms)) * rate / 1000.0)))
    if fo > 1:
        ramp = 0.5 * (1.0 + np.cos(np.linspace(0.0, math.pi, fo, dtype=np.float32)))
        samples = samples.copy()
        samples[n_cur - fo:] *= ramp[:, None]

    measured_before = measure_lufs(samples, rate)
    total_gain_db = float(gain_db or 0.0)
    if match_lufs is not None and measured_before > -65.0:
        delta = max(-24.0, min(24.0, float(match_lufs) - measured_before))
        total_gain_db += delta
    if abs(total_gain_db) > 0.01:
        samples = samples * float(10.0 ** (total_gain_db / 20.0))

    samples = soft_limit(samples, ceiling_db=-1.0)
    measured_after = measure_lufs(samples, rate)
    out_wav = write_wav_pcm16(samples, rate)
    return out_wav, {
        "sample_rate": rate,
        "channels": int(samples.shape[1]),
        "duration": round(samples.shape[0] / float(rate), 3),
        "lufs_before": measured_before,
        "lufs_after": measured_after,
        "applied_gain_db": round(total_gain_db, 2),
        "peak_dbfs": round(20.0 * math.log10(max(1e-6, float(np.max(np.abs(samples))))), 2),
    }


def waveform_peaks(wav_bytes: bytes, bars: int = 160) -> dict:
    """Compute a compact normalized peak envelope ``[0..1]`` + loudness/duration for canvas UI."""
    samples, rate = read_wav_float(wav_bytes)
    mono = np.mean(np.abs(samples), axis=1) if samples.shape[1] > 1 else np.abs(samples[:, 0])
    n = len(mono)
    bars = max(16, min(512, int(bars)))
    if n == 0:
        peaks = [0.0] * bars
    elif n <= bars:
        peaks = [round(float(v), 4) for v in mono] + [0.0] * (bars - n)
    else:
        edges = np.linspace(0, n, bars + 1, dtype=np.int64)
        peaks = [round(float(np.max(mono[edges[i]:max(edges[i] + 1, edges[i + 1])])), 4) for i in range(bars)]
    return {
        "peaks": peaks,
        "duration": round(n / float(rate), 3),
        "sample_rate": rate,
        "channels": int(samples.shape[1]),
        "lufs": measure_lufs(samples, rate),
    }
