"""Gemini 3.1 model identifiers — single source of truth for Persona integrations."""

from __future__ import annotations

import os

# Text rendering — Interactions API (PersonaRuntime LLM path)
DEFAULT_GEMINI_TEXT_MODEL = "gemini-3.1-flash-lite-preview"

# Duplex voice — Live API (persona-chat voice call)
DEFAULT_GEMINI_LIVE_MODEL = "gemini-3.1-flash-live-preview"

# Text-to-speech — chat read-aloud (same prebuilt voices as Live)
DEFAULT_GEMINI_TTS_MODEL = "gemini-2.5-flash-preview-tts"


def gemini_text_model() -> str:
    return os.environ.get("GEMINI_MODEL", DEFAULT_GEMINI_TEXT_MODEL)


def gemini_live_model() -> str:
    return os.environ.get("GEMINI_LIVE_MODEL", DEFAULT_GEMINI_LIVE_MODEL)


def gemini_tts_model() -> str:
    return os.environ.get("GEMINI_TTS_MODEL", DEFAULT_GEMINI_TTS_MODEL)


def gemini_post_call_model() -> str:
    """Post-call analytics — Retell Post Call Data Retrieval."""
    return os.environ.get("GEMINI_POST_CALL_MODEL", gemini_text_model())
