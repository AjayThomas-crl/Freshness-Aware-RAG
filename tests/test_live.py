"""
Live integration tests requiring real credentials/network.

These hit the real Firecrawl API (needs FIRECRAWL_API_KEY) and download the
embedding model. They are tagged `live` and skipped by default.

Run with:  pytest -m live
"""

import os

import pytest

pytestmark = pytest.mark.live


def _skip_without_key():
    if not os.getenv("FIRECRAWL_API_KEY"):
        pytest.skip("FIRECRAWL_API_KEY not set")


def test_firecrawl_scrapes_markdown():
    _skip_without_key()
    from app.scraper import FirecrawlScraper

    text = FirecrawlScraper().scrape("https://example.com")
    assert isinstance(text, str) and len(text.strip()) > 0


def test_embedder_produces_384_dim_vectors():
    from app.embeddings import LocalEmbedder

    emb = LocalEmbedder()
    vec = emb.embed_query("chocolate price comparison")
    assert len(vec) == 384


def test_gemini_generates_grounded_answer():
    if not os.getenv("GEMINI_API_KEY"):
        pytest.skip("GEMINI_API_KEY not set")
    from app.llm import GeminiGenerator

    answer = GeminiGenerator().generate_answer(
        "What is the price?",
        [
            {
                "source_name": "Demo competitor",
                "url": "https://example.com",
                "version_no": 1,
                "changed_at": "2026-09-07T00:00:00",
                "content": "The product costs 9.99 USD.",
            }
        ],
    )
    assert isinstance(answer, str) and answer.strip()


def test_full_pipeline_against_local_stores():
    """End-to-end against real SQLite + real Chroma (Firecrawl still faked)."""
    from app import pipeline
    from app.chunker import chunk_text
    from app.db import SessionLocal
    from app.models import Source
    from app.vectorstore import search
    from tests.conftest import FakeScraper

    db = SessionLocal()
    try:
        src = Source(name="example", url="https://example.com")
        db.add(src)
        db.commit()
        db.refresh(src)

        page = (
            "Competitor alpha sells the widget for 9.99 dollars with free "
            "shipping on all orders over fifty dollars placed this month.\n\n"
            "The warranty covers twelve months and includes accidental "
            "damage protection with a claims process that takes days.\n\n"
            "Customer reviews highlight battery life and build quality as "
            "the main reasons people choose this product over rivals.\n\n"
            "The latest firmware update added a companion mobile application "
            "with usage analytics and remote configuration settings."
        )

        # Replace only the network leg; embeddings + Chroma are real.
        pipeline.get_scraper = lambda url: FakeScraper(page)
        run = pipeline.process_source(db, src)
        db.refresh(run)

        assert run.status == "success"
        assert run.chunks_added == len(chunk_text(page))

        from app.embeddings import LocalEmbedder

        qv = LocalEmbedder().embed_query("what is the widget price?")
        hits = search(qv, top_k=5)
        assert len(hits) >= 1
    finally:
        db.close()
