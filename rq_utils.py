"""Shared helpers for the RQ folders: reading pipeline outputs and annotation exports, intervals,
weighted scores, agreement statistics. No numpy needed.
"""
import collections
import glob
import itertools
import json
import math
import os
import pathlib
import random

import config

ANN = config.ANNOTATIONS
RESULTS = config.OUTPUT / "results"
V1_YES = config.V1_DIR / "output" / "detection" / "q1b_yes_set.json" if config.V1_DIR else None


# ------------------------------------------------------------------ files
def jsonl(p) -> list[dict]:
    p = pathlib.Path(p)
    return [json.loads(l) for l in p.open(encoding="utf-8")] if p.exists() else []


def save(name: str, obj) -> pathlib.Path:
    RESULTS.mkdir(parents=True, exist_ok=True)
    p = RESULTS / name
    if name.endswith(".json"):
        p.write_text(json.dumps(obj, indent=1, ensure_ascii=False), encoding="utf-8")
    else:
        p.write_text(obj, encoding="utf-8")
    return p


def q1_v2() -> dict[str, str]:
    """pid -> 'Yes' / 'No' / 'pending' from output/q1_final.jsonl."""
    out = {}
    for r in jsonl(config.OUTPUT / "q1_final.jsonl"):
        out[r["pid"]] = {"yes": "Yes", "no": "No"}.get(r.get("q1"), r.get("source") or "pending")
    return out


def q1_v1() -> set[str] | None:
    """v1's Q1 Yes papers, or None when V1_DIR is not set (the comparison is then skipped)."""
    return set(json.loads(V1_YES.read_text(encoding="utf-8"))) if V1_YES and V1_YES.exists() else None


def inventory() -> dict[str, dict]:
    return {r["pid"]: r for r in jsonl(config.OUTPUT / "inventory.jsonl")}


# ------------------------------------------------------------------ annotation exports
def study_q1(s: dict) -> str | None:
    """Q1 of one study from either page version: v3 has the three checks, v1 a direct answer."""
    if any(k in s for k in ("c1", "c2", "c3")) and any(s.get(k) for k in ("c1", "c2", "c3")):
        if "No" in (s.get("c1"), s.get("c2"), s.get("c3")):
            return "No"
        if s.get("c1") == s.get("c2") == s.get("c3") == "Yes":
            return "Yes"
        return None
    v = s.get("q1")
    return v if v in ("Yes", "No") else ("Unsure" if v in ("Unsure", "", None) else None)


def paper_q1(paper: dict) -> str | None:
    qs = [study_q1(s) for s in paper.get("studies") or []]
    if "Yes" in qs:
        return "Yes"
    if qs and all(q == "No" for q in qs):
        return "No"
    return "Unsure" if any(q == "Unsure" for q in qs) else None


def read_exports(pattern: str) -> dict[str, dict[str, dict]]:
    """annotator -> pid -> paper, from export files matching a glob. The annotator is the name in the
    file name (round2_week1_<Name>_annotations.json, week1_<Name>.json, ..._<Name>_annotations_v2.json)."""
    out = collections.defaultdict(dict)
    for f in sorted(glob.glob(pattern)):
        stem = os.path.basename(f)[:-5]
        parts = [p for p in stem.split("_") if p not in ("annotations", "v2", "v3")]
        name = parts[-1]
        for p in json.load(open(f, encoding="utf-8")).get("papers", []):
            out[name][p["id"]] = p
    return out


# ------------------------------------------------------------------ statistics
def wilson(k: float, n: float, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return float("nan"), float("nan")
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (c - h) / d), min(1.0, (c + h) / d)


def prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else float("nan")
    r = tp / (tp + fn) if tp + fn else float("nan")
    f = 2 * p * r / (p + r) if p == p and r == r and p + r else float("nan")
    return p, r, f


def weighted_prf(items, pred: dict, truth: dict, weight: dict):
    """items: pids; weight[pid] = papers of the population the pid stands for. 'pending' predictions
    count as No (a Yes they miss is a miss)."""
    tp = fp = fn = tn = 0.0
    for p in items:
        x, t, w = pred.get(p) == "Yes", truth[p] == "Yes", weight[p]
        if x and t: tp += w
        elif x: fp += w
        elif t: fn += w
        else: tn += w
    return prf(tp, fp, fn), (tp, fp, fn, tn)


def stratified_boot(strata: dict, fn, k: int = 2000, seed: int = 7):
    """strata: name -> list of pids. fn(sample pids) -> tuple of numbers. 95% percentile intervals."""
    rng = random.Random(seed)
    draws = []
    for _ in range(k):
        s = [p for v in strata.values() for p in rng.choices(v, k=len(v))] if strata else []
        draws.append(fn(s))
    out = []
    for i in range(len(draws[0])):
        v = sorted(d[i] for d in draws if d[i] == d[i])
        out.append((v[int(.025 * len(v))], v[max(0, int(.975 * len(v)) - 1)]) if v else (float("nan"),) * 2)
    return out


def fleiss(rows: list[list[str]], cats: list[str]) -> float:
    n = len(rows[0])
    N = len(rows)
    P = [(sum(r.count(c) ** 2 for c in cats) - n) / (n * (n - 1)) for r in rows]
    pj = [sum(r.count(c) for r in rows) / (N * n) for c in cats]
    Pb, Pe = sum(P) / N, sum(x * x for x in pj)
    return (Pb - Pe) / (1 - Pe) if Pe < 1 else float("nan")


def cohen(a: list, b: list, cats: list) -> float:
    po = sum(x == y for x, y in zip(a, b)) / len(a)
    pe = sum((a.count(c) / len(a)) * (b.count(c) / len(b)) for c in cats)
    return (po - pe) / (1 - pe) if pe < 1 else float("nan")


def agreement(rows: list[list[str]], cats: list[str], k: int = 2000) -> dict:
    """Raw all-agree share, Fleiss' kappa with a bootstrap interval over items, mean pairwise Cohen."""
    rng = random.Random(7)
    boots = sorted(v for v in (fleiss([rows[rng.randrange(len(rows))] for _ in rows], cats) for _ in range(k)) if v == v)
    cols = list(zip(*rows))
    pair = [cohen(list(cols[i]), list(cols[j]), cats) for i, j in itertools.combinations(range(len(cols)), 2)]
    pair = [x for x in pair if x == x]
    return {"items": len(rows), "raters": len(rows[0]), "all_agree": sum(len(set(r)) == 1 for r in rows) / len(rows),
            "fleiss": fleiss(rows, cats), "fleiss_ci": (boots[int(.025 * len(boots))], boots[int(.975 * len(boots)) - 1])
            if boots else None, "pairwise_cohen": sum(pair) / len(pair) if pair else float("nan")}


def fmt(x, d=2):
    return "  nan" if x != x else f"{x:.{d}f}"


# ------------------------------------------------------------------ Q2 and Q3 (shared by RQ 2 and RQ 3)
def q23_rows() -> tuple[list[dict], list[dict]]:
    """(answered rows, rows with no answer yet) from output/q23_final.jsonl."""
    rows = jsonl(config.OUTPUT / "q23_final.jsonl")
    return [r for r in rows if "q2_any" in r], [r for r in rows if "q2_any" not in r]


def _norm_category(name: str, allowed: list[str]) -> str | None:
    n = name.strip().lower()
    for a in allowed:
        if n == a.lower():
            return a
    if n.startswith("other"):
        return "other"
    if n == "qualtrics panel":
        return "Qualtrics"
    return None


def human_q23(paths, allowed_q2: list[str], allowed_q3: list[str]) -> dict[str, dict]:
    """Human Q2 and Q3 labels per paper from annotation exports (files or folders).
    A paper's label is the union over the studies the annotator marked Q1 Yes; a paper read by several
    annotators keeps each category that at least half of them ticked.
    -> pid -> {"n": annotators, "q2_any": bool, "q2": set, "q3": set}"""
    acc = collections.defaultdict(lambda: {"n": 0, "q2_any": 0, "q2": collections.Counter(), "q3": collections.Counter()})
    files = []
    for p in map(pathlib.Path, paths):
        files += sorted(p.glob("*.json")) if p.is_dir() else ([p] if p.exists() else [])
    for f in files:
        for paper in json.loads(f.read_text(encoding="utf-8")).get("papers", []):
            yes = [s for s in paper.get("studies") or [] if study_q1(s) == "Yes"]
            if not yes:
                continue
            q2, q3 = set(), set()
            for s in yes:
                if not s.get("q2_none"):
                    q2 |= {c for c in (_norm_category(k, allowed_q2) for k in (s.get("q2_checks") or {})) if c}
                q3 |= {c for c in (_norm_category(k, allowed_q3) for k in (s.get("q3_sources") or {})) if c}
            q3.discard("Not reported")
            o = acc[paper["id"]]
            o["n"] += 1
            o["q2_any"] += bool(q2)
            o["q2"].update(q2)
            o["q3"].update(q3)
    return {pid: {"n": o["n"], "q2_any": o["q2_any"] * 2 >= o["n"],
                  "q2": {c for c, v in o["q2"].items() if v * 2 >= o["n"]},
                  "q3": {c for c, v in o["q3"].items() if v * 2 >= o["n"]}} for pid, o in acc.items()}


def category_scores(pairs: list[tuple[set, set]], cats: list[str], label: str) -> dict:
    """Per-category and micro precision, recall and F1 of (human set, pipeline set) pairs; prints a table."""
    print(f"\n{label:<44}{'n human':>8}{'n pipe':>8}{'prec':>7}{'rec':>7}{'F1':>7}")
    out, T, F, N = {}, 0, 0, 0
    for c in cats:
        tp = sum(c in h and c in m for h, m in pairs)
        fp = sum(c not in h and c in m for h, m in pairs)
        fn = sum(c in h and c not in m for h, m in pairs)
        T, F, N = T + tp, F + fp, N + fn
        if tp + fp + fn:
            p, r, f = prf(tp, fp, fn)
            out[c] = {"human": tp + fn, "pipeline": tp + fp, "precision": p, "recall": r, "f1": f}
            print(f"  {c:<42}{tp + fn:>8}{tp + fp:>8}{fmt(p):>7}{fmt(r):>7}{fmt(f):>7}")
    p, r, f = prf(T, F, N)
    out["micro"] = {"human": T + N, "pipeline": T + F, "precision": p, "recall": r, "f1": f}
    print(f"  {'micro average':<42}{T + N:>8}{T + F:>8}{fmt(p):>7}{fmt(r):>7}{fmt(f):>7}")
    return out


def annotation_paths(args: list[str]) -> list[pathlib.Path]:
    """Annotation exports to score: the command-line paths, else round 1 and the round-2 returns."""
    if args:
        return [pathlib.Path(a) for a in args]
    # the re-rate files repeat round-1 papers by the same annotators, so they are not added here
    return [ANN / "round1"] + sorted((ANN / "round2" / "returns").glob("round2_week*_*.json"))
