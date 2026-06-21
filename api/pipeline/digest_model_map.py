from typing import Dict

from pipeline.model_catalog import MODEL_CATALOG

# Afgeleid uit de catalogus — één bron van waarheid voor naam→alias-vertaling.
DIGEST_MODEL_TO_LITELLM: Dict[str, str] = {e.name: e.litellm for e in MODEL_CATALOG}


def resolve_model(name: str) -> str:
    """Vertaal Stroom-naam naar LiteLLM-alias. Onbekende naam → as-is.

    De as-is-fallback is bewust: cloud-modellen gebruiken hun alias als
    Stroom-naam, dus een nieuw LiteLLM-model werkt zonder hier iets toe te voegen.
    """
    return DIGEST_MODEL_TO_LITELLM.get(name, name)
