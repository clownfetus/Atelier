# Atelier Discord retrieval

Pulls Atelier-related reports out of the MRM Discord and keeps them searchable.

## Why it's built this way

Keyword matching alone misses things: plenty of Atelier conversation never says "Atelier"
(someone replies to a reply, or just says "it crashed on export"). So the pipeline finds
*anchors* three ways — the word Atelier, the word clownfetus, and mentions of your account
(which also catches reply-pings) — clusters anchors that are close together in the same
channel into one conversation, then fetches the **entire message range** for each cluster with
padding. What gets read is real conversation, not matched lines.

## Layout

| file | what it does |
|---|---|
| `dclient.py` | async Discord REST, serial + 429/bucket-aware, plain browser UA |
| `store.py` | JSONL corpus per channel + media download, dedupes on merge |
| `fetch.py` | walk a channel's whole history (`python retrieval/fetch.py <channel_id>`) |
| `api.py` | the exploration server — see below |
| `plan.py` | group anchors into conversation clusters -> `data/clusters.json` |
| `harvest.py` | fetch the full range for every cluster -> `data/harvested.json` |
| `review.py` | render clusters as readable transcripts (`review.py <from> <to> [channel]`) |
| `media_pass.py` | re-fetch signed URLs and download images for chosen messages |
| `report.py` | emit `data/findings.jsonl` + `REPORT.md` |

`data/` and `.env` are gitignored — `.env` holds a user token, keep it that way.

## The server

    .venv/bin/python retrieval/api.py     # 127.0.0.1:8777

Everything defaults to readable text; add `fmt=json` for records. Network endpoints also
ingest what they see, so browsing grows the archive.

| endpoint | |
|---|---|
| `/health` | corpus + api call counters |
| `/channels?q=` | guild channels, with how many messages are held for each |
| `/search?q=&mentions=&author_id=&channel_id=&pages=N` | live guild-wide search (user-token only) |
| `/around?msg=&n=6&cid=` | N messages either side, live-fetches if not held |
| `/range?cid=&start=&end=&pad=8` | every message between two ids — how a hit becomes a conversation |
| `/channel?cid=&before=&after=&limit=` | page through a channel |
| `/local?q=&regex=1&author=&cid=` | search what's already downloaded, no API calls |
| `/replies?msg=` | walk a reply chain up and down |
| `/pull?cid=` | full history of a channel |
| `/mark` + `/marks` | record and list curated findings |

## Re-running later

    .venv/bin/python retrieval/fetch.py 1519707061854670908   # refresh the thread
    .venv/bin/python retrieval/plan.py                        # re-cluster
    .venv/bin/python retrieval/harvest.py priority            # fetch new conversations
    .venv/bin/python retrieval/report.py                      # regenerate REPORT.md

Anything already stored is skipped, so re-runs are cheap.

## Caveat

The token in `.env` is a **user** token and `discord.py-self` is a selfbot library. Automating a
user account breaks Discord's ToS and risks the account. The client here is deliberately gentle
(one request at a time, real backoff, no TLS fingerprint spoofing) but the risk is inherent.
