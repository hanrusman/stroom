"""Bounded VoiceStudio client and persistent, single-worker test queue.

No local ML imports, model downloads or LLM rewriting. Input is spoken as supplied.
The transaction-scoped GPU lock is shared with Stroom's transcriber and scorer:
they take it in shared mode (so they never block each other), a GPU render takes
it exclusively. CPU-only Kitten never touches it. A separate converter lock keeps
one render at a time. External tenants (e.g. Immich) are only observed through
the optional host gate.
"""
import asyncio
import hashlib
import logging
import math
import os
import shutil
import time
from pathlib import Path
from uuid import UUID, uuid4

import httpx
from sqlalchemy import text as sql

log = logging.getLogger(__name__)
GPU_LOCK = 73102401
QUEUE_LOCK = 73102402
CONVERTER_LOCK = 73102403
MAX_TEXT = 4000
MAX_AUDIO_BYTES = 32 * 1024 * 1024
MODELS = {
    "omnivoice": ("OmniVoice", 6144),
    "kittentts": ("KittenTTS", 0),
    "cosyvoice": ("CosyVoice 3", 8192),
}


def enabled():
    return bool(os.environ.get("PODCAST_VOICESTUDIO_URL", "").strip())


def media_dir():
    return Path(os.environ.get("PODCAST_MEDIA_DIR", "/data/podcast-tests"))


def audio_path(job_id):
    return media_dir() / f"{UUID(str(job_id))}.mp3"


def voice_for(model):
    return os.environ.get(f"PODCAST_VOICE_{model.upper()}", "default")


def fingerprint(value):
    return hashlib.sha256(value.encode()).hexdigest()


def headers():
    key = os.environ.get("PODCAST_VOICESTUDIO_KEY", "")
    return {"Authorization": f"Bearer {key}"} if key else {}


def base_url():
    return os.environ.get("PODCAST_VOICESTUDIO_URL", "").rstrip("/")


def public_job(row):
    data = dict(row)
    data["id"] = str(data["id"])
    data["model_name"] = MODELS[data["model"]][0]
    for key in ("created_at", "started_at", "finished_at"):
        data[key] = data[key].isoformat() if data.get(key) else None
    data["audio_url"] = f"/api/podcast-tests/{data['id']}/audio" if data["status"] == "ready" else None
    return data


async def catalog(client):
    result = {"configured": enabled(), "max_characters": MAX_TEXT, "models": []}
    entries = {}
    reason = "VoiceStudio is nog niet gekoppeld."
    if enabled():
        try:
            response = await client.get(f"{base_url()}/engines/tts", headers=headers(), timeout=15)
            response.raise_for_status()
            entries = {entry["id"]: entry for entry in response.json()["backends"]}
            reason = "Installeer dit model in VoiceStudio."
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            reason = "VoiceStudio is niet bereikbaar of de koppeling is ongeldig."
    for model, (name, _) in MODELS.items():
        entry = entries.get(model, {})
        # Do not turn heavy TTS into an unexpected CPU workload on Strongbad.
        route = entry.get("routing_status")
        available = entry.get("available") is True and (
            route == "accelerated" or (model == "kittentts" and route == "cpu_only")
        )
        allowed = os.environ.get("PODCAST_ENABLED_MODELS", ",".join(MODELS)).split(",")
        detail = None if available else reason
        if entry.get("available") is True and not available:
            detail = "GPU-versnelling is niet bevestigd. Controleer dit model in VoiceStudio."
        if model not in {value.strip() for value in allowed}:
            available = False
            detail = "Nog niet vrijgegeven binnen het geheugenbudget van Strongbad."
        result["models"].append({"id": model, "name": name, "available": available, "reason": detail})
    return result


def host_gate(stats, model, now=None):
    """Conservative admission only; monitoring cannot reserve another service's GPU."""
    now = time.time() if now is None else now
    try:
        age = now - float(stats["ts"])
        cpu = stats["cpu"]
        load = float(cpu["load1"]) / int(cpu["cores"])
        mem = stats["mem"]
        free_mem = float(mem["total_mib"]) - float(mem["used_mib"])
        root_free = float(stats["disk"]["root"]["avail_gb"])
        metrics = [age, load, free_mem, root_free]
        # CPU-only models must not wait on missing GPU telemetry.
        if uses_gpu(model):
            gpu = next(g for g in stats["gpus"] if "A2" in g["name"])
            free_vram = float(gpu["vram_total_mib"]) - float(gpu["vram_used_mib"])
            util = float(gpu["util_now"])
            metrics += [free_vram, util]
        if not all(math.isfinite(v) for v in metrics):
            raise ValueError("invalid metric")
    except (KeyError, TypeError, ValueError, StopIteration, ZeroDivisionError):
        return "Wachten: capaciteitsgegevens van Strongbad zijn onvolledig."
    if age > 300 or age < -60:
        return "Wachten: capaciteitsgegevens van Strongbad zijn verouderd."
    if load > 0.85:
        return "Wachten: Strongbad heeft een hoge CPU-load."
    if free_mem < 12288 or root_free < 15:
        return "Wachten: onvoldoende vrij werkgeheugen of schijfruimte."
    if uses_gpu(model) and (free_vram < MODELS[model][1] or util > 20):
        return "Wachten: de gedeelde A2 heeft nog onvoldoende vrije capaciteit."
    return None


async def capacity_reason(client, model):
    url = os.environ.get("PODCAST_HOST_STATS_URL", "")
    if not url:
        return None
    try:
        response = await client.get(url, timeout=10, headers={"Cache-Control": "no-cache"})
        response.raise_for_status()
        return host_gate(response.json(), model)
    except (httpx.HTTPError, ValueError):
        return "Wachten: de capaciteitscontrole is niet bereikbaar."


def uses_gpu(model):
    return MODELS[model][1] > 0


async def _try_xact_lock(session, key, shared=False):
    fn = "pg_try_advisory_xact_lock_shared" if shared else "pg_try_advisory_xact_lock"
    return bool((await session.execute(sql(f"SELECT {fn}(:key)"), {"key": key})).scalar())


async def try_gpu_lock(session):
    """Exclusive GPU lease for a podcast render on the A2."""
    return await _try_xact_lock(session, GPU_LOCK)


async def try_gpu_share(session):
    """Shared GPU lease for the transcriber and scorer; excludes only a podcast render."""
    return await _try_xact_lock(session, GPU_LOCK, shared=True)


async def try_converter_lock(session):
    return await _try_xact_lock(session, CONVERTER_LOCK)


async def update_job(session_maker, job_id, **fields):
    # Column names originate only from internal keyword arguments.
    async with session_maker() as session:
        assignments = ", ".join(f"{key}=:{key}" for key in fields)
        await session.execute(sql(f"UPDATE podcast_tests SET {assignments} WHERE id=CAST(:id AS uuid)"),
                              {**fields, "id": str(job_id)})
        await session.commit()


async def render(client, job):
    """Stream MP3 directly to disk; never hold a whole episode in API memory."""
    destination = audio_path(job["id"])
    destination.parent.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(destination.parent).free < 256 * 1024 * 1024:
        raise ValueError("Te weinig vrije ruimte voor het audiobestand.")
    partial = destination.with_suffix(".part")
    size = 0
    try:
        async with client.stream(
            "POST", f"{base_url()}/v1/audio/speech", headers=headers(),
            json={"model": job["model"], "voice": job["voice"], "input": job["text"],
                  "response_format": "mp3", "language": "en", "seed": 42},
            timeout=httpx.Timeout(900, connect=10),
        ) as response:
            response.raise_for_status()
            if response.headers.get("content-type", "").split(";")[0] not in ("audio/mpeg", "audio/mp3"):
                raise ValueError("VoiceStudio gaf geen MP3 terug.")
            # A routing fallback would make model comparisons misleading.
            if response.headers.get("x-stroom-tts-engine") != job["model"] or response.headers.get("x-omnivoice-routing") not in ("accelerated", "cpu_only" if job["model"] == "kittentts" else "accelerated"):
                raise ValueError("VoiceStudio week af van het gekozen model of apparaat. Controleer de configuratie.")
            with partial.open("wb") as output:
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_AUDIO_BYTES:
                        raise ValueError("Audiobestand overschrijdt de limiet van 32 MB.")
                    output.write(chunk)
        if size < 128:
            raise ValueError("VoiceStudio gaf een leeg of onvolledig audiobestand terug.")
        with partial.open("rb") as source:
            magic = source.read(3)
        if not (magic == b"ID3" or (magic[0] == 0xff and magic[1] & 0xe0 == 0xe0)):
            raise ValueError("VoiceStudio gaf een ongeldig MP3-bestand terug.")
        partial.replace(destination)
        return size
    finally:
        partial.unlink(missing_ok=True)


def render_error(exc):
    if isinstance(exc, httpx.HTTPStatusError):
        return {
            401: "VoiceStudio weigert de API-sleutel. Controleer de koppeling.",
            403: "VoiceStudio weigert toegang. Controleer de modelconfiguratie en licentie.",
            429: "VoiceStudio is bezet. Probeer later opnieuw.",
            503: "Dit model is nog niet gereed. Controleer de installatie in VoiceStudio.",
        }.get(exc.response.status_code, "VoiceStudio kon de audio niet maken. Controleer het model en de stem.")
    if isinstance(exc, (httpx.TimeoutException, TimeoutError)):
        return "Generatie duurde te lang. Probeer later een kortere tekst."
    if isinstance(exc, httpx.HTTPError):
        return "De verbinding met VoiceStudio is verbroken."
    if isinstance(exc, ValueError):
        return str(exc)
    return "Generatie mislukt. Controleer de serverlogs en probeer opnieuw."


async def run_next(session_maker, client):
    """A DB transaction owns the converter (and GPU) lease across HTTP rendering, also across replicas."""
    from datetime import datetime, timezone

    async with session_maker() as lease:
        if not await try_converter_lock(lease):
            return False
        # Holding this lock proves no previous converter is still rendering.
        async with session_maker() as session:
            interrupted = (await session.execute(sql("SELECT id FROM podcast_tests WHERE status='rendering'"))).scalars().all()
            for job_id in interrupted:
                audio_path(job_id).with_suffix(".part").unlink(missing_ok=True)
                audio_path(job_id).unlink(missing_ok=True)
            await session.execute(sql("""
                UPDATE podcast_tests SET status='failed', finished_at=now(),
                    message='Generatie onderbroken door een herstart. Probeer opnieuw.'
                WHERE status='rendering'
            """))
            await session.execute(sql("""
                UPDATE podcast_tests SET status='failed', finished_at=now(),
                    message='Na een uur wachten geen capaciteit beschikbaar. Probeer later opnieuw.'
                WHERE status='queued' AND created_at < now() - interval '1 hour'
            """))
            job = (await session.execute(sql("SELECT * FROM podcast_tests WHERE status='queued' ORDER BY created_at LIMIT 1"))).mappings().first()
            await session.commit()
            if not job:
                return False
            job = dict(job)
        reason = None
        if uses_gpu(job["model"]):
            # Lock first, then check: a transcribe claim that commits later must see our lock.
            if not await try_gpu_lock(lease):
                reason = "Wachten: de A2 is bezet door transcriptie of de decision-scorer."
            else:
                async with session_maker() as session:
                    if (await session.execute(sql(
                        "SELECT EXISTS(SELECT 1 FROM items WHERE processing_status::text='transcribing')"
                    ))).scalar():
                        reason = "Wachten: Stroom transcribeert nog audio."
        if not reason:
            reason = await capacity_reason(client, job["model"])
        if reason:
            await update_job(session_maker, job["id"], message=reason)
            return False
        # Conditional: the job may have been deleted while it was still queued.
        async with session_maker() as session:
            claimed = (await session.execute(sql("""
                UPDATE podcast_tests SET status='rendering', message=NULL, started_at=:now
                WHERE id=CAST(:id AS uuid) AND status='queued'
            """), {"id": str(job["id"]), "now": datetime.now(timezone.utc)})).rowcount
            await session.commit()
        if not claimed:
            return True
        started = time.monotonic()
        try:
            # Availability may have changed since the user queued the request.
            models = (await catalog(client))["models"]
            if not any(m["id"] == job["model"] and m["available"] for m in models):
                raise ValueError("Het gekozen model is niet beschikbaar. Controleer VoiceStudio en de vrijgegeven modellen.")
            async with asyncio.timeout(900):
                size = await render(client, job)
            await update_job(session_maker, job["id"], status="ready", audio_bytes=size,
                             elapsed_seconds=round(time.monotonic() - started, 1),
                             finished_at=datetime.now(timezone.utc), message=None)
        except asyncio.CancelledError:
            await update_job(session_maker, job["id"], status="failed",
                             finished_at=datetime.now(timezone.utc),
                             message="Generatie onderbroken door een herstart. Probeer opnieuw.")
            raise
        except Exception as exc:
            log.warning("Podcast %s failed (%s)", job["id"], type(exc).__name__)
            await update_job(session_maker, job["id"], status="failed", message=render_error(exc),
                             finished_at=datetime.now(timezone.utc))
        return True


async def worker(session_maker):
    async with httpx.AsyncClient(limits=httpx.Limits(max_connections=2), follow_redirects=False) as client:
        while True:
            try:
                worked = await run_next(session_maker, client)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Podcast worker failed; check migration 026 and media volume")
                worked = False
            # Back off so a busy host is not polled continuously.
            await asyncio.sleep(2 if worked else 30)


async def enqueue(session, value, model):
    # Serialize bounded admission across API processes; deduplicate double clicks.
    await session.execute(sql("SELECT pg_advisory_xact_lock(:key)"), {"key": QUEUE_LOCK})
    params = {"hash": fingerprint(value), "model": model, "voice": voice_for(model)}
    existing = (await session.execute(sql("""
        SELECT * FROM podcast_tests WHERE text_hash=:hash AND model=:model AND voice=:voice
        AND status IN ('queued','rendering')
    """), params)).mappings().first()
    if existing:
        await session.commit()
        return public_job(existing)
    count = (await session.execute(sql("SELECT count(*) FROM podcast_tests WHERE status IN ('queued','rendering')"))).scalar()
    total = (await session.execute(sql("SELECT count(*) FROM podcast_tests"))).scalar()
    if total >= 30:
        await session.rollback()
        from fastapi import HTTPException
        raise HTTPException(409, "Er zijn 30 tests bewaard. Verwijder eerst een oude test.")
    if count >= 3:
        await session.rollback()
        from fastapi import HTTPException
        raise HTTPException(429, "Er staan al drie podcasts klaar of in verwerking. Wacht tot er één klaar is.")
    result = (await session.execute(sql("""
        INSERT INTO podcast_tests(id, text, text_hash, model, voice)
        VALUES (CAST(:id AS uuid), :text, :hash, :model, :voice) RETURNING *
    """), {**params, "id": str(uuid4()), "text": value})).mappings().one()
    await session.commit()
    return public_job(result)
