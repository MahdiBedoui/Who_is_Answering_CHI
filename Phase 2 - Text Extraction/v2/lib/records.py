"""Per-paper, per-section JSON records. One file per paper; stages update it in place.

Layout: <data store>/data/sections/<section>/<venue>/<year>/<key>.json

Record shape:
{
  "doi": ..., "key": ..., "venue": ..., "year": ..., "ptype": ...,
  "candidates": {
     "<source>": {"text": stored_form, "raw_len": int, "ok": bool,
                   "status": "ok"|"not_found"|"empty"|"error:<msg>",
                   "repairs": [...], "fetched_at": iso8601}
  },
  "resolution": {"status": "resolved"|"needs_adjudication"|"llm_adjudicated"|"manual_queue",
                  "text": ..., "source": ..., "confidence": "high"|"medium"|"low",
                  "scores": {"a|b": float, ...}, "flags": [...],
                  "parser_version": ..., "resolved_at": iso8601}
}
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterator, Optional

from .corpus import CorpusPaper


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def record_path(section_dir: Path, paper: CorpusPaper) -> Path:
    return section_dir / paper.venue / str(paper.year) / f"{paper.key}.json"


def load_record(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None  # corrupt/partial file: treat as absent, stage will rebuild


def new_record(paper: CorpusPaper) -> dict:
    return {"doi": paper.doi, "key": paper.key, "venue": paper.venue,
            "year": paper.year, "ptype": paper.ptype,
            "candidates": {}, "resolution": None}


def load_or_new(section_dir: Path, paper: CorpusPaper) -> dict:
    return load_record(record_path(section_dir, paper)) or new_record(paper)


def save_record(section_dir: Path, paper_or_rec, rec: dict | None = None) -> Path:
    """Atomic write (tmp + rename) so an interrupted run never corrupts a record."""
    if rec is None:
        rec, paper = paper_or_rec, None
        path = section_dir / rec["venue"] / str(rec["year"]) / f"{rec['key']}.json"
    else:
        path = record_path(section_dir, paper_or_rec)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(rec, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return path


def set_candidate(rec: dict, source: str, text: str, status: str,
                  repairs: list | None = None, raw_len: int = 0) -> None:
    rec["candidates"][source] = {
        "text": text, "raw_len": raw_len, "ok": status == "ok", "status": status,
        "repairs": repairs or [], "fetched_at": now_iso(),
    }


def has_ok_candidate(rec: dict, source: str) -> bool:
    c = rec.get("candidates", {}).get(source)
    return bool(c and c.get("ok"))


def candidate_attempted(rec: dict, source: str) -> bool:
    """True if a previous run reached a definitive answer (ok / not_found / empty).
    Transient errors are NOT definitive, so they are retried on the next run."""
    c = rec.get("candidates", {}).get(source)
    return bool(c and (c.get("ok") or c.get("status") in ("not_found", "empty")))


def iter_records(section_dir: Path, venue: str, years) -> Iterator[dict]:
    for year in sorted(years):
        ydir = section_dir / venue / str(year)
        if not ydir.is_dir():
            continue
        for f in sorted(ydir.glob("*.json")):
            rec = load_record(f)
            if rec:
                yield rec
