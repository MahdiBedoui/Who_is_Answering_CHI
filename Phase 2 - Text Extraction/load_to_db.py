#!/usr/bin/env python3
"""Load extracted JSON records into Postgres (Neon), validating each via Pydantic.

Reads every *.json in the extracted dir, validates against PaperRecord, and
UPSERTs into the `papers` table (insert-or-update on DOI). Idempotent: re-running
refreshes existing rows rather than duplicating them.

Usage:
    python scripts/load_to_db.py                       # loads data/extracted/*.json
    python scripts/load_to_db.py --input-dir data/extracted --batch 500
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pydantic import ValidationError  # noqa: E402
from sqlalchemy.dialects.postgresql import insert as pg_insert  # noqa: E402

from src.db import get_engine, init_db, session_scope  # noqa: E402
from src.models import Paper  # noqa: E402
from src.schema import PaperRecord  # noqa: E402


def log(message: str) -> None:
    """Print a progress/warning message to stderr."""
    print(message, file=sys.stderr, flush=True)


def iter_records(input_dir: Path) -> Iterable[Dict[str, object]]:
    """Yield validated record dicts from each JSON file, skipping invalid ones."""
    # Recurse so it works with both flat and venue/year/type subfolder layouts.
    files = sorted(p for p in input_dir.rglob("*.json") if not p.name.startswith("_"))
    for fp in files:
        try:
            raw = json.loads(fp.read_text(encoding="utf-8"))
            rec = PaperRecord(**raw)
        except (json.JSONDecodeError, ValidationError) as exc:
            log(f"[load] SKIP invalid {fp.name}: {exc}")
            continue
        yield rec.model_dump()


# Columns updated on conflict (everything except the DOI primary key).
_UPDATE_COLS = [
    "title", "venue", "year", "ptype", "abstract", "abstract_source",
    "abstract_mismatch", "methods", "methods_context", "methods_heading_found",
    "source_pdf_path", "grobid_ok", "extra",
]


def upsert_batch(engine, rows: List[Dict[str, object]]) -> None:
    """UPSERT a batch of records into `papers` on the DOI key."""
    if not rows:
        return
    stmt = pg_insert(Paper).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["doi"],
        set_={col: getattr(stmt.excluded, col) for col in _UPDATE_COLS},
    )
    with session_scope(engine) as session:
        session.execute(stmt)


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    p = argparse.ArgumentParser(description="Load extracted JSON into Postgres.")
    p.add_argument("--input-dir", default="data/extracted", help="Dir of *.json records.")
    p.add_argument("--batch", type=int, default=500, help="Rows per UPSERT batch.")
    p.add_argument("--no-init", action="store_true", help="Skip create-tables step.")
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    """Validate and bulk-upsert all JSON records into the database."""
    args = parse_args(argv)
    engine = get_engine()
    if not args.no_init:
        init_db(engine)

    batch: List[Dict[str, object]] = []
    loaded = 0
    for rec in iter_records(Path(args.input_dir)):
        batch.append(rec)
        if len(batch) >= args.batch:
            upsert_batch(engine, batch)
            loaded += len(batch)
            log(f"[load] upserted {loaded}")
            batch = []
    if batch:
        upsert_batch(engine, batch)
        loaded += len(batch)

    log(f"[load] DONE — {loaded} records upserted into papers.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
