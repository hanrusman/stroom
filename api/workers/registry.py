"""Start/stop van de achtergrond-workers, aangeroepen vanuit de lifespan."""
from __future__ import annotations

import asyncio

from fastapi import FastAPI

from core.config import settings
from core.db import async_session_maker
from workers.monitor import queue_depth_logger
from workers.summarize import summarize_worker
from workers.transcribe import transcribe_worker


async def start_workers(app: FastAPI) -> list[asyncio.Task]:
    tasks: list[asyncio.Task] = []
    for i in range(settings.SUMMARIZE_WORKERS):
        tasks.append(asyncio.create_task(summarize_worker(app, i, async_session_maker)))
    tasks.append(asyncio.create_task(transcribe_worker(async_session_maker)))
    tasks.append(asyncio.create_task(queue_depth_logger(async_session_maker)))
    return tasks


async def stop_workers(tasks: list[asyncio.Task]) -> None:
    for t in tasks:
        t.cancel()
    for t in tasks:
        try:
            await t
        except asyncio.CancelledError:
            pass
