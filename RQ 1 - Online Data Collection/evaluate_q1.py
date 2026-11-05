"""Q1 validation: how well v1 and the v2 pipeline (rules + judge) answer Q1 under the v2 codebook.

Four parts, each run when its data is there:
  A  round 1 (400 papers) under v2: truth from the blind 70-paper re-label (disputed papers all re-labelled,
     agreed papers sampled), estimated over all 400 by stratum weights, 95% stratified bootstrap
  B  round 2 (160 new papers): truth from the students' v2 pages; shared papers take the majority, ties are
     left out and listed. Each paper stands for its sampling stratum (year x v1 stratum, round2_pools.json),
     so precision and recall estimate the whole corpus outside round 1
  C  agreement among annotators on round 2's shared papers (Fleiss' kappa, v2 question)
  D  round 1's 25 shared papers before and after the Unsure re-rate (re-rate follows the workshop, so
     report it as agreement after training)
Writes output/results/q1_validation.json.

Run from the repo root:  py "RQ 1 - Online Data Collection/evaluate_q1.py"
"""
import collections
import glob
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import config  # noqa: E402
from rq_utils import (ANN, agreement, fmt, inventory, paper_q1, q1_v1, q1_v2, read_exports, save,  # noqa: E402
                      stratified_boot, weighted_prf)

RELABEL = ANN / "relabel_v2"
ROUND2 = ANN / "round2"
RETURNS = pathlib.Path(os.environ.get("ROUND2_RETURNS") or ROUND2 / "returns")   # where the students' exported files go


def pipelines(pids):
    v1, v2 = q1_v1(), q1_v2()
    out = {"v2": {p: v2.get(p, "pending") for p in pids}}
    if v1 is not None:                      # only when V1_DIR is set
        out["v1"] = {p: "Yes" if p in v1 else "No" for p in pids}
    return out


def report(title, strata, truth, weight):
    pids = [p for v in strata.values() for p in v]
    preds = pipelines(pids)
    print(f"\n{title}: {len(pids)} papers, standing for {sum(weight[p] for p in pids):,.0f}")
    pend = sum(preds["v2"][p] not in ("Yes", "No") for p in pids)
    if pend:
        print(f"  v2 has no answer yet for {pend} of them (counted as No)")
    print(f"  {'pipeline':<6}{'precision':>22}{'recall':>22}{'F1':>22}")
    out = {}
    for name, pred in preds.items():
        (p, r, f), counts = weighted_prf(pids, pred, truth, weight)
        ci = stratified_boot(strata, lambda s: weighted_prf(s, pred, truth, weight)[0])
        print(f"  {name:<6}" + "".join(f"{fmt(v):>10} [{fmt(c[0])}-{fmt(c[1])}]" for v, c in zip((p, r, f), ci)))
        out[name] = {"precision": p, "recall": r, "f1": f, "ci": ci, "weighted_counts": counts,
                     "sample_counts": weighted_prf(pids, pred, truth, {q: 1 for q in pids})[1]}
    return out


def part_a():
    key_f = RELABEL / "_key_do_not_open.json"
    files = sorted(RELABEL.glob("relabel_v2_*annotations*.json"), key=lambda f: f.stat().st_mtime)
    if not key_f.exists() or not files:
        print("A  round 1 under v2: no re-label export yet")
        return None
    key = json.loads(key_f.read_text(encoding="utf-8"))
    papers = json.loads(files[-1].read_text(encoding="utf-8"))["papers"]
    truth = {p["id"]: paper_q1(p) for p in papers}
    truth = {p: t for p, t in truth.items() if t in ("Yes", "No") and p in key["stratum"]}
    strata = collections.defaultdict(list)
    for p in truth:
        strata[key["stratum"][p]].append(p)
    pop = key["population"]
    weight = {p: (1 if s == "disputed" else pop[s] / len(strata[s])) for s, v in strata.items() for p in v}
    print(f"A  re-label file: {files[-1].name}")
    return report("A  round 1 under v2", strata, truth, weight)


def round2_truth():
    ann = read_exports(str(RETURNS / "round2_week*_*.json"))
    votes = collections.defaultdict(dict)
    for name, papers in ann.items():
        for pid, p in papers.items():
            q = paper_q1(p)
            if q in ("Yes", "No"):
                votes[pid][name] = q
    truth, ties = {}, []
    for pid, v in votes.items():
        c = collections.Counter(v.values())
        if c["Yes"] == c["No"]:
            ties.append(pid)
        else:
            truth[pid] = "Yes" if c["Yes"] > c["No"] else "No"
    return truth, ties, votes


def part_b():
    plan_f, pools_f = ROUND2 / "batch_plan_round2.json", ROUND2 / "round2_pools.json"
    truth, ties, _ = round2_truth()
    if not truth:
        print(f"\nB  round 2: no exported files in {RETURNS} yet")
        return None
    plan = json.loads(plan_f.read_text(encoding="utf-8"))["papers"]
    pools = json.loads(pools_f.read_text(encoding="utf-8"))["pools"]
    strata = collections.defaultdict(list)
    for p in truth:
        if p in plan:
            strata[(plan[p]["year"], plan[p]["stratum"])].append(p)
    weight = {p: pools[y][s] / len(v) for (y, s), v in strata.items() for p in v}
    if ties:
        print(f"\nB  round 2: {len(ties)} shared papers tied, left out until adjudicated: {ties}")
    out = report("B  round 2 (weighted to the corpus outside round 1)", strata, {p: truth[p] for p in weight}, weight)
    missing = sorted(set(plan) - set(truth) - set(ties))
    if missing:
        print(f"  not yet annotated: {len(missing)} of {len(plan)}")
    return out


def part_c():
    _, _, votes = round2_truth()
    plan_f = ROUND2 / "batch_plan_round2.json"
    if not votes or not plan_f.exists():
        print("\nC  round-2 agreement: no shared papers annotated yet")
        return None
    shared = [s["pid"] for s in json.loads(plan_f.read_text(encoding="utf-8"))["shared"]]
    rows = [list(votes[p].values()) for p in shared if p in votes and len(votes[p]) >= 2]
    if not rows:
        print("\nC  round-2 agreement: no shared papers annotated yet")
        return None
    n = min(len(r) for r in rows)
    rows = [r[:n] for r in rows]
    a = agreement(rows, ["Yes", "No"])
    print(f"\nC  round-2 agreement on {a['items']} shared papers, {a['raters']} annotators: all agree "
          f"{a['all_agree']:.0%}, Fleiss k {fmt(a['fleiss'])} [{fmt(a['fleiss_ci'][0])}-{fmt(a['fleiss_ci'][1])}], "
          f"pairwise Cohen {fmt(a['pairwise_cohen'])}")
    return a


def part_d():
    r1 = read_exports(str(ANN / "round1" / "week*_*.json"))
    rr = read_exports(str(RETURNS / "round2_rerate_*.json"))
    if not r1:
        print(f"\nD  round 1: no annotation files in {ANN / 'round1'}")
        return None
    shared = sorted(p for p in set.intersection(*[set(v) for v in r1.values()]))
    names = sorted(r1)
    before = [[("No" if paper_q1(r1[n][p]) != "Yes" else "Yes") for n in names] for p in shared]
    a_before = agreement(before, ["Yes", "No"])
    print(f"\nD  round 1, {len(shared)} shared papers, Unsure as No: Fleiss k {fmt(a_before['fleiss'])}, "
          f"all agree {a_before['all_agree']:.0%}")
    if not rr:
        print(f"   re-rate files not in {RETURNS} yet")
        return {"before": a_before}
    after, changed = [], 0
    for p in shared:
        row = []
        for n in names:
            q = paper_q1(r1[n][p])
            if q not in ("Yes", "No") and p in rr.get(n, {}):
                q = paper_q1(rr[n][p]) or q
                changed += 1
            row.append("Yes" if q == "Yes" else "No")
        after.append(row)
    a_after = agreement(after, ["Yes", "No"])
    print(f"   after the re-rate ({changed} answers replaced): Fleiss k {fmt(a_after['fleiss'])}, "
          f"all agree {a_after['all_agree']:.0%}  (after training: report as such)")
    return {"before": a_before, "after": a_after, "replaced": changed}


def main():
    if not ANN.exists():
        raise SystemExit(f"The human annotations are not in {ANN}. They are released separately from the code; "
                         "set ANNOTATIONS in .env to their folder.")
    res = {"A_round1_v2": part_a(), "B_round2": part_b(), "C_round2_agreement": part_c(), "D_round1_rerate": part_d()}
    print(f"\n-> {save('q1_validation.json', res)}")


if __name__ == "__main__":
    main()
