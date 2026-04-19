import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

import httpx
import soundfile as sf
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from models.base import Episode, EpisodeRange, EpisodeStatus, Insight, Save

logger = logging.getLogger(__name__)

MEDIA_DIR = os.environ.get("MEDIA_DIR", "/app/media")
MODEL_DIR = os.environ.get("KOKORO_MODEL_DIR", "/app/models")
KOKORO_MODEL = os.path.join(MODEL_DIR, "kokoro-v0_19.onnx")
KOKORO_VOICES = os.path.join(MODEL_DIR, "voices.bin")

_kokoro = None


def _get_kokoro():
    """Lazily load Kokoro-ONNX (in-process TTS). Model files must exist at MODEL_DIR."""
    global _kokoro
    if _kokoro is None:
        from kokoro_onnx import Kokoro

        if not os.path.exists(KOKORO_MODEL) or not os.path.exists(KOKORO_VOICES):
            raise RuntimeError(
                f"Kokoro model files not found in {MODEL_DIR}. "
                "Download kokoro-v0_19.onnx and voices.bin from "
                "https://huggingface.co/hexgrad/Kokoro-82M and place them there."
            )
        _kokoro = Kokoro(KOKORO_MODEL, KOKORO_VOICES)
    return _kokoro


class PodcastService:
    def __init__(self, http_client: httpx.AsyncClient):
        self.http_client = http_client

    async def generate_episode_task(self, episode_id: str):
        """
        Background task — creates its own DB session so the request session
        (which closes when the HTTP response is sent) is never used here.
        """
        from core.db import async_engine
        from services.llm_service import LLMService

        async with AsyncSession(async_engine) as session:
            episode = await session.get(Episode, episode_id)
            if not episode:
                return

            try:
                script = await self._generate_script(session, episode)
                episode.script = script

                audio_bytes, sample_rate = await asyncio.get_event_loop().run_in_executor(
                    None, self._synthesize, script
                )

                os.makedirs(MEDIA_DIR, exist_ok=True)
                filename = f"episode_{episode.id}.wav"
                file_path = os.path.join(MEDIA_DIR, filename)
                await asyncio.get_event_loop().run_in_executor(
                    None, lambda: sf.write(file_path, audio_bytes, sample_rate)
                )

                episode.audio_url = f"/{filename}"
                episode.audio_size_bytes = os.path.getsize(file_path)
                episode.duration_seconds = int(len(audio_bytes) / sample_rate)
                episode.status = EpisodeStatus.READY

            except Exception as e:
                logger.exception("Podcast generation failed for episode %s", episode_id)
                episode.error = str(e)
                episode.status = EpisodeStatus.FAILED

            session.add(episode)
            await session.commit()

    async def _generate_script(self, session: AsyncSession, episode: Episode) -> str:
        from services.llm_service import LLMService

        delta = {
            EpisodeRange.DAY: timedelta(days=1),
            EpisodeRange.WEEK: timedelta(days=7),
            EpisodeRange.MONTH: timedelta(days=30),
        }[episode.range]
        cutoff = datetime.now(timezone.utc) - delta

        result = await session.exec(select(Save).where(Save.saved_at >= cutoff))
        saves = result.all()
        if not saves:
            raise ValueError("Geen opgeslagen inzichten gevonden voor deze periode.")

        insights_context = "Hier zijn de waardevolle opgeslagen inzichten:\n"
        for s in saves:
            insight = await session.get(Insight, s.insight_id)
            if insight:
                insights_context += f"- Categorie: {s.category.value}, Inzicht: {insight.text}\n"

        llm = LLMService(self.http_client)
        return await llm.call_llm(
            "stroom-deep",
            [
                {
                    "role": "system",
                    "content": (
                        "Je bent de scriptschrijver en host voor een relaxte, wekelijkse podcast "
                        "waarin persoonlijke inzichten worden besproken. Schrijf een monoloog "
                        "(max 2 minuten spreektijd) in vloeiend, makkelijk uit te spreken Nederlands. "
                        "Gebruik de meegegeven inzichten organisch in de tekst. Geen opsommingen — "
                        "een doorlopend verhaal."
                    ),
                },
                {"role": "user", "content": insights_context},
            ],
        )

    @staticmethod
    def _synthesize(script: str):
        """Synchronous Kokoro-ONNX call — run in executor to avoid blocking the event loop."""
        kokoro = _get_kokoro()
        samples, sample_rate = kokoro.create(script, voice="af_bella", speed=1.0, lang="en-us")
        return samples, sample_rate
