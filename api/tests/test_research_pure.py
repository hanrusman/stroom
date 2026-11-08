"""Unit-tests voor dossiers (services/research_service.py): parsers, citaten,
en de hele pijplijn met MemoryStore, een nep-archief en een nep-LLM."""
import json
import sys
import uuid

import pytest
from fastapi import HTTPException

sys.path.insert(0, "/app")

from services import research_service as rs  # noqa: E402
from services.research_prompts import (  # noqa: E402
    ASK_SYSTEM, CRITIQUE_SYSTEM, CRITIQUE_TEXT_SUFFIX, DEEPEN_SYSTEM, EXTRACT_SYSTEM, PLAN_SYSTEM,
    REVISE_SYSTEM, SCREEN_SYSTEM, SYNTH_SYSTEM,
)

pytestmark = pytest.mark.unit

GOOD_PLAN = {
    "title": "Software-inkoop verschuift",
    "question": "Hoe verandert software-inkoop?",
    "aspects": [{"id": "x", "name": "Zelf bouwen", "description": "Waar bouwt men zelf?"},
                {"id": "y", "name": "Open standaarden", "description": "Rol van standaarden"}],
    "queries": ["build vs buy", "zelf bouwen", "vendor lock-in", "open standaarden",
                "SaaS", "soevereiniteit", "build vs buy"],
    "include": "inkoopkeuzes", "exclude": "consumentenapps",
}


# ---------------------------------------------------------------- parsers


def test_parse_plan_renumbers_dedupes_and_keeps_fields():
    p = rs.parse_plan(GOOD_PLAN, "vraag")
    assert [a["id"] for a in p["aspects"]] == ["a1", "a2"]
    assert p["queries"].count("build vs buy") == 1
    assert len(p["queries"]) == 6
    assert p["title"] == "Software-inkoop verschuift"


@pytest.mark.parametrize("bad", [
    {"title": "...", "aspects": [{"id": "a1", "name": "...", "description": "..."}],
     "queries": ["...", "..."]},          # sjabloon teruggegeven
    {**GOOD_PLAN, "queries": ["a", "b"]},  # te weinig zoekvragen
    "geen object",
])
def test_parse_plan_rejects_unusable(bad):
    with pytest.raises(ValueError):
        rs.parse_plan(bad, "vraag")


def test_parse_plan_placeholder_title_falls_back_to_question():
    p = rs.parse_plan({**GOOD_PLAN, "title": "…"}, "Mijn vraag over inkoop")
    assert p["title"] == "Mijn vraag over inkoop"


def test_parse_screen_ignores_garbage_and_out_of_range():
    obj = {"scores": [{"i": 1, "r": 3}, {"i": "2", "r": "2"}, {"i": 9, "r": 3},
                      {"i": 3, "r": 7}, "rommel", {"i": None}]}
    assert rs.parse_screen(obj, 3) == {1: 3, 2: 2}
    assert rs.parse_screen({"nope": 1}, 3) == {}


def test_parse_findings_validates_and_normalises():
    obj = {"relevance": "3", "findings": [
        {"claim": "De Belastingdienst kiest eigen servers in plaats van Microsoft-cloud.",
         "aspect": "a1", "evidence": "CASE", "actors": ["Belastingdienst", "", 3]},
        {"claim": "kort", "aspect": "a1"},
        {"claim": "Een bewering zonder bekend aspect, maar lang genoeg.", "aspect": "zz"},
    ]}
    rel, fs = rs.parse_findings(obj, {"a1"})
    assert rel == 3 and len(fs) == 2
    assert fs[0]["evidence"] == "case" and fs[0]["actors"] == ["Belastingdienst"]
    assert fs[1]["aspect"] == "other"


def test_parse_findings_requires_list_and_caps_relevance_without_findings():
    with pytest.raises(ValueError):
        rs.parse_findings({"relevance": 2}, set())
    assert rs.parse_findings({"relevance": 3, "findings": []}, set()) == (1, [])


def test_verify_quotes_drops_paraphrases():
    fs = [{"quote": "We are moving everything   back on-prem"},
          {"quote": "Dit staat nergens in de bron, echt niet"},
          {"quote": ""}]
    rs.verify_quotes(fs, "He said: we are moving everything back on-prem, because of cost.")
    assert fs[0]["quote"] and not fs[1]["quote"]


def test_fix_citations_normalises_and_drops_unknown():
    text, used = rs.fix_citations("A [S2, 3] b [S9] c [S1; S2] d [S3]", 3)
    assert text == "A [S2, S3] b  c [S1, S2] d [S3]"
    assert used == [2, 3, 1]


def test_teaser_prefers_takeaways_and_strips_metadata():
    summary = ("# Titel\n\n## Metadata\n- **Podcast**: X\n- **Host**: Y\n\n"
               "## Key takeaways\n1. **Data is king:** agents gebruiken de datalaag.")
    t = rs.teaser(summary, None)
    assert t.startswith("1. Data is king:") and "Podcast" not in t
    assert rs.teaser(None, "<p>Alleen <b>beschrijving</b></p>") == "Alleen beschrijving"


def test_extract_input_adds_body_for_short_summary():
    c = {"title": "T", "source": "S", "format": "article", "date": "2026-01-01",
         "summary": "kort", "transcript": "<p>volledige tekst</p>", "description": "",
         "author": "", "lessons": [("Les", "body")]}
    prompt, raw = rs.extract_input(c)
    assert "Brontekst:\nvolledige tekst" in prompt and "- Les: body" in prompt
    assert "volledige tekst" in raw


def test_findings_block_budget_keeps_most_relevant():
    plan = rs.parse_plan(GOOD_PLAN, "v")
    mk = lambda ref, rel, n: {"ref": ref, "relevance": rel, "recall_score": 0.1, "date": "2026-01-01",
                              "source": "Bron", "format": "podcast", "title": ref,
                              "findings": [{"claim": "x" * 400, "aspect": "a1"}] * n}
    srcs = [mk("S1", 1, 3), mk("S2", 3, 3), mk("S3", 2, 3)]
    block = rs.findings_block(plan, srcs, max_chars=3000)
    assert "[S2]" in block and "[S3]" in block and "[S1]" not in block


def test_to_markdown_links_citations_and_lists_cited_sources():
    run = {"question": "v", "plan": {"question": "v"}, "report": "Zie [S1, S2].",
           "finished_at": "2026-11-08T10:00:00",
           "sources": [{"ref": "S1", "item_id": "i1", "title": "Een", "source": "A", "date": "2026-01-01", "cited": True},
                       {"ref": "S2", "item_id": "i2", "title": "Twee", "source": "B", "date": "2026-02-01", "cited": False}],
           "followups": [{"question": "En nu?", "answer": "Zo [S1]."}]}
    md = rs.to_markdown(run, lambda i: f"https://stroom/?item={i}")
    assert "[[S1](#s1), [S2](#s2)]" in md
    assert "[Een](https://stroom/?item=i1)" in md and "Twee" not in md
    assert "### Vervolgvraag: En nu?" in md and md.startswith("---\ntype: stroom-dossier")


# ---------------------------------------------------------------- pijplijn


ITEMS = {f"i{k}": {"title": f"Item {k}", "source": "Bron", "format": "podcast",
                   "date": f"2026-0{1 + k % 9}-01", "summary": f"Samenvatting {k} " + "x" * 3000,
                   "transcript": "", "description": "", "author": "", "lessons": []}
         for k in range(1, 8)}


EXTRA = {f"x{k}": {**ITEMS["i1"], "title": f"Extra {k}", "date": "2026-10-01"} for k in (1, 2)}


class FakeCorpus:
    """Eerste ronde vindt ITEMS; zoekvragen met 'gat' (verdieping) vinden ook EXTRA."""

    def __init__(self, items=ITEMS, extra=EXTRA):
        self.items = {**items, **extra}
        self.base, self.extra = list(items), list(extra)
        self.recall_calls = 0

    async def recall(self, queries):
        self.recall_calls += 1
        ids = self.base + (self.extra if any("gat" in q for q in queries) else [])
        return [{"item_id": iid, "recall_score": 1.0 / (k + 1), "queries": queries[:1]}
                for k, iid in enumerate(ids)]

    async def meta(self, ids):
        return {i: {"item_id": i, "title": self.items[i]["title"], "source": "Bron",
                    "format": "podcast", "date": self.items[i]["date"], "url": None,
                    "teaser": "t"} for i in ids if i in self.items}

    async def content(self, iid):
        return self.items.get(iid)


class FakeLLM:
    def __init__(self, fail_models=(), plan=GOOD_PLAN, irrelevant=("Item 7",),
                 truncate_write=False, critique_json=True, deepen_queries=("gat in tegengeluid",)):
        self.fail_models = set(fail_models)
        self.plan = plan
        self.irrelevant = set(irrelevant)
        self.truncate_write = truncate_write
        self.critique_json = critique_json
        self.deepen_queries = list(deepen_queries)
        self.calls: list[tuple[str, str]] = []

    async def call_llm(self, model, messages, temperature=0.7, response_format="text",
                       timeout=180.0, max_tokens=None, meta=None):
        system, user = messages[0]["content"], messages[1]["content"]
        role = {PLAN_SYSTEM: "plan", SCREEN_SYSTEM: "screen", EXTRACT_SYSTEM: "extract",
                SYNTH_SYSTEM: "write", CRITIQUE_SYSTEM: "critique", REVISE_SYSTEM: "revise",
                ASK_SYSTEM: "ask", DEEPEN_SYSTEM: "deepen",
                CRITIQUE_SYSTEM + CRITIQUE_TEXT_SUFFIX: "critique_text"}[system]
        if len(messages) > 2:
            role = "continue"
        self.calls.append((role, model))
        if meta is not None:
            meta["finish_reason"] = "stop"
        if model in self.fail_models:
            raise HTTPException(status_code=400, detail="krediet op")
        if role == "plan":
            return json.dumps(self.plan)
        if role == "deepen":
            return json.dumps({"gaps": "Tegengeluid ontbreekt.",
                               "queries": self.deepen_queries + ["build vs buy"]})
        if role == "continue":
            return " en het slot [S2]."
        if role == "write" and self.truncate_write:
            if meta is not None:
                meta["finish_reason"] = "length"
            return "# Dossier\n\nBedrijven bouwen zelf [S1]"
        if role == "critique" and not self.critique_json:
            return "dit is geen json"
        if role == "critique_text":
            return "Matig.\n1. [vague] In het kort — te algemeen → concreter"

        if role == "screen":
            lines = [ln for ln in user.splitlines() if ln[:1].isdigit() and " — " in ln]
            return json.dumps({"scores": [
                {"i": int(ln.split(".")[0]), "r": 0 if any(t in ln for t in self.irrelevant) else 3}
                for ln in lines]})
        if role == "extract":
            title = user.split("Titel: ")[1].splitlines()[0]
            return json.dumps({"relevance": 3, "findings": [
                {"claim": f"{title}: bedrijf X bouwt nu zelf zijn CRM met AI-tools.",
                 "aspect": "a1", "evidence": "case", "quote": "verzonnen citaat dat er niet staat"}]})
        if role == "write":
            return "# Dossier\n\nBedrijven bouwen zelf [S1, S2] en [S99]."
        if role == "critique":
            return json.dumps({"verdict": "ok", "issues": [
                {"type": "overgeneralized", "where": "In het kort", "problem": "één bron", "fix": "nuanceer"}]})
        if role == "revise":
            return "# Dossier\n\nSommige bedrijven bouwen zelf [S1] en [S3]."
        return "Antwoord [S2]."


@pytest.fixture(autouse=True)
def _models(monkeypatch):
    monkeypatch.setattr(rs, "PLAN_MODELS", ["p1", "p2"])
    monkeypatch.setattr(rs, "SCREEN_MODELS", ["cloud-s"])
    monkeypatch.setattr(rs, "EXTRACT_MODELS", ["cloud-e"])
    monkeypatch.setattr(rs, "WRITE_MODELS", ["w1", "w2"])
    monkeypatch.setattr(rs, "CRITIQUE_MODELS", ["c1"])
    monkeypatch.setattr(rs, "ASK_MODELS", ["w1"])

    async def no_sleep(_):
        return None
    monkeypatch.setattr(rs.asyncio, "sleep", no_sleep)


async def _run(store, llm, corpus=None, run_id="r1", **extra):
    await store.update_run(run_id, question="Hoe verandert software-inkoop?", parent_id=None, **extra)
    ctx = rs.Ctx(store=store, corpus=corpus or FakeCorpus(), llm=llm)
    await rs.run_pipeline(ctx, run_id)
    return store.runs[run_id], ctx


async def test_full_pipeline_happy_path():
    store, llm = rs.MemoryStore(), FakeLLM()
    run, ctx = await _run(store, llm)
    assert run["status"] == "done", run.get("error")
    assert run["title"] == "Software-inkoop verschuift"
    # Item 7 viel af bij screening (score 0); de verdieping vond 2 extra items
    assert set(store.finds["r1"]) == {f"i{k}" for k in range(1, 7)} | {"x1", "x2"}
    assert run["plan"]["deepen"]["queries"] == ["gat in tegengeluid"]  # 'build vs buy' was al gebruikt
    assert {c["round"] for c in store.cands["r1"].values() if c["item_id"].startswith("x")} == {1}
    # Verzonnen citaat is weggehaald
    assert all(not f["quote"] for v in store.finds["r1"].values() for f in v["findings"])
    # Herziene versie staat er, met geldige verwijzingen; S-nummers op datum
    assert "[S1]" in run["report"] and "[S3]" in run["report"]
    dates = [s["date"] for s in run["sources"]]
    assert dates == sorted(dates)
    assert [s["cited"] for s in run["sources"]][:3] == [True, False, True]
    assert run["models"] == {"plan": "p1", "deepen": "p1", "write": "w1", "critique": "c1",
                            "revise": "w1"}
    assert run["progress"]["stage"] == "done" and run["stats"]["llm_calls"] == ctx.usage.calls


async def test_falls_back_to_next_model_on_4xx():
    store, llm = rs.MemoryStore(), FakeLLM(fail_models={"p1", "w1"})
    run, _ = await _run(store, llm)
    assert run["status"] == "done"
    assert run["models"]["plan"] == "p2" and run["models"]["write"] == "w2"


async def test_template_plan_moves_to_next_model_then_fails_cleanly():
    bad = {"title": "...", "aspects": [{"id": "a1", "name": "...", "description": "..."}],
           "queries": ["..."]}
    store, llm = rs.MemoryStore(), FakeLLM(plan=bad)
    run, _ = await _run(store, llm)
    assert run["status"] == "failed" and "geen bruikbaar plan" in run["error"]
    assert [c for c in llm.calls if c[0] == "plan"] == [("plan", "p1"), ("plan", "p2")]


async def test_no_relevant_sources_fails_with_explanation():
    store = rs.MemoryStore()
    llm = FakeLLM(irrelevant={f"Item {k}" for k in range(1, 8)} | {"Extra 1", "Extra 2"})
    run, _ = await _run(store, llm)
    assert run["status"] == "failed" and "buiten het archief" in run["error"]


async def test_resume_skips_finished_stages():
    store, llm = rs.MemoryStore(), FakeLLM(fail_models={"w1", "w2"})
    run, _ = await _run(store, llm)
    assert run["status"] == "failed"
    llm2 = FakeLLM()
    corpus = FakeCorpus()
    ctx = rs.Ctx(store=store, corpus=corpus, llm=llm2)
    await rs.run_pipeline(ctx, "r1")
    assert store.runs["r1"]["status"] == "done"
    roles = {r for r, _ in llm2.calls}
    assert roles == {"write", "critique", "revise"} and corpus.recall_calls == 0


async def test_refresh_reuses_parent_work_and_only_processes_new_items():
    store = rs.MemoryStore()
    await _run(store, FakeLLM())
    items = dict(ITEMS)
    items["i8"] = {**ITEMS["i1"], "title": "Item 8", "date": "2026-11-01"}
    llm2 = FakeLLM()
    await store.update_run("r2", question="Hoe verandert software-inkoop?", parent_id="r1")
    await rs.run_pipeline(rs.Ctx(store=store, corpus=FakeCorpus(items), llm=llm2), "r2")
    run = store.runs["r2"]
    assert run["status"] == "done" and run["plan"]["title"] == "Software-inkoop verschuift"
    roles = [r for r, _ in llm2.calls]
    assert "plan" not in roles and "deepen" not in roles  # plan + verdieping hergebruikt
    assert roles.count("extract") == 1 and roles.count("screen") == 1
    assert len(store.finds["r2"]) == 9


async def test_cancel_stops_run():
    store, llm = rs.MemoryStore(), FakeLLM()
    await store.update_run("r1", question="v", parent_id=None)

    async def yes():
        return True
    await rs.run_pipeline(rs.Ctx(store=store, corpus=FakeCorpus(), llm=llm, should_cancel=yes), "r1")
    assert store.runs["r1"]["status"] == "cancelled"


async def test_ask_uses_report_and_findings():
    store, llm = rs.MemoryStore(), FakeLLM()
    run, _ = await _run(store, llm)
    answer, model = await rs.ask(llm, run, "Welke sectoren bouwen zelf?")
    assert answer == "Antwoord [S2]." and model == "w1"
    with pytest.raises(ValueError):
        await rs.ask(llm, {"question": "v"}, "x")


async def test_truncated_text_is_continued():
    store, llm = rs.MemoryStore(), FakeLLM(truncate_write=True)
    run, _ = await _run(store, llm)
    assert run["status"] == "done"
    assert run["draft"].endswith("[S1] en het slot [S2].")
    assert ("continue", "w1") in llm.calls


async def test_critique_falls_back_to_text_and_still_revises():
    store, llm = rs.MemoryStore(), FakeLLM(critique_json=False)
    run, _ = await _run(store, llm)
    assert run["status"] == "done"
    assert run["critique"]["text"].startswith("Matig.")
    assert "revise" in [r for r, _ in llm.calls]


async def test_deepen_without_new_queries_skips_second_round():
    store, llm = rs.MemoryStore(), FakeLLM(deepen_queries=())
    run, _ = await _run(store, llm)
    assert run["status"] == "done" and run["plan"]["deepen"]["queries"] == []
    assert "x1" not in store.finds["r1"]


def test_select_for_extraction_fills_with_weak_up_to_limit(monkeypatch):
    monkeypatch.setattr(rs, "EXTRACT_FILL_LOW", 2)
    pool = ([{"item_id": f"s{k}", "screen_score": 3, "recall_score": 0.1} for k in range(3)]
            + [{"item_id": f"w{k}", "screen_score": 1, "recall_score": k / 10} for k in range(5)]
            + [{"item_id": "z", "screen_score": 0, "recall_score": 1.0}])
    ids = [c["item_id"] for c in rs.select_for_extraction(pool, 10)]
    assert ids == ["s0", "s1", "s2", "w4", "w3"]
    assert len(rs.select_for_extraction(pool, 2)) == 2


def test_coverage_summary_counts_per_aspect():
    plan = rs.parse_plan(GOOD_PLAN, "v")
    f = {"i1": {"relevance": 2, "findings": [
        {"claim": "Gemeente bouwt zelf", "aspect": "a1", "actors": ["Gemeente X"], "region": "NL", "evidence": "case"}]}}
    out = rs.coverage_summary(plan, f, {"i1": {"source": "Bron"}})
    assert "Zelf bouwen (a1): 1 bevindingen" in out and "Gemeente X" in out and "Open standaarden (a2): 0" in out


def test_date_spread_by_year_and_recent_quarters():
    srcs = [{"date": d} for d in ("2024-05-01", "2026-01-10", "2026-02-01", "2026-08-30", None)]
    assert rs.date_spread(srcs) == "2024: 1, 2026: 3, ?: 1 (waarvan 2026 per kwartaal: Q1 2, Q3 1)"


def test_can_access_owner_and_unowned_only():
    assert rs.can_access("u1", "u1")
    assert rs.can_access(None, "u1")  # via Okavango gestart
    assert not rs.can_access("u2", "u1")
    assert rs.can_access(uuid.UUID(int=1), str(uuid.UUID(int=1)))


def test_today_note_names_the_date_and_year():
    from datetime import date
    note = rs.today_note(date(2026, 11, 8))
    assert note.startswith("Vandaag is het 8 november 2026.")
    assert "t/m 2026" not in note and "tot en met 2026" in note


def test_drop_date_disputes_keeps_real_issues():
    issues = [
        # Letterlijk uit de eerste live-run (Gemini 2.5 Pro):
        {"type": "unsupported", "where": "Wat verschuift er in de tijd",
         "fix": "Erken expliciet dat dit een prospectief scenario-archief, fictieve dataset of "
                "speculatieve exercitie is. Gebruik geen '2026'-bronnen als empirische bewijslast."},
        {"type": "unsupported", "where": "In het kort",
         "problem": "Sources dated 2026 are fictional and have not yet been published."},
        {"type": "miscited", "where": "Nederlandse overheidsdynamiek",
         "fix": "Wijzig 'verbod' in 'aanbeveling' (S90, 2026)."},
        {"type": "overgeneralized", "where": "In het kort",
         "fix": "Meld dat dit een speculatief inzicht van één analist is."},
    ]
    kept = rs.drop_date_disputes(issues)
    assert [i["type"] for i in kept] == ["miscited", "overgeneralized"]


async def test_write_critique_and_revise_prompts_carry_todays_date():
    seen = []

    class DateLLM(FakeLLM):
        async def call_llm(self, model, messages, **kw):
            seen.append(messages[-1]["content"])
            return await super().call_llm(model, messages, **kw)

    run, _ = await _run(rs.MemoryStore(), DateLLM())
    assert run["status"] == "done"
    dated = [m for m in seen if m.startswith("Vandaag is het ")]
    assert len(dated) >= 3  # schrijven, kritiek, herziening


DRAFT = "# Titel\n\n" + "Bedrijven bouwen zelf software [S1]. " * 100


def test_clean_revision_accepts_dossier_and_strips_short_preamble():
    good = "# Titel\n\n" + "Sommige bedrijven bouwen zelf [S1]. " * 100
    assert rs.clean_revision(DRAFT, good) == good.strip()
    assert rs.clean_revision(DRAFT, "Hier is het herziene dossier:\n\n" + good) == good.strip()


def test_clean_revision_rejects_leaked_reasoning_and_runaway_length():
    leaked = ("De gebruiker vraagt me om het dossier te herzien. Ik moet:\n1. punten verwerken\n"
              + "Ik moet ook controleren of ik iets herhaal. " * 200 + "\n# Titel\n\nTekst [S1].")
    assert rs.clean_revision(DRAFT, leaked) is None
    assert rs.clean_revision(DRAFT, DRAFT * 3) is None            # ontspoord doorschrijven
    assert rs.clean_revision(DRAFT, "Geen kop, alleen tekst. " * 100) is None
    thinking_inside = DRAFT + "\nIk moet nog de tabel aanpassen.\n"
    assert rs.clean_revision(DRAFT, thinking_inside) is None


class LeakyReviseLLM(FakeLLM):
    def __init__(self, bad_models, **kw):
        super().__init__(**kw)
        self.bad_models = set(bad_models)

    async def call_llm(self, model, messages, **kw):
        out = await super().call_llm(model, messages, **kw)
        if messages[0]["content"] == REVISE_SYSTEM and model in self.bad_models:
            return "De gebruiker vraagt me om het onderzoeksdossier te herzien. Ik moet: ..."
        return out


async def test_bad_revision_falls_back_to_next_model():
    run, _ = await _run(rs.MemoryStore(), LeakyReviseLLM({"w1"}))
    assert run["status"] == "done"
    assert run["models"]["revise"] == "w2"
    assert run["report"].startswith("# Dossier\n\nSommige bedrijven")


async def test_all_revisions_bad_keeps_the_draft():
    run, _ = await _run(rs.MemoryStore(), LeakyReviseLLM({"w1", "w2"}))
    assert run["status"] == "done"
    assert run["models"]["revise"] is None
    assert run["report"].startswith("# Dossier\n\nBedrijven bouwen zelf [S1, S2]")
    assert "S99" not in run["report"]


async def test_resume_adds_to_earlier_stats_instead_of_replacing():
    store = rs.MemoryStore()
    earlier = {"llm_calls": 5, "llm_failures": 1, "secs": 600,
               "by_model": {"w1": {"calls": 4, "failures": 1, "secs": 500.0}}}
    run, _ = await _run(store, FakeLLM(), stats=earlier)
    s = run["stats"]
    assert s["llm_calls"] > 5 and s["llm_failures"] >= 1
    assert s["by_model"]["w1"]["calls"] > 4
    assert s["by_model"]["w1"]["secs"] >= 500.0
    assert s["secs"] >= 600
