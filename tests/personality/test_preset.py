"""Personality preset tests — Phase 4 configuration extraction."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from persona_ai.behavior.engine import decide, execution_profile
from persona_ai.coherence.bind import bind
from persona_ai.core.types import (
    BehaviorInput,
    Message,
    PersonalityProfile,
    ResponseLength,
    SpeakAction,
    TurnHistory,
)
from persona_ai.personality.apply import apply
from persona_ai.personality.preset import (
    PRESET_SCHEMA_VERSION,
    PresetValidationError,
    default_preset_path,
    legacy_default_profile,
    load_default_preset,
    load_preset,
    validate_preset,
)
from persona_ai.runtime import PersonaRuntime
from persona_ai.session.store import InMemorySessionStore


@pytest.fixture
def preset_path() -> Path:
    return default_preset_path()


class TestDefaultPresetLoads:
    def test_loads_successfully(self, preset_path: Path):
        profile = load_preset(preset_path)
        assert profile.preset_id == "default_companion"
        assert profile.preset_version == "1.0.0"

    def test_schema_version(self, preset_path: Path):
        data = json.loads(preset_path.read_text(encoding="utf-8"))
        assert data["schema_version"] == PRESET_SCHEMA_VERSION
        validate_preset(data)


class TestPresetValuesMatchLegacy:
    def test_traits_equal_hardcoded_defaults(self, preset_path: Path):
        preset = load_preset(preset_path)
        legacy = legacy_default_profile()
        assert preset.warmth == legacy.warmth == 0.6
        assert preset.formality == legacy.formality == 0.3
        assert preset.directness == legacy.directness == 0.5

    def test_ack_templates_are_empty(self, preset_path: Path):
        preset = load_preset(preset_path)
        assert preset.ack_templates.vent == []
        assert preset.ack_templates.neutral == []
        assert preset.ack_templates.warm == []

    def test_expression_word_limits_match_apply_defaults(self, preset_path: Path):
        preset = load_preset(preset_path)
        assert preset.max_words_minimal == 20
        assert preset.max_words_normal == 70
        assert preset.max_words_expand == 180


class TestPersonaRuntimePresetResolution:
    def test_runtime_without_profile_uses_default_preset(self):
        runtime = PersonaRuntime(session_store=InMemorySessionStore())
        assert runtime.personality_profile.preset_id == "default_companion"

    def test_injected_profile_overrides_preset(self):
        custom = PersonalityProfile(id="custom", warmth=0.8)
        runtime = PersonaRuntime(
            session_store=InMemorySessionStore(),
            personality_profile=custom,
        )
        assert runtime.personality_profile.id == "custom"
        assert runtime.personality_profile.preset_id is None
        assert runtime.personality_profile.warmth == 0.8


class TestBehaviorUnchanged:
    def test_bdv_identical_preset_vs_legacy(self, preset_path: Path):
        preset = load_preset(preset_path)
        legacy = legacy_default_profile()
        text = "Besok meeting jam berapa?"
        inp = BehaviorInput(message=Message.from_text("user", text))
        bdv_preset = decide(inp)
        bdv_legacy = decide(inp)
        assert bdv_preset.speak == bdv_legacy.speak == SpeakAction.RESPOND
        assert preset.warmth == legacy.warmth

    def test_expression_identical_preset_vs_legacy(self, preset_path: Path):
        preset = load_preset(preset_path)
        legacy = legacy_default_profile()
        text = "Ah capek banget hari ini ya..."
        bdv = decide(BehaviorInput(message=Message.from_text("user", text)))
        expr_preset = apply(preset, bdv, execution_profile=execution_profile(bdv))
        expr_legacy = apply(legacy, bdv, execution_profile=execution_profile(bdv))
        assert expr_preset.template_ack is None
        assert expr_legacy.template_ack is None
        assert expr_preset.max_words == expr_legacy.max_words
        assert expr_preset.max_sentences == expr_legacy.max_sentences

    def test_coherence_clamp_identical(self, preset_path: Path):
        preset = load_preset(preset_path)
        legacy = legacy_default_profile()
        text = "Ah capek banget hari ini ya..."
        bdv = decide(BehaviorInput(message=Message.from_text("user", text)))
        for profile in (preset, legacy):
            expr = apply(profile, bdv, execution_profile=execution_profile(bdv))
            voice = bind(bdv, expr, profile)
            assert voice.effective_warmth >= 0.45


class TestRuntimeBehaviorPaths:
    def test_vent_ack_is_natural_not_canned(self):
        runtime = PersonaRuntime(session_store=InMemorySessionStore())
        out = runtime.process_turn("vent-preset", "Ah capek banget hari ini ya...")
        assert out.text not in ("Berat ya.", "Iyaa, paham.", "Iya.")
        assert out.text

    def test_silence_unchanged(self):
        runtime = PersonaRuntime(session_store=InMemorySessionStore())
        from persona_ai.session.models import SessionState

        session = SessionState.new("silent-preset", profile_warmth=0.6)
        session.turn_history = TurnHistory(
            last_assistant_word_count=200,
            last_assistant_verbosity=ResponseLength.EXPAND,
        )
        runtime.session_store.save(session)
        out = runtime.process_turn("silent-preset", "Oke")
        assert out.voice.speak == SpeakAction.SILENCE
        assert out.text is None

    def test_defer_unchanged(self):
        runtime = PersonaRuntime(session_store=InMemorySessionStore())
        out = runtime.process_turn("defer-preset", "Jadi rencananya...", voice_pause_ms=1200)
        assert out.voice.speak == SpeakAction.DEFER


class TestMalformedPreset:
    def test_unknown_schema_version(self, tmp_path: Path, preset_path: Path):
        data = json.loads(preset_path.read_text(encoding="utf-8"))
        data["schema_version"] = "persona_preset_v9"
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(PresetValidationError, match="unsupported schema_version"):
            load_preset(bad)

    def test_missing_required_field(self, tmp_path: Path, preset_path: Path):
        data = json.loads(preset_path.read_text(encoding="utf-8"))
        del data["traits"]
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(PresetValidationError, match="missing required field"):
            load_preset(bad)

    def test_trait_out_of_range(self, tmp_path: Path, preset_path: Path):
        data = json.loads(preset_path.read_text(encoding="utf-8"))
        data["traits"]["warmth"] = 1.5
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(PresetValidationError, match="out of range"):
            load_preset(bad)

    def test_invalid_tone_shift(self, tmp_path: Path, preset_path: Path):
        data = json.loads(preset_path.read_text(encoding="utf-8"))
        data["tone"]["allowed_shifts"] = ["LOUD"]
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(PresetValidationError, match="invalid tone shift"):
            load_preset(bad)

    def test_no_diagnostics_in_preset_file(self, preset_path: Path):
        data = json.loads(preset_path.read_text(encoding="utf-8"))
        blob = json.dumps(data).lower()
        for forbidden in ("diagnostics", "forecast", "metastability", "telemetry"):
            assert forbidden not in blob
