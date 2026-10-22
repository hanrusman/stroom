import asyncio
import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from routers.podcast_tests import GenerateRequest
from services import podcast_converter as pc

pytestmark = pytest.mark.unit


def stats():
    return {"ts": 1000, "cpu": {"load1": 10, "cores": 44},
            "mem": {"total_mib": 120000, "used_mib": 40000},
            "disk": {"root": {"avail_gb": 60}},
            "gpus": [{"name": "NVIDIA A2", "vram_total_mib": 15356,
                      "vram_used_mib": 0, "util_now": 0}]}


def test_text_limits():
    assert GenerateRequest(text="  Hello.  ", model="omnivoice").text == "Hello."
    for text in (" ", "x" * 4001):
        with pytest.raises(ValidationError):
            GenerateRequest(text=text, model="omnivoice")
    with pytest.raises(ValidationError):
        GenerateRequest(text="Hello", model="tts-1")  # never silently use active engine


def test_host_admission():
    snapshot = stats()
    assert pc.host_gate(snapshot, "omnivoice", now=1000) is None
    assert "verouderd" in pc.host_gate(snapshot, "omnivoice", now=1400)
    snapshot["cpu"]["load1"] = 41
    assert "CPU" in pc.host_gate(snapshot, "omnivoice", now=1000)
    snapshot["cpu"]["load1"] = 10
    snapshot["gpus"][0]["vram_used_mib"] = 14000
    assert "A2" in pc.host_gate(snapshot, "omnivoice", now=1000)
    assert pc.host_gate(snapshot, "kittentts", now=1000) is None
    snapshot["mem"]["total_mib"] = float("nan")
    assert "onvolledig" in pc.host_gate(snapshot, "kittentts", now=1000)
    assert "onvolledig" in pc.host_gate({}, "omnivoice", now=1000)


async def test_catalog_only_allows_explicit_accelerated_models(monkeypatch):
    monkeypatch.setenv("PODCAST_VOICESTUDIO_URL", "http://voice")
    backend = {"backends": [
        {"id": "omnivoice", "available": True, "routing_status": "cpu_fallback"},
        {"id": "cosyvoice", "available": True, "routing_status": "accelerated"},
        {"id": "kittentts", "available": True, "routing_status": "cpu_only"},
        {"id": "unlisted", "available": True, "routing_status": "accelerated"},
    ]}
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=backend))) as client:
        result = await pc.catalog(client)
    assert len(result["models"]) == 3
    assert [m["id"] for m in result["models"] if m["available"]] == ["kittentts", "cosyvoice"]


async def test_render_routes_exact_text_and_model_and_commits_audio(monkeypatch, tmp_path):
    monkeypatch.setenv("PODCAST_MEDIA_DIR", str(tmp_path))
    monkeypatch.setenv("PODCAST_VOICESTUDIO_URL", "http://voice")
    monkeypatch.setenv("PODCAST_VOICESTUDIO_KEY", "private-test-key")
    job = {"id": str(uuid4()), "model": "cosyvoice", "voice": "test-profile", "text": "Exact text.\nNo rewriting."}
    def handle(request):
        assert request.url.path == "/v1/audio/speech"
        body = json.loads(request.content)
        assert body["model"] == job["model"] and body["voice"] == job["voice"]
        assert body["input"] == job["text"] and body["language"] == "en"
        assert request.headers["authorization"] == "Bearer private-test-key"
        return httpx.Response(200, content=b"ID3" + b"x" * 200, headers={"Content-Type": "audio/mpeg", "X-Stroom-TTS-Engine": job["model"], "X-OmniVoice-Routing": "accelerated"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        assert await pc.render(client, job) == 203
    assert pc.audio_path(job["id"]).read_bytes().startswith(b"ID3")
    assert not list(tmp_path.glob("*.part"))


@pytest.mark.parametrize("body,headers", [
    (b'{"error":"broken"}', {"Content-Type": "application/json"}),
    (b"not an mp3" * 30, {"Content-Type": "audio/mpeg", "X-Stroom-TTS-Engine": "omnivoice", "X-OmniVoice-Routing": "accelerated"}),
    (b"ID3" + b"x" * 200, {"Content-Type": "audio/mpeg"}),
    (b"ID3" + b"x" * 200, {"Content-Type": "audio/mpeg", "X-Stroom-TTS-Engine": "kittentts", "X-OmniVoice-Routing": "accelerated"}),
    (b"ID3" + b"x" * 200, {"Content-Type": "audio/mpeg", "X-OmniVoice-Routing": "cpu_fallback", "X-Stroom-TTS-Engine": "omnivoice"}),
])
async def test_bad_audio_is_never_published(monkeypatch, tmp_path, body, headers):
    monkeypatch.setenv("PODCAST_MEDIA_DIR", str(tmp_path))
    monkeypatch.setenv("PODCAST_VOICESTUDIO_URL", "http://voice")
    job = {"id": str(uuid4()), "model": "omnivoice", "voice": "default", "text": "Test"}
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=body, headers=headers))) as client:
        with pytest.raises(ValueError):
            await pc.render(client, job)
    assert not list(tmp_path.iterdir())


async def test_size_limit_and_cancel_cleanup(monkeypatch, tmp_path):
    monkeypatch.setenv("PODCAST_MEDIA_DIR", str(tmp_path))
    monkeypatch.setenv("PODCAST_VOICESTUDIO_URL", "http://voice")
    monkeypatch.setattr(pc, "MAX_AUDIO_BYTES", 128)
    job = {"id": str(uuid4()), "model": "omnivoice", "voice": "default", "text": "Test"}
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"ID3" + b"x" * 200, headers={"Content-Type": "audio/mpeg", "X-Stroom-TTS-Engine": job["model"], "X-OmniVoice-Routing": "accelerated"}))) as client:
        with pytest.raises(ValueError, match="32 MB"):
            await pc.render(client, job)
    assert not list(tmp_path.iterdir())

    class Interrupted(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"ID3"
            raise asyncio.CancelledError()
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, stream=Interrupted(), headers={"Content-Type": "audio/mpeg", "X-Stroom-TTS-Engine": job["model"], "X-OmniVoice-Routing": "accelerated"}))) as client:
        with pytest.raises(asyncio.CancelledError):
            await pc.render(client, job)
    assert not list(tmp_path.iterdir())


def test_error_messages_do_not_leak_backend_body_or_url():
    request = httpx.Request("POST", "http://private-host?secret=hidden")
    error = httpx.HTTPStatusError("hidden", request=request, response=httpx.Response(500, request=request, text="hidden"))
    assert "hidden" not in pc.render_error(error)


def test_audio_path_rejects_traversal():
    with pytest.raises(ValueError):
        pc.audio_path("../../secret")
    assert isinstance(pc.audio_path(uuid4()), Path)


async def test_server_allowlist_keeps_unvalidated_models_disabled(monkeypatch):
    monkeypatch.setenv("PODCAST_VOICESTUDIO_URL", "http://voice")
    monkeypatch.setenv("PODCAST_ENABLED_MODELS", "kittentts")
    entries = {"backends": [{"id": model, "available": True, "routing_status": "accelerated"} for model in pc.MODELS]}
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=entries))) as client:
        result = await pc.catalog(client)
    assert [m["id"] for m in result["models"] if m["available"]] == ["kittentts"]
    assert all("geheugenbudget" in m["reason"] for m in result["models"] if not m["available"])
