"""Render harvested clusters as readable transcripts, in batches."""
import json, sys, datetime as dt
sys.path.insert(0, "retrieval")
from store import Store, ROOT

st = Store()
names = {str(c["id"]): c["name"] for c in json.loads((ROOT / "channels.json").read_text())}
names["1519707061854670908"] = "atelier-thread"
ME = "1084293843731611750"


def body(m):
    t = (m.get("content") or "").replace("\n", " ⏎ ").strip()
    for a in m.get("attachments", []):
        t += f" [file:{a.get('name')}]"
    for e in m.get("embeds", []):
        if e.get("title"):
            t += f" [embed:{str(e['title'])[:60]}]"
    return t


def transcript(cid, start, end, pad=8, width=300):
    rows = st.channel(cid)
    lo = next((i for i, m in enumerate(rows) if int(m["id"]) >= int(start)), 0)
    hi = next((i for i, m in enumerate(rows) if int(m["id"]) > int(end)), len(rows))
    sl = rows[max(0, lo - pad): hi + pad]
    out = []
    for m in sl:
        who = (m.get("author_nick") or m.get("author") or "?")[:16]
        star = "*" if m["author_id"] == ME else " "
        out.append(f"  {star}{who:<16} {body(m)[:width]}")
    return sl, out


if __name__ == "__main__":
    lo, hi = int(sys.argv[1]), int(sys.argv[2])
    only = sys.argv[3] if len(sys.argv) > 3 else None
    cs = json.loads((ROOT / "harvested.json").read_text())
    cs = [c for c in cs if c.get("fetched", 0) > 0]
    if only:
        cs = [c for c in cs if only in c["channel"]]
    cs.sort(key=lambda c: c["ts"])
    print(f"### clusters {lo}..{hi} of {len(cs)}" + (f" in {only}" if only else ""))
    for i, c in enumerate(cs):
        if not (lo <= i < hi):
            continue
        sl, lines = transcript(c["cid"], c["start"], c["end"])
        print(f"\n@@{i} [{c['ts'][:16]}] #{c['channel']}  msg={c['start']} ({len(sl)} msgs)")
        print("\n".join(lines))
