import json
import httpx
from fastapi import HTTPException
from typing import List, Dict, Any
from sqlmodel import select, delete
from sqlmodel.ext.asyncio.session import AsyncSession
from core.config import settings


class LLMService:
    def __init__(self, http_client: httpx.AsyncClient):
        self.http_client = http_client

    async def call_llm(
        self,
        model: str,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        response_format: str = "text",
    ):
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if response_format == "json_object":
            payload["response_format"] = {"type": "json_object"}

        response = await self.http_client.post(
            settings.LITELLM_URL,
            headers={"Authorization": f"Bearer {settings.LITELLM_MASTER_KEY}"},
            json=payload,
            timeout=60.0,
        )

        if response.status_code != 200:
            raise HTTPException(
                status_code=response.status_code,
                detail=f"LiteLLM error: {response.text}",
            )

        return response.json()["choices"][0]["message"]["content"]

    async def regenerate_summary(self, session: AsyncSession, item_id: str):
        from models.base import Item, Insight

        item = await session.get(Item, item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")

        # Dutch prompt with Martin Bril tone (Fase 3 alignment)
        prompt = [
            {
                "role": "system",
                "content": (
                    "Je bent een curator van hoogwaardige content. Je schrijft in een stijl die zakelijk maar "
                    "warm is, met een focus op bruikbaarheid en intellectuele nieuwsgierigheid (denk aan de toon van Martin Bril). "
                    "Analyseer het transcript en lever een JSON-object met: "
                    "1. 'summary': Een compacte, prikkelende samenvatting in het Nederlands (max 3 zinnen). "
                    "2. 'insights': Een lijst van 3-5 concrete, scherpe inzichten ('aha-momenten') in het Nederlands."
                ),
            },
            {"role": "user", "content": f"Transcript: {item.transcript}"},
        ]

        raw_content = await self.call_llm(
            "stroom-bulk", prompt, temperature=0.3, response_format="json_object"
        )

        try:
            data = json.loads(raw_content)

            # 1. Update summary
            item.summary = data.get("summary", item.summary)
            item.processing_status = "ready"

            # 2. Update insights: Delete old and insert new
            await session.exec(delete(Insight).where(Insight.item_id == item.id))

            new_insights_list = data.get("insights", [])
            for idx, text in enumerate(new_insights_list):
                insight = Insight(item_id=item.id, position=idx + 1, text=text)
                session.add(insight)

            session.add(item)
            await session.commit()
            await session.refresh(item)
            return item
        except json.JSONDecodeError:
            raise HTTPException(status_code=500, detail="LLM returned invalid JSON")

    async def explore_insight(
        self, session: AsyncSession, insight_id: str, user_query: str
    ):
        from models.base import Insight, Item

        insight = await session.get(Insight, insight_id)
        if not insight:
            raise HTTPException(status_code=404, detail="Insight not found")

        item = await session.get(Item, insight.item_id)

        # Dutch prompt for deep exploration
        prompt = [
            {
                "role": "system",
                "content": (
                    f"Je bent een analytische expert. De gebruiker wil dieper graven in een specifiek inzicht uit de {item.type} '{item.title}'.\n\n"
                    f"Context van het item: {item.summary}\n\n"
                    f"Het specifieke inzicht: {insight.text}\n\n"
                    "Geef een verdiepend antwoord in het Nederlands. Wees concreet, verbind het met bredere concepten en blijf in de Martin-Bril toon."
                ),
            },
            {"role": "user", "content": user_query},
        ]

        return await self.call_llm("stroom-deep", prompt)
