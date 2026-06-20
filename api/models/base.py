from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID, uuid4
from enum import Enum
from sqlmodel import SQLModel, Field, Relationship
from sqlalchemy import Column
from pgvector.sqlalchemy import Vector


class ContentKind(str, Enum):
    YOUTUBE = "youtube"
    RSS = "rss"
    PODCAST = "podcast"


class ProcessingStatus(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"                    # Generic queue (legacy/compatibility)
    TRANSCRIBE_QUEUED = "transcribe_queued"  # Await A2 GPU (WhisperX)
    TRANSCRIBING = "transcribing"          # A2 GPU busy
    SUMMARIZE_QUEUED = "summarize_queued"  # Await external LLM (Qwen)
    SUMMARIZING = "summarizing"            # External LLM busy
    READY = "ready"
    FAILED = "failed"


class ItemStatus(str, Enum):
    NEW = "new"
    PINNED = "pinned"
    LATER = "later"
    ARCHIVED = "archived"


class InsightCategory(str, Enum):
    IDEEN = "ideeën"
    QUOTES = "quotes"
    FILM_TV = "film-tv"
    KIDS = "kids"
    PODCASTS = "podcasts"
    BOEKEN = "boeken"


class EpisodeRange(str, Enum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"


class EpisodeStatus(str, Enum):
    GENERATING = "generating"
    READY = "ready"
    FAILED = "failed"


class FeedEventType(str, Enum):
    NEW = "new"
    PINNED = "pinned"
    LATER = "later"
    ARCHIVED = "archived"
    VIEWED = "viewed"


class ScoreChangeReason(str, Enum):
    AUTO = "auto"                          # Automatisch door systeem
    WRONG_TOPIC = "wrong_topic"            # Verkeerd onderwerp
    TOO_MANY_ADS = "too_many_ads"          # Te veel reclame
    LOW_QUALITY = "low_quality"            # Lage technische kwaliteit
    HIGH_QUALITY = "high_quality"          # Hoge kwaliteit, moet hoger
    PERSONAL_INTEREST = "personal_interest"  # Persoonlijke interesse
    NOT_INTERESTING = "not_interesting"    # Niet interessant
    OTHER = "other"                        # Anders


class ItemFormat(str, Enum):
    # Volgorde is bewust podcast → video → article → short: dit bepaalt de
    # rij-volgorde van de rails op de tijdlijn-pagina (de frontend rendert
    # ze in de volgorde waarin ze uit de backend komen — zie main.py:_build_rails).
    # TODO 2026-06-20: short is uitgecommentarieerd. Short-form items
    # worden niet meer ondersteund; als we 'm later terug willen zetten,
    # SHORT weer uncommenten + in App.tsx de ShortCard / RAIL_META.short
    # / FORMAT_BADGE.short weer aanzetten (zie TODO-commentaar aldaar).
    PODCAST = "podcast"
    VIDEO = "video"
    ARTICLE = "article"
    # SHORT = "short"


class Topic(SQLModel, table=True):
    __tablename__ = "topics"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    slug: str = Field(unique=True, index=True)
    name: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SourceTopic(SQLModel, table=True):
    __tablename__ = "source_topics"
    source_id: UUID = Field(foreign_key="sources.id", primary_key=True)
    topic_id: UUID = Field(foreign_key="topics.id", primary_key=True)


class ItemTopic(SQLModel, table=True):
    __tablename__ = "item_topics"
    item_id: UUID = Field(foreign_key="items.id", primary_key=True)
    topic_id: UUID = Field(foreign_key="topics.id", primary_key=True)


class Source(SQLModel, table=True):
    __tablename__ = "sources"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    kind: ContentKind
    name: str
    url: str
    poll_interval_min: int = Field(default=60)
    last_polled_at: Optional[datetime] = None
    last_poll_status: Optional[str] = None
    image_url: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    items: List["Item"] = Relationship(back_populates="source")


class Item(SQLModel, table=True):
    __tablename__ = "items"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    source_id: UUID = Field(foreign_key="sources.id")
    external_id: str
    type: ContentKind
    format: Optional[ItemFormat] = None
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
    processing_status: ProcessingStatus = Field(default=ProcessingStatus.PENDING)
    processing_error: Optional[str] = None
    status: ItemStatus = Field(default=ItemStatus.NEW)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Quality score tracking
    quality_score_updated_at: Optional[datetime] = None
    quality_score_reason: Optional[ScoreChangeReason] = None
    quality_score_note: Optional[str] = None

    source: Source = Relationship(back_populates="items")
    insights: List["Insight"] = Relationship(back_populates="item")


class Insight(SQLModel, table=True):
    __tablename__ = "insights"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    item_id: UUID = Field(foreign_key="items.id")
    position: int
    text: str
    suggested_category: Optional[InsightCategory] = None
    embedding: Optional[List[float]] = Field(
        default=None, sa_column=Column(Vector(768))
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    item: Item = Relationship(back_populates="insights")


class Save(SQLModel, table=True):
    __tablename__ = "saves"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    insight_id: UUID = Field(foreign_key="insights.id")
    category: InsightCategory
    note: Optional[str] = None
    obsidian_synced: bool = Field(default=False)
    obsidian_path: Optional[str] = None
    saved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class FeedEvent(SQLModel, table=True):
    __tablename__ = "feed_events"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    item_id: UUID = Field(foreign_key="items.id")
    event_type: FeedEventType
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Episode(SQLModel, table=True):
    __tablename__ = "episodes"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    range: EpisodeRange
    title: str
    script: Optional[str] = None
    audio_url: Optional[str] = None
    audio_size_bytes: Optional[int] = None
    duration_seconds: Optional[int] = None
    status: EpisodeStatus = Field(default=EpisodeStatus.GENERATING)
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Reflection(SQLModel, table=True):
    __tablename__ = "reflections"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    content: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Todo(SQLModel, table=True):
    __tablename__ = "todos"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    insight_id: UUID = Field(foreign_key="insights.id")
    vikunja_task_id: int
    title: str
    done: bool = Field(default=False)
    done_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
