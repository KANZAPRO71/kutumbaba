"""Tests for simple local RAG database loader."""

from __future__ import annotations

import json
from pathlib import Path

from persona_ai.personality.papua_local_database import (
    ambil_mop_acak_dari_database,
    database_stats,
    format_papua_database_context,
    load_papua_database,
    muat_pengetahuan_lokal,
)


def test_muat_pengetahuan_lokal_from_repo_file():
    text = muat_pengetahuan_lokal()
    assert "DATABASE PENGETAHUAN LOKALMU" in text
    assert "Jang Ganggu" in text
    assert "Barapen" in text
    assert "lampu merah" in text
    assert "helm terbalik" in text.lower() or "Helm Terbalik" in text
    assert "Nokia" in text or "nimboran" in text.lower()


def test_ambil_mop_acak_dari_database():
    text = ambil_mop_acak_dari_database()
    assert len(text) > 30


def test_format_skips_empty_sections(tmp_path: Path):
    data = {"mop_list": ["Satu mop."], "lagu_list": [], "budaya_list": []}
    text = format_papua_database_context(data)
    assert "CERITA MOP KANTONG" in text
    assert "DAFTAR LAGU POPULER" not in text


def test_load_missing_file_returns_empty(tmp_path: Path):
    missing = tmp_path / "missing.json"
    data = load_papua_database(missing)
    assert data["mop_list"] == []
    assert muat_pengetahuan_lokal(missing) == ""


def test_load_custom_json(tmp_path: Path):
    path = tmp_path / "database_papua.json"
    path.write_text(
        json.dumps(
            {
                "mop_list": ["Mop tes."],
                "lagu_list": ["Lagu tes."],
                "budaya_list": ["Budaya tes."],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    data = load_papua_database(path)
    assert database_stats(data) == {"mop_list": 1, "lagu_list": 1, "budaya_list": 1}
    text = muat_pengetahuan_lokal(path)
    assert "Mop tes." in text
    assert "Lagu tes." in text
    assert "Budaya tes." in text
