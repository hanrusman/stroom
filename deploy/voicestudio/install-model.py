"""Run inside stroom-voice: python3 -u - < install-model.py [model].

Uses the pinned image's reviewed installers. No model is loaded for synthesis.
Run one installer at a time, then restart VoiceStudio to reload persisted paths.
"""
import os
import sys
import time

# Match main.py before importing Hugging Face or installer modules.
cache = os.environ.get("OMNIVOICE_CACHE_DIR")
if cache:
    for key in ("HF_HOME", "HF_HUB_CACHE", "TORCH_HOME"):
        os.environ[key] = cache
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
os.environ.setdefault("UV_CONCURRENT_DOWNLOADS", "1")
os.environ.setdefault("UV_CONCURRENT_BUILDS", "1")
os.environ.setdefault("UV_CONCURRENT_INSTALLS", "1")

engine = sys.argv[1] if len(sys.argv) > 1 else "omnivoice"
if engine == "omnivoice":
    from huggingface_hub import snapshot_download
    from huggingface_hub.constants import HF_HUB_CACHE
    from services.hf_revisions import remember_revision, revision_for
    from api.routers.setup.models import KNOWN_MODELS, snapshot_is_complete

    spec = next(m for m in KNOWN_MODELS if m["repo_id"] == "k2-fsa/OmniVoice")
    revision = revision_for(spec["repo_id"])
    print("Downloading OmniVoice", revision, flush=True)
    path = snapshot_download(spec["repo_id"], revision=revision, max_workers=1)
    if not snapshot_is_complete(spec, path):
        raise RuntimeError("OmniVoice snapshot is incomplete")
    remember_revision(spec["repo_id"], revision, HF_HUB_CACHE)
    print("OmniVoice weights verified", flush=True)
elif engine == "cosyvoice":
    from services.sidecar_install import get_status, start_install

    print(start_install(engine), flush=True)
    previous = None
    while True:
        status = get_status(engine)
        job = status.get("job") or {}
        progress = (job.get("state"), [(s["id"], s["state"]) for s in job.get("steps", [])])
        if progress != previous:
            print(progress, flush=True)
            previous = progress
        if job.get("state") == "failed":
            print(job.get("log", [])[-20:], flush=True)
            raise RuntimeError(job.get("error"))
        if job.get("state") == "succeeded" or (not job and status["installed"]):
            print("CosyVoice runtime and weights verified", flush=True)
            break
        time.sleep(10)
else:
    raise ValueError("Choose omnivoice or cosyvoice")
