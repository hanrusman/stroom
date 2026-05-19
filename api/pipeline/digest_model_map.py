from typing import Dict

DIGEST_MODEL_TO_LITELLM: Dict[str, str] = {
    "qwen": "stroom-bulk",
    "sonnet": "stroom-sonnet",
    "opus": "stroom-deep",
    "long": "stroom-long-context",
    "cloud-kimi": "cloud-kimi",
    "cloud-qwen-coder": "cloud-qwen-coder",
    "cloud-gpt-120b": "cloud-gpt-120b",
    "cloud-gpt-20b": "cloud-gpt-20b",
    "cloud-gemma": "cloud-gemma",
}

def resolve_model(name: str) -> str:
    """Vertaal Stroom-naam naar LiteLLM-alias. Onbekende naam → as-is."""
    return DIGEST_MODEL_TO_LITELLM.get(name, name)
