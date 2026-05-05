from typing import List, Optional, Literal
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel import select
from sqlalchemy.orm import selectinload

from core.db import get_async_session
from models.base import (
    Item, Insight, ProcessingStatus, InsightCategory,
    Save, Todo, Episode, EpisodeRange, EpisodeStatus,
)
from services.llm_service import LLMService
from services.obsidian_service import ObsidianService
from services.vikunja_service import VikunjaService
from services.podcast_service import PodcastService

router = APIRouter()


class InsightRead(BaseModel):
    id: str
    text: str


class StreamItem(BaseModel):
    id: str
    title: str
    summary: Optional[str]
    type: str
    status: str
    published_at: Optional[str]
    duration: Optional[int]
    insights: List[InsightRead]


class ItemDetail(BaseModel):
    id: str
    title: str
    summary: Optional[str]
    type: str
    insights: List[InsightRead]


class SaveCreate(BaseModel):
    insight_id: str
    category: InsightCategory
    note: Optional[str] = None


class SaveRead(BaseModel):
    id: str
    insight_id: str
    category: InsightCategory
    note: Optional[str]
    obsidian_synced: bool
    obsidian_path: Optional[str]


class TodoCreate(BaseModel):
    insight_id: str
    title: str


class TodoRead(BaseModel):
    id: str
    insight_id: str
    vikunja_task_id: int
    title: str
    done: bool


class EpisodeCreate(BaseModel):
    range: EpisodeRange
    title: str


class EpisodeRead(BaseModel):
    id: str
    range: EpisodeRange
    title: str
    status: EpisodeStatus
    audio_url: Optional[str]


@router.get("/stream", response_model=List[StreamItem])
async def get_stream(
    status: Literal["all", "new", "pinned", "later", "archived"] = "all",
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    session=Depends(get_async_session),
):
    statement = (
        select(Item)
        .where(Item.processing_status == ProcessingStatus.READY)
        .options(selectinload(Item.insights))
        .order_by(Item.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    if status and status != "all":
        statement = statement.where(Item.status == status)

    results = await session.exec(statement)
    items = results.all()

    return [
        StreamItem(
            id=str(item.id),
            title=item.title,
            summary=item.summary,
            type=item.type,
            status=item.status,
            published_at=str(item.published_at) if item.published_at else None,
            duration=item.duration_seconds,
            insights=[InsightRead(id=str(i.id), text=i.text) for i in item.insights],
        )
        for item in items
    ]


@router.get("/items/{item_id}", response_model=ItemDetail)
async def get_item_detail(item_id: str, session=Depends(get_async_session)):
    item = await session.get(Item, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    insights_result = await session.exec(select(Insight).where(Insight.item_id == item.id))
    insights = insights_result.all()

    return ItemDetail(
        id=str(item.id),
        title=item.title,
        summary=item.summary,
        type=item.type,
        insights=[InsightRead(id=str(i.id), text=i.text) for i in insights],
    )


@router.post("/items/{item_id}/regenerate")
async def regenerate_summary(item_id: str, request: Request, session=Depends(get_async_session)):
    llm = LLMService(request.app.state.http_client)
    item = await llm.regenerate_summary(session, item_id)
    return {"id": str(item.id), "summary": item.summary, "status": item.processing_status}


@router.post("/insights/{insight_id}/explore")
async def explore_insight(
    insight_id: str, query: str, request: Request, session=Depends(get_async_session)
):
    llm = LLMService(request.app.state.http_client)
    generator = await llm.explore_insight(session, insight_id, query)
    return StreamingResponse(generator, media_type="text/plain")


@router.post("/saves", response_model=SaveRead)
async def create_save(save_in: SaveCreate, request: Request, session=Depends(get_async_session)):
    insight = await session.get(Insight, save_in.insight_id)
    if not insight:
        raise HTTPException(status_code=404, detail="Insight not found")

    db_save = Save(insight_id=save_in.insight_id, category=save_in.category, note=save_in.note)
    session.add(db_save)
    await session.commit()
    await session.refresh(db_save)

    obsidian = ObsidianService(request.app.state.http_client)
    db_save = await obsidian.push_insight(session, str(db_save.id))

    return SaveRead(
        id=str(db_save.id),
        insight_id=str(db_save.insight_id),
        category=db_save.category,
        note=db_save.note,
        obsidian_synced=db_save.obsidian_synced,
        obsidian_path=db_save.obsidian_path,
    )


@router.post("/todos", response_model=TodoRead)
async def create_todo(todo_in: TodoCreate, request: Request, session=Depends(get_async_session)):
    vikunja = VikunjaService(request.app.state.http_client)
    db_todo = await vikunja.create_task(session, todo_in.insight_id, todo_in.title)
    return TodoRead(
        id=str(db_todo.id),
        insight_id=str(db_todo.insight_id),
        vikunja_task_id=db_todo.vikunja_task_id,
        title=db_todo.title,
        done=db_todo.done,
    )


@router.post("/episodes", response_model=EpisodeRead)
async def create_episode(
    episode_in: EpisodeCreate,
    background_tasks: BackgroundTasks,
    request: Request,
    session=Depends(get_async_session),
):
    db_episode = Episode(range=episode_in.range, title=episode_in.title)
    session.add(db_episode)
    await session.commit()
    await session.refresh(db_episode)

    podcast_svc = PodcastService(request.app.state.http_client)
    background_tasks.add_task(podcast_svc.generate_episode_task, str(db_episode.id))

    return EpisodeRead(
        id=str(db_episode.id),
        range=db_episode.range,
        title=db_episode.title,
        status=db_episode.status,
        audio_url=db_episode.audio_url,
    )
