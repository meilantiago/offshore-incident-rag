"""`ChunkerPlan` and `CHUNKERS_BY_DOC_TYPE` (AC-002-01, AC-002-02)."""

from __future__ import annotations

import pytest

from offshore_rag.config import Settings
from offshore_rag.ingestion.chunking import ChunkerConfigError, ChunkerPlan, FixedWordChunker
from offshore_rag.ingestion.pdf import PageText


def _settings(**kwargs: object) -> Settings:
    return Settings(_env_file=None, **kwargs)  # type: ignore[arg-type]


def test_defaults_run_fixed_words_for_every_type() -> None:
    plan = ChunkerPlan.from_settings(_settings())
    for doc_type in ("safety_alert", "panel_report", "district_report"):
        (chunker,) = plan.for_doc_type(doc_type)
        assert chunker.id == "fixed_words"
        assert dict(chunker.params) == {"size": 250, "overlap": 40}


def test_per_type_override_replaces_the_list_only_for_that_type() -> None:
    plan = ChunkerPlan.from_settings(_settings(chunkers_by_doc_type={"panel_report": ["fixed_words", "fixed_words"]}))
    assert len(plan.for_doc_type("panel_report")) == 2
    assert len(plan.for_doc_type("safety_alert")) == 1


def test_empty_override_disables_chunking_for_that_type() -> None:
    plan = ChunkerPlan.from_settings(_settings(chunkers_by_doc_type={"safety_alert": []}))
    assert plan.for_doc_type("safety_alert") == []


def _assert_message(e: pytest.ExceptionInfo[ChunkerConfigError], setting: str, offending: str) -> None:
    msg = str(e.value)
    assert setting in msg
    assert offending in msg
    assert "fixed_words" in msg
    for doc_type in ("safety_alert", "panel_report", "district_report"):
        assert doc_type in msg


def test_unknown_strategy_names_setting_strategies_and_types() -> None:
    with pytest.raises(ChunkerConfigError) as e:
        ChunkerPlan.from_settings(_settings(chunkers=["fixed_words", "semantic_v9"]))
    _assert_message(e, "CHUNKERS", "semantic_v9")


def test_unknown_strategy_in_override_names_the_override_setting() -> None:
    with pytest.raises(ChunkerConfigError) as e:
        ChunkerPlan.from_settings(_settings(chunkers_by_doc_type={"panel_report": ["semantic_v9"]}))
    _assert_message(e, "CHUNKERS_BY_DOC_TYPE", "semantic_v9")


def test_unknown_doc_type_names_setting_and_valid_types() -> None:
    with pytest.raises(ChunkerConfigError) as e:
        ChunkerPlan.from_settings(_settings(chunkers_by_doc_type={"incident_memo": ["fixed_words"]}))
    _assert_message(e, "CHUNKERS_BY_DOC_TYPE", "incident_memo")


def test_fixed_words_output_ignores_doc_type_and_has_no_section() -> None:
    pages = [PageText(1, " ".join(f"w{i}" for i in range(30)), False)]
    chunker = FixedWordChunker(size=10, overlap=2)
    outputs = [chunker.chunk(pages, t) for t in ("safety_alert", "panel_report", "district_report")]
    assert outputs[0] == outputs[1] == outputs[2]
    assert all(d.section is None for d in outputs[0])
