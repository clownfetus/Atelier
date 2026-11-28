"""Audio & Voice Line Studio backend: Wwise bank discovery, subtitle linking, preview & mod export.

Project edit layout (first-class Mod tray entries):
  - ``<project>/<audio_rel>.audio.json`` — sidecar recording target pak/bank/media_id, DSP settings
    (LUFS match, gain dB, trim, fade), friendly label and linked subtitle.
  - ``<project>/<audio_rel>.wav``        — user's uploaded PCM WAV source audio.

Subtitle notes (tags without replacing audio) persist separately in
``<project>/.atelier/audio_subtitles.json`` so tagging clips never pollutes the Mod tray.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import threading

from atelier import config, jobs
from atelier.handlers import audio_dsp, audio_subtitles, wwise_bnk, wwise_pak, wwise_wem
from atelier.storage import atomic_json

_HERO_ID_RE = re.compile(r"(?<!\d)(10\d{2})(?!\d)")
_CACHE_LOCK = threading.Lock()
_CATALOG_CACHE = {"key": None, "data": None}
_SUB_CACHE = {"key": None, "index": None}
_CUSTOM_SUBS_FILE = os.path.join(".atelier", "audio_subtitles.json")

DEFAULT_DSP = {
    "match_lufs": True,
    "gain_db": 0.0,
    "trim_start": 0.0,
    "trim_end": 0.0,
    "fade_in_ms": 0.0,
    "fade_out_ms": 15.0,
    "prefer_vorbis": True,
}


def _hero_name(hero_id: str) -> str:
    if not hero_id:
        return ""
    try:
        from atelier.handlers import skinnames
        fn = getattr(skinnames, "char_name", None)
        if callable(fn):
            name = fn(hero_id)
            if name:
                return name
    except Exception:
        pass
    return f"Hero {hero_id}"


def _classify_bank(path_str: str) -> tuple[str, str, str]:
    """Return ``(category, hero_id, hero_label)`` for a Wwise bank or stream path."""
    low = path_str.replace("\\", "/").lower()
    base = low.rsplit("/", 1)[-1]
    m = _HERO_ID_RE.search(base) or _HERO_ID_RE.search(low)
    if m:
        hid = m.group(1)
        return "hero", hid, _hero_name(hid)
    if any(tok in low for tok in ("ui", "announcer", "battle_ui", "hud", "kill", "ko_", "system")):
        return "ui", "", "UI & Announcer"
    if any(tok in low for tok in ("music", "bgm", "mvp", "lobby", "map", "ambient", "env")):
        return "music", "", "Music & Maps"
    return "other", "", "Other banks"


def _pak_files(paks_dir: str | Path | None = None) -> list[Path]:
    root = Path(paks_dir if paks_dir is not None else config.PAKS)
    if not str(root) or not root.is_dir():
        return []
    # Sort ASCII ascending so base paks come before _P patch paks (later overrides earlier).
    paks = [p for p in root.iterdir() if p.is_file() and p.suffix.lower() == ".pak"]
    return sorted(paks, key=lambda p: p.name.casefold())


def _pak_sig(paks: list[Path]) -> str:
    parts = []
    for p in paks:
        try:
            st = p.stat()
            parts.append(f"{p.name}:{st.st_size}:{st.st_mtime_ns}")
        except OSError:
            pass
    return "|".join(parts)


def load_custom_subtitles(project_dir: str | Path | None = None) -> dict[str, dict]:
    merged: dict[str, dict] = {}
    # Optional global community subtitle map under Tools/audio/subtitles.json
    global_path = Path(config.TOOLS) / "audio" / "subtitles.json"
    for path in (global_path, Path(project_dir or config.get_import_root()) / _CUSTOM_SUBS_FILE):
        if path.is_file():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    merged.update(raw)
            except Exception:
                pass
    return merged


def save_custom_subtitle(media_id: str, *, subtitle: str = "", label: str = "", event: str = "", project_dir: str | Path | None = None) -> dict:
    sid = str(media_id or "").replace(".wem", "").strip()
    if not sid:
        raise ValueError("Missing audio media ID.")
    root = Path(project_dir or config.get_import_root())
    path = root / _CUSTOM_SUBS_FILE
    existing = {}
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            existing = {}
    if not isinstance(existing, dict):
        existing = {}
    entry = {
        "subtitle": str(subtitle or "").strip()[:400],
        "label": str(label or "").strip()[:120],
        "event": str(event or "").strip()[:120],
    }
    if not any(entry.values()):
        existing.pop(sid, None)
    else:
        existing[sid] = entry
    atomic_json(path, existing)
    return {"ok": True, "media_id": sid, **entry}


def import_subtitles(raw_text: str, filename: str = "", project_dir: str | Path | None = None) -> dict:
    parsed = audio_subtitles.parse_subtitle_map(raw_text, filename)
    if not parsed:
        raise ValueError("No valid subtitle entries found. Expected JSON or CSV/TSV with media_id and subtitle columns.")
    root = Path(project_dir or config.get_import_root())
    path = root / _CUSTOM_SUBS_FILE
    existing = {}
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            existing = {}
    if not isinstance(existing, dict):
        existing = {}
    existing.update(parsed)
    atomic_json(path, existing)
    return {"ok": True, "imported_count": len(parsed), "total_custom": len(existing)}


def scan_audio_catalog(paks_dir: str | Path | None = None) -> dict:
    """Scan game ``.pak`` archives for Wwise ``.bnk`` SoundBanks, loose ``.wem`` streams, and metadata."""
    paks = _pak_files(paks_dir)
    sig = _pak_sig(paks)
    with _CACHE_LOCK:
        if _CATALOG_CACHE["key"] == sig and _CATALOG_CACHE["data"] is not None:
            return _CATALOG_CACHE["data"]

    banks: dict[str, dict] = {}
    streams: dict[str, dict] = {}
    info_files: list[dict] = []
    locres_files: list[dict] = []
    warnings: list[str] = []

    for pak_path in paks:
        try:
            reader = wwise_pak.PakReader(pak_path)
        except Exception:
            # Skip non-readable or IoStore stub paks silently (IoStore .pak stubs often have 0 loose entries).
            continue
        for entry_name in reader.names:
            low = entry_name.replace("\\", "/").lower()
            if low.endswith(".bnk"):
                stem = entry_name.replace("\\", "/").rsplit("/", 1)[-1][:-4]
                cat, hid, group_label = _classify_bank(entry_name)
                key = low
                banks[key] = {
                    "bank_rel": entry_name.replace("\\", "/"),
                    "stem": stem,
                    "pak_path": str(pak_path),
                    "pak_name": pak_path.name,
                    "mount": reader.mount,
                    "category": cat,
                    "hero_id": hid,
                    "group_label": group_label,
                }
            elif low.endswith(".wem"):
                stem = entry_name.replace("\\", "/").rsplit("/", 1)[-1][:-4]
                cat, hid, group_label = _classify_bank(entry_name)
                streams[low] = {
                    "game_rel": f"Audio/Streams/{stem}",
                    "pak_entry": entry_name.replace("\\", "/"),
                    "media_id": stem,
                    "pak_path": str(pak_path),
                    "pak_name": pak_path.name,
                    "mount": reader.mount,
                    "category": cat,
                    "hero_id": hid,
                    "group_label": group_label,
                }
            elif low.endswith(("soundbanksinfo.json", "soundbanksinfo.xml")):
                info_files.append({"pak_path": str(pak_path), "entry": entry_name})
            elif low.endswith(".locres"):
                locres_files.append({"pak_path": str(pak_path), "entry": entry_name})

    bank_list = sorted(banks.values(), key=lambda b: (b["category"] != "hero", b["group_label"].casefold(), b["stem"].casefold()))
    stream_list = sorted(streams.values(), key=lambda s: (s["category"] != "hero", s["group_label"].casefold(), s["media_id"].casefold()))
    data = {
        "ok": True,
        "banks": bank_list,
        "streams": stream_list,
        "info_files": info_files,
        "locres_files": locres_files,
        "warnings": warnings,
        "tools": wwise_wem.audio_tools_status(),
    }
    with _CACHE_LOCK:
        _CATALOG_CACHE["key"] = sig
        _CATALOG_CACHE["data"] = data
    return data


def subtitle_index(paks_dir: str | Path | None = None, project_dir: str | Path | None = None) -> audio_subtitles.SubtitleIndex:
    """Build or reuse cached ``.locres`` + ``SoundbanksInfo`` subtitle resolver merged with custom tags."""
    cat = scan_audio_catalog(paks_dir)
    sig = _pak_sig(_pak_files(paks_dir))
    base_locres = {}
    base_bank_info = {}

    with _CACHE_LOCK:
        cached = _SUB_CACHE["index"] if _SUB_CACHE["key"] == sig else None

    if cached is None:
        # Prefer English localization first, then any other available .locres as fallback.
        ordered_loc = sorted(
            cat.get("locres_files") or [],
            key=lambda item: (0 if "/en/" in item["entry"].lower() or item["entry"].lower().endswith("/en.locres") else 1, item["entry"].lower()),
        )
        for item in ordered_loc[:3]:
            try:
                raw = wwise_pak.PakReader(item["pak_path"]).read_file(item["entry"])
                parsed = audio_subtitles.parse_locres(raw)
                for ns, kv in parsed.items():
                    base_locres.setdefault(ns, {}).update(kv)
            except Exception:
                continue
        for item in (cat.get("info_files") or [])[:4]:
            try:
                raw = wwise_pak.PakReader(item["pak_path"]).read_file(item["entry"]).decode("utf-8", errors="ignore")
                parsed = (
                    audio_subtitles.parse_soundbanks_info_json(raw)
                    if item["entry"].lower().endswith(".json")
                    else audio_subtitles.parse_soundbanks_info_xml(raw)
                )
                base_bank_info.update(parsed)
            except Exception:
                continue
        with _CACHE_LOCK:
            _SUB_CACHE["key"] = sig
            _SUB_CACHE["index"] = (base_locres, base_bank_info)
    else:
        base_locres, base_bank_info = cached

    return audio_subtitles.SubtitleIndex(base_locres, base_bank_info, load_custom_subtitles(project_dir))


def _project_audio_paths(game_rel: str, project_dir: str | Path | None = None) -> tuple[Path, Path]:
    base = config.project_base(game_rel, str(project_dir) if project_dir else None)
    return Path(base + ".audio.json"), Path(base + ".wav")


def _edited_map(project_dir: str | Path | None = None) -> dict[str, dict]:
    root = Path(project_dir or config.get_import_root())
    out: dict[str, dict] = {}
    if not root.is_dir():
        return out
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in (".atelier", ".atelier-trash")]
        for fname in files:
            if not fname.endswith(".audio.json"):
                continue
            fpath = Path(dirpath) / fname
            try:
                meta = json.loads(fpath.read_text(encoding="utf-8"))
                gr = meta.get("game_rel")
                if gr:
                    out[gr.casefold()] = meta
            except Exception:
                continue
    return out


def audio_game_rel_for_bank_clip(bank_stem: str, media_id: int | str) -> str:
    return f"Audio/Banks/{bank_stem}/{media_id}"


def list_bank_clips(bank_rel: str, *, paks_dir: str | Path | None = None, project_dir: str | Path | None = None) -> dict:
    """List every embedded ``.wem`` clip in a SoundBank with codec, duration, subtitle & edit status."""
    cat = scan_audio_catalog(paks_dir)
    low = (bank_rel or "").replace("\\", "/").lower()
    bank = next((b for b in cat["banks"] if b["bank_rel"].lower() == low or b["stem"].lower() == low), None)
    if bank is None:
        raise LookupError(f"SoundBank '{bank_rel}' was not found in your game paks.")

    bnk_bytes = wwise_pak.PakReader(bank["pak_path"]).read_file(bank["bank_rel"])
    parsed = wwise_bnk.parse_bnk(bnk_bytes)
    subs = subtitle_index(paks_dir, project_dir)
    edited = _edited_map(project_dir)

    clips = []
    for entry in parsed["media"]:
        mid = entry["media_id"]
        gr = audio_game_rel_for_bank_clip(bank["stem"], mid)
        wem_info = {"codec": "Unknown", "duration": 0.0, "sample_rate": 48000, "channels": 2}
        if entry["valid"]:
            try:
                wem_bytes = wwise_bnk.extract_wem(bnk_bytes, mid)
                wem_info = wwise_wem.inspect_wem(wem_bytes)
            except Exception:
                pass
        sub_info = subs.resolve(mid)
        ed = edited.get(gr.casefold())
        clips.append({
            "game_rel": gr,
            "media_id": str(mid),
            "bank_rel": bank["bank_rel"],
            "bank_stem": bank["stem"],
            "hero_id": bank["hero_id"],
            "group_label": bank["group_label"],
            "size": entry["size"],
            "codec": wem_info.get("codec", "Unknown"),
            "duration": wem_info.get("duration", 0.0),
            "sample_rate": wem_info.get("sample_rate", 48000),
            "channels": wem_info.get("channels", 2),
            "subtitle": (ed or {}).get("subtitle") or sub_info.get("subtitle", ""),
            "label": (ed or {}).get("label") or sub_info.get("label", ""),
            "event": sub_info.get("event", ""),
            "subtitle_source": sub_info.get("source", ""),
            "edited": ed is not None,
        })
    return {
        "ok": True,
        "bank": bank,
        "clip_count": len(clips),
        "clips": clips,
        "tools": wwise_wem.audio_tools_status(),
    }


def _resolve_clip_source(game_rel: str, *, paks_dir: str | Path | None = None, project_dir: str | Path | None = None) -> dict:
    """Locate original ``.wem`` bytes and target metadata for ``game_rel``."""
    config.validate_game_rel(game_rel)
    norm = game_rel.replace("\\", "/").strip("/")
    meta_path, wav_path = _project_audio_paths(norm, project_dir)
    saved_meta = None
    if meta_path.is_file():
        try:
            saved_meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            saved_meta = None

    cat = scan_audio_catalog(paks_dir)
    parts = norm.split("/")
    if len(parts) >= 4 and parts[0].lower() == "audio" and parts[1].lower() == "banks":
        bank_stem, raw_mid = parts[2], parts[3]
        bank = next((b for b in cat["banks"] if b["stem"].casefold() == bank_stem.casefold()), None)
        if bank is None and saved_meta and saved_meta.get("bank_rel"):
            bank = next((b for b in cat["banks"] if b["bank_rel"].casefold() == saved_meta["bank_rel"].casefold()), None)
        if bank is None:
            raise LookupError(f"SoundBank '{bank_stem}' not found in game files.")
        mid = int(raw_mid)
        bnk_bytes = wwise_pak.PakReader(bank["pak_path"]).read_file(bank["bank_rel"])
        wem_bytes = wwise_bnk.extract_wem(bnk_bytes, mid)
        return {
            "kind": "bank",
            "game_rel": norm,
            "media_id": str(mid),
            "bank_rel": bank["bank_rel"],
            "bank_stem": bank["stem"],
            "pak_path": bank["pak_path"],
            "mount": bank["mount"],
            "hero_id": bank["hero_id"],
            "group_label": bank["group_label"],
            "wem_bytes": wem_bytes,
            "saved_meta": saved_meta,
            "wav_path": wav_path,
        }

    if len(parts) >= 3 and parts[0].lower() == "audio" and parts[1].lower() == "streams":
        mid = parts[2]
        stream = next((s for s in cat["streams"] if s["media_id"].casefold() == mid.casefold()), None)
        if stream is None:
            raise LookupError(f"Audio stream '{mid}' not found in game files.")
        wem_bytes = wwise_pak.PakReader(stream["pak_path"]).read_file(stream["pak_entry"])
        return {
            "kind": "stream",
            "game_rel": norm,
            "media_id": str(mid),
            "pak_entry": stream["pak_entry"],
            "pak_path": stream["pak_path"],
            "mount": stream["mount"],
            "hero_id": stream["hero_id"],
            "group_label": stream["group_label"],
            "wem_bytes": wem_bytes,
            "saved_meta": saved_meta,
            "wav_path": wav_path,
        }

    raise ValueError(f"Unrecognised audio asset path: {game_rel}")


def _decode_original_wav_cached(wem_bytes: bytes, *, tools_dir: str | Path | None = None) -> bytes:
    digest = hashlib.sha256(wem_bytes).hexdigest()[:24]
    cache_dir = Path(config._CACHE) / "audio_preview"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / f"{digest}.wav"
    if cached.is_file():
        return cached.read_bytes()
    wav_bytes = wwise_wem.decode_wem_to_wav(wem_bytes, tools_dir=tools_dir)
    tmp = cached.with_suffix(".wav.tmp")
    tmp.write_bytes(wav_bytes)
    os.replace(tmp, cached)
    return wav_bytes


def inspect_clip(game_rel: str, *, paks_dir: str | Path | None = None, project_dir: str | Path | None = None, tools_dir: str | Path | None = None) -> dict:
    """Return full studio metadata, original & edited waveform envelopes, subtitle, and DSP settings."""
    src = _resolve_clip_source(game_rel, paks_dir=paks_dir, project_dir=project_dir)
    wem_info = wwise_wem.inspect_wem(src["wem_bytes"])
    subs = subtitle_index(paks_dir, project_dir)
    sub_info = subs.resolve(src["media_id"])

    orig_wave = None
    orig_error = ""
    try:
        orig_wav = _decode_original_wav_cached(src["wem_bytes"], tools_dir=tools_dir)
        orig_wave = audio_dsp.waveform_peaks(orig_wav)
    except Exception as exc:
        orig_error = str(exc)

    edited_wave = None
    saved = src["saved_meta"]
    dsp_settings = {**DEFAULT_DSP, **((saved or {}).get("dsp") or {})}
    if saved and src["wav_path"].is_file():
        try:
            raw_edit = src["wav_path"].read_bytes()
            target_lufs = orig_wave["lufs"] if (dsp_settings.get("match_lufs") and orig_wave) else None
            proc_wav, _meta = audio_dsp.process_audio(
                raw_edit,
                target_rate=wem_info["sample_rate"] or 48000,
                target_channels=wem_info["channels"] or 2,
                trim_start=dsp_settings.get("trim_start", 0.0),
                trim_end=dsp_settings.get("trim_end", 0.0),
                fade_in_ms=dsp_settings.get("fade_in_ms", 0.0),
                fade_out_ms=dsp_settings.get("fade_out_ms", 15.0),
                match_lufs=target_lufs,
                gain_db=dsp_settings.get("gain_db", 0.0),
            )
            edited_wave = audio_dsp.waveform_peaks(proc_wav)
        except Exception:
            pass

    return {
        "ok": True,
        "game_rel": src["game_rel"],
        "media_id": src["media_id"],
        "kind": src["kind"],
        "bank_rel": src.get("bank_rel", ""),
        "bank_stem": src.get("bank_stem", ""),
        "hero_id": src.get("hero_id", ""),
        "group_label": src.get("group_label", ""),
        "wem": wem_info,
        "original_wave": orig_wave,
        "original_error": orig_error,
        "edited": bool(saved and src["wav_path"].is_file()),
        "edited_wave": edited_wave,
        "dsp": dsp_settings,
        "subtitle": (saved or {}).get("subtitle") or sub_info.get("subtitle", ""),
        "label": (saved or {}).get("label") or sub_info.get("label", ""),
        "event": sub_info.get("event", ""),
        "subtitle_source": sub_info.get("source", ""),
        "tools": wwise_wem.audio_tools_status(tools_dir),
    }


def clip_wav_bytes(game_rel: str, *, version: str = "original", paks_dir: str | Path | None = None, project_dir: str | Path | None = None, tools_dir: str | Path | None = None) -> bytes:
    """Return playable WAV bytes for ``original`` or processed ``edited`` playback."""
    src = _resolve_clip_source(game_rel, paks_dir=paks_dir, project_dir=project_dir)
    if version == "edited":
        if not src["wav_path"].is_file() or not src["saved_meta"]:
            raise FileNotFoundError("No edited audio saved for this clip yet.")
        wem_info = wwise_wem.inspect_wem(src["wem_bytes"])
        dsp = {**DEFAULT_DSP, **(src["saved_meta"].get("dsp") or {})}
        target_lufs = None
        if dsp.get("match_lufs"):
            try:
                orig_wav = _decode_original_wav_cached(src["wem_bytes"], tools_dir=tools_dir)
                target_lufs = audio_dsp.waveform_peaks(orig_wav)["lufs"]
            except Exception:
                target_lufs = None
        proc_wav, _ = audio_dsp.process_audio(
            src["wav_path"].read_bytes(),
            target_rate=wem_info["sample_rate"] or 48000,
            target_channels=wem_info["channels"] or 2,
            trim_start=dsp.get("trim_start", 0.0),
            trim_end=dsp.get("trim_end", 0.0),
            fade_in_ms=dsp.get("fade_in_ms", 0.0),
            fade_out_ms=dsp.get("fade_out_ms", 15.0),
            match_lufs=target_lufs,
            gain_db=dsp.get("gain_db", 0.0),
        )
        return proc_wav
    return _decode_original_wav_cached(src["wem_bytes"], tools_dir=tools_dir)


def save_audio_edit(
    game_rel: str,
    *,
    wav_bytes: bytes | None = None,
    wav_b64: str | None = None,
    dsp: dict | None = None,
    label: str | None = None,
    subtitle: str | None = None,
    paks_dir: str | Path | None = None,
    project_dir: str | Path | None = None,
) -> dict:
    """Save an uploaded replacement WAV and DSP recipe for an audio clip into the active project."""
    src = _resolve_clip_source(game_rel, paks_dir=paks_dir, project_dir=project_dir)
    meta_path, wav_path = _project_audio_paths(src["game_rel"], project_dir)
    meta_path.parent.mkdir(parents=True, exist_ok=True)

    raw_wav = wav_bytes
    if raw_wav is None and wav_b64:
        raw_wav = base64.b64decode(wav_b64)
    if raw_wav is not None:
        # Validate WAV structure before writing to disk.
        audio_dsp.read_wav_float(raw_wav)
        tmp = wav_path.with_suffix(".wav.tmp")
        tmp.write_bytes(raw_wav)
        os.replace(tmp, wav_path)
    elif not wav_path.is_file():
        raise ValueError("Choose or drop an audio file before saving.")

    clean_dsp = {
        **DEFAULT_DSP,
        **((src["saved_meta"] or {}).get("dsp") or {}),
        **(dsp or {}),
    }
    meta = {
        "version": 1,
        "game_rel": src["game_rel"],
        "kind": src["kind"],
        "media_id": src["media_id"],
        "bank_rel": src.get("bank_rel", ""),
        "bank_stem": src.get("bank_stem", ""),
        "pak_entry": src.get("pak_entry", ""),
        "mount": src.get("mount", "../../../"),
        "hero_id": src.get("hero_id", ""),
        "group_label": src.get("group_label", ""),
        "dsp": {
            "match_lufs": bool(clean_dsp.get("match_lufs", True)),
            "gain_db": max(-24.0, min(24.0, float(clean_dsp.get("gain_db", 0.0)))),
            "trim_start": max(0.0, float(clean_dsp.get("trim_start", 0.0))),
            "trim_end": max(0.0, float(clean_dsp.get("trim_end", 0.0))),
            "fade_in_ms": max(0.0, min(5000.0, float(clean_dsp.get("fade_in_ms", 0.0)))),
            "fade_out_ms": max(0.0, min(5000.0, float(clean_dsp.get("fade_out_ms", 15.0)))),
            "prefer_vorbis": bool(clean_dsp.get("prefer_vorbis", True)),
        },
        "label": str(label if label is not None else ((src["saved_meta"] or {}).get("label") or "")).strip()[:120],
        "subtitle": str(subtitle if subtitle is not None else ((src["saved_meta"] or {}).get("subtitle") or "")).strip()[:400],
    }
    atomic_json(meta_path, meta)
    if meta["label"] or meta["subtitle"]:
        save_custom_subtitle(src["media_id"], subtitle=meta["subtitle"], label=meta["label"], project_dir=project_dir)
    return {"ok": True, "game_rel": src["game_rel"], "meta": meta}


def reset_audio_edit(game_rel: str, *, project_dir: str | Path | None = None) -> dict:
    config.validate_game_rel(game_rel)
    meta_path, wav_path = _project_audio_paths(game_rel, project_dir)
    for p in (meta_path, wav_path):
        try:
            p.unlink(missing_ok=True)
        except OSError:
            pass
    return {"ok": True, "game_rel": game_rel}


def build_audio_pak(
    audio_items: list[str],
    out_pak_path: str | Path,
    *,
    paks_dir: str | Path | None = None,
    project_dir: str | Path | None = None,
    tools_dir: str | Path | None = None,
) -> dict:
    """Process, encode, repack SoundBanks, and package all selected audio edits into one UE5 v11 ``.pak``."""
    applied: list[str] = []
    skipped: list[str] = []
    bank_groups: dict[str, dict] = {}
    pak_payloads: dict[str, bytes] = {}
    mount = "../../../"

    for gr in audio_items or []:
        jobs.checkpoint()
        try:
            src = _resolve_clip_source(gr, paks_dir=paks_dir, project_dir=project_dir)
            if not src["wav_path"].is_file() or not src["saved_meta"]:
                skipped.append(f"{os.path.basename(gr)}: replacement audio file missing")
                continue
            wem_info = wwise_wem.inspect_wem(src["wem_bytes"])
            dsp = {**DEFAULT_DSP, **(src["saved_meta"].get("dsp") or {})}
            target_lufs = None
            if dsp.get("match_lufs"):
                try:
                    orig_wav = _decode_original_wav_cached(src["wem_bytes"], tools_dir=tools_dir)
                    target_lufs = audio_dsp.waveform_peaks(orig_wav)["lufs"]
                except Exception:
                    target_lufs = None

            proc_wav, _dsp_meta = audio_dsp.process_audio(
                src["wav_path"].read_bytes(),
                target_rate=wem_info["sample_rate"] or 48000,
                target_channels=wem_info["channels"] or 2,
                trim_start=dsp.get("trim_start", 0.0),
                trim_end=dsp.get("trim_end", 0.0),
                fade_in_ms=dsp.get("fade_in_ms", 0.0),
                fade_out_ms=dsp.get("fade_out_ms", 15.0),
                match_lufs=target_lufs,
                gain_db=dsp.get("gain_db", 0.0),
            )
            prefer_vorbis = bool(dsp.get("prefer_vorbis", True)) and wem_info["format_tag"] == 0xFFFF
            wem_out, codec_used = wwise_wem.encode_wav_to_wem(proc_wav, prefer_vorbis=prefer_vorbis, tools_dir=tools_dir)
            mount = src.get("mount") or mount

            if src["kind"] == "bank":
                bkey = src["bank_rel"].casefold()
                grp = bank_groups.setdefault(bkey, {
                    "bank_rel": src["bank_rel"],
                    "pak_path": src["pak_path"],
                    "replacements": {},
                })
                grp["replacements"][int(src["media_id"])] = wem_out
                applied.append(f"audio:{src['bank_stem']}/{src['media_id']} ({codec_used})")
            else:
                pak_payloads[src["pak_entry"]] = wem_out
                applied.append(f"audio:{src['media_id']} ({codec_used})")
        except Exception as exc:
            skipped.append(f"{os.path.basename(gr)}: {exc}")

    for grp in bank_groups.values():
        jobs.checkpoint()
        try:
            orig_bnk = wwise_pak.PakReader(grp["pak_path"]).read_file(grp["bank_rel"])
            repacked = wwise_bnk.repack_bnk(orig_bnk, grp["replacements"])
            pak_payloads[grp["bank_rel"]] = repacked
        except Exception as exc:
            skipped.append(f"{grp['bank_rel']}: repack failed ({exc})")

    if not pak_payloads:
        return {"ok": False, "pak": None, "applied": applied, "skipped": skipped, "error": "No audio files staged."}

    pak_path = wwise_pak.write_loose_pak(out_pak_path, pak_payloads, mount=mount)
    return {"ok": True, "pak": pak_path, "applied": applied, "skipped": skipped}
