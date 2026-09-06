import os
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

# Must be set BEFORE any app module is imported so config picks them up.
# Tests use isolated SQLite + Chroma dirs; never touch real data/.
os.environ["DATABASE_URL"] = f"sqlite:///{(REPO_ROOT / 'data' / 'test_rag.db').as_posix()}"
os.environ["CHROMA_DIR"] = str(REPO_ROOT / "data" / "test_chroma")

sys.path.insert(0, str(REPO_ROOT))

import pytest

from app.db import Base, SessionLocal, engine


@pytest.fixture(autouse=True)
def db():
    """Fresh empty schema per test, for every test (incl. TestClient ones)."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


class FakeScraper:
    """Stand-in for FirecrawlScraper: returns canned markdown. Never hits network."""

    def __init__(self, text: str):
        self.text = text

    def scrape(self, url: str) -> str:
        return self.text


class FakeEmbedder:
    """Stand-in for LocalEmbedder: zero vectors of the real dimension. No model load."""

    DIM = 384

    def __init__(self):
        self.calls = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        return [[0.0] * self.DIM for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        return [0.0] * self.DIM


class FakeVectorStore:
    """Records upsert/delete/search calls instead of touching Chroma."""

    def __init__(self):
        self.upserts: list[list[str]] = []
        self.deletes: list[list[str]] = []
        self.search_results: list[dict] = []

    def upsert_live(self, *, ids, contents, embeddings, metadatas) -> None:
        self.upserts.append(list(ids))

    def delete(self, ids) -> None:
        self.deletes.append(list(ids))

    def search(self, query_embedding, top_k) -> list[dict]:
        return self.search_results


def install_fakes(monkeypatch, text: str) -> tuple[FakeEmbedder, FakeVectorStore]:
    """Point app.pipeline at fakes so process_source runs fully offline."""
    from app import pipeline

    embedder = FakeEmbedder()
    vectorstore = FakeVectorStore()

    monkeypatch.setattr(pipeline, "FirecrawlScraper", lambda: FakeScraper(text))
    monkeypatch.setattr(pipeline, "LocalEmbedder", lambda: embedder)
    monkeypatch.setattr(pipeline, "vectorstore", vectorstore)
    return embedder, vectorstore
