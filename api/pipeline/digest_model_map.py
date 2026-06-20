from typing import Dict

DIGEST_MODEL_TO_LITELLM: Dict[str, str] = {
    # Lokale Ollama modellen
    "qwen": "stroom-bulk",
    "sonnet": "stroom-sonnet",
    "opus": "stroom-deep",
    "long": "stroom-long-context",
    "mistral": "stroom-mistral",
    "llama": "stroom-llama",
    "gemma": "stroom-gemma",
    "phi": "stroom-phi",
    # Cloud modellen
    "cloud-kimi": "cloud-kimi",
    "cloud-kimi-latest": "cloud-kimi-latest",
    "cloud-qwen-coder": "cloud-qwen-coder",
    "cloud-gpt-120b": "cloud-gpt-120b",
    "cloud-gpt-20b": "cloud-gpt-20b",
    "cloud-gemma": "cloud-gemma",
    "cloud-minimax": "cloud-minimax",
    "cloud-glm-5.1": "cloud-glm-5.1",
    "cloud-gemini-flash": "cloud-gemini-flash",
    "cloud-nemotron": "cloud-nemotron",
    "cloud-deepseek": "cloud-deepseek",
    "cloud-deepseek-reasoner": "cloud-deepseek-reasoner",
    "cloud-mistral-large": "cloud-mistral-large",
    "cloud-mistral-medium": "cloud-mistral-medium",
    "cloud-codestral": "cloud-codestral",
}

def resolve_model(name: str) -> str:
    """Vertaal Stroom-naam naar LiteLLM-alias. Onbekende naam → as-is."""
    return DIGEST_MODEL_TO_LITELLM.get(name, name)
