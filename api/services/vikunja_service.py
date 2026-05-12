from typing import Optional
import httpx
from fastapi import HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession
from core.config import settings
from models.base import Todo, Insight, Item


class VikunjaService:
    def __init__(self, http_client: httpx.AsyncClient):
        self.http_client = http_client

    async def send_lesson_to_inbox(
        self,
        session: AsyncSession,
        lesson_id: str,
        title: str,
        body: str,
        source_name: str,
        item_title: str,
        media_url: Optional[str],
        topic_name: str
    ) -> int:
        """
        Sends a lesson to Vikunja inbox and returns the task ID.
        """
        from sqlalchemy import text as sa_text
        from datetime import datetime, timezone

        # Build description with all info
        description_parts = [body]
        description_parts.append(f"\n\n**Bron:** {source_name} — {item_title}")
        if media_url:
            description_parts.append(f"\n**Link:** {media_url}")
        description = "".join(description_parts)

        project_id = settings.VIKUNJA_DEFAULT_PROJECT_ID
        url = f"{settings.VIKUNJA_URL.rstrip('/')}/projects/{project_id}/tasks"

        headers = {
            "Authorization": f"Bearer {settings.VIKUNJA_TOKEN}",
            "Content-Type": "application/json"
        }

        payload = {
            "title": title,
            "description": description,
            "labels": [{"title": topic_name}] if topic_name else []
        }

        if not settings.VIKUNJA_TOKEN:
            raise HTTPException(status_code=503, detail="Vikunja not configured — set VIKUNJA_TOKEN in .env")

        try:
            response = await self.http_client.put(
                url,
                headers=headers,
                json=payload,
                timeout=10.0
            )
            response.raise_for_status()
            data = response.json()
            vikunja_task_id = data.get("id")
        except Exception as e:
            print(f"Failed to create task in Vikunja: {str(e)}")
            raise HTTPException(status_code=502, detail="Failed to sync with Vikunja API")

        # Update lesson record with Vikunja task ID
        await session.exec(sa_text(
            "UPDATE lessons SET vikunja_task_id = :task_id, vikunja_sent_at = :sent_at WHERE id = :lesson_id"
        ).bindparams(
            task_id=vikunja_task_id,
            sent_at=datetime.now(timezone.utc),
            lesson_id=lesson_id
        ))
        await session.commit()

        return vikunja_task_id

    async def create_task(self, session: AsyncSession, insight_id: str, title: str) -> Todo:
        """
        Creates a task in Vikunja for a given insight, and saves the Todo record in Postgres.
        """
        insight = await session.get(Insight, insight_id)
        if not insight:
            raise HTTPException(status_code=404, detail="Insight not found")
            
        item = await session.get(Item, insight.item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")

        description = f"**Bron:** [{item.title}]({item.media_url or ''})\n\n**Inzicht:** {insight.text}"

        project_id = settings.VIKUNJA_DEFAULT_PROJECT_ID
        url = f"{settings.VIKUNJA_URL.rstrip('/')}/projects/{project_id}/tasks"
        
        headers = {
            "Authorization": f"Bearer {settings.VIKUNJA_TOKEN}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "title": title,
            "description": description
        }

        if not settings.VIKUNJA_TOKEN:
            raise HTTPException(status_code=503, detail="Vikunja not configured — set VIKUNJA_TOKEN in .env")
        else:
            try:
                response = await self.http_client.put(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=10.0
                )
                response.raise_for_status()
                data = response.json()
                # Vikunja returns the created task, ID is in 'id' field
                vikunja_task_id = data.get("id")
            except Exception as e:
                print(f"Failed to create task in Vikunja: {str(e)}")
                raise HTTPException(status_code=502, detail="Failed to sync with Vikunja API")

        # Create Todo in DB
        db_todo = Todo(
            insight_id=insight.id,
            vikunja_task_id=vikunja_task_id,
            title=title
        )
        
        session.add(db_todo)
        await session.commit()
        await session.refresh(db_todo)
        
        return db_todo
