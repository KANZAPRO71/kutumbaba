#!/usr/bin/env python3
"""Export frasa logat Papua dari Hugging Face — delegasi ke build_papua_corpus.

Requires: pip install datasets

Usage:
  python scripts/export_papua_dialect_hf.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    script = ROOT / "scripts" / "build_papua_corpus.py"
    subprocess.run([sys.executable, str(script)], check=True)


if __name__ == "__main__":
    main()
