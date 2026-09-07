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
    run = ScrapeRun(source_id=source.id, status="success")
    db.add(run)
    db.flush()

    try:
        text = get_scraper(source.url).scrape(source.url)
    except Exception as exc:  # noqa: BLE001 - record any failure for the run log
        run.status = "failed"
        run.error = str(exc)
        run.finished_at = datetime.utcnow()
        db.commit()
        return run

    chunks = chunk_text(text)
    actions, unchanged = detect_changes(db, source.id, chunks)

    added = [a for a in actions if a["action"] == "added"]
    removed = [a for a in actions if a["action"] == "removed"]

    embedder = LocalEmbedder()
    added_texts = [a["content"] for a in added]

    new_version_numbers = _next_version_numbers(db, source.id, len(added))
    now = datetime.utcnow()

    version_rows = []
    ids: list[str] = []
    metadatas: list[dict] = []
    for i, action in enumerate(added):
        version = ChunkVersion(
            source_id=source.id,
            chunk_key=action["chunk_key"],
            version_no=new_version_numbers[i],
            content=action["content"],
            content_hash=action["chunk_key"],
            changed_at=now,
            is_live=True,
        )
        db.add(version)
        version_rows.append(version)
        ids.append(_chroma_id(source.id, action["chunk_key"]))
        metadatas.append(
            {
                "source_id": source.id,
                "url": source.url,
                "chunk_key": action["chunk_key"],
                "version_no": version.version_no,
                "changed_at": now.isoformat(),
            }
        )

    # Retire removed blocks and drop their vectors from the live index.
    for action in removed:
        db.query(ChunkVersion).filter(
            ChunkVersion.source_id == source.id,
            ChunkVersion.chunk_key == action["chunk_key"],
            ChunkVersion.is_live.is_(True),
        ).update({ChunkVersion.is_live: False, ChunkVersion.removed_at: now})

    removed_ids = [_chroma_id(source.id, a["chunk_key"]) for a in removed]

    db.flush()

    if added_texts:
        vectors = embedder.embed(added_texts)
        vectorstore.upsert_live(
            ids=ids, contents=added_texts, embeddings=vectors, metadatas=metadatas
        )
    if removed_ids:
        vectorstore.delete(removed_ids)

    run.chunks_added = len(added)
    run.chunks_changed = 0
    run.chunks_unchanged = unchanged
    run.raw_text = text
    run.finished_at = datetime.utcnow()
    db.commit()
    return run


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
