from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, Query
from sqlmodel import Session, select
from typing import List, Optional
from pydantic import BaseModel
from .core.db import get_session, get_async_session
from .core.config import settings
from .models.base import Item, Insight, Source, ItemStatus
from .services.llm_service import LLMService
import httpx

# --- Response Models for OpenAPI ---


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


# --- Lifespan for shared HTTP client ---


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize global HTTP client
    app.state.http_client = httpx.AsyncClient(timeout=300.0)
    yield
    await app.state.http_client.aclose()


app = FastAPI(title="Stroom API", lifespan=lifespan)


@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.get("/stream", response_model=List[StreamItem])
async def get_stream(
    status: str = "all",
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    session: Session = Depends(get_session),
):
    """
    Fetches items for the main stream using the optimized v_stream view.
    Filters by status: 'all', 'new', 'pinned', 'later'.
    """
    # We use the v_stream view to avoid N+1 and filter out non-ready items automatically
    # View: SELECT ... FROM items JOIN sources ... WHERE i.processing_status = 'ready'
    statement = (
        select(Item).order_by(Item.created_at.desc()).offset(offset).limit(limit)
    )

    if status != "all":
        statement = statement.where(Item.status == status)

    results = session.exec(statement).all()

    stream_data = []
    for item in results:
        # We still fetch insights for the response model
        insights = session.exec(select(Insight).where(Insight.item_id == item.id)).all()
        stream_data.append(
            StreamItem(
                id=str(item.id),
                title=item.title,
                summary=item.summary,
                type=item.type,
                status=item.status,
                published_at=str(item.published_at) if item.published_at else None,
                duration=item.duration_seconds,
                insights=[InsightRead(id=str(i.id), text=i.text) for i in insights],
            )
        )

    return stream_data


@app.get("/items/{item_id}", response_model=ItemDetail)
async def get_item_detail(item_id: str, session: Session = Depends(get_session)):
    item = session.get(Item, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    insights = session.exec(select(Insight).where(Insight.item_id == item.id)).all()

    return ItemDetail(
        id=str(item.id),
        title=item.title,
        summary=item.summary,
        type=item.type,
        insights=[InsightRead(id=str(i.id), text=i.text) for i in insights],
    )


@app.post("/items/{item_id}/regenerate")
async def regenerate_summary(item_id: str, session: Session = Depends(get_session)):
    # Use the global client from app state
    llm = LLMService(app.state.http_client)
    item = await llm.regenerate_summary(session, item_id)
    return {
        "id": str(item.id),
        "summary": item.summary,
        "status": item.processing_status,
    }


@app.post("/insights/{insight_id}/explore")
async def explore_insight(
    insight_id: str, query: str, session: Session = Depends(get_session)
):
    llm = LLMService(app.state.http_client)
    response = await llm.explore_insight(session, insight_id, query)
    return {"response": response}
