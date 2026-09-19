"""Mid-call experience mode switch — gov update + meta steer text."""

from __future__ import annotations

from persona_ai.conversation.experience_modes import normalize_experience_mode
from persona_ai.conversation.mode_prompt import mid_session_experience_mode_steer
from persona_ai.web.live_mode import LiveModeConfig
from persona_ai.web.conversation_controller import ConversationController


def prepare_live_experience_mode_switch(
    gov: dict,
    live_mode: LiveModeConfig,
    mode_raw: str,
    *,
    dialect: str | None = None,
) -> str | None:
    """Update runtime gov for new mode; return steer/meta body or None if unchanged."""
    new_mode = normalize_experience_mode(mode_raw)
    prev = normalize_experience_mode(gov.get("conversation_mode"))
    if new_mode == prev:
        return None
    gov["conversation_mode"] = new_mode
    gov["conv_ctrl"] = ConversationController.from_live_mode(
        live_mode,
        conversation_mode=new_mode,
    )
    stats = gov.get("experience_session_stats")
    if isinstance(stats, dict):
        stats["experience_mode"] = new_mode
    d = dialect if dialect is not None else gov.get("dialect")
    return mid_session_experience_mode_steer(
        new_mode,
        prev_mode=prev,
        dialect=d,
    )
