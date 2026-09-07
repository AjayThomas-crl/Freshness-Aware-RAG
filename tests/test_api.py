from fastapi.testclient import TestClient

from app import pipeline
from app.chunker import chunk_text
from app.main import app

PAGE = (
    "Nestle milk chocolate 100g bar made with cocoa butter and the current "
    "retail list price of 3.99 USD for a single unit.\n\n"
    "This paragraph covers the ingredients list including sugar and "
    "emulsifiers plus the allergy information in full detail.\n\n"
    "Nutritional values per hundred grams with energy fat and protein "
    "and carbohydrate content in a table format.\n\n"
    "Shipping is available across Europe with a standard delivery of "
    "two working days for all orders.\n\n"
    "Stock availability is shown live on the online storefront with "
    "local pickup options listed per city."
)


def _chunk_count() -> int:
    return len(chunk_text(PAGE))


def _start_source(
    client: TestClient, name="nestle", url="https://competitor.example/nestle"
) -> dict:
    resp = client.post("/sources", json={"name": name, "url": url})
    assert resp.status_code == 200
    return resp.json()


class TestSourcesApi:
    def test_create_and_list(self):
        with TestClient(app) as client:
            src = _start_source(client)
            assert src["enabled"] is True
            listed = client.get("/sources").json()
            assert any(s["url"] == src["url"] for s in listed)

    def test_duplicate_source_rejected(self):
        with TestClient(app) as client:
            _start_source(client)
            resp = client.post(
                "/sources", json={"name": "again", "url": "https://competitor.example/nestle"}
            )
            assert resp.status_code == 400

    def test_delete_source(self):
        with TestClient(app) as client:
            src = _start_source(client)
            assert client.delete(f"/sources/{src['id']}").status_code == 200
            assert client.delete(f"/sources/{src['id']}").status_code == 404


class TestRunApi:
    def test_run_reports_counts(self, monkeypatch):
        from tests.conftest import FakeEmbedder, FakeScraper, FakeVectorStore

        embedder, vs = FakeEmbedder(), FakeVectorStore()
        monkeypatch.setattr(pipeline, "get_scraper", lambda url: FakeScraper(PAGE))
        monkeypatch.setattr(pipeline, "LocalEmbedder", lambda: embedder)
        monkeypatch.setattr(pipeline, "vectorstore", vs)

        with TestClient(app) as client:
            src = _start_source(client)
            resp = client.post(f"/sources/{src['id']}/run")
            assert resp.status_code == 200
            body = resp.json()
            assert body["status"] == "success"
            assert body["added"] == _chunk_count()

    def test_run_on_missing_source_404(self):
        with TestClient(app) as client:
            assert client.post("/sources/999/run").status_code == 404


class TestQueryApi:
    def test_query_returns_ranked_chunks(self, monkeypatch, db):
        src = _start_source_sync(db)

        fake_results = [
            {
                "content": "Nestle milk chocolate price 3.99 USD",
                "distance": 0.12,
                "metadata": {
                    "source_id": str(src.id),
                    "url": src.url,
                    "chunk_key": "abc123",
                    "version_no": "1",
                    "changed_at": "2026-09-06T00:00:00",
                },
            }
        ]
        monkeypatch.setattr(pipeline, "query_live", lambda q, top_k=None: fake_results)

        with TestClient(app) as client:
            resp = client.post("/query", json={"question": "how much is the chocolate?"})
            assert resp.status_code == 200
            body = resp.json()
            assert len(body["results"]) == 1
            r = body["results"][0]
            assert r["source_id"] == src.id
            assert r["source_name"] == "nestle"
            assert r["version_no"] == 1
            assert r["changed_at"] == "2026-09-06T00:00:00"


class TestAnswerApi:
    def test_answer_limits_contexts_to_four(self):
        with TestClient(app) as client:
            response = client.post(
                "/answer",
                json={"question": "What changed?", "top_k": 5},
            )
        assert response.status_code == 422

    def test_answer_returns_generated_text_and_contexts(self, monkeypatch):
        from app import main
        from tests.conftest import FakeVectorStore

        source_result = {
            "content": "Alpha Cocoa premium bar costs 6.80 USD.",
            "distance": 0.12,
            "metadata": {
                "source_id": "1",
                "url": "http://localhost:9000/alpha",
                "chunk_key": "abc123",
                "version_no": "4",
                "changed_at": "2026-09-07T12:00:00",
            },
        }
        monkeypatch.setattr(pipeline, "query_live", lambda question, top_k=None: [source_result])

        captured = {}

        class FakeGemini:
            def generate_answer(self, question, contexts):
                captured["question"] = question
                captured["contexts"] = contexts
                return "Alpha Cocoa's premium bar costs 6.80 USD."

        monkeypatch.setattr(main, "GeminiGenerator", FakeGemini)
        monkeypatch.setattr(pipeline, "vectorstore", FakeVectorStore())

        with TestClient(app) as client:
            src = _start_source(client, name="Alpha Cocoa", url="http://localhost:9000/alpha")
            # The fake Chroma metadata uses source id 1 in this isolated test.
            assert src["id"] == 1
            response = client.post(
                "/answer",
                json={"question": "What is the premium bar price?", "top_k": 4},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["answer"] == "Alpha Cocoa's premium bar costs 6.80 USD."
        assert len(body["results"]) == 1
        assert captured["question"] == "What is the premium bar price?"
        assert captured["contexts"][0]["version_no"] == 4


class TestHistoryApi:
    def test_history_empty_for_new_source(self):
        with TestClient(app) as client:
            src = _start_source(client)
            body = client.get(f"/sources/{src['id']}/history").json()
            assert body["changes"] == []

    def test_history_after_run(self, monkeypatch):
        from tests.conftest import FakeEmbedder, FakeScraper, FakeVectorStore

        monkeypatch.setattr(pipeline, "get_scraper", lambda url: FakeScraper(PAGE))
        monkeypatch.setattr(pipeline, "LocalEmbedder", lambda: FakeEmbedder())
        monkeypatch.setattr(pipeline, "vectorstore", FakeVectorStore())

        with TestClient(app) as client:
            src = _start_source(client)
            client.post(f"/sources/{src['id']}/run")
            body = client.get(f"/sources/{src['id']}/history").json()
            assert len(body["changes"]) == _chunk_count()
            assert all(c["action"] == "live" for c in body["changes"])

    def test_history_missing_source_404(self):
        with TestClient(app) as client:
            assert client.get("/sources/999/history").status_code == 404


def _start_source_sync(db):
    """Insert a source directly (outside a request lifecycle) and return the model."""
    from app.models import Source

    src = Source(name="nestle", url="https://competitor.example/nestle-sync")
    db.add(src)
    db.commit()
    db.refresh(src)
    return src
