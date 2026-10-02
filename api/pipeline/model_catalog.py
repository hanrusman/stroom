"""Stroom-specifieke kant van de modelkeuze.

Labels, verbergen en volgorde staan op één plek voor Stroom én Okavango: de
`model_info` per model in vps-stacks/litellm/config.yaml. LiteLLM geeft die
ongewijzigd terug via `GET /model/info` (zie routers/settings.py). Een repoint of
nieuw model is daarmee één edit in die config — geen code-edit hier meer.

Wat hier blijft is wat alleen Stroom weet:
- de Stroom-naam ↔ LiteLLM-alias-vertaling (in app_settings/DB staan namen als
  'qwen' en 'opus', niet de alias);
- de categorie (lokaal/embed) en welke modellen krediet-/quota-gevoelig zijn.
Onbekende aliassen zijn per conventie cloud, met de alias als Stroom-naam.
"""
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class CatalogEntry:
    name: str          # Stroom-naam (wat in app_settings/DB staat)
    litellm: str       # LiteLLM-alias (wat de proxy serveert)
    category: str      # 'local' | 'cloud' | 'embed'
    # Krediet-/quota-gevoelig: kan tijdelijk falen (bv. Anthropic-credit op,
    # Gemini-quota bereikt). De UI mag deze markeren en de status live pollen.
    flaky: bool = False


MODEL_CATALOG = [
    # Stroom-naam ≠ alias → vertaling nodig. Cloud-modellen via Ollama Turbo
    # gebruiken hun alias als naam en hoeven hier niet te staan.
    CatalogEntry("qwen", "stroom-bulk", "local"),
    CatalogEntry("sonnet", "stroom-sonnet", "cloud", flaky=True),
    CatalogEntry("opus", "stroom-deep", "cloud", flaky=True),
    CatalogEntry("long", "stroom-long-context", "cloud", flaky=True),
    # Embeddings — nooit in de chat-/digest-keuze tonen
    CatalogEntry("stroom-embed", "stroom-embed", "embed"),
]

BY_NAME: Dict[str, CatalogEntry] = {e.name: e for e in MODEL_CATALOG}
BY_ALIAS: Dict[str, CatalogEntry] = {e.litellm: e for e in MODEL_CATALOG}


@dataclass(frozen=True)
class LiveModel:
    """Eén alias zoals LiteLLM 'm serveert, met de curatie uit config.yaml."""
    alias: str
    label: Optional[str]   # model_info.label; None → UI valt terug op de naam
    hidden: bool           # model_info.hidden: wel geserveerd, niet in de keuze


def parse_model_info(payload: dict) -> List[LiveModel]:
    """`GET /model/info` → één LiveModel per alias, in config-volgorde.

    LiteLLM geeft één regel per deployment; een alias met meerdere deployments
    telt één keer (de eerste bepaalt label/hidden)."""
    out: List[LiveModel] = []
    seen = set()
    for d in payload.get("data", []):
        alias = d.get("model_name")
        if not alias or alias in seen:
            continue
        seen.add(alias)
        info = d.get("model_info") or {}
        out.append(LiveModel(
            alias=alias,
            label=info.get("label") or None,
            hidden=bool(info.get("hidden", False)),
        ))
    return out


def entry_for_alias(alias: str) -> Optional[CatalogEntry]:
    return BY_ALIAS.get(alias)


def stroom_name_for_alias(alias: str) -> str:
    """LiteLLM-alias → Stroom-naam. Onbekende alias → identiteit (cloud-conventie)."""
    e = BY_ALIAS.get(alias)
    return e.name if e else alias


def is_embedding_alias(alias: str) -> bool:
    """Embeddings horen niet thuis in de chat-/digest-keuze."""
    e = BY_ALIAS.get(alias)
    if e is not None:
        return e.category == "embed"
    return "embed" in alias.lower()
