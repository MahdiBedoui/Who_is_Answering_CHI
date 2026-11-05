"""Module 6: Q1 evidence.

Contract
  in:  output/sentences/<year>/<pid>.json   (module 5)
  out: output/q1_evidence/<year>/<pid>.json
         pid, year
         units    one per study the paper reports, each with
                    unit     "Study 2", "main" (study sections with no number),
                             or "context" (abstract, unclear, limits, appendix)
                    hits     every cue found: sentence index, cue, check,
                             polarity (+ or -), the matched words
                    checks   c1, c2, c3: yes, no or unknown, from the hits
                    route    yes, no or judge, and why
         route    the paper's: yes if any study unit is yes, no if every unit
                  is no, judge otherwise
         reason   one line
       output/q1_evidence_summary.json   routes per year

What it establishes
  - for every paper, the sentences that bear on each of Q1's three checks
    (CODEBOOK.md): data collected for the results, online,
    unmoderated. These are the evidence the judge (Phase 3) is shown.
  - a route. Papers whose evidence points one way with nothing against it
    are settled here; everything else goes to the judge. The rules are
    written to send a doubtful paper to the judge rather than settle it.

What it does not do
  - It does not read sections labelled prior work, framing or other
    (module 4), unless --framing adds the introduction and conclusion.
  - It does not decide a paper from a cue outside a study section. A
    platform named in the abstract or an appendix can send a paper to the
    judge but cannot settle it as yes.
  - It does not handle negation ("we did not use MTurk"). Rare enough that
    the judge sees those.

Safe to rerun. Needs no PDFs. Run from the repo root:
    py "Phase 2 - NLP and Regex Detectors/q1_evidence.py" [--year 2023] [--framing]
"""
import argparse
import collections
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))   # the repo root, where config.py is
import config  # noqa: E402

SENTENCES_DIR = config.OUTPUT / "sentences"
EVIDENCE_DIR = config.OUTPUT / "q1_evidence"

STUDY_LABELS = ("study", "unclear")                        # can settle a paper
CONTEXT_LABELS = ("abstract", "limits", "appendix")        # can only send it to the judge
FRAMING_LABELS = ("framing",)                              # read with --framing, as context


def rx(pattern: str, flags=re.I) -> re.Pattern:
    return re.compile(pattern, flags)


# (cue name, check, polarity, pattern). Polarity + supports Yes on the check,
# - supports No. Platform names that are also English words are matched in the
# spelling and context the platform uses.
CUES = [
    # check 2 online, and for crowd platforms also check 3 unmoderated
    ("crowd_platform", "c2", "+", rx(
        r"\b(?:Amazon )?Mechanical Turk\b|\bM-?Turk\b|\bCloudResearch\b|\bTurkPrime\b|\bCrowdFlower\b|"
        r"\bFigure Eight\b|\bToloka\b|\bClickworker\b|\bLucid (?:Marketplace|Theorem)\b")),
    ("crowd_platform", "c2", "+", rx(r"\bAMT\b|\bProlific(?:\.co|\.com| Academic)?\b(?! (?:author|writer|use|amount))",
                                     0)),
    ("survey_tool", "c2", "+", rx(
        r"\bQualtrics\b|\bSurvey ?Monkey\b|\bGoogle Forms?\b|\bMicrosoft Forms?\b|\bLimeSurvey\b|\bTypeform\b|"
        r"\bSoSci ?Survey\b|\bREDCap\b|\bjsPsych\b|\bPavlovia\b|\bGorilla(?: Experiment Builder|\.sc)\b|\boTree\b")),
    ("online_phrase", "c2", "+", rx(
        r"\bonline (?:survey|questionnaire|experiment|study|studies|form|task|panel|platform|data collection)s?\b|"
        r"\bweb-?based (?:survey|questionnaire|experiment|study|form|task)s?\b|\binternet survey\b|"
        r"\bcrowd-?sourc\w*|\bcrowd ?workers?\b|\bsurvey link\b|\bquestionnaire link\b|"
        r"\b(?:distributed|administered|conducted|deployed|hosted) (?:online|via the web)\b")),
    ("remote_data", "c2", "+", rx(
        r"\bexperience[- ]sampling\b|\becological momentary assessment\b|"
        r"\bdiary (?:app|application|entries)\b|\b(?:app|usage|interaction|system|activity) logs?\b|\blog data\b|"
        r"\btelemetry\b|\bin[- ]the[- ]wild (?:deployment|study)\b")),
    ("remote_data", "c2", "+", rx(r"\bESM\b|\bEMA\b", 0)),
    ("offline", "c2", "-", rx(
        r"\bin[- ]person\b|\bface[- ]to[- ]face\b|\bin (?:the|our|a) (?:lab|laboratory)\b|\blab(?:oratory)? (?:study|session|experiment)s?\b|"
        r"\bpaper(?:-based)? (?:survey|questionnaire|form)s?\b|\bprinted (?:survey|questionnaire|form)s?\b|\bon-?site\b")),
    # check 3 unmoderated
    ("moderated", "c3", "-", rx(
        r"\bZoom\b|\bMicrosoft Teams\b|\bGoogle Meet\b|\bSkype\b|\bWebex\b|\bvideo[- ]?(?:call|conferenc\w*)s?\b|"
        r"\b(?:semi-?structured |structured |in-depth |follow-up )?interviews?\b|\bfocus groups?\b|\bworkshops?\b|"
        r"\bthink[- ]aloud\b|\bco-?design sessions?\b|\bmoderated\b|\bexperimenters?\b|"
        r"\bresearchers? (?:was|were) present\b")),
    ("unmoderated", "c3", "+", rx(
        r"\bunmoderated\b|\bunsupervised\b|\bwithout (?:a |the |any )?(?:researcher|experimenter|supervision)\b|"
        r"\bself-administered\b|\bat their own pace\b|\basynchronous(?:ly)?\b|\bon their own (?:time|devices?|schedule)\b")),
    # check 1 data collected for the results
    ("collected", "c1", "+", rx(
        r"\b(?:conducted|ran|administered|distributed|deployed|launched|designed) (?:an? |the |two |three )?(?:online )?"
        r"(?:survey|questionnaire)s?\b|\b\d[\d,]* (?:participants|respondents|workers|users|people) "
        r"(?:completed|took part|responded|participated|filled|answered)\b|\brespondents\b|"
        r"\b(?:survey|questionnaire) (?:responses|data|results|answers)\b|\bresponses (?:from|of) \d")),
    ("screener", "c1", "-", rx(
        r"\bscreening (?:survey|questionnaire|form)s?\b|\bscreeners?\b|\bpre-?screen\w*|"
        r"\b(?:only )?used (?:only )?to (?:recruit|select|identify|screen)\b|\beligibility (?:survey|questionnaire|form)s?\b")),
]

# cues that say the mode of a survey is unknown: a survey with no online or
# offline marker goes to the judge instead of being settled as no
SURVEY_WORDS = rx(r"\bsurvey(?:ed|s)?\b|\bquestionnaires?\b|\brespondents\b")


def find_hits(text: str) -> list[dict]:
    hits = []
    for name, check, pol, pat in CUES:
        for m in pat.finditer(text):
            if name == "moderated" and text[max(0, m.start() - 2):m.start()].lower() == "un":
                continue
            hits.append({"cue": name, "check": check, "polarity": pol, "match": m.group(0)})
    return hits


def units_of(paper: dict, framing: bool = False) -> dict[str, list[int]]:
    """Sentence indices per unit. Study sections group by their study number;
    the rest of what is read is 'context'."""
    read_context = CONTEXT_LABELS + (FRAMING_LABELS if framing else ())
    units: dict[str, list[int]] = collections.defaultdict(list)
    for i, s in enumerate(paper["sentences"]):
        sec = paper["sections"][s["section"]]
        if sec["label"] in STUDY_LABELS:
            units[sec.get("study") or "main"].append(i)
        elif sec["label"] in read_context:
            units["context"].append(i)
    return units


def judge_checks(hits: list[dict]) -> dict[str, str]:
    by = collections.Counter((h["check"], h["polarity"]) for h in hits)
    crowd = any(h["cue"] == "crowd_platform" for h in hits)

    def decide(check):
        pos, neg = by[(check, "+")], by[(check, "-")]
        if pos and not neg:
            return "yes"
        if neg and not pos:
            return "no"
        return "mixed" if pos and neg else "unknown"

    c = {k: decide(k) for k in ("c1", "c2", "c3")}
    if crowd and c["c3"] == "unknown":
        c["c3"] = "yes"          # a crowd platform task is done by the worker alone
    if crowd and c["c1"] == "unknown":
        c["c1"] = "yes"          # workers were paid to produce data
    return c


def route_unit(unit: str, hits: list[dict], texts: list[str]) -> tuple[str, str]:
    c = judge_checks(hits)
    online = c["c2"] in ("yes", "mixed")
    if not online:
        if c["c2"] == "no":
            return "no", "only offline cues"
        if any(SURVEY_WORDS.search(t) for t in texts):
            if c["c3"] in ("no", "mixed"):
                # codebook: a questionnaire filled in during a moderated session fails check 3
                return "no", "questionnaire inside a moderated session"
            return "judge", "a survey with no online or offline marker"
        return "no", "no online cue"
    if unit == "context":
        return "judge", "online cue outside the study sections"
    if c["c1"] in ("no", "mixed"):
        return "judge", "screener language"
    if c["c3"] in ("no", "mixed"):
        return "judge", "online cue but also a moderated session"
    if c["c2"] == "mixed":
        return "judge", "both online and offline cues"
    if c["c1"] == "yes" and c["c3"] == "yes":
        return "yes", "online, unmoderated, collected"
    if c["c1"] == "yes":
        return "yes" if any(h["cue"] == "survey_tool" for h in hits) else "judge", \
            "online collection, no moderation cue either way"
    return "judge", "online cue but no sign the data feeds the results"


def build(paper: dict, framing: bool = False) -> dict:
    units = []
    for unit, idx in units_of(paper, framing).items():
        texts = [paper["sentences"][i]["text"] for i in idx]
        hits = [{"s": i, **h} for i, t in zip(idx, texts) for h in find_hits(t)]
        route, why = route_unit(unit, hits, texts)
        units.append({"unit": unit, "sentences": len(idx), "hits": hits, "checks": judge_checks(hits),
                      "route": route, "why": why})
    study = [u for u in units if u["unit"] != "context"]
    if any(u["route"] == "yes" for u in study):
        route, reason = "yes", next(f'{u["unit"]}: {u["why"]}' for u in study if u["route"] == "yes")
    elif all(u["route"] == "no" for u in units):
        route, reason = "no", "no unit has an online cue" if units else "no sentences read"
    else:
        u = next(u for u in units if u["route"] == "judge")
        route, reason = "judge", f'{u["unit"]}: {u["why"]}'
    return {"pid": paper["pid"], "year": paper["year"], "framing": framing, "units": units,
            "route": route, "reason": reason}


def summarize(rows: list[dict]) -> dict:
    per_year = collections.defaultdict(lambda: {"papers": 0, "routes": collections.Counter(),
                                                 "reasons": collections.Counter(), "errors": []})
    for r in rows:
        y = per_year[r["year"]]
        y["papers"] += 1
        if "error" in r:
            y["errors"].append({"pid": r["pid"], "error": r["error"]})
            continue
        y["routes"][r["route"]] += 1
        y["reasons"][r["reason"].split(": ", 1)[-1]] += 1
    return {"per_year": {k: {**v, "routes": dict(v["routes"]), "reasons": dict(v["reasons"].most_common())}
                         for k, v in sorted(per_year.items())}}


def main() -> None:
    ap = argparse.ArgumentParser(description="Find the evidence for Q1's three checks and route each paper.")
    ap.add_argument("--year", choices=config.YEARS, help="one year only (default: all)")
    ap.add_argument("--framing", action="store_true", help="also read the introduction and conclusion, as context")
    args = ap.parse_args()

    rows = []
    for year in ((args.year,) if args.year else config.YEARS):
        out_dir = EVIDENCE_DIR / year
        out_dir.mkdir(parents=True, exist_ok=True)
        files = sorted((SENTENCES_DIR / year).glob("*.json"))
        if not files:
            raise SystemExit(f"no sentences for {year}: run Phase 1 first")
        for f in files:
            try:
                result = build(json.loads(f.read_text(encoding="utf-8")), args.framing)
                (out_dir / f.name).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
                rows.append({"pid": result["pid"], "year": year, "route": result["route"], "reason": result["reason"]})
            except Exception as e:  # noqa: BLE001 - a paper we cannot read is a finding
                rows.append({"pid": f.stem, "year": year, "error": type(e).__name__ + ": " + str(e)[:120]})
        print(f"  {year}: {len(files)}", flush=True)

    summary = summarize(rows)
    suffix = (f"_{args.year}" if args.year else "") + ("_framing" if args.framing else "")
    with open(config.OUTPUT / f"q1_evidence_summary{suffix}.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1)

    print(f"\n{'year':<6}{'papers':>8}{'yes':>7}{'no':>7}{'judge':>7}{'errors':>8}")
    for year, s in summary["per_year"].items():
        r = s["routes"]
        print(f"{year:<6}{s['papers']:>8}{r.get('yes', 0):>7}{r.get('no', 0):>7}{r.get('judge', 0):>7}"
              f"{len(s['errors']):>8}")
    print(f"\n-> {EVIDENCE_DIR}")
    sys.exit(1 if any(s["errors"] for s in summary["per_year"].values()) else 0)


if __name__ == "__main__":
    main()
