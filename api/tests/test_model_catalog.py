"""Unit tests voor de modelcuratie uit LiteLLM `GET /model/info`.

Labels en `hidden` staan in vps-stacks/litellm/config.yaml (model_info); Stroom
leest ze alleen. Payloads hieronder volgen de vorm van LiteLLM 1.83.
"""
import sys

import pytest

sys.path.insert(0, "/app")

from pipeline.model_catalog import (  # noqa: E402
    is_embedding_alias,
    parse_model_info,
    stroom_name_for_alias,
)

pytestmark = pytest.mark.unit


def _dep(alias, **info):
    return {"model_name": alias, "litellm_params": {"model": f"openai/{alias}"},
            "model_info": {"id": f"id-{alias}", "max_tokens": None, **info}}


class TestParseModelInfo:
    def test_label_en_hidden_uit_model_info(self):
        live = parse_model_info({"data": [
            _dep("cloud-kimi", label="Kimi K2.6 (cloud)"),
            _dep("cloud-qwen-coder", label="Qwen (uitgefaseerd)", hidden=True),
        ]})
        assert [(m.alias, m.label, m.hidden) for m in live] == [
            ("cloud-kimi", "Kimi K2.6 (cloud)", False),
            ("cloud-qwen-coder", "Qwen (uitgefaseerd)", True),
        ]

    def test_zonder_curatie_geen_label_en_zichtbaar(self):
        # Nieuw model in config.yaml zonder model_info: verschijnt gewoon.
        (m,) = parse_model_info({"data": [
            {"model_name": "cloud-nieuw", "litellm_params": {}, "model_info": None},
        ]})
        assert m.label is None
        assert m.hidden is False

    def test_volgorde_van_de_config_blijft(self):
        live = parse_model_info({"data": [_dep("b"), _dep("a"), _dep("c")]})
        assert [m.alias for m in live] == ["b", "a", "c"]

    def test_meerdere_deployments_per_alias_tellen_een_keer(self):
        live = parse_model_info({"data": [
            _dep("cloud-gpt-120b", label="eerste"),
            _dep("cloud-gpt-120b", label="tweede"),
        ]})
        assert [(m.alias, m.label) for m in live] == [("cloud-gpt-120b", "eerste")]

    def test_lege_of_rare_payload(self):
        assert parse_model_info({}) == []
        assert parse_model_info({"data": [{"model_info": {"label": "x"}}]}) == []


class TestNaamvertaling:
    def test_stroom_namen_voor_eigen_aliassen(self):
        assert stroom_name_for_alias("stroom-bulk") == "qwen"
        assert stroom_name_for_alias("stroom-deep") == "opus"

    def test_cloud_alias_is_zijn_eigen_naam(self):
        assert stroom_name_for_alias("cloud-mistral") == "cloud-mistral"

    def test_embeddings_herkend(self):
        assert is_embedding_alias("stroom-embed")
        assert is_embedding_alias("iets-embed-v2")
        assert not is_embedding_alias("cloud-kimi")


class TestUitgefaseerd:
    """cloud-qwen-coder wijst in LiteLLM naar Kimi: nooit stil gebruiken."""

    def test_resolve_weigert_met_opvolger_in_de_melding(self):
        from pipeline.digest_model_map import RetiredModelError, resolve_model
        with pytest.raises(RetiredModelError, match="cloud-kimi-code"):
            resolve_model("cloud-qwen-coder")

    def test_resolve_laat_gewone_namen_door(self):
        from pipeline.digest_model_map import resolve_model
        assert resolve_model("qwen") == "stroom-bulk"
        assert resolve_model("opus") == "stroom-deep"
        # Cloud-namen staan niet in de catalogus maar moeten gewoon werken.
        assert resolve_model("cloud-kimi") == "cloud-kimi"
        assert resolve_model("cloud-mistral") == "cloud-mistral"

    def test_opgeslagen_keuze_gaat_naar_opvolger(self):
        from pipeline.digest_model_map import replace_retired
        assert replace_retired("cloud-qwen-coder") == "cloud-kimi-code"
        assert replace_retired("opus") == "opus"
