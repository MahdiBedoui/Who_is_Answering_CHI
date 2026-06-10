#!/usr/bin/env python3
"""Create the database schema (tables, indexes, generated columns).

Usage:
    python "Phase 2 - Text Extraction/init_db.py"        # uses DATABASE_URL from .env
"""

from __future__ import annotations

import sys
from pathlib import Path

# src/ lives alongside this script (Phase 2 - Text Extraction/src/); put this
# script's own directory on the path so `from src.X` resolves regardless of cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.db import get_engine, init_db  # noqa: E402


def main() -> int:
    """Create all tables and exit."""
    engine = get_engine()
    init_db(engine)
    print(f"[init_db] schema created on {engine.url.render_as_string(hide_password=True)}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
