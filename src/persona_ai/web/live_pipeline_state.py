"""Shared Live pipeline busy/idle — gate send_client_content away from mic/ASR."""

from __future__ import annotations


def answer_in_flight(gov: dict) -> bool:
    """True while Persona is steering or Gemini is still producing the governed reply."""
    if gov.get("pending") or gov.get("awaiting_steered_turn"):
        return True
    if gov.get("awaiting_turn_complete"):
        return True
    if gov.get("model_generating") and not (
        gov.get("activity_end_for_asr") or gov.get("awaiting_asr_recovery")
    ):
        return True
    final_task = gov.get("final_task")
    return final_task is not None and not final_task.done()


def live_pipeline_idle(gov: dict) -> bool:
    """Safe window for send_client_content (turn_complete=False) meta/context inject."""
    return not (
        gov.get("user_activity_open")
        or gov.get("gemini_activity_open")
        or gov.get("model_generating")
        or answer_in_flight(gov)
        or gov.get("pending")
    )
