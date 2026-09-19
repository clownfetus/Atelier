"""Fetch the full message range for each cluster via the running API."""
import json, sys, time, urllib.parse, urllib.request, pathlib
sys.path.insert(0, "retrieval")
from store import ROOT

BASE = "http://127.0.0.1:8777"
MOD = ("mod-help", "mod-general", "mod-suggestions", "mod-ui", "mod-vfx",
       "mod-meshes", "mod-mats", "mod-audio", "share-your-work")

cs = json.loads((ROOT / "clusters.json").read_text())
which = sys.argv[1] if len(sys.argv) > 1 else "priority"

def prio(c):
    if c["kw"]:
        return True
    ch = c["channel"]
    return any(m in ch for m in MOD) or ch.isdigit()

todo = [c for c in cs if prio(c)] if which == "priority" else cs
done = json.loads((ROOT / "harvested.json").read_text()) if (ROOT / "harvested.json").exists() else []
doneset = {f"{d['cid']}:{d['start']}" for d in done}
todo = [c for c in todo if f"{c['cid']}:{c['start']}" not in doneset]
print(f"harvesting {len(todo)} clusters ({len(doneset)} already done)", flush=True)

for i, c in enumerate(todo, 1):
    q = urllib.parse.urlencode({"cid": c["cid"], "start": c["start"], "end": c["end"],
                                "pad": 8, "fmt": "json"})
    try:
        with urllib.request.urlopen(f"{BASE}/range?{q}", timeout=300) as r:
            d = json.loads(r.read())
        c["fetched"] = d["count"]
        done.append(c); doneset.add(f"{c['cid']}:{c['start']}")
    except Exception as e:
        print(f"  !! {c['channel']} {c['start']}: {str(e)[:100]}", flush=True)
        c["fetched"] = -1; done.append(c)
    if i % 20 == 0:
        print(f"  {i}/{len(todo)} clusters", flush=True)
        (ROOT / "harvested.json").write_text(json.dumps(done, indent=1))
(ROOT / "harvested.json").write_text(json.dumps(done, indent=1))
print("harvest complete", flush=True)
