"""Tests for live session memory recap."""

from __future__ import annotations

from persona_ai.core.types import Message
from persona_ai.web.session_memory import (
    collapse_history,
    format_companion_context_block,
    format_live_history_block,
    live_memory_steer_text,
    load_companion_context_for_turn,
    post_call_summary,
)
from persona_ai.memory.engine import add_memory, reset_memory_store
from persona_ai.memory.open_loop_engine import create_open_loop, reset_open_loop_store
from persona_ai.memory.open_loop_extract import OpenLoopCandidate


class TestSessionMemory:
    def test_collapse_partials(self):
        history = [
            Message.from_text("user", "Ko nama sa Obet"),
            Message.from_text("user", "Ko nama sa Obet dari Jayapura"),
        ]
        collapsed = collapse_history(history)
        assert len(collapsed) == 1
        assert "Jayapura" in collapsed[0].text

    def test_post_call_summary(self):
        summary = post_call_summary(
            {"data": {"call_summary": "Ko cerita tentang mop Obet dan mobil ceper."}}
        )
        assert summary and "Obet" in summary

    def test_format_block_papua(self):
        history = [
            Message.from_text("user", "Ko ingat nama sa Obet?"),
            Message.from_text("assistant", "Iyo toh, ko Obet dari Jayapura."),
            Message.from_text("user", "Kemarin ko bilang su beli mobil ceper."),
        ]
        block = format_live_history_block(history, dialect="papua")
        assert "Konteks obrolan" in block
        assert "Obet" in block
        assert "Percakapan terbaru" in block
        assert "mobil ceper" in block

    def test_older_digest_when_long(self):
        history = [
            Message.from_text("user" if i % 2 == 0 else "assistant", f"Giliran {i} topik {i}")
            for i in range(20)
        ]
        block = format_live_history_block(history, dialect="papua")
        assert "Ringkasan awal" in block
        assert "Giliran 0" in block or "Giliran 1" in block

    def test_memory_steer_disabled_mid_call(self):
        """Mid-call text injection caused Gemini to speak twice — steer stays off."""
        history = [
            Message.from_text("user", f"Topik {i}") for i in range(6)
        ]
        steer = live_memory_steer_text(history, dialect="papua")
        assert steer is None

    def test_post_call_deduped_when_in_user_memory(self):
        from persona_ai.memory.models import UserMemoryRecord

        memories = [
            UserMemoryRecord(
                content="Ngobrol tentang mop Obet dan mobil ceper.",
                memory_type="episodic",
            )
        ]
        block = format_live_history_block(
            [],
            post_call={"data": {"call_summary": "Ko cerita tentang mop Obet dan mobil ceper."}},
            dialect="papua",
            user_memories=memories,
            include_user_memory=True,
        )
        assert block.count("mobil ceper") == 1
        assert "Ringkasan panggilan" not in block

    def test_companion_memory_in_live_block(self, tmp_path, monkeypatch):
        db_path = tmp_path / "user_memory.db"
        monkeypatch.setenv("PERSONA_MEMORY_DB", str(db_path))
        reset_memory_store()
        reset_open_loop_store()
        add_memory("Nama ko Obet", memory_type="semantic")
        create_open_loop(
            OpenLoopCandidate(
                topic="motor",
                content="Minggu depan sa mo beli motor",
                time_hint="minggu depan",
                confidence=0.9,
            ),
        )
        history = [Message.from_text("user", "Eh motor minggu depan gimana ya?")]
        block = format_live_history_block(
            history,
            dialect="papua",
            include_companion_memory=True,
        )
        assert "URUSAN BELUM SELESAI" in block
        assert "motor" in block.lower()
        reset_memory_store()
        reset_open_loop_store()

    def test_format_companion_context_block(self, tmp_path, monkeypatch):
        db_path = tmp_path / "user_memory.db"
        monkeypatch.setenv("PERSONA_MEMORY_DB", str(db_path))
        reset_memory_store()
        reset_open_loop_store()
        create_open_loop(
            OpenLoopCandidate(
                topic="rapat",
                content="Lusa sa ada rapat dengan tim",
                time_hint="lusa",
                confidence=0.9,
            ),
        )
        ctx = load_companion_context_for_turn("rapat tim", messages=[])
        block = format_companion_context_block(ctx, dialect="papua")
        assert "rapat" in block.lower()
        reset_memory_store()
        reset_open_loop_store()
