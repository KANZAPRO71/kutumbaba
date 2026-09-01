"""Tests for permanent developer credit — Posman Silaban."""

from __future__ import annotations

from persona_ai.personality.papua_developer_credit import (
    developer_credit_prompt_lines,
    developer_name,
    is_developer_query,
    retrieve_developer_facts,
    ui_credit_line,
)


class TestDeveloperCredit:
    def test_developer_name(self):
        assert developer_name() == "Posman Silaban"

    def test_ui_credit(self):
        assert "Posman Silaban" in ui_credit_line()

    def test_is_developer_query(self):
        assert is_developer_query("siapa yang buat app ini")
        assert is_developer_query("Posman Silaban siapa")
        assert not is_developer_query("cerita mop obet")

    def test_retrieve_facts(self):
        hits = retrieve_developer_facts("siapa pengembang papua ai")
        assert hits
        assert any("posman silaban" in h.lower() for h in hits)

    def test_prompt_permanent(self):
        lines = developer_credit_prompt_lines("papua")
        joined = " ".join(lines).lower()
        assert "posman silaban" in joined
        assert "permanen" in joined or "wajib" in joined

    def test_prompt_query(self):
        lines = developer_credit_prompt_lines("papua", query="siapa dev nya")
        joined = " ".join(lines).lower()
        assert "posman silaban" in joined
