"""Group keyword/mention hits into conversation clusters worth reading."""
import json, sys, datetime as dt, pathlib
sys.path.insert(0, "retrieval")
from store import Store, ROOT

ME = "1084293843731611750"
THREAD = "1519707061854670908"


def is_hit(m):
    c = (m.get("content") or "").lower()
    for e in m.get("embeds", []):
        c += " " + (e.get("title") or "").lower() + " " + (e.get("desc") or "").lower()
    if "atelier" in c or "clownfetus" in c:
        return "kw"
    if any(u["id"] == ME for u in m.get("mentions", [])):
        return "mention"
    return None


def clusters(gap_min=45):
    st = Store()
    names = {str(c["id"]): c["name"] for c in json.loads((ROOT / "channels.json").read_text())}
    out = []
    for cid, rows in st.by_channel.items():
        if cid == THREAD:
            continue
        hits = [(m, is_hit(m)) for m in rows]
        hits = [(m, k) for m, k in hits if k]
        if not hits:
            continue
        cur = []
        for m, k in hits:
            t = dt.datetime.fromisoformat(m["ts"])
            if cur and (t - dt.datetime.fromisoformat(cur[-1][0]["ts"])).total_seconds() > gap_min * 60:
                out.append((cid, cur)); cur = []
            cur.append((m, k))
        if cur:
            out.append((cid, cur))
    res = []
    for cid, grp in out:
        kinds = {k for _, k in grp}
        res.append({
            "cid": cid, "channel": names.get(cid, cid),
            "start": grp[0][0]["id"], "end": grp[-1][0]["id"],
            "ts": grp[0][0]["ts"], "n_hits": len(grp),
            "kinds": sorted(kinds),
            "kw": "kw" in kinds,
            "authors": sorted({(m.get("author_nick") or m.get("author")) for m, _ in grp}),
            "sample": (grp[0][0].get("content") or "")[:150].replace("\n", " "),
        })
    res.sort(key=lambda c: c["ts"])
    return res


if __name__ == "__main__":
    cs = clusters()
    kw = [c for c in cs if c["kw"]]
    print(f"{len(cs)} clusters total; {len(kw)} contain an explicit Atelier/clownfetus keyword")
    print(f"mention-only clusters: {len(cs) - len(kw)}")
    (ROOT / "clusters.json").write_text(json.dumps(cs, indent=1))
    import collections
    for k, v in collections.Counter(c["channel"] for c in cs).most_common(20):
        print(f"  {v:>4}  {k}")
