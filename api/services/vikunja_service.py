import httpx
from fastapi import HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession
from core.config import settings
from models.base import Todo, Insight, Item


class VikunjaService:
    def __init__(self, http_client: httpx.AsyncClient):
        self.http_client = http_client

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

        description = f"**Bron:** [{item.title}]({item.url if hasattr(item, 'url') else ''})\n\n**Inzicht:** {insight.text}"

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
            # If no token is provided, just simulate for dev
            vikunja_task_id = 9999
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
