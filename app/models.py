from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Source(Base):
    """A competitor URL we watch."""

    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    url: Mapped[str] = mapped_column(String(2000), unique=True)
    enabled: Mapped[bool] = mapped_column(default=True)
    interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    versions: Mapped[list["ChunkVersion"]] = relationship(back_populates="source")
    runs: Mapped[list["ScrapeRun"]] = relationship(back_populates="source")


class ChunkVersion(Base):
    """
    One snapshot of one chunk of a source.

    Identity across time = `chunk_key`. Content snapshot = one ROW per (chunk_key, version_no).
    A new row is inserted ONLY when content_hash changes from the latest live row.
    `is_live` marks the newest version; only live versions are embedded in the vector store.
    """

    __tablename__ = "chunk_versions"
    __table_args__ = (
        UniqueConstraint("source_id", "chunk_key", "version_no", name="uq_chunk_version"),
        Index("ix_chunk_live", "source_id", "is_live"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"))
    chunk_key: Mapped[str] = mapped_column(String(200))
    version_no: Mapped[int] = mapped_column(Integer, default=1)
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    is_live: Mapped[bool] = mapped_column(default=True)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    source: Mapped[Source] = relationship(back_populates="versions")


class ScrapeRun(Base):
    """
    Record of EVERY scheduled scrape attempt (whether anything changed or not).

    Enables the freshness signal: 'last successful check of the source'.
    """

    __tablename__ = "scrape_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"))
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(20))  # success | failed
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunks_added: Mapped[int] = mapped_column(Integer, default=0)
    chunks_changed: Mapped[int] = mapped_column(Integer, default=0)
    chunks_unchanged: Mapped[int] = mapped_column(Integer, default=0)

    source: Mapped[Source] = relationship(back_populates="runs")
