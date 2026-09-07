# Demo Guide

This walks through a **keyless, self-contained demo** that shows off the actual
freshness machinery — scheduled scraping, change detection, versioned history, and
live-only vector search — without depending on Firecrawl, an API key, or scraping a
site you don't control.

## Why a mock source?

The pipeline was designed around Firecrawl (see `app/scraper.py`), but a *demo* should
not depend on scraping live e-commerce sites:

- Many sites block scrapers or violate their ToS to scrape (LinkedIn already refused us).
- Content you don't control makes a scripted demo non-reproducible.
- A reviewer cloning the repo shouldn't need a paid API key to see it work.

So the scraper gained a **dispatcher**: URLs on local/demo hosts use a plain
`LocalHttpScraper` (no key); everything else still routes to `FirecrawlScraper`. The
demo points the pipeline at a local *clock-driven mock competitor site* whose content
changes over time. Same code path — hash, compare, version, embed — just a different,
reliable source.

## What the mock site does

`demo/competitor_site.py` serves two fake competitors, **Alpha Cocoa** and
**Beta Beverages**, on port `9000`. Every page is a pure function of a "market tick"
(one tick = 20s):

- a **drifting price** on one product line (changes most ticks)
- a **rotating promo banner** (changes every few ticks)
- a **limited product** that appears/disappears on a slow cadence
- a **stable product** and an **about** paragraph that never change

So each scheduled poll usually registers a change, while stable blocks stay untouched —
exactly the pattern the pipeline is built to handle.

## Run it locally (no Docker)

You need: Python 3.11, `uv`, and a `.env` (a copy of `.env.example`; no Firecrawl key
needed for the demo). First run downloads the embedding model once.

Terminal 1 — mock competitor site:

```bash
uv run uvicorn demo.competitor_site:app --port 9000
```

Terminal 2 — backend (uses `LOCAL_SCRAPE_HOSTS` default `localhost,127.0.0.1`):

```bash
uv run uvicorn app.main:app --port 8000
```

Terminal 3 — UI:

```bash
uv run streamlit run frontend/app.py
```

Register two sources in the **Sources** tab:

| Name | URL | Interval |
|---|---|---|
| Alpha Cocoa | `http://localhost:9000/alpha` | 20 |
| Beta Beverages | `http://localhost:9000/beta` | 20 |

## Run it with Docker (one command)

```bash
docker compose -f docker-compose.demo.yml up --build
```

Open http://localhost:8501. The `competitors` service changes content every ~20s, the
`app` service polls it on the same cadence, and the UI shows the result. Nothing else
to configure.

To generate natural-language answers in the **Ask** tab, add `GEMINI_API_KEY` to `.env`
and pass it to the demo app environment. Without a Gemini key, `/query` and the raw
supporting-context display still work; only answer synthesis is unavailable.
The backend retries transient provider failures with `GEMINI_FALLBACK_MODEL` (default:
`gemini-flash-lite-latest`).

## What to watch (and what it proves)

While the stack runs, click **Run now** a couple of times or just wait:

1. **Change History tab** — new rows appear over time. Stable blocks show as a single
   `live` version that persists; changed blocks appear once, then later as `removed`
   once replaced. This is Path 2 (versioned lineage from `chunk_versions`).
2. **Backend logs / `scrape_runs`** — every poll is logged even when nothing changed
   (`unchanged` counts). That is the freshness/coverage signal.
3. **Sources → Run now immediately after a run** — `unchanged` stays high and no new
   vectors are written: identical hash ⇒ skip re-embedding. (Type in the product name
   and hit Search again: answers come back with a `version` and `changed_at`, i.e.
   freshness metadata — Path 1.)

Storage check after many ticks: `chunk_versions` rows grow with *changes*, not with
*polls*, because unchanged content is never re-stored.

## Instant history for screenshots (optional)

If you don't want to wait for ticks, replay a deterministic snapshot sequence through
the real pipeline:

```bash
uv run python scripts/seed_history.py --fresh
```

This drives several market ticks per competitor through embeddings + Chroma + versioning
in seconds, producing a ready-made history and populated index.

## Real websites

Point a source at any external URL and it is scraped with Firecrawl (set
`FIRECRAWL_API_KEY`). Respect each site's terms of service and robots policy. See the
main README for the API and architecture.

## Troubleshooting

- **UI says "Cannot reach backend"** — start the backend, or point the UI elsewhere:
  `API_URL=http://host:8000 uv run streamlit run frontend/app.py`.
- **History not growing** — confirm the mock site is up (`curl localhost:9000/alpha`)
  and that the source interval is short (20s) so ticks roll over during your session.
- **Wipe demo state** — `rm -f data/rag.db && rm -rf data/chroma`.
