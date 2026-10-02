from typing import Dict

from pipeline.model_catalog import MODEL_CATALOG, RETIRED

# Afgeleid uit de catalogus — één bron van waarheid voor naam→alias-vertaling.
DIGEST_MODEL_TO_LITELLM: Dict[str, str] = {e.name: e.litellm for e in MODEL_CATALOG}


class RetiredModelError(ValueError):
    """Uitgefaseerde modelnaam in een verzoek (main.py maakt er een 400 van)."""


def replace_retired(name: str) -> str:
    """Opgeslagen keuze op een uitgefaseerde naam → opvolger. Voor model_defaults
    uit de DB, zodat cron en scoring niet stil op een misleidende alias draaien."""
    return RETIRED.get(name, name)


def resolve_model(name: str) -> str:
    """Vertaal Stroom-naam naar LiteLLM-alias. Onbekende naam → as-is.

    De as-is-fallback is bewust: cloud-modellen gebruiken hun alias als
    Stroom-naam, dus een nieuw LiteLLM-model werkt zonder hier iets toe te voegen.
    Gebruik altijd deze functie, nooit DIGEST_MODEL_TO_LITELLM[name] direct: die
    kent alleen de catalogusnamen.

    Raises RetiredModelError voor een uitgefaseerde naam.
    """
    if name in RETIRED:
        raise RetiredModelError(
            f"Model '{name}' is uitgefaseerd: de alias wijst niet meer naar het model "
            f"dat de naam belooft. Kies '{RETIRED[name]}' of een ander model."
        )
    return DIGEST_MODEL_TO_LITELLM.get(name, name)
