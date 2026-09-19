"""Minimal async Discord REST wrapper for a user token.

Deliberately serial + conservative: one request in flight, honours 429
`retry_after` and per-bucket `X-RateLimit-Reset-After`, and sends a plain
browser User-Agent (no TLS fingerprint impersonation).
"""
import asyncio, os, pathlib, time
import aiohttp

API = "https://discord.com/api/v10"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")


def load_env(path="retrieval/.env"):
    env = {}
    p = pathlib.Path(path)
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    for k, v in env.items():
        os.environ.setdefault(k, v)
    return env


class Discord:
    def __init__(self, token, log=print):
        self._token = token
        self.log = log
        self.session = None
        self._lock = asyncio.Lock()      # serialise every API call
        self._next_ok = 0.0              # monotonic time we may fire again
        self.calls = 0

    async def __aenter__(self):
        self.session = aiohttp.ClientSession(
            headers={"Authorization": self._token, "User-Agent": UA,
                     "Accept": "application/json", "X-Discord-Locale": "en-US"},
            timeout=aiohttp.ClientTimeout(total=60),
        )
        return self

    async def __aexit__(self, *a):
        await self.session.close()

    async def req(self, method, path, **params):
        """One rate-limit-respecting API call. Returns parsed JSON."""
        url = path if path.startswith("http") else API + path
        params = {k: v for k, v in params.items() if v is not None}
        for attempt in range(8):
            async with self._lock:
                delay = self._next_ok - time.monotonic()
                if delay > 0:
                    await asyncio.sleep(delay)
                async with self.session.request(method, url, params=params) as r:
                    self.calls += 1
                    body = None
                    if r.content_type == "application/json":
                        body = await r.json()
                    # pace off the bucket headers
                    rem = r.headers.get("X-RateLimit-Remaining")
                    rst = r.headers.get("X-RateLimit-Reset-After")
                    if rem == "0" and rst:
                        self._next_ok = time.monotonic() + float(rst)
                    else:
                        self._next_ok = time.monotonic() + 0.35  # gentle floor

                    if r.status == 429:
                        wait = float((body or {}).get("retry_after", 5))
                        self._next_ok = time.monotonic() + wait + 0.5
                        self.log(f"  429 rate limited, waiting {wait:.1f}s")
                        continue
                    if r.status == 202:
                        # search index not ready yet
                        wait = float((body or {}).get("retry_after", 3))
                        self.log(f"  202 index warming, waiting {wait:.1f}s")
                        self._next_ok = time.monotonic() + wait + 0.5
                        continue
                    if r.status in (500, 502, 503, 504):
                        self._next_ok = time.monotonic() + 2 * (attempt + 1)
                        continue
                    if r.status >= 400:
                        raise RuntimeError(f"{method} {url} -> {r.status}: {body}")
                    return body
        raise RuntimeError(f"{method} {url}: gave up after retries")

    # ---- endpoints -------------------------------------------------
    async def me(self):
        return await self.req("GET", "/users/@me")

    async def guild(self, gid):
        return await self.req("GET", f"/guilds/{gid}")

    async def channels(self, gid):
        return await self.req("GET", f"/guilds/{gid}/channels")

    async def messages(self, cid, limit=100, before=None, after=None, around=None):
        return await self.req("GET", f"/channels/{cid}/messages",
                              limit=limit, before=before, after=after, around=around)

    async def message(self, cid, mid):
        """Single message via around=1 (user tokens can't GET one directly)."""
        got = await self.messages(cid, limit=1, around=mid)
        return next((m for m in got if m["id"] == str(mid)), None)

    async def search(self, gid, offset=0, **filters):
        """Guild-wide search. filters: content, author_id, mentions, channel_id..."""
        return await self.req("GET", f"/guilds/{gid}/messages/search",
                              offset=offset, include_nsfw="true", **filters)
