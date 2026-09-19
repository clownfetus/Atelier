"""Async exploration API over the Discord corpus.

Runs one shared, rate-limited Discord session; every endpoint that touches the
network also ingests what it sees into the local corpus, so browsing builds the
archive as a side effect.

Text output (fmt=txt, the default) is the readable transcript form; fmt=json
gives the raw records.
"""
import asyncio, json, pathlib, re, sys, aiohttp
from aiohttp import web
sys.path.insert(0, "retrieval")
from dclient import Discord, load_env, UA
from store import Store, slim, download_media, ROOT
from fetch import fetch_channel

env = load_env()
GUILD = env["GUILD_ID"]
CH_CACHE = ROOT / "channels.json"
MARKS = ROOT / "findings.jsonl"

app = web.Application()
S = {"store": None, "d": None, "cdn": None, "chan": {}}


# ---------- rendering -------------------------------------------------
def cname(cid):
    c = S["chan"].get(str(cid))
    return ("#" + c["name"]) if c else f"<{cid}>"


def render(msgs, hits=()):
    hits = {str(h) for h in hits}
    out = []
    last_ch = None
    for m in msgs:
        if m.get("channel_id") != last_ch:
            out.append(f"--- {cname(m.get('channel_id'))} ---")
            last_ch = m.get("channel_id")
        mark = ">>" if m["id"] in hits else "  "
        who = m.get("author_nick") or m.get("author")
        out.append(f"{mark}[{m['ts'].replace('T',' ')}] {who}  ({m['id']})")
        body = (m.get("content") or "").strip()
        if body:
            for line in body.splitlines():
                out.append(f"     {line}")
        if m.get("ref"):
            rc = (m.get("ref_content") or "")[:120].replace("\n", " ")
            out.append(f"     ↳ reply to {m.get('ref_author')}: {rc!r} ({m['ref']})")
        for a in m.get("attachments", []):
            out.append(f"     [file] {a.get('name')} {a.get('ct') or ''}")
        for e in m.get("embeds", []):
            t = e.get("title") or e.get("url") or ""
            if t:
                out.append(f"     [embed] {str(t)[:140]}")
        if m.get("thread"):
            out.append(f"     [opens thread {m['thread']}]")
        rx = ", ".join(f"{r['emoji']}x{r['count']}" for r in m.get("reactions", []) if r.get("emoji"))
        if rx:
            out.append(f"     ({rx})")
    return "\n".join(out)


def reply(request, msgs, hits=(), **extra):
    fmt = request.query.get("fmt", "txt")
    if fmt == "json":
        return web.json_response({"count": len(msgs), "messages": msgs, **extra})
    head = " ".join(f"{k}={v}" for k, v in extra.items())
    body = (head + "\n" if head else "") + render(msgs, hits)
    return web.Response(text=body or "(none)", content_type="text/plain")


async def ingest(raws, media=False):
    """Store raw API messages, grouped by channel; pull their media."""
    slims = [slim(r) for r in raws]
    by_ch = {}
    for m in slims:
        by_ch.setdefault(str(m["channel_id"]), []).append(m)
    for cid, rows in by_ch.items():
        S["store"].add(cid, rows)
    if media and slims:
        await download_media(S["cdn"], S["store"], slims, log=lambda *a: None)
    return slims


# ---------- endpoints -------------------------------------------------
async def h_health(r):
    st = S["store"]
    return web.json_response({
        "ok": True, "guild": GUILD,
        "channels_cached": len(S["chan"]),
        "messages": sum(len(v) for v in st.by_channel.values()),
        "channels_with_data": {cname(k): len(v) for k, v in sorted(
            st.by_channel.items(), key=lambda kv: -len(kv[1]))},
        "api_calls": S["d"].calls,
    })


async def h_channels(r):
    """List guild channels; q= filters by name."""
    q = (r.query.get("q") or "").lower()
    rows = [c for c in S["chan"].values() if q in c["name"].lower()]
    rows.sort(key=lambda c: c["name"])
    return web.json_response([
        {"id": c["id"], "name": c["name"], "type": c["type"],
         "parent": (S["chan"].get(str(c.get("parent_id"))) or {}).get("name"),
         "topic": (c.get("topic") or "")[:150],
         "have": len(S["store"].channel(c["id"]))}
        for c in rows])


async def h_search(r):
    """Live guild-wide search. q=content, mentions=, author_id=, channel_id=,
    pages=N to walk pagination. Ingests every hit."""
    q = r.query
    pages = int(q.get("pages", 1))
    filters = {k: q[k] for k in ("author_id", "mentions", "channel_id", "has", "max_id", "min_id")
               if q.get(k)}
    if q.get("q"):
        filters["content"] = q["q"]
    offset = int(q.get("offset", 0))
    hits, total = [], None
    for _ in range(pages):
        res = await S["d"].search(GUILD, offset=offset, **filters)
        total = res.get("total_results")
        batch = [m for group in res.get("messages", []) for m in group if m.get("hit")]
        if not batch:
            break
        hits.extend(batch)
        offset += 25
        if offset >= (total or 0):
            break
    slims = await ingest(hits, media=r.query.get("media")=="1")
    slims.sort(key=lambda m: (str(m["channel_id"]), int(m["id"])))
    return reply(r, slims, hits=[m["id"] for m in slims],
                 total_results=total, next_offset=offset)


async def h_around(r):
    """N messages either side of a message id. Falls back to a live fetch."""
    mid = r.query["msg"]
    n = int(r.query.get("n", 6))
    cid = r.query.get("cid")
    ctx = S["store"].context(mid, n)
    if ctx is None:
        if not cid:
            m = S["store"].by_id.get(str(mid))
            cid = m and m["channel_id"]
        if not cid:
            raise web.HTTPBadRequest(text="unknown message; pass cid=<channel_id>")
        raw = await S["d"].messages(cid, limit=max(2 * n + 1, 25), around=mid)
        await ingest(raw)
        ctx = S["store"].context(mid, n) or []
    return reply(r, ctx, hits=[mid])


async def h_channel(r):
    """Read a slice of a channel: cid=, before=/after=, limit=. Live-fetches."""
    cid = r.query["cid"]
    limit = int(r.query.get("limit", 50))
    before, after = r.query.get("before"), r.query.get("after")
    if r.query.get("live", "1") == "1":
        raw = await S["d"].messages(cid, limit=min(100, limit), before=before, after=after)
        await ingest(raw)
    rows = S["store"].channel(cid)
    if before:
        rows = [m for m in rows if int(m["id"]) < int(before)]
    if after:
        rows = [m for m in rows if int(m["id"]) > int(after)]
    rows = rows[-limit:] if not after else rows[:limit]
    return reply(r, rows, oldest=rows[0]["id"] if rows else None,
                 newest=rows[-1]["id"] if rows else None)


async def h_local(r):
    """Regex/substring search of the already-downloaded corpus."""
    q = r.query.get("q", "")
    rx = re.compile(q, re.I) if r.query.get("regex") else None
    author = (r.query.get("author") or "").lower()
    cid = r.query.get("cid")
    limit = int(r.query.get("limit", 60))
    out = []
    for c, rows in S["store"].by_channel.items():
        if cid and c != str(cid):
            continue
        for m in rows:
            blob = (m.get("content") or "") + " " + " ".join(
                (e.get("title") or "") + " " + (e.get("desc") or "") for e in m.get("embeds", []))
            if q and not (rx.search(blob) if rx else q.lower() in blob.lower()):
                continue
            if author and author not in ((m.get("author") or "") + (m.get("author_nick") or "")).lower():
                continue
            out.append(m)
    out.sort(key=lambda m: int(m["id"]))
    return reply(r, out[:limit], hits=[m["id"] for m in out[:limit]], matched=len(out))


async def h_replies(r):
    """Follow a reply chain: ancestors via ref, descendants via who replied to it."""
    mid = str(r.query["msg"])
    seen, chain = set(), []
    cur = S["store"].by_id.get(mid)
    while cur and cur["id"] not in seen:
        seen.add(cur["id"]); chain.append(cur)
        cur = S["store"].by_id.get(str(cur.get("ref"))) if cur.get("ref") else None
    frontier = {mid}
    for _ in range(6):
        nxt = set()
        for c, rows in S["store"].by_channel.items():
            for m in rows:
                if str(m.get("ref")) in frontier and m["id"] not in seen:
                    seen.add(m["id"]); chain.append(m); nxt.add(m["id"])
        if not nxt:
            break
        frontier = nxt
    chain.sort(key=lambda m: int(m["id"]))
    return reply(r, chain, hits=[mid])


async def h_pull(r):
    """Full-history fetch of a channel into the corpus."""
    cid = r.query["cid"]
    logs = []
    total, fresh = await fetch_channel(S["d"], S["store"], cid, log=logs.append,
                                       media=r.query.get("media", "1") == "1")
    return web.json_response({"channel": cname(cid), "fetched": total, "new": fresh,
                              "log": logs})


async def h_mark(r):
    """Record a curated finding: msg=, why=, tag=."""
    body = await r.json() if r.can_read_body else dict(r.query)
    rec = {"msg": str(body.get("msg")), "tag": body.get("tag", ""),
           "why": body.get("why", ""), "channel": body.get("channel", "")}
    with MARKS.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return web.json_response({"saved": rec})


async def h_marks(r):
    if not MARKS.exists():
        return web.json_response([])
    return web.json_response([json.loads(l) for l in MARKS.read_text().splitlines() if l.strip()])



async def h_range(r):
    """Fetch EVERY message between start and end in a channel (walks forward),
    plus pad messages either side. This is how a keyword hit becomes a
    readable conversation."""
    cid = r.query["cid"]
    start, end = int(r.query["start"]), int(r.query["end"])
    pad = int(r.query.get("pad", 6))
    if pad:
        raw = await S["d"].messages(cid, limit=pad, before=str(start))
        await ingest(raw)
    cursor, guard = str(start - 1), 0
    while guard < 60:
        guard += 1
        raw = await S["d"].messages(cid, limit=100, after=cursor)
        if not raw:
            break
        await ingest(raw)
        newest = max(int(m["id"]) for m in raw)
        if newest <= int(cursor):
            break
        cursor = str(newest)
        if newest >= end:
            break
    if pad:
        raw = await S["d"].messages(cid, limit=pad, after=str(end))
        await ingest(raw)
    rows = [m for m in S["store"].channel(cid)]
    lo = next((i for i, m in enumerate(rows) if int(m["id"]) >= start), 0)
    hi = next((i for i, m in enumerate(rows) if int(m["id"]) > end), len(rows))
    sl = rows[max(0, lo - pad): hi + pad]
    return reply(r, sl, span=f"{start}..{end}", pages=guard)


for path, fn in [("/health", h_health), ("/channels", h_channels), ("/search", h_search),
                 ("/around", h_around), ("/channel", h_channel), ("/local", h_local),
                 ("/replies", h_replies), ("/pull", h_pull), ("/range", h_range), ("/marks", h_marks)]:
    app.router.add_get(path, fn)
app.router.add_route("*", "/mark", h_mark)


async def startup(a):
    S["store"] = Store()
    d = Discord(env["DISCORD_TOKEN"], log=lambda *x: None)
    await d.__aenter__(); S["d"] = d
    S["cdn"] = aiohttp.ClientSession(headers={"User-Agent": UA},
                                     timeout=aiohttp.ClientTimeout(total=120))
    if CH_CACHE.exists():
        chans = json.loads(CH_CACHE.read_text())
    else:
        chans = await d.channels(GUILD)
        CH_CACHE.write_text(json.dumps(chans))
    S["chan"] = {str(c["id"]): c for c in chans}
    # threads aren't in the channel list; label the ones we hold
    S["chan"].setdefault(env["THREAD_ID"], {"id": env["THREAD_ID"], "name": "atelier-thread", "type": 11})
    print(f"ready: {len(S['chan'])} channels, "
          f"{sum(len(v) for v in S['store'].by_channel.values())} messages")


async def cleanup(a):
    await S["d"].__aexit__(); await S["cdn"].close()

app.on_startup.append(startup)
app.on_cleanup.append(cleanup)

if __name__ == "__main__":
    web.run_app(app, host="127.0.0.1", port=8777, print=None)
