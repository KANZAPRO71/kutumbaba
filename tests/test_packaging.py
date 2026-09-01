"""Preset packaging tests — bundled resources survive wheel install."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from persona_ai.personality.preset import (
    list_preset_resources,
    load_default_preset,
    load_preset_by_id,
    load_preset_resource,
)
from persona_ai.runtime import PersonaRuntime


class TestBundledPresets:
    def test_default_companion_loads_from_package(self):
        profile = load_default_preset()
        assert profile.preset_id == "default_companion"

    def test_preset_resources_listed(self):
        names = list_preset_resources()
        assert "default_companion.json" in names

    def test_runtime_uses_bundled_default(self):
        runtime = PersonaRuntime()
        assert runtime.personality_profile.preset_id == "default_companion"

    def test_load_preset_resource_round_trip(self):
        profile = load_preset_resource("default_companion.json")
        assert profile.warmth == 0.6


@pytest.mark.packaging
def test_wheel_install_loads_default_preset(tmp_path: Path):
    """Build wheel, install in isolated env, verify bundled preset loads."""
    project_root = Path(__file__).resolve().parents[1]
    wheel_dir = tmp_path / "wheels"
    venv_dir = tmp_path / "venv"
    wheel_dir.mkdir()
    subprocess.run(
        [sys.executable, "-m", "pip", "wheel", str(project_root), "-w", str(wheel_dir)],
        check=True,
        capture_output=True,
        text=True,
    )
    wheels = list(wheel_dir.glob("persona_ai-*.whl"))
    assert wheels, "wheel build produced no artifact"
    subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True, capture_output=True)
    pip = venv_dir / ("Scripts" if sys.platform == "win32" else "bin") / "pip"
    python = venv_dir / ("Scripts" if sys.platform == "win32" else "bin") / "python"
    subprocess.run([str(pip), "install", str(wheels[0])], check=True, capture_output=True)
    probe = (
        "from persona_ai import PersonaRuntime; "
        "r=PersonaRuntime(); "
        "assert r.personality_profile.preset_id=='default_companion'"
    )
    subprocess.run([str(python), "-c", probe], check=True, capture_output=True, text=True)
