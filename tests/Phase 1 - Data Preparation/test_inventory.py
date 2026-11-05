"""Unit tests for module 0. These run without the corpus.

    py -m pytest tests -q
"""
import hashlib

import pytest

import inventory


def test_pid_to_doi():
    assert inventory.pid_to_doi("10_1145_3491102_3501822") == "10.1145/3491102.3501822"
    assert inventory.pid_to_doi("10_1145_3772318_3790263") == "10.1145/3772318.3790263"


def test_pid_to_doi_rejects_non_acm():
    with pytest.raises(ValueError):
        inventory.pid_to_doi("not_a_pid")
    with pytest.raises(ValueError):
        inventory.pid_to_doi("10_1145_3491102")


def test_sha256_matches_hashlib(tmp_path):
    p = tmp_path / "x.bin"
    data = b"who is answering chi\n" * 5000
    p.write_bytes(data)
    assert inventory.sha256_of(p) == hashlib.sha256(data).hexdigest()


def test_probe_flags_a_non_pdf(tmp_path):
    p = tmp_path / "broken.pdf"
    p.write_bytes(b"this is not a pdf")
    pages, readable, error = inventory.probe(p)
    assert pages is None
    assert readable is False
    assert error


def test_summary_counts_and_duplicates():
    rows = [
        {"pid": "a", "year": "2022", "readable": True, "sha256": "h1"},
        {"pid": "b", "year": "2022", "readable": False, "sha256": "h2"},
        {"pid": "c", "year": "2023", "readable": True, "sha256": "h1"},
    ]
    s = inventory.summarize(rows)
    assert s["total_on_disk"] == 3
    assert s["total_readable"] == 2
    assert s["per_year"]["2022"]["on_disk"] == 2
    assert s["per_year"]["2022"]["unreadable"] == ["b"]
    assert s["duplicate_files"] == {"h1": ["a", "c"]}
