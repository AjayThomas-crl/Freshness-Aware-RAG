from datetime import datetime

from sqlalchemy.orm import Session

from app import vectorstore
from app.chunker import chunk_text, content_hash
from app.config import settings
from app.embeddings import LocalEmbedder
from app.models import ChunkVersion, ScrapeRun, Source
from app.scraper import get_scraper

# ---------------------------------------------------------------------------
# CORE ALGORITHM (boxed for you to study / rewrite)
# ---------------------------------------------------------------------------


def detect_changes(db: Session, source_id: int, new_chunks: list[str]) -> tuple[list[dict], int]:
    """
    Compare this run's chunks against the source's LIVE chunk versions and
    classify each as: added | removed | unchanged.

    NOTE ON IDENTITY: a chunk's `chunk_key` is its content hash, so any text edit
    yields a NEW key -> surfaces as one removed + one added block. This is robust
    to insertions (only the touched block changes) and makes the history report a
    clean "what came and went" diff. If you later want old->new text on ONE key,
    swap the key for a stable structural/semantic id (see learning notes).

    Returns (actions, unchanged_count) where each action is:
      {"chunk_key", "action", "content"}
    """
    existing = (
        db.query(ChunkVersion)
        .filter(ChunkVersion.source_id == source_id, ChunkVersion.is_live.is_(True))
        .all()
    )
    live_by_key = {v.chunk_key: v for v in existing}

    new_keys = {content_hash(c) for c in new_chunks}

    actions: list[dict] = []
    unchanged = 0

    for text in new_chunks:
        key = content_hash(text)
        if key in live_by_key:
            unchanged += 1
            continue
        actions.append({"chunk_key": key, "action": "added", "content": text})

    for key, version in live_by_key.items():
        if key not in new_keys:
            actions.append({"chunk_key": key, "action": "removed", "content": version.content})

    return actions, unchanged


# ---------------------------------------------------------------------------
# Pipeline orchestration
# ---------------------------------------------------------------------------


def process_source(db: Session, source: Source) -> ScrapeRun:
    """
    Scrape + version one source.

    Ordering matters for SQLite concurrency: ALL slow work (network scrape,
    embedding) happens BEFORE any write, so no transaction is held open across
    them. Writes are batched into one short transaction at the end. If a scrape
    fails, only a small `failed` run row is written.
    """
    source_id = source.id
    url = source.url

    try:
        text = get_scraper(url).scrape(url)
    except Exception as exc:  # noqa: BLE001 - record any failure for the run log
        return _write_failed_run(db, source_id, exc)

    chunks = chunk_text(text)
    actions, unchanged = detect_changes(db, source_id, chunks)

    added = [a for a in actions if a["action"] == "added"]
    removed = [a for a in actions if a["action"] == "removed"]
    added_texts = [a["content"] for a in added]

    now = datetime.utcnow()
    # Capture version numbers and release the read transaction before embedding.
    version_numbers = _next_version_numbers(db, source_id, len(added))
    db.rollback()

    # Slow external work — no DB transaction open during it.
    if added_texts:
        vectors = LocalEmbedder().embed(added_texts)
        vectorstore.upsert_live(
            ids=[_chroma_id(source_id, a["chunk_key"]) for a in added],
            contents=added_texts,
            embeddings=vectors,
            metadatas=_metadata_for(source_id, url, added, version_numbers, now),
        )
    removed_ids = [_chroma_id(source_id, a["chunk_key"]) for a in removed]
    if removed_ids:
        vectorstore.delete(removed_ids)

    # One short write transaction.
    run = ScrapeRun(
        source_id=source_id,
        status="success",
        finished_at=now,
        raw_text=text,
        chunks_added=len(added),
        chunks_changed=0,
        chunks_unchanged=unchanged,
    )
    db.add(run)
    for i, action in enumerate(added):
        db.add(
            ChunkVersion(
                source_id=source_id,
                chunk_key=action["chunk_key"],
                version_no=version_numbers[i],
                content=action["content"],
                content_hash=action["chunk_key"],
                changed_at=now,
                is_live=True,
            )
        )
    for action in removed:
        db.query(ChunkVersion).filter(
            ChunkVersion.source_id == source_id,
            ChunkVersion.chunk_key == action["chunk_key"],
            ChunkVersion.is_live.is_(True),
        ).update({ChunkVersion.is_live: False, ChunkVersion.removed_at: now})
    db.commit()
    return run


def _write_failed_run(db: Session, source_id: int, exc: Exception) -> ScrapeRun:
    run = ScrapeRun(
        source_id=source_id,
        status="failed",
        error=str(exc),
        finished_at=datetime.utcnow(),
    )
    db.add(run)
    db.commit()
    return run


def _metadata_for(
    source_id: int,
    url: str,
    added: list[dict],
    version_numbers: list[int],
    now: datetime,
) -> list[dict]:
    return [
        {
            "source_id": source_id,
            "url": url,
            "chunk_key": action["chunk_key"],
            "version_no": version_numbers[i],
            "changed_at": now.isoformat(),
        }
        for i, action in enumerate(added)
    ]


def _next_version_numbers(db: Session, source_id: int, count: int) -> list[int]:
    if count == 0:
        return []
    start = (
        db.query(ChunkVersion.version_no)
        .filter(ChunkVersion.source_id == source_id)
        .order_by(ChunkVersion.version_no.desc())
        .first()
    )
    base = start[0] if start else 0
    return [base + i + 1 for i in range(count)]


def _chroma_id(source_id: int, chunk_key: str) -> str:
    return f"{source_id}:{chunk_key}"


def query_live(question: str, top_k: int | None = None) -> list[dict]:
    embedder = LocalEmbedder()
    qv = embedder.embed_query(question)
    return vectorstore.search(qv, top_k or settings.top_k)


def get_history(db: Session, source_id: int) -> list[dict]:
    """
    Path 2: change history for a source.

    Each `chunk_versions` row is one distinct content block that went live at
    `changed_at`. If it was later superseded (removed/replaced), it carries
    `removed_at` (when it stopped being live) and is_live=False.

    NOTE (content-hash identity): an edit to a block yields a NEW chunk_key, so
    it surfaces as one row disappearing + one row appearing. To show true
    old->new text on ONE key, swap the key for a stable structural/semantic id.
    This returns the full lineage ordered by appearance.
    """
    versions = (
        db.query(ChunkVersion)
        .filter(ChunkVersion.source_id == source_id)
        .order_by(ChunkVersion.changed_at.asc(), ChunkVersion.id.asc())
        .all()
    )
    return [
        {
            "chunk_key": v.chunk_key,
            "version_no": v.version_no,
            "action": "live" if v.is_live else "removed",
            "changed_at": v.changed_at,
            "removed_at": v.removed_at,
            "content": v.content,
        }
        for v in versions
    ]
