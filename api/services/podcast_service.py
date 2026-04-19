import os
import io
import httpx
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from core.config import settings
from models.base import Episode, EpisodeRange, EpisodeStatus, Save, Insight


class PodcastService:
    def __init__(self, http_client: httpx.AsyncClient):
        self.http_client = http_client

    async def generate_episode_task(self, session: AsyncSession, episode_id: str):
        from services.llm_service import LLMService
        
        episode = await session.get(Episode, episode_id)
        if not episode:
            return

        try:
            # 1. Gather insights for the range
            now = datetime.now(timezone.utc)
            delta = timedelta(days=1)
            if episode.range == EpisodeRange.WEEK:
                delta = timedelta(days=7)
            elif episode.range == EpisodeRange.MONTH:
                delta = timedelta(days=30)
                
            cutoff = now - delta
            
            stmt = select(Save).where(Save.saved_at >= cutoff)
            result = await session.exec(stmt)
            saves = result.all()
            
            if not saves:
                raise ValueError("No saved insights found for this period.")
                
            insights_context = "Hier zijn de waardevolle opgeslagen inzichten:\n"
            for s in saves:
                insight = await session.get(Insight, s.insight_id)
                if insight:
                    insights_context += f"- Categorie: {s.category}, Inzicht: {insight.text}\n"

            # 2. Script generation via LiteLLM
            llm = LLMService(self.http_client)
            prompt = [
                {
                    "role": "system",
                    "content": (
                        "Je bent de scriptschrijver en host voor een relaxte, wekelijkse podcast "
                        "waarin we persoonlijke inzichten bespreken. Schrijf een monoloog script (max 2 minuten spreektijd) "
                        "in makkelijk uit te spreken Nederlands. Gebruik de meegegeven inzichten vloeiend in de tekst."
                    ),
                },
                {"role": "user", "content": insights_context},
            ]
            
            # Using deep model for script writing
            script = await llm.call_llm("stroom-deep", prompt)
            episode.script = script
            
            # 3. TTS generation via Kokoro
            # Note: Assuming kokoro is accessible. We fallback gracefully if it's down.
            kokoro_url = "http://stroom-kokoro:8880/v1/audio/speech" # Needs to be configured, fallback to localhost 
            payload = {
                "input": script,
                "voice": "af_bella", # Default voice
                "response_format": "mp3",
                "speed": 1.0
            }
            
            try:
                # Kokoro generation
                tts_response = await self.http_client.post(
                    kokoro_url,
                    json=payload,
                    timeout=300.0
                )
                tts_response.raise_for_status()
                audio_bytes = tts_response.read()
                
                # 4. Save to media folder (assuming we are running in stroom-api container mapped to root OR local)
                # Ensure media dir exists
                media_path = "/app/media" if os.path.exists("/app") else os.path.abspath(os.path.join(os.path.dirname(__file__), "../../media"))
                os.makedirs(media_path, exist_ok=True)
                
                filename = f"episode_{episode.id}.mp3"
                file_path = os.path.join(media_path, filename)
                
                with open(file_path, "wb") as f:
                    f.write(audio_bytes)
                
                episode.audio_url = f"/{filename}"
                episode.audio_size_bytes = len(audio_bytes)
                episode.status = EpisodeStatus.READY
                
            except Exception as e:
                episode.error = f"Kokoro TTS or File Save error: {str(e)}"
                episode.status = EpisodeStatus.FAILED
                
            session.add(episode)
            await session.commit()
            
        except Exception as e:
            episode.error = f"Generation error: {str(e)}"
            episode.status = EpisodeStatus.FAILED
            session.add(episode)
            await session.commit()
