"""Persona preset loading and validation — data-driven personality only."""

from __future__ import annotations

import json
from importlib.resources import as_file, files
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from persona_ai.core.types import AckTemplates, PersonalityProfile, ToneShift

PRESET_SCHEMA_VERSION = "persona_preset_v1"
DEFAULT_PRESET_ID = "default_companion"
PRESET_PACKAGE = "persona_ai.presets"

VALID_TONE_SHIFTS = {shift.value for shift in ToneShift}


class PresetValidationError(ValueError):
    """Raised when a preset file fails validation."""


class PresetTraits(BaseModel):
    warmth: float
    formality: float
    directness: float
    empathy: float = 0.5
    humor: float = 0.0


class PresetExpression(BaseModel):
    default_language: str = "id"
    max_words_normal: int = 70
    max_words_minimal: int = 20
    max_words_expand: int = 180
    question_budget: int = 0
    lexicon: dict[str, list[str]] = Field(default_factory=dict)


class PresetTone(BaseModel):
    baseline: str = "casual-warm"
    allowed_shifts: list[str] = Field(default_factory=list)


class PersonaPresetDocument(BaseModel):
    schema_version: str
    preset_id: str
    version: str
    display_name: str = "Persona"
    traits: PresetTraits
    expression: PresetExpression
    tone: PresetTone
    ack_templates: AckTemplates


def list_preset_resources() -> list[str]:
    return [item.name for item in files(PRESET_PACKAGE).iterdir() if item.name.endswith(".json")]


def preset_resource_name(preset_id: str) -> str:
    if preset_id.endswith(".json"):
        return preset_id
    return f"{preset_id}.json"


def read_preset_json(filename: str) -> dict[str, Any]:
    resource = files(PRESET_PACKAGE).joinpath(preset_resource_name(filename))
    with resource.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def default_preset_path() -> Path:
    """Path to bundled default preset (for tests/tools that need a filesystem path)."""
    with as_file(files(PRESET_PACKAGE).joinpath("default_companion.json")) as path:
        return Path(path)


def validate_preset(data: dict[str, Any]) -> PersonaPresetDocument:
    """Validate preset document; fail loudly on malformed required fields."""
    if not isinstance(data, dict):
        raise PresetValidationError("preset must be a JSON object")

    version = data.get("schema_version")
    if version is None:
        raise PresetValidationError("missing required field: schema_version")
    if version != PRESET_SCHEMA_VERSION:
        raise PresetValidationError(f"unsupported schema_version: {version!r}")

    for field in ("preset_id", "version", "traits", "expression", "tone", "ack_templates"):
        if field not in data:
            raise PresetValidationError(f"missing required field: {field}")

    try:
        doc = PersonaPresetDocument.model_validate(data)
    except ValidationError as exc:
        raise PresetValidationError(f"invalid preset document: {exc}") from exc

    for name, value in doc.traits.model_dump().items():
        if not 0.0 <= value <= 1.0:
            raise PresetValidationError(f"trait {name} out of range [0,1]: {value}")

    if doc.expression.question_budget < 0:
        raise PresetValidationError("expression.question_budget must be >= 0")

    for shift in doc.tone.allowed_shifts:
        if shift not in VALID_TONE_SHIFTS:
            raise PresetValidationError(f"invalid tone shift: {shift!r}")

    for key in ("vent", "neutral", "warm", "closure"):
        items = getattr(doc.ack_templates, key)
        if not isinstance(items, list) or not all(isinstance(item, str) for item in items):
            raise PresetValidationError(f"ack_templates.{key} must be a list of strings")

    lexicon = doc.expression.lexicon
    for key in ("preferred_phrases", "avoided_phrases"):
        if key in lexicon and (
            not isinstance(lexicon[key], list)
            or not all(isinstance(item, str) for item in lexicon[key])
        ):
            raise PresetValidationError(f"expression.lexicon.{key} must be a list of strings")

    _reject_diagnostics_keys(data)
    return doc


def _reject_diagnostics_keys(data: dict[str, Any]) -> None:
    forbidden = {
        "diagnostics",
        "forecast",
        "metastability",
        "manifold",
        "telemetry",
        "cqf",
        "cps",
        "learning",
    }
    for key in data:
        if key.lower() in forbidden:
            raise PresetValidationError(f"preset must not contain diagnostics key: {key}")


def _document_to_profile(doc: PersonaPresetDocument) -> PersonalityProfile:
    lexicon = doc.expression.lexicon
    return PersonalityProfile(
        id=doc.preset_id,
        preset_id=doc.preset_id,
        preset_version=doc.version,
        display_name=doc.display_name,
        warmth=doc.traits.warmth,
        formality=doc.traits.formality,
        directness=doc.traits.directness,
        empathy=doc.traits.empathy,
        humor=doc.traits.humor,
        default_language=doc.expression.default_language,
        max_words_minimal=doc.expression.max_words_minimal,
        max_words_normal=doc.expression.max_words_normal,
        max_words_expand=doc.expression.max_words_expand,
        question_budget_cap=doc.expression.question_budget,
        lexicon_preferred=list(lexicon.get("preferred_phrases", [])),
        lexicon_avoided=list(lexicon.get("avoided_phrases", [])),
        tone_baseline=doc.tone.baseline,
        allowed_tone_shifts=list(doc.tone.allowed_shifts),
        ack_templates=doc.ack_templates.model_copy(deep=True),
    )


def load_preset_data(data: dict[str, Any]) -> PersonalityProfile:
    return _document_to_profile(validate_preset(data))


def load_preset_resource(filename: str) -> PersonalityProfile:
    """Load a bundled preset from the installed persona_ai.presets package."""
    return load_preset_data(read_preset_json(filename))


def load_preset_by_id(preset_id: str) -> PersonalityProfile:
    return load_preset_resource(preset_resource_name(preset_id))


def load_preset(path: str | Path) -> PersonalityProfile:
    """Load a preset from an explicit filesystem path (dev/override)."""
    preset_path = Path(path)
    if not preset_path.is_file():
        raise PresetValidationError(f"preset file not found: {preset_path}")
    try:
        raw = json.loads(preset_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PresetValidationError(f"invalid JSON in preset: {exc}") from exc
    return load_preset_data(raw)


def load_default_preset() -> PersonalityProfile:
    """Load the default companion preset shipped with Persona AI."""
    return load_preset_by_id(DEFAULT_PRESET_ID)


def legacy_default_profile() -> PersonalityProfile:
    """Equivalent to pre-preset hardcoded PersonalityProfile() defaults."""
    return PersonalityProfile()
