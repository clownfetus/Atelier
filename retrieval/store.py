"""On-disk corpus: one JSONL per channel + downloaded media."""
import json, pathlib, re, asyncio, hashlib

ROOT = pathlib.Path("retrieval/data")
MSGS = ROOT / "messages"
MEDIA = ROOT / "attachments"
SAFE = re.compile(r"[^A-Za-z0-9._-]")


def slim(m):
    """Keep the fields that matter for reading + threading, drop the noise."""
    return {
        "id": m["id"],
        "channel_id": m.get("channel_id"),
        "ts": m.get("timestamp", "")[:19],
        "author": m["author"].get("username"),
        "author_id": m["author"]["id"],
        "author_nick": (m.get("member") or {}).get("nick"),
        "content": m.get("content", ""),
        "type": m.get("type"),
        "mentions": [{"id": u["id"], "name": u.get("username")} for u in m.get("mentions", [])],
        "mention_roles": m.get("mention_roles", []),
        "ref": (m.get("message_reference") or {}).get("message_id"),
        "ref_channel": (m.get("message_reference") or {}).get("channel_id"),
        "ref_author": ((m.get("referenced_message") or {}).get("author") or {}).get("username"),
        "ref_content": (m.get("referenced_message") or {}).get("content"),
        "attachments": [{"name": a.get("filename"), "url": a.get("url"),
                         "ct": a.get("content_type"), "size": a.get("size")}
                        for a in m.get("attachments", [])],
        "embeds": [{"title": e.get("title"), "desc": e.get("description"),
                    "url": e.get("url"),
                    "image": (e.get("image") or e.get("thumbnail") or {}).get("url")}
                   for e in m.get("embeds", [])],
        "reactions": [{"emoji": (r.get("emoji") or {}).get("name"), "count": r.get("count")}
                      for r in m.get("reactions", [])],
        "edited": m.get("edited_timestamp"),
        "pinned": m.get("pinned", False),
        "thread": (m.get("thread") or {}).get("id"),
    }


class Store:
    def __init__(self):
        MSGS.mkdir(parents=True, exist_ok=True)
        MEDIA.mkdir(parents=True, exist_ok=True)
        self.by_id = {}
        self.by_channel = {}
        self.load()

    def load(self):
        self.by_id.clear(); self.by_channel.clear()
        for f in MSGS.glob("*.jsonl"):
            cid = f.stem
            rows = []
            for line in f.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    m = json.loads(line)
                except json.JSONDecodeError:
                    continue  # torn write from a concurrent flush; skip
                rows.append(m)
                self.by_id[m["id"]] = m
            rows.sort(key=lambda m: int(m["id"]))
            self.by_channel[cid] = rows
        return sum(len(v) for v in self.by_channel.values())

    def add(self, cid, raw_msgs):
        """Merge messages into channel cid. Returns count of genuinely new ones."""
        cid = str(cid)
        rows = self.by_channel.setdefault(cid, [])
        have = {m["id"] for m in rows}
        new = 0
        for raw in raw_msgs:
            m = slim(raw) if "author" in raw and isinstance(raw.get("author"), dict) else raw
            m.setdefault("channel_id", cid)
            if m["id"] in have:
                continue
            have.add(m["id"]); rows.append(m); self.by_id[m["id"]] = m; new += 1
        rows.sort(key=lambda m: int(m["id"]))
        self.flush(cid)
        return new

    def flush(self, cid):
        cid = str(cid)
        p = MSGS / f"{cid}.jsonl"
        with p.open("w", encoding="utf-8") as fh:
            for m in self.by_channel[cid]:
                fh.write(json.dumps(m, ensure_ascii=False) + "\n")

    def channel(self, cid):
        return self.by_channel.get(str(cid), [])

    def context(self, mid, n=6):
        """N messages either side of mid, from whichever channel holds it."""
        m = self.by_id.get(str(mid))
        if not m:
            return None
        rows = self.by_channel.get(str(m["channel_id"]), [])
        i = next((k for k, r in enumerate(rows) if r["id"] == str(mid)), None)
        if i is None:
            return None
        return rows[max(0, i - n): i + n + 1]

    def media_paths(self, m):
        out = []
        urls = [(a["name"], a["url"]) for a in m.get("attachments", []) if a.get("url")]
        urls += [(None, e["image"]) for e in m.get("embeds", []) if e.get("image")]
        for name, url in urls:
            base = name or hashlib.sha1(url.encode()).hexdigest()[:12]
            fn = SAFE.sub("_", base)[:120]
            out.append((url, MEDIA / str(m["channel_id"]) / f"{m['id']}_{fn}"))
        return out


async def download_media(session, store, msgs, log=print, limit=None, max_mb=25):
    """Fetch attachments/embed images for msgs. CDN links are signed+expiring,
    so this must run close in time to the message fetch."""
    jobs = []
    cap = max_mb * 1024 * 1024
    for m in msgs:
        big = {a.get("url") for a in m.get("attachments", []) if (a.get("size") or 0) > cap}
        for url, dest in store.media_paths(m):
            if url not in big and not dest.exists():
                jobs.append((url, dest))
    if limit:
        jobs = jobs[:limit]
    ok = fail = 0
    for url, dest in jobs:
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            async with session.get(url) as r:
                if r.status != 200:
                    fail += 1; continue
                dest.write_bytes(await r.read())
                ok += 1
        except Exception:
            fail += 1
        await asyncio.sleep(0.05)
    if jobs:
        log(f"  media: {ok} downloaded, {fail} failed ({len(jobs)} queued)")
    return ok, fail
