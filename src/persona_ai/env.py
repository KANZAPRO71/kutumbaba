"""Load `.env` from project cwd or nearest parent — safe no-op without python-dotenv."""

from __future__ import annotations

from pathlib import Path


def load_project_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return

    load_dotenv()
    found: Path | None = None
    start = Path.cwd()
    for directory in (start, *start.parents):
        env_file = directory / ".env"
        if env_file.is_file():
            found = env_file
            break

    module_root = Path(__file__).resolve().parents[2]
    if found is None:
        for directory in (module_root, *module_root.parents):
            env_file = directory / ".env"
            if env_file.is_file():
                found = env_file
                break

    if found is not None:
        load_dotenv(found, override=True)
