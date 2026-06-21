"""Curatie-laag voor de modelkeuze in Stroom.

Eén plek die Stroom-modelnamen koppelt aan LiteLLM-aliassen, vriendelijke labels
en een categorie. De *beschikbaarheid* is dynamisch — die komt live uit LiteLLM
`/v1/models` (zie routers/settings.py). Deze catalogus levert alleen de curatie
eromheen: labels, naam↔alias-vertaling, en welke modellen krediet-/quota-gevoelig
zijn.

Gevolg: een model dat LiteLLM serveert maar hier niet staat, verschijnt alsnog in
de UI met een afgeleid label. Zet je een nieuw model in `litellm/config.yaml`, dan
duikt het vanzelf op in Stroom — geen code-edit op vier plekken meer nodig.
"""
from dataclasses import dataclass
from typing import Dict, Optional


@dataclass(frozen=True)
class CatalogEntry:
    name: str          # Stroom-naam (wat in app_settings/DB staat)
    litellm: str       # LiteLLM-alias (wat de proxy serveert)
    label: str         # UI-label
    category: str      # 'local' | 'cloud' | 'embed'
    # Krediet-/quota-gevoelig: kan tijdelijk falen (bv. Anthropic-credit op,
    # Gemini-quota bereikt). De UI mag deze markeren en de status live pollen.
    flaky: bool = False


MODEL_CATALOG = [
    # Lokale / eigen-gehoste modellen (Stroom-naam ≠ alias → vertaling nodig)
    CatalogEntry("qwen", "stroom-bulk", "Qwen3.6 35B (lokaal)", "local"),
    CatalogEntry("sonnet", "stroom-sonnet", "Claude Sonnet 4.6", "cloud", flaky=True),
    CatalogEntry("opus", "stroom-deep", "Claude Opus 4.7", "cloud", flaky=True),
    CatalogEntry("long", "stroom-long-context", "Gemini 2.5 Pro (lange context)", "cloud", flaky=True),
    # Cloud-modellen via Ollama Turbo (Stroom-naam == alias)
    CatalogEntry("cloud-kimi", "cloud-kimi", "Kimi K2.5 (cloud)", "cloud"),
    CatalogEntry("cloud-qwen-coder", "cloud-qwen-coder", "Qwen3-coder 480B (cloud)", "cloud"),
    CatalogEntry("cloud-gpt-120b", "cloud-gpt-120b", "gpt-oss 120B (cloud)", "cloud"),
    CatalogEntry("cloud-gpt-20b", "cloud-gpt-20b", "gpt-oss 20B (snel)", "cloud"),
    CatalogEntry("cloud-gemma", "cloud-gemma", "Gemma3 27B (cloud)", "cloud"),
    CatalogEntry("cloud-minimax", "cloud-minimax", "MiniMax M2 (cloud)", "cloud"),
    # Embeddings — nooit in de chat-/digest-keuze tonen
    CatalogEntry("stroom-embed", "stroom-embed", "Embeddings (nomic)", "embed"),
]

BY_NAME: Dict[str, CatalogEntry] = {e.name: e for e in MODEL_CATALOG}
BY_ALIAS: Dict[str, CatalogEntry] = {e.litellm: e for e in MODEL_CATALOG}


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
