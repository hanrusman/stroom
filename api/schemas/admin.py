"""Request/response-modellen voor de admin-endpoints (voorheen in main.py)."""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel


class AdminSource(BaseModel):
    id: str
    name: str
    url: str
    kind: str
    image_url: Optional[str]
    weight: int
    max_per_rail: Optional[int]
    active: bool
    poll_interval_min: int
    topic_slugs: List[str]
    item_count: int


class AdminSourceUpdate(BaseModel):
    name: Optional[str] = None
    url: Optional[str] = None
    kind: Optional[str] = None
    image_url: Optional[str] = None
    weight: Optional[int] = None
    max_per_rail: Optional[int] = None
    active: Optional[bool] = None
    poll_interval_min: Optional[int] = None
    topic_slugs: Optional[List[str]] = None


class AdminSourceCreate(BaseModel):
    name: str
    url: str
    kind: str  # rss / podcast / youtube
    image_url: Optional[str] = None
    weight: int = 5
    max_per_rail: Optional[int] = None
    active: bool = True
    poll_interval_min: int = 60
    topic_slugs: List[str] = []


class BackfillResult(BaseModel):
    inserted: int
    checked: int
    feed_total: int


class QueueItem(BaseModel):
    id: str
    title: str
    source_name: str
    format: str
    processing_status: str
    queued_at: Optional[str]
    queue_position: Optional[int]


class BulkArchiveRequest(BaseModel):
    topic_slugs: List[str]
    older_than_days: int
    weight_max: int = 10
    formats: List[str]  # article, podcast, video, short


class BulkArchiveResponse(BaseModel):
    archived: int


class QualityBackfillRequest(BaseModel):
    limit: int = 100
    only_null: bool = True


class QualityBackfillResponse(BaseModel):
    processed: int
    updated: int
    avg_score: Optional[float] = None
    error: Optional[str] = None


class QualityScorerTopic(BaseModel):
    name: str
    keywords: list[str]


class QualityScorerPerson(BaseModel):
    name: str
    keywords: list[str]


class ExtractKeywordsRequest(BaseModel):
    text: str
    title: Optional[str] = None
    max_keywords: int = 20


class QualityBoostTestResponse(BaseModel):
    topic_slug: str
    quality_boost_factor: float
    per_rail: int
    old_top_items: list[dict]
    new_top_items: list[dict]
    quality_distribution: dict[str, int]
    new_quality_distribution: dict[str, int]
