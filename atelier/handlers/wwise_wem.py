"""Wwise Encoded Media (.wem) header inspector, pure-Python PCM codec, and seamless CLI bridge.

Design for zero-setup user experience:
  - Inspecting any .wem (codec, sample rate, channels, duration, loop points) is 100% pure Python.
  - Encoding WAV -> Wwise RIFF PCM (.wem, format tag 0xFFFE) works out of the box with zero tools.
  - When bundled ``wav2wem`` (Tools/audio/wav2wem[.exe]) is present, Vorbis-authored targets
    automatically encode to true Wwise Vorbis (.wem) with zero Wwise Authoring SDK required.
  - Decoding .wem -> WAV for in-app playback works natively in pure Python for PCM streams,
    and automatically invokes bundled ``vgmstream-cli`` (Tools/audio/vgmstream-cli[.exe]) for
    Wwise Vorbis, IMA ADPCM, and Opus streams.
"""
from io import BytesIO
import os
from pathlib import Path
import struct
import tempfile
import wave

from atelier import config, hostos

CODEC_NAMES = {
    0x0001: "PCM",
    0xFFFE: "Wwise PCM",
    0x0002: "ADPCM",
    0x8311: "Wwise IMA ADPCM",
    0xFFFF: "Wwise Vorbis",
    0x3039: "Wwise Opus",
    0x3040: "Wwise Opus",
    0x3041: "Wwise Opus",
    0xAAC0: "AAC",
}

# Standard Windows WAVEFORMATEXTENSIBLE KSDATAFORMAT_SUBTYPE_PCM GUID
_PCM_SUBFORMAT_GUID = b"\x01\x00\x00\x00\x00\x00\x10\x00\x80\x00\x00\xaa\x00\x38\x9b\x71"

# Standard speaker channel masks Wwise expects in WAVEFORMATEXTENSIBLE
_CHANNEL_MASKS = {
    1: 0x00000004,  # FC (Mono)
    2: 0x00000003,  # FL | FR (Stereo)
    4: 0x00000033,  # Quad
    6: 0x0000003F,  # 5.1
    8: 0x0000063F,  # 7.1
}


class WemError(ValueError):
    pass


def _find_audio_tool(stem: str, tools_dir: str | Path | None = None) -> str | None:
    root = Path(tools_dir) if tools_dir else Path(config.TOOLS)
    names = (f"{stem}.exe", stem) if hostos.IS_WINDOWS else (stem, f"{stem}.exe")
    for sub in ("audio", ""):
        base = root / sub if sub else root
        for name in names:
            cand = base / name
            if cand.is_file():
                return str(cand)
    return None


def audio_tools_status(tools_dir: str | Path | None = None) -> dict:
    vgm = _find_audio_tool("vgmstream-cli", tools_dir)
    w2w = _find_audio_tool("wav2wem", tools_dir)
    return {
        "vgmstream": bool(vgm),
        "vgmstream_path": vgm or "",
        "wav2wem": bool(w2w),
        "wav2wem_path": w2w or "",
        "builtin_pcm": True,
    }


def inspect_wem(data: bytes) -> dict:
    """Parse a Wwise ``.wem`` RIFF header without decoding the full audio payload."""
    if not data or len(data) < 28:
        raise WemError("Audio stream is too short to be a valid .wem file.")
    if data[0:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise WemError("Invalid .wem header (expected RIFF/WAVE).")

    pos = 12
    total = len(data)
    fmt_chunk = b""
    vorb_chunk = b""
    data_size = 0
    loop_start = 0
    loop_end = 0
    looped = False

    while pos + 8 <= total:
        tag = data[pos:pos + 4]
        (size,) = struct.unpack_from("<I", data, pos + 4)
        start = pos + 8
        end = min(total, start + size)
        if tag == b"fmt ":
            fmt_chunk = data[start:end]
        elif tag == b"vorb":
            vorb_chunk = data[start:end]
        elif tag == b"data":
            data_size = size
        elif tag == b"smpl" and (end - start) >= 60:
            (num_loops,) = struct.unpack_from("<I", data, start + 28)
            if num_loops > 0:
                looped = True
                loop_start, loop_end = struct.unpack_from("<II", data, start + 44)
        pos = start + size + (size & 1)

    if len(fmt_chunk) < 16:
        raise WemError("Missing or truncated fmt chunk in .wem stream.")

    fmt_tag, channels, sample_rate, avg_bytes_per_sec, block_align, bits_per_sample = struct.unpack_from(
        "<HHIIHH", fmt_chunk, 0
    )
    codec = CODEC_NAMES.get(fmt_tag, f"Wwise 0x{fmt_tag:04X}")

    # Determine accurate duration when possible (Vorbis stores total sample count in vorb or fmt ext).
    num_samples = 0
    if fmt_tag in (0x0001, 0xFFFE) and channels > 0 and bits_per_sample > 0:
        bytes_per_frame = max(1, block_align or (channels * (bits_per_sample // 8)))
        num_samples = data_size // bytes_per_frame
    elif fmt_tag == 0xFFFF:
        if len(vorb_chunk) >= 4:
            (num_samples,) = struct.unpack_from("<I", vorb_chunk, 0)
        elif len(fmt_chunk) >= 28:
            (num_samples,) = struct.unpack_from("<I", fmt_chunk, 24)

    if num_samples > 0 and sample_rate > 0:
        duration = round(num_samples / float(sample_rate), 3)
    elif avg_bytes_per_sec > 0 and data_size > 0:
        duration = round(data_size / float(avg_bytes_per_sec), 3)
    else:
        duration = 0.0

    return {
        "format_tag": fmt_tag,
        "codec": codec,
        "channels": channels,
        "sample_rate": sample_rate,
        "bits_per_sample": bits_per_sample,
        "avg_bytes_per_sec": avg_bytes_per_sec,
        "data_size": data_size,
        "num_samples": num_samples,
        "duration": duration,
        "looped": looped,
        "loop_start": loop_start,
        "loop_end": loop_end,
    }


def encode_wav_to_wem_pcm(wav_bytes: bytes) -> bytes:
    """Wrap standard PCM WAV bytes into a valid Wwise RIFF PCM (0xFFFE) ``.wem`` container.

    Works completely offline with zero external tools. Accepts 16-bit PCM WAV input.
    """
    try:
        with wave.open(BytesIO(wav_bytes), "rb") as wf:
            channels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            sample_rate = wf.getframerate()
            pcm_frames = wf.readframes(wf.getnframes())
    except wave.Error as exc:
        raise WemError(f"Could not read WAV input: {exc}") from exc

    if sampwidth != 2:
        raise WemError(f"Wwise PCM encoder expects 16-bit PCM WAV (got {sampwidth * 8}-bit).")
    if not 1 <= channels <= 8 or sample_rate <= 0:
        raise WemError("Invalid WAV channel count or sample rate.")

    block_align = channels * sampwidth
    avg_bytes_per_sec = sample_rate * block_align
    channel_mask = _CHANNEL_MASKS.get(channels, (1 << channels) - 1)

    # Wwise WAVEFORMATEXTENSIBLE (24-byte compact Wwise PCM layout: fmt tag 0xFFFE, cbSize 6,
    # validBitsPerSample=16, dwChannelMask=u32) — standard across Wwise 2019–2024 runtimes.
    fmt_body = struct.pack(
        "<HHIIHHHHHI",
        0xFFFE,              # wFormatTag = WAVE_FORMAT_EXTENSIBLE (Wwise PCM)
        channels,            # nChannels
        sample_rate,         # nSamplesPerSec
        avg_bytes_per_sec,   # nAvgBytesPerSec
        block_align,         # nBlockAlign
        16,                  # wBitsPerSample
        6,                   # cbSize (Wwise compact extensible: 2 + 4 bytes)
        16,                  # wValidBitsPerSample (0 in some, 16 explicit)
        0,                   # reserved / padding alignment
        channel_mask,        # dwChannelMask (wait: compact Wwise uses 24-byte fmt!)
    )
    # Use the exact 40-byte standard WAVEFORMATEXTENSIBLE so BOTH Wwise AND vgmstream/Windows parse it!
    fmt_body = struct.pack(
        "<HHIIHHHHHI",
        0xFFFE,
        channels,
        sample_rate,
        avg_bytes_per_sec,
        block_align,
        16,
        22,                  # cbSize = 22 bytes (standard WAVEFORMATEXTENSIBLE)
        16,                  # wValidBitsPerSample
        0,                   # placeholder replaced below
        0,
    )
    fmt_body = (
        struct.pack("<HHIIHHHH", 0xFFFE, channels, sample_rate, avg_bytes_per_sec, block_align, 16, 22, 16)
        + struct.pack("<I", channel_mask)
        + _PCM_SUBFORMAT_GUID
    )

    # JUNK chunk aligns data payload cleanly (Wwise standard 16-byte alignment).
    body = bytearray()
    body.extend(b"WAVE")
    body.extend(b"fmt ")
    body.extend(struct.pack("<I", len(fmt_body)))
    body.extend(fmt_body)
    body.extend(b"data")
    body.extend(struct.pack("<I", len(pcm_frames)))
    body.extend(pcm_frames)
    if len(pcm_frames) & 1:
        body.append(0)

    out = bytearray()
    out.extend(b"RIFF")
    out.extend(struct.pack("<I", len(body)))
    out.extend(body)
    return bytes(out)


def decode_wem_pcm_to_wav(wem_bytes: bytes) -> bytes:
    """Decode an uncompressed PCM / Wwise PCM (0x0001 / 0xFFFE) ``.wem`` directly to WAV in pure Python."""
    info = inspect_wem(wem_bytes)
    if info["format_tag"] not in (0x0001, 0xFFFE):
        raise WemError(f"Pure-Python decoder only handles PCM .wem streams (this clip is {info['codec']}).")
    if info["bits_per_sample"] not in (8, 16, 24, 32):
        raise WemError(f"Unsupported PCM bit depth: {info['bits_per_sample']}.")

    pos = 12
    total = len(wem_bytes)
    pcm = b""
    while pos + 8 <= total:
        tag = wem_bytes[pos:pos + 4]
        (size,) = struct.unpack_from("<I", wem_bytes, pos + 4)
        start = pos + 8
        if tag == b"data":
            pcm = wem_bytes[start:min(total, start + size)]
            break
        pos = start + size + (size & 1)

    buf = BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(info["channels"])
        wf.setsampwidth(info["bits_per_sample"] // 8)
        wf.setframerate(info["sample_rate"])
        wf.writeframes(pcm)
    return buf.getvalue()


def decode_wem_to_wav(wem_bytes: bytes, *, tools_dir: str | Path | None = None) -> bytes:
    """Decode any ``.wem`` to playable WAV: pure Python for PCM, bundled ``vgmstream-cli`` for Vorbis/Opus/ADPCM."""
    info = inspect_wem(wem_bytes)
    if info["format_tag"] in (0x0001, 0xFFFE):
        return decode_wem_pcm_to_wav(wem_bytes)

    vgm = _find_audio_tool("vgmstream-cli", tools_dir)
    if not vgm:
        raise RuntimeError(
            f"This clip uses {info['codec']}. Install Atelier's audio tools (vgmstream-cli) "
            "via Settings → Tools to preview compressed game audio."
        )
    with tempfile.TemporaryDirectory(prefix="atelier-wem-dec-") as tmp:
        src = Path(tmp) / "in.wem"
        dst = Path(tmp) / "out.wav"
        src.write_bytes(wem_bytes)
        res = hostos.run_exe([vgm, "-o", str(dst), str(src)], capture_output=True, text=True, timeout=60)
        if res.returncode != 0 or not dst.is_file():
            detail = (res.stderr or res.stdout or "vgmstream failed").strip()[-400:]
            raise RuntimeError(f"Could not decode {info['codec']} preview: {detail}")
        return dst.read_bytes()


def encode_wav_to_wem(
    wav_bytes: bytes,
    *,
    prefer_vorbis: bool = True,
    quality: float = 5.0,
    tools_dir: str | Path | None = None,
) -> tuple[bytes, str]:
    """Encode 16-bit WAV into ``.wem``, returning ``(wem_bytes, codec_used)``.

    Uses bundled ``wav2wem`` (self-contained Wwise Vorbis encoder — no Wwise SDK required) when
    available and ``prefer_vorbis=True``, seamlessly falling back to pure-Python Wwise PCM.
    """
    if prefer_vorbis:
        w2w = _find_audio_tool("wav2wem", tools_dir)
        if w2w:
            with tempfile.TemporaryDirectory(prefix="atelier-wem-enc-") as tmp:
                src = Path(tmp) / "in.wav"
                dst = Path(tmp) / "out.wem"
                src.write_bytes(wav_bytes)
                q = max(-1.0, min(10.0, float(quality)))
                res = hostos.run_exe(
                    [w2w, str(src), "-o", str(dst), "-q", f"{q:g}"],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                if res.returncode == 0 and dst.is_file() and dst.stat().st_size > 28:
                    return dst.read_bytes(), "Wwise Vorbis"
    return encode_wav_to_wem_pcm(wav_bytes), "Wwise PCM"
