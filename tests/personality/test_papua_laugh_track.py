"""Tests for Raja Mop laugh track triggers."""

from __future__ import annotations

from persona_ai.personality.papua_laugh_track import (
    mark_humor_turn,
    should_play_jedag_jedug,
    should_play_laugh_track,
)

_LONG_MOP = (
    "Obet dengan Tinus dorang dua baru sewa rumah murah di pinggiran Jayapura. "
    "Pas dorang dua pasang TV baru setel, layarnya tra mau ganti, isinya film setan terus. "
    "Obet emosi... Ko kira sa ini ko punya bapak kah?!"
)


class TestPapuaLaughTrack:
    def test_mark_humor_turn_mop_request(self):
        gov: dict = {}
        mark_humor_turn(gov, "Pace, kasi mop yang paling tope dulu!")
        assert gov.get("laugh_track_pending") is True

    def test_should_play_after_mop_punchline(self):
        gov = {
            "laugh_track_pending": True,
            "assistant_text": _LONG_MOP,
        }
        assert should_play_laugh_track(gov, "papua") is True

    def test_skipped_short_response(self):
        gov = {
            "laugh_track_pending": True,
            "assistant_text": "Hahaha adooo pace...",
        }
        assert should_play_laugh_track(gov, "papua") is False

    def test_skipped_non_papua(self):
        gov = {"laugh_track_pending": True, "assistant_text": _LONG_MOP}
        assert should_play_laugh_track(gov, None) is False

    def test_assistant_mop_markers_long(self):
        gov = {
            "assistant_text": (
                "Satu kali Tinus de ikut tes mengemudi truk kontainer di Jayapura. "
                "Penguji tanya banyak hal sampai Tinus emosi... Adooo Komandan, sa tabrak jurang saja toh!"
            ),
        }
        assert should_play_laugh_track(gov, "papua") is True

    def test_jedag_jedug_same_as_laugh(self):
        gov = {"laugh_track_pending": True, "assistant_text": _LONG_MOP}
        assert should_play_jedag_jedug(gov, "papua") is True
        assert should_play_jedag_jedug(gov, None) is False
