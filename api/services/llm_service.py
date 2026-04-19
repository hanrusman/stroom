import os
import httpx
from fastapi import HTTPException
from typing import List, Dict, Any
from sqlmodel import Session, select
from .core.db import get_session
from ..models.base import Item, Insight

LITELLM_URL = os.getenv("LITELLM_URL", "http://stroom-litellm:4000/v1/chat/completions")
LITELLM_KEY = os.getenv("LITELLM_MASTER_KEY", "sk-default")


class LLMService:
    def __init__(self, session: Session):
        self.session = session

    async def call_llm(
        self, model: str, messages: List[Dict[str, str]], temperature: float = 0.7
    ):
        async with httpx.AsyncClient() as client:
            response = await client.post(
                LITELLM_URL,
                headers={"Authorization": f"Bearer {LITELLM_KEY}"},
                json={"model": model, "messages": messages, "temperature": temperature},
                timeout=60.0,
            )
            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"LiteLLM error: {response.text}",
                )

            return response.json()["choices"][0]["message"]["content"]

    async def regenerate_summary(self, item_id: str):
        item = self.session.get(Item, item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")

        # Use 'stroom-bulk' for summaries (Qwen 3.6)
        prompt = [
            {
                "role": "system",
                "content": "You are a professional content curator. Create a concise, engaging summary and a list of high-impact insights from the following transcript. Format as JSON: { 'summary': '...', 'insights': ['...', '...'] }",
            },
            {"role": "user", "content": f"Transcript: {item.transcript}"},
        ]

        new_content = await self.call_llm("stroom-bulk", prompt)
        # Note: In a real implementation, we would parse the JSON here and update the DB.
        # For this foundation, we'll update the summary and mark as processed.
        item.summary = new_content
        item.processing_status = "ready"
        self.session.add(item)
        self.session.commit()
        self.session.refresh(item)
        return item

    async def explore_insight(self, insight_id: str, user_query: str):
        # Find the insight and its parent item for context
        insight = self.session.get(Insight, insight_id)
        if not insight:
            raise HTTPException(status_code=404, detail="Insight not found")

        item = self.session.get(Item, insight.item_id)

        # Use 'stroom-deep' for exploration (Opus 4.7 / High reasoning)
        prompt = [
            {
                "role": "system",
                "content": f"You are an expert analyst. The user is exploring a specific insight from a {item.type} called '{item.title}'.\n\nItem Summary: {item.summary}\n\nSpecific Insight: {insight.text}",
            },
            {"role": "user", "content": user_query},
        ]

        return await self.call_llm("stroom-deep", prompt)
