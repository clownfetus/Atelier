"""Pure-Python UE5 .locres subtitle reader and Wwise event/media-ID subtitle resolver.

Surfaces the associated spoken subtitle line right inside Audio Studio whenever it can be
resolved from:
  1. Wwise ``SoundbanksInfo.json`` / ``SoundbanksInfo.xml`` (event name <-> numeric media ID)
  2. Unreal Engine ``.locres`` (v1 / v2 / v3) localization tables (key -> English subtitle text)
  3. Project/user custom subtitle labels or imported community subtitle maps (JSON/CSV)
"""
import csv
from io import StringIO
import json
import re
import struct
import xml.etree.ElementTree as ET

_LOCRES_MAGIC = bytes.fromhex("0e147475674a03fc4a15909dc3377f1b")
_ALT_LOCRES_MAGIC = bytes.fromhex("0e147475674a03fc4b3b5603952ee7a1")  # alternate byte order check
_WORD_RE = re.compile(r"[a-z0-9]+")


def _read_fstring(data: bytes, pos: int) -> tuple[str, int]:
    if pos + 4 > len(data):
        raise ValueError("Truncated FString in .locres.")
    (length,) = struct.unpack_from("<i", data, pos)
    pos += 4
    if length == 0:
        return "", pos
    if length > 0:
        end = pos + length
        if end > len(data):
            raise ValueError("Truncated ANSI FString in .locres.")
        return data[pos:end].rstrip(b"\x00").decode("utf-8", errors="replace"), end
    byte_len = (-length) * 2
    end = pos + byte_len
    if end > len(data):
        raise ValueError("Truncated UTF-16LE FString in .locres.")
    return data[pos:end].decode("utf-16-le", errors="replace").rstrip("\x00"), end


def parse_locres(data: bytes) -> dict[str, dict[str, str]]:
    """Parse a UE4/UE5 ``.locres`` binary (versions 1, 2, or 3) into ``{namespace: {key: text}}``."""
    if not data or len(data) < 25:
        raise ValueError("Not a valid .locres file (too short).")
    if data[:16] not in (_LOCRES_MAGIC, _ALT_LOCRES_MAGIC):
        raise ValueError("Unrecognised .locres header magic.")

    version = data[16]
    if version not in (1, 2, 3):
        raise ValueError(f"Unsupported .locres version: {version}")

    (str_array_offset,) = struct.unpack_from("<q", data, 17)
    pos = 25

    # Read localized string table at str_array_offset
    if not (0 < str_array_offset < len(data)):
        raise ValueError("Invalid .locres localized string table offset.")
    s_pos = str_array_offset
    (str_count,) = struct.unpack_from("<I", data, s_pos)
    s_pos += 4
    strings: list[str] = []
    for _ in range(str_count):
        text, s_pos = _read_fstring(data, s_pos)
        if version >= 2:
            s_pos += 4  # i32 ref_count
        strings.append(text)

    if version >= 2:
        pos += 4  # u32 entries_count

    (ns_count,) = struct.unpack_from("<I", data, pos)
    pos += 4
    result: dict[str, dict[str, str]] = {}
    for _ in range(ns_count):
        if version >= 2:
            pos += 4  # u32 namespace hash
        ns_name, pos = _read_fstring(data, pos)
        (key_count,) = struct.unpack_from("<I", data, pos)
        pos += 4
        bucket = result.setdefault(ns_name, {})
        for _ in range(key_count):
            if version >= 2:
                pos += 4  # u32 key hash
            key_name, pos = _read_fstring(data, pos)
            pos += 4  # u32 source string hash
            (str_idx,) = struct.unpack_from("<i", data, pos)
            pos += 4
            if 0 <= str_idx < len(strings):
                bucket[key_name] = strings[str_idx]
    return result


def parse_soundbanks_info_json(text: str) -> dict[int, dict]:
    """Parse Wwise ``SoundbanksInfo.json`` into ``{media_id: {name, event, bank, language}}``."""
    doc = json.loads(text)
    root = doc.get("SoundBanksInfo", doc)
    out: dict[int, dict] = {}
    for bank in root.get("SoundBanks") or []:
        bank_name = bank.get("ShortName") or bank.get("Path") or ""
        lang = bank.get("Language") or ""
        for media in (bank.get("Media") or []) + (bank.get("IncludedMemoryFiles") or []) + (bank.get("ReferencedStreamedFiles") or []):
            try:
                mid = int(media.get("Id"))
            except (TypeError, ValueError):
                continue
            short = media.get("ShortName") or media.get("Path") or ""
            out.setdefault(mid, {"media_id": mid, "short_name": short, "bank": bank_name, "language": lang, "events": []})
        for ev in bank.get("Events") or []:
            ev_name = ev.get("Name") or ""
            for ref in ev.get("MediaRefs") or []:
                try:
                    mid = int(ref.get("Id"))
                except (TypeError, ValueError):
                    continue
                rec = out.setdefault(mid, {"media_id": mid, "short_name": "", "bank": bank_name, "language": lang, "events": []})
                if ev_name and ev_name not in rec["events"]:
                    rec["events"].append(ev_name)
    return out


def parse_soundbanks_info_xml(text: str) -> dict[int, dict]:
    """Parse Wwise ``SoundbanksInfo.xml`` into ``{media_id: {short_name, bank, language, events}}``."""
    root = ET.fromstring(text)
    out: dict[int, dict] = {}
    for bank in root.findall(".//SoundBank"):
        bank_name = (bank.findtext("ShortName") or bank.findtext("Path") or "").strip()
        lang = bank.attrib.get("Language") or (bank.findtext("Language") or "").strip()
        for file_el in bank.findall(".//File") + bank.findall(".//Media/File"):
            raw_id = file_el.attrib.get("Id")
            if not raw_id or not raw_id.isdigit():
                continue
            mid = int(raw_id)
            short = (file_el.findtext("ShortName") or file_el.findtext("Path") or "").strip()
            out.setdefault(mid, {"media_id": mid, "short_name": short, "bank": bank_name, "language": lang, "events": []})
        for ev in bank.findall(".//Event"):
            ev_name = ev.attrib.get("Name") or ""
            for ref in ev.findall(".//MediaRef") + ev.findall(".//File"):
                raw_id = ref.attrib.get("Id")
                if not raw_id or not raw_id.isdigit():
                    continue
                mid = int(raw_id)
                rec = out.setdefault(mid, {"media_id": mid, "short_name": "", "bank": bank_name, "language": lang, "events": []})
                if ev_name and ev_name not in rec["events"]:
                    rec["events"].append(ev_name)
    return out


def parse_subtitle_map(raw_text: str, filename: str = "") -> dict[str, dict]:
    """Import a community JSON or CSV/TSV mapping of ``media_id -> {subtitle, label, event}``."""
    low = (filename or "").lower()
    out: dict[str, dict] = {}
    stripped = raw_text.lstrip()
    if low.endswith(".json") or stripped.startswith(("{", "[")):
        data = json.loads(raw_text)
        if isinstance(data, dict):
            for k, v in data.items():
                if isinstance(v, str):
                    out[str(k).strip()] = {"subtitle": v.strip(), "label": "", "event": ""}
                elif isinstance(v, dict):
                    out[str(k).strip()] = {
                        "subtitle": str(v.get("subtitle") or v.get("text") or v.get("line") or "").strip(),
                        "label": str(v.get("label") or v.get("name") or "").strip(),
                        "event": str(v.get("event") or "").strip(),
                    }
        elif isinstance(data, list):
            for row in data:
                if not isinstance(row, dict):
                    continue
                mid = str(row.get("media_id") or row.get("id") or row.get("wem") or "").replace(".wem", "").strip()
                if not mid:
                    continue
                out[mid] = {
                    "subtitle": str(row.get("subtitle") or row.get("text") or row.get("line") or "").strip(),
                    "label": str(row.get("label") or row.get("name") or "").strip(),
                    "event": str(row.get("event") or "").strip(),
                }
        return out

    # CSV / TSV fallback (common for Marvel Rivals Audio Spreadsheets)
    dialect = "excel-tab" if "\t" in raw_text[:2048] else "excel"
    reader = csv.DictReader(StringIO(raw_text), dialect=dialect)
    for row in reader:
        norm = {str(k or "").strip().lower(): str(v or "").strip() for k, v in row.items()}
        mid = (norm.get("media_id") or norm.get("wem") or norm.get("wem_id") or norm.get("id") or "").replace(".wem", "").strip()
        sub = norm.get("subtitle") or norm.get("text") or norm.get("dialogue") or norm.get("line") or norm.get("transcript") or ""
        lbl = norm.get("label") or norm.get("name") or norm.get("description") or ""
        ev = norm.get("event") or norm.get("event_name") or ""
        if mid and (sub or lbl or ev):
            out[mid] = {"subtitle": sub, "label": lbl, "event": ev}
    return out


class SubtitleIndex:
    """Fast lookup bridging Wwise media IDs, event names, and UE5 ``.locres`` subtitle strings."""

    def __init__(self, locres_tables: dict[str, dict[str, str]] | None = None, bank_info: dict[int, dict] | None = None, overrides: dict[str, dict] | None = None):
        self.bank_info = dict(bank_info or {})
        self.overrides = dict(overrides or {})
        self._by_key: dict[str, str] = {}
        self._by_norm: dict[str, tuple[str, str]] = {}
        self._hero_lines: dict[str, list[dict]] = {}

        for ns, entries in (locres_tables or {}).items():
            for key, text in (entries or {}).items():
                clean_text = str(text or "").strip()
                if not clean_text:
                    continue
                self._by_key[key.casefold()] = clean_text
                norm = "_".join(_WORD_RE.findall(key.lower()))
                if norm:
                    self._by_norm.setdefault(norm, (key, clean_text))
                # Index voiceover lines under any 4-digit hero ID found in namespace or key.
                for hid in set(re.findall(r"(?<!\d)(10\d{2})(?!\d)", f"{ns}_{key}")):
                    self._hero_lines.setdefault(hid, []).append({"key": key, "namespace": ns, "text": clean_text})

    def resolve(self, media_id: int | str, *, event_hint: str = "") -> dict:
        """Resolve subtitle text, friendly event label and provenance for a ``media_id``."""
        sid = str(media_id).replace(".wem", "").strip()
        mid = int(sid) if sid.isdigit() else -1

        # 1. Explicit user / community subtitle map always wins.
        ov = self.overrides.get(sid)
        if ov and (ov.get("subtitle") or ov.get("label")):
            return {
                "subtitle": ov.get("subtitle", ""),
                "label": ov.get("label", ""),
                "event": ov.get("event", ""),
                "source": "custom",
            }

        # 2. Direct media_id key inside .locres
        if sid and sid.casefold() in self._by_key:
            return {"subtitle": self._by_key[sid.casefold()], "label": "", "event": event_hint, "source": "locres"}

        # 3. SoundbanksInfo event / short name -> .locres cross-reference
        info = self.bank_info.get(mid) or {}
        candidates = []
        if event_hint:
            candidates.append(event_hint)
        candidates.extend(info.get("events") or [])
        short = info.get("short_name") or ""
        if short:
            stem = short.replace("\\", "/").rsplit("/", 1)[-1].rsplit(".", 1)[0]
            candidates.append(stem)

        for cand in candidates:
            if not cand:
                continue
            low = cand.casefold()
            if low in self._by_key:
                return {"subtitle": self._by_key[low], "label": cand, "event": cand, "source": "locres"}
            # Strip common Wwise prefixes like Play_ / VO_ and retry normalized match.
            for stripped in (cand, re.sub(r"^(?:play_|stop_|vo_|sfx_|ak_)+", "", cand, flags=re.I)):
                norm = "_".join(_WORD_RE.findall(stripped.lower()))
                if norm and norm in self._by_norm:
                    _k, text = self._by_norm[norm]
                    return {"subtitle": text, "label": cand, "event": cand, "source": "locres"}

        primary_event = (info.get("events") or [""])[0] or short
        return {"subtitle": "", "label": primary_event, "event": primary_event, "source": "bank_info" if primary_event else ""}

    def hero_subtitles(self, hero_id: str, query: str = "", limit: int = 80) -> list[dict]:
        """Search all ``.locres`` subtitle lines belonging to ``hero_id`` so users can browse & link lines."""
        lines = self._hero_lines.get(str(hero_id), [])
        q = (query or "").strip().lower()
        if q:
            lines = [row for row in lines if q in row["text"].lower() or q in row["key"].lower()]
        return lines[:limit]
