# Freshness-Aware RAG for Competitive Analysis

A scheduled web-scraping + retrieval pipeline that watches competitor pages and
answers two kinds of questions:

1. **Current state** (live retrieval): "What is Nestlé's current price for milk chocolate?"
2. **Change history** (versioned diff): "What changed on Nestlé's product page over the last month?"

It scrapes with **Firecrawl**, chunks + fingerprints the text, stores **one row per
content change** in SQLite, and keeps **only the live version of each chunk** embedded
in a local **ChromaDB** vector store. Local embeddings via `sentence-transformers`,
so there are no embedding API costs.

## Why this design (the 30-second version)

Naive "re-scrape and re-embed everything" grows storage with the *number of runs* and
can't tell you *what* changed. This pipeline grows storage only with the *number of
real changes*, and separates two concerns that are easy to conflate:

| Store | Owns | Written when |
|---|---|---|
| `chunk_versions` (SQLite) | Identity + history + diffs | A chunk's content **changes** |
| `scrape_runs` (SQLite) | Freshness / "how current is our picture" | **Every** scheduled run |
| Chroma (local) | Live similarity search | A chunk goes **live** |

Three clocks you should be able to name:
- `chunk_key` = **identity** (stable across time) → content hash
- `changed_at` = when content last **changed**
- `scrape_runs` = when we last **successfully checked the source**

## Architecture

```
                ┌─────────────────────────────────────────────┐
 cron/APScheduler                                              │  FastAPI
   │  /sources/{id}/run                                        │
   ▼                                                           ▼
Firecrawl scrape ──► chunk_text() ──► content_hash() ──► detect_changes()
   (markdown)              │                │                     │
                           │                │              added / removed
                           ▼                ▼                     │
                        SQLite:  chunk_versions (insert ONLY on change)   ScrapeRun (every run)
                           │                                          │
                           ▼ live versions only                        │
                embed (local MiniLM) ──► Chroma upsert/delete           │
                           │                                           │
                           ▼                                           │
                /query  ◄── live vectors + metadata (Path 1)            │
                /history ◄───────────────── SQL lineage (Path 2) ◄─────┘
```

## Quick start

```bash
cp .env.example .env        # set FIRECRAWL_API_KEY
uv venv --python 3.11 && uv pip install -e .
uv run uvicorn app.main:app --reload
```

Firecrawl API key: get one at https://firecrawl.dev (a keyless free tier exists but is
rate-limited; the code currently requires a key).

## API

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/sources` | Register a competitor URL to watch. Body: `{name, url, interval_seconds?}` |
| `GET` | `/sources` | List sources |
| `DELETE` | `/sources/{id}` | Remove a source |
| `POST` | `/sources/{id}/run` | Trigger a scrape now (also runs on schedule) |
| `POST` | `/query` | **Path 1** — live retrieval. Body: `{question, top_k?}` |
| `GET` | `/sources/{id}/history` | **Path 2** — change lineage across versions |

Scheduling: APScheduler runs in-process. Each enabled source scrapes every
`interval_seconds` (default `DEFAULT_INTERVAL_SECONDS`, 6h).

## Project layout

```
app/
├── config.py      # settings from .env
├── db.py          # SQLAlchemy engine/session
├── models.py      # Source, ChunkVersion, ScrapeRun
├── schemas.py     # Pydantic request/response models
├── chunker.py     # plain block chunker + SHA-256 content hashing
├── scraper.py     # Firecrawl wrapper (returns markdown)
├── embeddings.py  # local sentence-transformers embedder
├── vectorstore.py # Chroma: upsert/delete/search live chunks
├── pipeline.py    # CORE: change detection, versioning, embed/delete, history
├── scheduler.py   # APScheduler job registration
└── main.py        # FastAPI routes
```

## The core algorithm (`app/pipeline.py`)

1. **Scrape** the source → markdown text.
2. **Chunk** the text into blocks.
3. **Hash** each block (`content_hash`, SHA-256). Hash *is* the identity `chunk_key`.
4. **Detect changes** against live rows: same hash → *unchanged* (skip); new hash →
   *added*; live hash no longer present → *removed*.
5. **Version**: for each added block, insert a `chunk_versions` row
   (`source_id, chunk_key, version_no, content, changed_at, is_live`). Retire removed
   blocks (`is_live=False, removed_at=now`).
6. **Embed & store**: embed only the *added* live blocks, upsert into Chroma under id
   `"{source_id}:{chunk_key}"`; delete Chroma vectors for removed blocks.
7. **Log the run**: insert a `scrape_runs` row every run, success or failure.

Storage consequence: a page scraped 20× that changed twice yields ~12 chunk rows
(8 stable × 1 + 2 changed × 2), not 200.

## Retrieval paths

- **Path 1 — `/query`**: embed the question, cosine-search Chroma (which only ever
  contains live vectors), return chunks with metadata (`version_no`, `changed_at`,
  `url`). The LLM can then weigh recency.
- **Path 2 — `/history`**: read the `chunk_versions` lineage straight from SQL. No
  vectors involved — diff/reporting is a data problem, not a similarity problem.

## Known limitations / honest gaps

- **Content-hash identity**: an edit to a block changes its hash → new key → surfaces
  as one block *removed* + one *added*, not a per-key old→new text diff. To report
  "price fell 3.99 → 4.49" on *one* key you need a stable structural/semantic chunk id
  instead of a content hash. The current history shows the lineage (which blocks came
  and went) but does not pair old/new text.
- **Firecrawl call is not integration-tested** (needs a real API key).
- **"Last verified" freshness** is recorded in `scrape_runs` but not yet surfaced as
  recency metadata to the LLM in Path 1.
- **No auth / multi-user** — single-tenant by design.

## Deployment

```bash
cp .env.example .env
docker compose up --build
```

SQLite + Chroma persist under `./data` (volume-mounted). Swap `DATABASE_URL` for
Postgres if you outgrow SQLite.

## Development

```bash
# install with dev extras (pytest, ruff)
uv sync --extra dev        # or: uv pip install -e '.[dev]'

# run the suite (live-marked tests are skipped without a Firecrawl key)
pytest

# run the real network/model tests (needs FIRECRAWL_API_KEY set)
pytest -m live

# lint + format
ruff check .
ruff format .

# wipe local state
rm -f data/rag.db && rm -rf data/chroma
```

Tests use isolated `data/test_rag.db` + `data/test_chroma` (auto-cleaned per test);
the scraper and embedder are faked so the suite runs fully offline. Live tests hit the
real Firecrawl API and download the embedding model.
