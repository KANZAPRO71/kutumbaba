from __future__ import annotations

from persona_ai.web.live_context_injection import (
    build_context_summary,
    format_context_turn_text,
    telemetry_signature,
)


def test_format_context_turn_text():
    t = format_context_turn_text("Baterai 50%")
    assert t.startswith("[SITUATIONAL_CONTEXT_UPDATE:")
    assert "Baterai 50%" in t
    assert t.endswith("]")


def test_build_context_summary_from_telemetry():
    summary = build_context_summary(
        {
            "ok": True,
            "latitude": -2.5,
            "longitude": 140.7,
            "accuracy_m": 12,
            "movement_mode": "driving",
            "speed_kmh": 48,
            "battery_percent": 15,
            "charging": False,
            "network": "cellular",
        }
    )
    assert summary is not None
    assert "15%" in summary
    assert "driving" in summary


def test_telemetry_signature_changes_on_movement():
    a = telemetry_signature({"movement_mode": "walking", "speed_kmh": 2, "battery_percent": 80})
    b = telemetry_signature({"movement_mode": "driving", "speed_kmh": 50, "battery_percent": 80})
    assert a != b
