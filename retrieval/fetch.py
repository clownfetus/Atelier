"""Walk a channel's full history backwards and persist it (+ media)."""
import asyncio, sys, aiohttp
sys.path.insert(0, "retrieval")
from dclient import Discord, load_env, UA
from store import Store, slim, download_media


async def fetch_channel(d, store, cid, log=print, media=True, stop_at=None):
    cid = str(cid)
    before, total, fresh = None, 0, 0
    pages = 0
    all_new = []
    while True:
        batch = await d.messages(cid, limit=100, before=before)
        if not batch:
            break
        pages += 1
        slims = [slim(m) for m in batch]
        n = store.add(cid, slims)
        all_new.extend(slims)
        fresh += n
        total += len(batch)
        before = min(batch, key=lambda m: int(m["id"]))["id"]
        log(f"  page {pages:>3}: +{len(batch):>3} msgs ({n} new)  oldest={before}  total={total}")
        if stop_at and int(before) <= int(stop_at):
            break
        if len(batch) < 100:
            break
    log(f"  history done: {total} fetched, {fresh} new, {pages} pages")
    if media and all_new:
        async with aiohttp.ClientSession(
            headers={"User-Agent": UA},
            timeout=aiohttp.ClientTimeout(total=120)) as cdn:
            await download_media(cdn, store, all_new, log=log)
    return total, fresh


async def main():
    env = load_env()
    cid = sys.argv[1] if len(sys.argv) > 1 else env["THREAD_ID"]
    store = Store()
    async with Discord(env["DISCORD_TOKEN"]) as d:
        print(f"fetching channel {cid} ...")
        await fetch_channel(d, store, cid)
        print(f"api calls: {d.calls}")
    print(f"corpus now holds {sum(len(v) for v in store.by_channel.values())} messages")

if __name__ == "__main__":
    asyncio.run(main())
