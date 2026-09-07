from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy.orm import Session

from app import pipeline, scheduler, vectorstore
from app.db import get_db, init_db
from app.llm import GeminiGenerator, GeminiUnavailableError
from app.models import Source
from app.schemas import (
    AnswerIn,
    AnswerOut,
    ChunkChange,
    HistoryOut,
    QueryIn,
    QueryOut,
    RetrievedChunk,
    RunOut,
    SourceCreate,
    SourceOut,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    scheduler.start_scheduler()
    yield
    scheduler.stop_scheduler()


app = FastAPI(title="Freshness-Aware RAG", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/sources", response_model=SourceOut)
def create_source(body: SourceCreate, db: Session = Depends(get_db)):
    if db.query(Source).filter(Source.url == body.url).first():
        raise HTTPException(400, "Source already exists")
    source = Source(
        name=body.name,
        url=body.url,
        interval_seconds=body.interval_seconds,
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    scheduler._refresh_jobs()
    return source


@app.get("/sources", response_model=list[SourceOut])
def list_sources(db: Session = Depends(get_db)):
    return db.query(Source).all()


@app.delete("/sources/{source_id}")
def delete_source(source_id: int, db: Session = Depends(get_db)):
    source = db.get(Source, source_id)
    if not source:
        raise HTTPException(404, "Source not found")
    vectorstore.delete_for_source(source_id)
    db.delete(source)
    db.commit()
    scheduler._refresh_jobs()
    return {"ok": True}


@app.post("/sources/{source_id}/run", response_model=RunOut)
def run_source_now(source_id: int, db: Session = Depends(get_db)):
    source = db.get(Source, source_id)
    if not source:
        raise HTTPException(404, "Source not found")
    run = pipeline.process_source(db, source)
    return RunOut(
        run_id=run.id,
        source_id=run.source_id,
        status=run.status,
        added=run.chunks_added,
        changed=run.chunks_changed,
        unchanged=run.chunks_unchanged,
    )


@app.post("/query", response_model=QueryOut)
def query(body: QueryIn, db: Session = Depends(get_db)):
    """Path 1: retrieve live chunks by similarity. Freshness metadata rides along."""
    out = _retrieve(db, body.question, body.top_k)
    return QueryOut(question=body.question, results=out)


def _retrieve(db: Session, question: str, top_k: int | None) -> list[RetrievedChunk]:
    results = pipeline.query_live(question, top_k)
    db_sources = {s.id: s for s in db.query(Source).all()}
    out = []
    for r in results:
        meta = r["metadata"]
        source = db_sources.get(int(meta.get("source_id", 0)))
        out.append(
            RetrievedChunk(
                source_id=int(meta["source_id"]),
                source_name=source.name if source else "?",
                url=meta.get("url", ""),
                chunk_key=meta.get("chunk_key", ""),
                version_no=int(meta.get("version_no", 0)),
                changed_at=meta.get("changed_at", ""),
                content=r["content"],
                distance=r["distance"],
            )
        )
    return out


@app.post("/answer", response_model=AnswerOut)
def answer(body: AnswerIn, db: Session = Depends(get_db)):
    """Retrieve the top contexts, then synthesize a grounded Gemini answer."""
    contexts = _retrieve(db, body.question, body.top_k)
    try:
        generated = GeminiGenerator().generate_answer(
            body.question,
            [context.model_dump() for context in contexts],
        )
    except GeminiUnavailableError as exc:
        raise HTTPException(503, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, f"Gemini request failed: {exc}") from exc
    return AnswerOut(question=body.question, answer=generated, results=contexts)


@app.get("/sources/{source_id}/history", response_model=HistoryOut)
def history(source_id: int, db: Session = Depends(get_db)):
    """Path 2: change history / diff across versions for a source."""
    if not db.get(Source, source_id):
        raise HTTPException(404, "Source not found")
    changes = pipeline.get_history(db, source_id)
    return HistoryOut(
        source_id=source_id,
        changes=[ChunkChange(**c) for c in changes],
    )
