"""Download media for a chosen set of messages (post-curation backfill).

Usage: media_pass.py <ids_file>     one message id per line
       media_pass.py --relevant     ids from data/findings.jsonl
"""
import asyncio, json, sys, aiohttp
sys.path.insert(0, "retrieval")
from dclient import Discord, load_env, UA
from store import Store, slim, download_media, ROOT


async def main():
    env = load_env()
    st = Store()
    if sys.argv[1] == "--relevant":
        ids = [json.loads(l)["msg"] for l in (ROOT / "findings.jsonl").read_text().splitlines() if l.strip()]
    else:
        ids = [l.strip() for l in open(sys.argv[1]) if l.strip()]
    msgs = [st.by_id[i] for i in ids if i in st.by_id]
    # media links expire, so re-fetch the message first to get fresh signed urls
    async with Discord(env["DISCORD_TOKEN"]) as d:
        fresh = []
        need = [m for m in msgs if m.get("attachments") or any(e.get("image") for e in m.get("embeds", []))]
        print(f"{len(need)} of {len(msgs)} messages carry media; refreshing urls")
        for i, m in enumerate(need, 1):
            try:
                raw = await d.message(m["channel_id"], m["id"])
                if raw:
                    s = slim(raw); st.add(m["channel_id"], [s]); fresh.append(s)
            except Exception as e:
                print(f"  !! {m['id']}: {str(e)[:80]}")
            if i % 25 == 0:
                print(f"  refreshed {i}/{len(need)}")
        async with aiohttp.ClientSession(headers={"User-Agent": UA},
                                         timeout=aiohttp.ClientTimeout(total=180)) as cdn:
            ok, fail = await download_media(cdn, st, fresh or need, max_mb=25)
    print(f"media pass done: {ok} ok, {fail} failed")

if __name__ == "__main__":
    asyncio.run(main())
