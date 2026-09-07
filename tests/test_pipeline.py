from app import pipeline
from app.chunker import chunk_text
from app.models import ChunkVersion, ScrapeRun, Source


def _content(price: str) -> str:
    paras = [
        f"Nestle milk chocolate 100g bar made with cocoa butter and the "
        f"current retail list price of {price} USD for a single unit.",
        "This paragraph covers the ingredients list including sugar and "
        "emulsifiers plus the allergy information in full detail.",
        "Nutritional values per hundred grams with energy fat and protein "
        "and carbohydrate content in a table format.",
        "Shipping is available across Europe with a standard delivery of "
        "two working days for all orders.",
        "Stock availability is shown live on the online storefront with "
        "local pickup options listed per city.",
    ]
    return "\n\n".join(paras)


def _expected_chunks(content: str) -> int:
    return len(chunk_text(content))


def _add_source(db) -> Source:
    src = Source(name="nestle", url="https://competitor.example/nestle")
    db.add(src)
    db.commit()
    db.refresh(src)
    return src


class TestChangeDetection:
    def test_first_scrape_adds_all_and_embeds(self, db, monkeypatch):
        content = _content("3.99")
        _, vectorstore = _install(content, monkeypatch)
        src = _add_source(db)

        run = pipeline.process_source(db, src)
        db.refresh(run)

        n = _expected_chunks(content)
        assert run.status == "success"
        assert run.chunks_added == n
        assert run.chunks_unchanged == 0
        assert len(vectorstore.upserts) == 1  # single batched embed call
        assert len(vectorstore.upserts[0]) == n
        assert vectorstore.deletes == []
        assert db.query(ChunkVersion).count() == n
        assert db.query(ScrapeRun).count() == 1

    def test_unchanged_rescrape_skips_embed(self, db, monkeypatch):
        content = _content("3.99")
        _, vectorstore = _install(content, monkeypatch)
        src = _add_source(db)
        pipeline.process_source(db, src)

        run = pipeline.process_source(db, src)
        db.refresh(run)

        n = _expected_chunks(content)
        assert run.chunks_added == 0
        assert run.chunks_unchanged == n
        assert len(vectorstore.upserts) == 1  # no new embed call
        assert db.query(ChunkVersion).count() == n
        assert db.query(ScrapeRun).count() == 2  # run still logged

    def test_edit_adds_new_version_and_retires_old(self, db, monkeypatch):
        before = _content("3.99")
        _, _ = _install(before, monkeypatch)  # first store (discarded)
        src = _add_source(db)
        pipeline.process_source(db, src)
        first_count = _expected_chunks(before)

        after = _content("4.49")
        _, vectorstore = _install(after, monkeypatch)  # active store for 2nd run
        run = pipeline.process_source(db, src)
        db.refresh(run)

        assert run.status == "success"
        assert run.chunks_added == 1
        assert run.chunks_unchanged == first_count - 1
        # only the changed block was embedded; its stale vector was deleted
        assert len(vectorstore.upserts) == 1
        assert len(vectorstore.upserts[0]) == 1
        assert len(vectorstore.deletes) == 1
        assert len(vectorstore.deletes[0]) == 1

        versions = db.query(ChunkVersion).order_by(ChunkVersion.version_no).all()
        assert len(versions) == first_count + 1
        live = [v for v in versions if v.is_live]
        removed = [v for v in versions if not v.is_live]
        assert len(live) == first_count
        assert len(removed) == 1
        assert removed[0].removed_at is not None

    def test_history_reports_lineage(self, db, monkeypatch):
        before = _content("3.99")
        _install(before, monkeypatch)
        src = _add_source(db)
        pipeline.process_source(db, src)
        first_count = _expected_chunks(before)

        _install(_content("4.49"), monkeypatch)
        pipeline.process_source(db, src)

        history = pipeline.get_history(db, src.id)

        assert len(history) == first_count + 1
        removed = [h for h in history if h["action"] == "removed"]
        live = [h for h in history if h["action"] == "live"]
        assert len(removed) == 1 and removed[0]["removed_at"] is not None
        assert len(live) == first_count

    def test_failed_scrape_logs_failed_run(self, db, monkeypatch):
        import app.pipeline as pl

        class Boom:
            def scrape(self, url):
                raise RuntimeError("network down")

        monkeypatch.setattr(pl, "get_scraper", lambda url: Boom())
        src = _add_source(db)

        run = pipeline.process_source(db, src)
        db.refresh(run)

        assert run.status == "failed"
        assert run.error == "network down"
        assert db.query(ScrapeRun).count() == 1
        assert db.query(ChunkVersion).count() == 0  # nothing versioned

    def test_delete_source_cascades_children(self, db, monkeypatch):
        content = _content("3.99")
        _install(content, monkeypatch)
        src = _add_source(db)
        pipeline.process_source(db, src)

        assert db.query(ScrapeRun).count() == 1
        assert db.query(ChunkVersion).count() == _expected_chunks(content)

        db.delete(src)
        db.commit()

        assert db.query(Source).count() == 0
        assert db.query(ScrapeRun).count() == 0
        assert db.query(ChunkVersion).count() == 0


def _install(text: str, monkeypatch):
    from tests.conftest import install_fakes

    return install_fakes(monkeypatch, text)


class TestConcurrentWrites:
    """Two sources scraped at once must not raise 'database is locked'."""

    def test_parallel_process_source_succeeds(self, monkeypatch):
        import threading
        import time

        from app.db import SessionLocal

        content = _content("3.99")
        barrier = threading.Barrier(2)
        errors: list[Exception] = []

        def fake_scrape(url):
            barrier.wait()  # both threads reach the scrape at the same time
            time.sleep(0.2)  # widen the overlap window
            return content

        class SlowEmbedder:
            def __init__(self):
                self.dim = 384

            def embed(self, texts):
                time.sleep(0.2)
                return [[0.0] * self.dim for _ in texts]

            def embed_query(self, text):
                return [0.0] * self.dim

        class NoopVectorStore:
            def upsert_live(self, **kw):
                pass

            def delete(self, ids):
                pass

        class ScrapeOnce:
            def scrape(self, url):
                return fake_scrape(url)

        monkeypatch.setattr(pipeline, "get_scraper", lambda url: ScrapeOnce())
        monkeypatch.setattr(pipeline, "LocalEmbedder", lambda: SlowEmbedder())
        monkeypatch.setattr(pipeline, "vectorstore", NoopVectorStore())

        # Two sources, each processed in its own thread/session.
        db = SessionLocal()
        s1 = _add_source(db)
        s2 = Source(name="cadbury", url="https://competitor.example/cadbury")
        db.add(s2)
        db.commit()
        db.refresh(s1)
        db.refresh(s2)
        s1_id, s2_id = s1.id, s2.id
        db.close()

        results: dict[int, str] = {}
        run_errors: dict[int, str] = {}

        def run(src_id):
            session = SessionLocal()
            try:
                src = session.get(Source, src_id)
                run = pipeline.process_source(session, src)
                results[src_id] = run.status
                run_errors[src_id] = run.error or ""
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
            finally:
                session.close()

        t1 = threading.Thread(target=run, args=(s1_id,))
        t2 = threading.Thread(target=run, args=(s2_id,))
        t1.start()
        t2.start()
        t1.join(timeout=60)
        t2.join(timeout=60)

        assert not errors, f"concurrent write raised: {errors}"
        assert results == {s1_id: "success", s2_id: "success"}, (
            f"results={results} run_errors={run_errors}"
        )
