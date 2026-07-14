"""Response/request-modellen voor de Huygens-endpoints (voorheen in main.py)."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel

from models.base import ItemFormat, ItemStatus, ProcessingStatus


class TopicRead(BaseModel):
    slug: str
    name: str
    item_count: int


class HuygensItem(BaseModel):
    id: str
    title: str
    description: Optional[str]
    author: Optional[str]
    thumbnail_url: Optional[str]
    media_url: Optional[str]
    source_id: str
    source_name: str
    source_image_url: Optional[str]
    published_at: Optional[str]
    format: Optional[str] = None
    status: Optional[str] = None
    processing_status: Optional[str] = None
    has_summary: bool = False
    has_transcript: bool = False
    scheduled_for: Optional[str] = None
    quality_score: Optional[int] = None


class HuygensRail(BaseModel):
    format: ItemFormat
    items: List[HuygensItem]


class HuygensTopic(BaseModel):
    slug: str
    name: str
    rails: List[HuygensRail]


class HuygensItemDetail(BaseModel):
    id: str
    format: ItemFormat
    title: str
    description: Optional[str]
    summary: Optional[str]
    summary_model: Optional[str]
    transcript: Optional[str]
    transcript_segments: Optional[List[dict]] = None
    author: Optional[str]
    media_url: Optional[str]
    thumbnail_url: Optional[str]
    source_id: str
    source_name: str
    source_url: str
    source_image_url: Optional[str]
    published_at: Optional[str]
    topics: List[str]
    status: ItemStatus
    processing_status: ProcessingStatus
    queue_position: Optional[int] = None
    scheduled_for: Optional[str] = None
    quality_score: Optional[int] = None


class StatusUpdate(BaseModel):
    status: ItemStatus


class ScheduleUpdate(BaseModel):
    scheduled_for: Optional[datetime] = None


class SearchHit(BaseModel):
    id: str
    title: str
    format: str
    source_name: str
    published_at: Optional[str]
    snippet: str
    rank: float


class SourceDetail(BaseModel):
    id: str
    name: str
    url: str
    kind: str
    image_url: Optional[str]
    item_count: int


class TranscribeCallback(BaseModel):
    transcript: Optional[str] = None
    transcript_segments: Optional[List[dict]] = None
    summary: Optional[str] = None
    error: Optional[str] = None


class AddItemTopicRequest(BaseModel):
    topic_slug: str


class QualityScoreUpdate(BaseModel):
    quality_score: Optional[int] = None  # 1-10 or null for neutral
    reason: Optional[str] = None  # ScoreChangeReason value
    note: Optional[str] = None  # Optional free text note


class TopicDigest(BaseModel):
    markdown: Optional[str]
    item_count: Optional[int]
    model: Optional[str]
    window_hours: int
    generated_at: Optional[str]
    is_generating: bool = False
    error: Optional[str] = None


class TopicDigestRun(BaseModel):
    id: str
    generated_at: str
    model: Optional[str]
    item_count: Optional[int]
    markdown: str
