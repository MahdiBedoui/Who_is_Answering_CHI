"""Q3 validation: the pipeline's participant sources against human annotations.

Only papers that both the pipeline and the humans call Q1 Yes are scored: Q3 is asked only there.
Reports per source precision, recall and F1, the micro average, and the papers with the largest
disagreements. Writes output/results/q3_validation.json.

By default round 1 and the round-2 returns are read; pass files or folders to score something else.

Run from the repo root:  py "RQ 3 - Participant Sources/evaluate_q3.py" [annotation files or folders ...]
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "Phase 2 - NLP and Regex Detectors"))
from q23_evidence import Q2_CHECKS, Q3_SOURCES  # noqa: E402
from rq_utils import ANN, annotation_paths, category_scores, human_q23, q23_rows, save  # noqa: E402


def main():
    if not ANN.exists():
        raise SystemExit(f"The human annotations are not in {ANN}. They are released separately from the code; "
                         "set ANNOTATIONS in .env to their folder.")
    rows, _ = q23_rows()
    pipe = {r["pid"]: r for r in rows}
    human = human_q23(annotation_paths(sys.argv[1:]), Q2_CHECKS, Q3_SOURCES)
    both = sorted(set(pipe) & set(human))
    print(f"papers with a human Q1 Yes: {len(human)}; with a pipeline Q3 answer: {len(both)}")
    if not both:
        return
    pairs = [(human[p]["q3"], set(pipe[p]["q3_sources"]) - {"Not reported"}) for p in both]
    per = category_scores(pairs, [s for s in Q3_SOURCES if s != "Not reported"], "per source")

    print("\nlargest disagreements (missing in pipeline / extra in pipeline):")
    for pid, (h, m) in sorted(zip(both, pairs), key=lambda x: -len(x[1][0] ^ x[1][1]))[:12]:
        if h ^ m:
            print(f"  {pid}  -{sorted(h - m)} +{sorted(m - h)}")
    out = save("q3_validation.json", {"papers": len(both), "per_source": per})
    print(f"\n-> {out}")


if __name__ == "__main__":
    main()
