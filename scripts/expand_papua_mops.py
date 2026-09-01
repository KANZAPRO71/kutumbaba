"""One-off helper: validate papua_mops.json count (run after manual edits)."""

from persona_ai.personality.papua_mops import mop_count, preview_mops, session_mop_samples

if __name__ == "__main__":
    print("mop_count:", mop_count())
    print("session_samples:", len(session_mop_samples()))
    print("preview:", preview_mops(5))
