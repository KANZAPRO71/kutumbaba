import asyncio

from persona_ai.web.live_session_hub import (
    note_mode_applied_via_websocket,
    register_live_session,
    request_mode_change_from_ui,
    unregister_live_session,
)


def test_hub_skips_duplicate_and_websocket_sync():
    loop = asyncio.new_event_loop()
    applied: list[str] = []

    async def apply_mode(mode: str) -> None:
        applied.append(mode)

    register_live_session(loop, apply_mode, initial_mode="nongkrong")
    try:
        r1 = request_mode_change_from_ui("nongkrong")
        assert r1["applied"] is False
        assert r1["reason"] == "unchanged"

        r2 = request_mode_change_from_ui("mop")
        assert r2["applied"] is True
        loop.run_until_complete(asyncio.sleep(0.05))
        assert applied == ["mop"]

        note_mode_applied_via_websocket("cerita_tong")
        r3 = request_mode_change_from_ui("cerita_tong")
        assert r3["applied"] is False
    finally:
        unregister_live_session()
        loop.close()
