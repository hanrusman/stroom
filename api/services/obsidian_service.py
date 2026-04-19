import json
from datetime import datetime, timezone
import httpx
from fastapi import HTTPException
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from core.config import settings
from models.base import Save, Insight, Item, InsightCategory


class ObsidianService:
    def __init__(self, http_client: httpx.AsyncClient):
        self.http_client = http_client
        
        # Mapping category ENUM to relative folder paths in Obsidian
        self.folder_mapping = {
            InsightCategory.IDEEN: "Inzichten/Ideeën",
            InsightCategory.QUOTES: "Inzichten/Quotes",
            InsightCategory.FILM_TV: "Inzichten/Film & TV",
            InsightCategory.KIDS: "Inzichten/Kids",
            InsightCategory.PODCASTS: "Inzichten/Podcasts",
            InsightCategory.BOEKEN: "Inzichten/Boeken",
        }

    def format_markdown(self, save: Save, insight: Insight, item: Item) -> str:
        """
        Creates a markdown file format with frontmatter for Obsidian.
        """
        
        
        # Frontmatter
        lines = [
            "---",
            f"created: {save.saved_at.isoformat()}",
            f"category: {save.category.value}",
            f"source_type: {item.type.value}",
            f"source_title: \"{item.title}\"",
            "---",
            "",
            f"# {insight.text}",
            ""
        ]
        
        if save.note:
            lines.extend([
                "### Notitie",
                save.note,
                ""
            ])
            
        lines.extend([
            "---",
            f"**Bron:** [{item.title}]({item.media_url or ''})", 
            f"**Geëxporteerd via Stroom**"
        ])
        
        return "\n".join(lines)

    async def push_insight(self, session: AsyncSession, save_id: str) -> Save:
        """
        Pulls a save from DB, formats it, and pushes it to Obsidian.
        Updates the obsidian_synced boolean.
        """
        save = await session.get(Save, save_id)
        if not save:
            raise HTTPException(status_code=404, detail="Save not found")

        insight = await session.get(Insight, save.insight_id)
        if not insight:
            raise HTTPException(status_code=404, detail="Insight not found")
            
        item = await session.get(Item, insight.item_id)
        
        if not settings.OBSIDIAN_API_KEY or not settings.OBSIDIAN_BASE_URL:
            # If no API key configured, we just return the save un-synced.
            return save

        # Prepare payload
        markdown_content = self.format_markdown(save, insight, item)
        folder = self.folder_mapping.get(save.category, "Inzichten/Overig")
        
        # Generate generic filename: insight text max 30 chars, alphanumeric only
        safe_title = "".join(c for c in insight.text[:30] if c.isalnum() or c.isspace()).strip()
        filename = f"{save.saved_at.strftime('%Y%m%d_%H%M%S')} - {safe_title}.md"
        filepath = f"{folder}/{filename}"
        
        # Obsidian Local REST API endpoint
        url = f"{settings.OBSIDIAN_BASE_URL.rstrip('/')}/vault/{filepath}"
        
        headers = {
            "Authorization": f"Bearer {settings.OBSIDIAN_API_KEY}",
            "Content-Type": "text/markdown"
        }
        
        try:
            response = await self.http_client.put(
                url,
                headers=headers,
                content=markdown_content.encode('utf-8'),
                timeout=10.0
            )
            response.raise_for_status()
            
            # Update DB mapping
            save.obsidian_synced = True
            save.obsidian_path = filepath
            
            session.add(save)
            await session.commit()
            await session.refresh(save)
            
        except Exception as e:
            # If Obsidian is down or something failed, we catch it but leave obsidian_synced = False
            # so it can be retried later.
            print(f"Failed to push to Obsidian: {str(e)}")
            
        return save
