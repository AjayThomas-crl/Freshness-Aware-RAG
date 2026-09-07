import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import settings
from app.db import SessionLocal
from app.models import Source
from app.pipeline import process_source

logger = logging.getLogger("scheduler")

_scheduler: BackgroundScheduler | None = None


def _job(source_id: int) -> None:
    db = SessionLocal()
    try:
        source = db.get(Source, source_id)
        if source and source.enabled:
            run = process_source(db, source)
            logger.info(
                "source=%s status=%s added=%d removed_logged unchanged=%d",
                source.name,
                run.status,
                run.chunks_added,
                run.chunks_unchanged,
            )
    finally:
        db.close()


def start_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.start()
    _refresh_jobs()
    return _scheduler


def _refresh_jobs() -> None:
    assert _scheduler is not None
    db = SessionLocal()
    try:
        sources = db.query(Source).filter(Source.enabled.is_(True)).all()
    finally:
        db.close()

    existing = {job.id for job in _scheduler.get_jobs()}
    wanted = set()
    for source in sources:
        job_id = f"source-{source.id}"
        wanted.add(job_id)
        if job_id not in existing:
            interval = source.interval_seconds or settings.default_interval_seconds
            _scheduler.add_job(
                _job,
                trigger=IntervalTrigger(seconds=interval),
                args=[source.id],
                id=job_id,
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )

    # Drop jobs whose source was deleted.
    for job_id in existing - wanted:
        _scheduler.remove_job(job_id)


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
