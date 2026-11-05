"""Q2 validation: the pipeline's data-quality checks against human annotations.

Only papers that both the pipeline and the humans call Q1 Yes are scored: Q2 is asked only there.
Reports
  any check reported (yes / no): agreement, precision, recall, F1, Cohen's kappa
  per check: precision, recall, F1, and the micro average
  the papers with the largest disagreements, to read
Writes output/results/q2_validation.json.

Round 1 asked an older Q1 and its Q2 boxes were often left unticked where the paper reports checks, so its
numbers understate precision; round 2 is the test. By default both are read (round 1, then the round-2
returns); pass files or folders to score something else.

Run from the repo root:  py "RQ 2 - Data Quality Checks/evaluate_q2.py" [annotation files or folders ...]
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "Phase 2 - NLP and Regex Detectors"))
from q23_evidence import Q2_CHECKS, Q3_SOURCES  # noqa: E402
from rq_utils import ANN, annotation_paths, category_scores, cohen, fmt, human_q23, prf, q23_rows, save  # noqa: E402


def main():
    if not ANN.exists():
        raise SystemExit(f"The human annotations are not in {ANN}. They are released separately from the code; "
                         "set ANNOTATIONS in .env to their folder.")
    rows, _ = q23_rows()
    pipe = {r["pid"]: r for r in rows}
    human = human_q23(annotation_paths(sys.argv[1:]), Q2_CHECKS, Q3_SOURCES)
    both = sorted(set(pipe) & set(human))
    print(f"papers with a human Q1 Yes: {len(human)}; with a pipeline Q2 answer: {len(both)}")
    if not both:
        return
    pairs = [(human[p], pipe[p]) for p in both]
    h = ["Yes" if x["q2_any"] else "No" for x, _ in pairs]
    m = ["Yes" if y["q2_any"] else "No" for _, y in pairs]
    tp = sum(a == b == "Yes" for a, b in zip(h, m))
    fp = sum(a == "No" and b == "Yes" for a, b in zip(h, m))
    fn = sum(a == "Yes" and b == "No" for a, b in zip(h, m))
    p, r, f = prf(tp, fp, fn)
    k = cohen(h, m, ["Yes", "No"])
    agree = sum(a == b for a, b in zip(h, m)) / len(h)
    print(f"\nany check reported: humans {h.count('Yes')}/{len(h)}, pipeline {m.count('Yes')}/{len(m)}")
    print(f"  agreement {agree:.2f}  precision {fmt(p)}  recall {fmt(r)}  F1 {fmt(f)}  Cohen kappa {fmt(k)}")
    per = category_scores([(x["q2"], set(y["q2_checks"])) for x, y in pairs], Q2_CHECKS, "per check")

    print("\nlargest disagreements (missing in pipeline / extra in pipeline):")
    for x, y in sorted(pairs, key=lambda xy: -len(xy[0]["q2"] ^ set(xy[1]["q2_checks"])))[:12]:
        miss, extra = sorted(x["q2"] - set(y["q2_checks"])), sorted(set(y["q2_checks"]) - x["q2"])
        if miss or extra:
            print(f"  {y['pid']}  -{miss} +{extra}")
    out = save("q2_validation.json", {"papers": len(both), "any": {"agreement": agree, "precision": p, "recall": r,
                                                                    "f1": f, "kappa": k}, "per_check": per})
    print(f"\n-> {out}")


if __name__ == "__main__":
    main()
