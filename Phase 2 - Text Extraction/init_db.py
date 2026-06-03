#!/usr/bin/env python3
"""Create the database schema (tables, indexes, generated columns).

Usage:
    python scripts/init_db.py        # uses DATABASE_URL from .env
"""

from __future__ import annotations

import sys

from src.db import get_engine, init_db


def main() -> int:
    """Create all tables and exit."""
    engine = get_engine()
    init_db(engine)
    print(f"[init_db] schema created on {engine.url.render_as_string(hide_password=True)}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
