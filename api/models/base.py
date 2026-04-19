from datetime import datetime
from typing import List, Optional
from uuid import UUID, uuid4
from sqlmodel import SQLModel, Field, Relationship
from pgvector.sqlalchemy import Vector

# --- Enums are handled as strings/literals in SQLModel for simplicity,
# but we can add Pydantic validators later.


class Source(SQLModel, table=True):
    __tablename__ = "sources"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    kind: str  # 'youtube', 'rss', 'podcast'
    name: str
    url: str
    poll_interval_min: int = Field(default=60)
    last_polled_at: Optional[datetime] = None
    last_poll_status: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    items: List["Item"] = Relationship(back_populates="source")


class Item(SQLModel, table=True):
    __tablename__ = "items"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    source_id: UUID = Field(foreign_key="sources.id")
    external_id: str
    type: str  # 'youtube', 'rss', 'podcast'
    title: str
    description: Optional[str] = None
    author: Optional[str] = None
    media_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    published_at: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    transcript: Optional[str] = None
    summary: Optional[str] = None
    summary_model: Optional[str] = None
    summary_generated_at: Optional[datetime] = None
    processing_status: str = Field(default="pending")  # 'pending', 'transcribing', etc.
    processing_error: Optional[str] = None
    status: str = Field(default="new")  # 'new', 'pinned', 'later', 'archived'
    created_at: datetime = Field(default_factory=datetime.utcnow)

    source: Source = Relationship(back_populates="items")
    insights: List["Insight"] = Relationship(back_populates="item")


class Insight(SQLModel, table=True):
    __tablename__ = "insights"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    item_id: UUID = Field(foreign_key="items.id")
    position: int
    text: str
    suggested_category: Optional[str] = None  # 'ideeën', 'quotes', etc.
    embedding: Optional[Vector] = Field(default=None, sa_column=Vector(768))
    created_at: datetime = Field(default_factory=datetime.utcnow)

    item: Item = Relationship(back_populates="insights")


class Save(SQLModel, table=True):
    __tablename__ = "saves"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    insight_id: UUID = Field(foreign_key="insights.id")
    category: str
    note: Optional[str] = None
    obsidian_synced: bool = Field(default=False)
    obsidian_path: Optional[str] = None
    saved_at: datetime = Field(default_factory=datetime.utcnow)


class FeedEvent(SQLModel, table=True):
    __tablename__ = "feed_events"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    item_id: UUID = Field(foreign_key="items.id")
    event_type: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Episode(SQLModel, table=True):
    __tablename__ = "episodes"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    range: str  # 'day', 'week', 'month'
    title: str
    script: Optional[str] = None
    audio_url: Optional[str] = None
    audio_size_bytes: Optional[int] = None
    duration_seconds: Optional[int] = None
    status: str = Field(default="generating")
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Reflection(SQLModel, table=True):
    __tablename__ = "reflections"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    content: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Todo(SQLModel, table=True):
    __tablename__ = "todos"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    insight_id: UUID = Field(foreign_key="insights.id")
    vikunja_task_id: int
    title: str
    done: bool = Field(default=False)
    done_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
