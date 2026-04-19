from fastapi import FastAPI, Depends, HTTPException
from sqlmodel import Session, select
from typing import List
from .core.db import get_session
from .models.base import Item, Insight, Source
from .services.llm_service import LLMService

app = FastAPI(title="Stroom API")


@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.get("/stream")
async def get_stream(status: str = "all", session: Session = Depends(get_session)):
    """
    Fetches items for the main stream.
    Filtering by status: 'all', 'new', 'pinned', 'later'.
    """
    statement = select(Item).order_by(Item.created_at.desc())

    if status != "all":
        statement = statement.where(Item.status == status)

    results = session.exec(statement).all()

    # We want to include insights for each item as requested by the frontend
    stream_data = []
    for item in results:
        insights = session.exec(select(Insight).where(Insight.item_id == item.id)).all()
        stream_data.append(
            {
                "id": item.id,
                "title": item.title,
                "summary": item.summary,
                "type": item.type,
                "status": item.status,
                "published_at": item.published_at,
                "duration": item.duration_seconds,
                "insights": [{"id": i.id, "text": i.text} for i in insights],
            }
        )

    return stream_data


@app.get("/items/{item_id}")
async def get_item_detail(item_id: str, session: Session = Depends(get_session)):
    item = session.get(Item, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    insights = session.exec(select(Insight).where(Insight.item_id == item.id)).all()

    return {
        "id": item.id,
        "title": item.title,
        "summary": item.summary,
        "type": item.type,
        "insights": [{"id": i.id, "text": i.text} for i in insights],
    }


@app.post("/items/{item_id}/regenerate")
async def regenerate_summary(item_id: str, session: Session = Depends(get_session)):
    llm = LLMService(session)
    item = await llm.regenerate_summary(item_id)
    return {"id": item.id, "summary": item.summary, "status": item.processing_status}


@app.post("/insights/{insight_id}/explore")
async def explore_insight(
    insight_id: str, query: str, session: Session = Depends(get_session)
):
    llm = LLMService(session)
    response = await llm.explore_insight(insight_id, query)
    return {"response": response}
