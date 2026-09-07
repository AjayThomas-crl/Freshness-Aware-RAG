"""
Seed a rich change history through the REAL pipeline for demos/docs.

Builds deterministic competitor snapshots (from demo/competitor_site.py) and
feeds them through process_source just as a scheduled run would — so SQLite
(chunk_versions + scrape_runs) and Chroma (live index) are populated without
waiting on the timer or needing Firecrawl.

Usage (from repo root):
    uv run python scripts/seed_history.py            # seed into data/rag.db
    uv run python scripts/seed_history.py --fresh    # wipe db+chroma first
"""

import argparse
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# Point config at the runtime store BEFORE importing app modules.
import os

os.environ.setdefault("DATABASE_URL", f"sqlite:///{(REPO / 'data' / 'rag.db').as_posix()}")
os.environ.setdefault("CHROMA_DIR", str(REPO / "data" / "chroma"))

from app import pipeline
from app.db import SessionLocal, init_db
from app.htmltext import html_to_text
from app.models import Source
from demo import competitor_site as site

# (epoch offsets, description) — monotonic ticks exercising price drift,
# promo rotation, and the rotating limited product.
SCENARIO = {
    "alpha": ([0, 1, 2, 4, 7], "Alpha Cocoa"),
    "beta": ([0, 2, 3, 6, 8], "Beta Beverages"),
}


def wipe() -> None:
    import shutil

    db_path = REPO / "data" / "rag.db"
    chroma_dir = REPO / "data" / "chroma"
    db_path.unlink(missing_ok=True)
    shutil.rmtree(chroma_dir, ignore_errors=True)
    print("wiped data/rag.db and data/chroma")


def upsert_source(db, url: str, name: str, interval_seconds: int) -> Source:
    src = db.query(Source).filter(Source.url == url).first()
    if src is None:
        src = Source(name=name, url=url, interval_seconds=interval_seconds)
        db.add(src)
        db.commit()
        db.refresh(src)
    return src


def main(fresh: bool) -> None:
    if fresh:
        wipe()
    init_db()
    db = SessionLocal()
    try:
        for name, (epochs, label) in SCENARIO.items():
            url = f"http://localhost:9000/{name}"
            src = upsert_source(db, url, label, interval_seconds=20)

            for epoch in epochs:
                page = site.render_page(name, epoch)
                text = html_to_text(page)

                class _S:
                    def scrape(self, url, _text=text):
                        return _text

                # Run through the REAL pipeline: embeddings, chroma, versioning.
                real_scraper = pipeline.get_scraper
                try:
                    pipeline.get_scraper = lambda u: _S()
                    run = pipeline.process_source(db, src)
                finally:
                    pipeline.get_scraper = real_scraper

                print(
                    f"{label:14s} tick {epoch:<3d} -> {run.status:8s} "
                    f"added {run.chunks_added} unchanged {run.chunks_unchanged}"
                )
            db.rollback()

        live = db.query(Source).count()
        print(f"\nDone. {live} source(s) seeded. Start the backend + UI and open:")
        print("  history:  GET /sources/{{id}}/history")
        print("  query:    POST /query")
    finally:
        db.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fresh", action="store_true", help="wipe runtime data before seeding")
    args = ap.parse_args()
    main(fresh=args.fresh)
