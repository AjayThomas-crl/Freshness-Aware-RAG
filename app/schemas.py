from datetime import datetime

from pydantic import BaseModel, Field


class SourceCreate(BaseModel):
    name: str
    url: str = Field(..., description="Competitor page to watch")
    interval_seconds: int | None = None


class SourceOut(BaseModel):
    id: int
    name: str
    url: str
    enabled: bool
    interval_seconds: int | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ChunkChange(BaseModel):
    chunk_key: str
    version_no: int
    action: str  # live | removed
    changed_at: datetime
    removed_at: datetime | None = None
    content: str


class HistoryOut(BaseModel):
    source_id: int
    changes: list[ChunkChange]


class QueryIn(BaseModel):
    question: str
    top_k: int | None = None


class RetrievedChunk(BaseModel):
    source_id: int
    source_name: str
    url: str
    chunk_key: str
    version_no: int
    changed_at: datetime
    content: str
    distance: float


class QueryOut(BaseModel):
    question: str
    results: list[RetrievedChunk]


class RunOut(BaseModel):
    run_id: int
    source_id: int
    status: str
    added: int
    changed: int
    unchanged: int
