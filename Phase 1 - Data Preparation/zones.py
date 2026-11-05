"""Module 4: study sections.

Contract
  in:  output/sections/<year>/<pid>.json   (module 3)
  out: output/zones/<year>/<pid>.json
         pid, year
         zones   one per section of module 3, in the same order, each with
                   title, level, role, text_chars   copied from module 3
                   label   what the section is for (see LABELS)
                   rule    the rule that gave the label (see RULES)
                   read    whether the detection modules read it by default
                   study   "Study 2", "Experiment 1": the numbered study the
                           section belongs to, or null
       output/zones_summary.json   counts per year, the titles no rule
                                   knew, and every paper with no study section

What it establishes
  - which sections report the authors' own study, from the section titles
    alone. A recruitment platform named in "4.2 Participants" is evidence
    about this paper; the same name in "2 Related Work" is about someone
    else's.
  - a label for every section, so that a later module states which labels
    it reads instead of working on text that was cut away beforehand.
    Nothing is removed here.

What it does not do
  - It does not read the text of a section. Two sections with the same
    title get the same label.
  - It does not decide anything about a paper. A paper with no section
    labelled `study` is listed in the summary, not judged.

The rule when in doubt: read it. A section read by mistake costs a later
module some work. A section skipped by mistake is evidence nobody sees.

Safe to rerun. Needs no PDFs. Run from the repo root:
    py "Phase 1 - Data Preparation/zones.py" [--year 2023]
"""
import argparse
import collections
import json
import re
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))   # the repo root, where config.py is
import config  # noqa: E402
from sections import SECTIONS_DIR

ZONES_DIR = config.OUTPUT / "zones"

LABELS = (
    "study",        # the authors' own study: method, participants, procedure, analysis, results
    "limits",       # limitations and threats to validity
    "appendix",     # after the reference list: questionnaires, codebooks, extra tables
    "abstract",     # the authors' own summary, which often names the study and its data collection
    "unclear",      # no rule knows the title, or it is on the ambiguous list
    "framing",      # the authors' account of the paper around prior work: introduction, conclusion
    "prior_work",   # related work, background, literature: other people's studies
    "other",        # discussion, implications, system and design description
    "apparatus",    # title block, CCS concepts, keywords, acknowledgments, references
)
READ = ("study", "limits", "appendix", "abstract", "unclear")

# The rule that gave a section its label. For a section of the paper's body
# the first of these that applies wins, in this order.
RULES = (
    "role",          # not in the body: its role from module 3 decides
    "listed",        # the title is on one of the lists below
    "prior work",    # the title names related work, literature or references
    "subsection",    # a subsection is titled like part of a study ("Participants")
    "pattern",       # the title contains study, limitation or non-study vocabulary
    "system",        # the title describes the artefact, not a study
    "reviewed",      # one of 15 titles labelled by an LLM from paper outlines, then reviewed
    "parent",        # an unknown subsection takes the label of the section above it
    "none",          # nothing applied: unclear, and read
)
UNDER_STUDY = " under study"   # added to the rule when a section inside a study section is read with it


# ----------------------------------------------------------------- vocabulary
# Built from the section titles of all 5,524 papers. The lists hold titles
# after `normal`; the patterns are searched in them.

STUDY = frozenset("""results|findings|method|methods|methodology|participants|procedure|data analysis|analysis
|data collection|study design|user study|evaluation|apparatus|measures|materials|measurements|tasks|stimuli
|data collection and analysis|study procedure|formative study|experimental design|recruitment|hypotheses
|quantitative results|qualitative results|participant recruitment|participants and procedure|interview protocol
|technical evaluation|results and discussion|findings and discussion|experiment|codebook|ethical considerations
|ethics statement|manipulation check|study N|experiment N|phase N|pilot study|user evaluation|survey design
|quantitative analysis|qualitative analysis|participants and recruitment|analysis and results|study setup
|research questions|survey|interviews|focus groups|experimental setup|study overview|demographics
|informed consent|inter-rater reliability|user studies|evaluation study|main study|preliminary study|diary study
|field study|lab study|online experiment|deployment|field deployment|study context|research design
|study N design|study N results|study N method|study N methods|study N procedure|study N findings
|measures and analysis|data|dataset|datasets|procedure and tasks|task|design and procedure
|setting and participants|data analysis and results|analysis methods|survey study|interview study
|evaluation method|evaluation design|evaluation procedure|evaluation results|study method|study methods
|study materials""".replace("\n", "").split("|"))

NOT_STUDY = frozenset("""abstract|references|introduction|conclusion|conclusions|acknowledgments|acknowledgements
|discussion|related work|related works|background|background and related work|background & related work
|design implications|future work|summary|implementation|system design|design goals|applications
|discussion and future work|conclusion and future work|discussions|general discussion|motivation|contributions
|overview|implications|implications for design|design considerations|positionality|positionality statement
|related literature|literature review|prior work|theoretical background|conceptual framework|design space
|system architecture|architecture|system overview|scenario|design process|design rationale|use cases
|example applications|conclusion and limitations|introduction and background|discussion & future work
|concluding remarks|author contributions|open science|data availability
|selection and participation of children""".replace("\n", "").split("|"))

LIMITS = frozenset("""limitations|limitations and future work|limitation and future work
|limitations & future work|appendix|appendices|limitations and future directions|supplementary materials
|limitations & future directions""".replace("\n", "").split("|"))

AMBIGUOUS = frozenset("""design|case study|workshops|workshop|probes|technology probe|system evaluation
|evaluations""".replace("\n", "").split("|"))

# Titles the rules did not settle, labelled from paper outlines by an LLM
# (Claude, 2026-07-02) and reviewed by hand. Kept apart so they can be audited.
REVIEWED = {
    "discussion and conclusion": "other", "discussion & conclusion": "other",
    "general discussion and conclusion": "other", "technical approach": "other", "system": "other",
    "system requirements": "other", "system design and development": "other", "scenarios": "other",
    "application examples": "other", "application": "other", "threat model": "other",
    "lessons learned": "other", "research context": "study", "empirical setting": "study",
    "threats to validity": "limits",
}

# Whole words only. Without the word boundaries "reference" matches inside
# "Preference", and "User Preference Survey" is dropped as prior work.
PRIOR_WORK = re.compile(r"\brelated works?\b|\bliterature\b|\bprior work\b|\breferences?\b")
LIMITS_PATTERN = re.compile(r"\blimitation|\bappendix|supplement")
NOT_STUDY_PATTERN = re.compile(
    r"related work|literature|prior work|^background\b|introduction$|^conclusion|acknowledg|^reference"
    r"|future work$|implication|^discussions?$")
STUDY_PATTERN = re.compile(
    r"\b(stud(y|ies)|experiment|evaluat|pilot|deploy|survey|interview|participant|procedure|recruit|method"
    r"|finding|result|analys|apparatus|measure|materials|stimul|data collection|focus group|diary|hypothes"
    r"|manipulation checks?|questionnaire|sampl|codebook|coding|inter.rater|quantitative|qualitative|demographic"
    r"|compensat|consent|irb|preregist|pre.regist|attention check)")
SYSTEM_PATTERN = re.compile(
    r"implement|architecture|hardware|usage scenario|user scenario|application scenario|prototype"
    r"|algorithm|system description|interface design|design principles|design requirements|user interface")
STUDY_SUBSECTION = re.compile(
    r"participant|procedure|recruit|apparatus|measure|\bresults?\b|finding|method|data collection"
    r"|demographic|\btasks?\b|stimul|hypothes")

# What a section that is not a study is instead.
BACKGROUND = re.compile(r"related work|literature|prior work|\bbackground\b|\breferences?\b")
FRAMING = re.compile(r"^abstract$|\bintroduction\b|^conclu|^summary$|^contributions?$|^motivation$")
STUDY_NUMBER = re.compile(r"\b(study|experiment|phase|part)\s+(\d+|[ivx]+)\b", re.I)


def normal(title: str) -> str:
    """A title as the lists hold it: lower case, without its section number,
    and with every other number replaced by N ("Study 2 Results" and
    "Study 3 Results" are one title, "study N results")."""
    t = title.strip().lower()
    t = re.sub(r"^[\divxlc]+(\.\d+)*\.?\s+", "", t)      # "4.1 Methods"
    t = re.sub(r"^[a-z](\.\d+)*\s+(?=[a-z])", "", t)     # "A.2 Survey Items"
    t = re.sub(r"\d+", "N", t)
    return re.sub(r"\s+", " ", t).strip(" :.")


def not_study_label(name: str) -> str:
    if BACKGROUND.search(name):
        return "prior_work"
    return "framing" if FRAMING.search(name) else "other"


# --------------------------------------------------------------------- rules

def label_by_title(name: str, subsections: list[str]) -> tuple[str | None, str | None]:
    """(label, rule) for a body section from its own title and the titles of
    the subsections directly under it, or (None, None)."""
    if name in STUDY:
        return "study", "listed"
    if name in NOT_STUDY:
        return not_study_label(name), "listed"
    if name in LIMITS:
        return "limits", "listed"
    if name in AMBIGUOUS:
        return "unclear", "listed"
    if PRIOR_WORK.search(name):
        return "prior_work", "prior work"
    if any(STUDY_SUBSECTION.search(s) for s in subsections):
        return "study", "subsection"
    if LIMITS_PATTERN.search(name):                 # before the next rule: "Limitations and future work"
        return "limits", "pattern"
    if NOT_STUDY_PATTERN.search(name):
        return not_study_label(name), "pattern"
    if STUDY_PATTERN.search(name):
        return "study", "pattern"
    if SYSTEM_PATTERN.search(name):
        return "other", "system"
    if name in REVIEWED:
        return REVIEWED[name], "reviewed"
    return None, None


def label_sections(sections: list[dict]) -> list[dict]:
    """Label every section of one paper (module 3's list)."""
    names = [normal(s["title"]) for s in sections]
    children = collections.defaultdict(list)
    for i, s in enumerate(sections):
        if s["parent"] is not None and s["level"] == sections[s["parent"]]["level"] + 1:
            children[s["parent"]].append(names[i])

    zones, open_study = [], False
    for i, s in enumerate(sections):
        parent = zones[s["parent"]] if s["parent"] is not None else None
        if s["role"] != "body":
            label = {"abstract": "abstract", "appendix": "appendix"}.get(s["role"], "apparatus")
            rule = "role"
        else:
            label, rule = label_by_title(names[i], children[i])
            if label is None:
                label, rule = (parent["label"], "parent") if parent else ("unclear", "none")
            # "Discussion" inside "Study 1" often holds that study's exclusions,
            # and "Background" there is the study's setting. Related work
            # and literature stay prior work wherever they are.
            if (parent and parent["open"] and label in ("framing", "other", "prior_work")
                    and not PRIOR_WORK.search(names[i])):
                label, rule = parent["label"], rule + UNDER_STUDY
        # a section opens a study for its subsections if it is one, or if no
        # rule knew it: unknown is treated as a study, not as its opposite
        is_open = s["role"] == "body" and (label == "study" or (label == "unclear" and names[i] not in AMBIGUOUS
                                                               and (rule == "none" or (parent and parent["open"]))))
        number = STUDY_NUMBER.search(s["title"])
        zones.append({"title": s["title"], "level": s["level"], "role": s["role"], "text_chars": s["text_chars"],
                      "label": label, "rule": rule, "read": label in READ,
                      "study": number.group(0).title() if number else (parent["study"] if parent else None),
                      "open": is_open})
    for z in zones:
        del z["open"]
    return zones


def build(sectioned: dict) -> dict:
    return {"pid": sectioned["pid"], "year": sectioned["year"], "zones": label_sections(sectioned["sections"])}


# ------------------------------------------------------------------- summary

def summary_row(result: dict) -> dict:
    zones = result["zones"]
    body = [z for z in zones if z["role"] == "body"]
    return {"pid": result["pid"], "year": result["year"],
            "labels": dict(collections.Counter(z["label"] for z in zones)),
            "chars": dict(sum((collections.Counter({z["label"]: z["text_chars"]}) for z in zones), collections.Counter())),
            "rules": dict(collections.Counter(z["rule"].replace(UNDER_STUDY, "") for z in body)),
            "unknown": [normal(z["title"]) for z in body if z["rule"] == "none"]}


def summarize(rows: list[dict]) -> dict:
    per_year, unknown = {}, collections.Counter()
    for year in sorted({r["year"] for r in rows}):
        ys = [r for r in rows if r["year"] == year]
        ok = [r for r in ys if "error" not in r]
        labels, chars, rules = collections.Counter(), collections.Counter(), collections.Counter()
        for r in ok:
            labels.update(r["labels"]); chars.update(r["chars"]); rules.update(r["rules"])
            unknown.update(r["unknown"])
        total = sum(chars.values()) or 1
        per_year[year] = {
            "papers": len(ys),
            "sections": {label: labels[label] for label in LABELS},
            "text_share": {label: round(chars[label] / total, 4) for label in LABELS},
            "read_share": round(sum(chars[label] for label in READ) / total, 4),
            "rules": {rule: rules[rule] for rule in RULES if rule != "role"},
            "no_study_section": [r["pid"] for r in ok if not r["labels"].get("study")],
            "errors": [r["pid"] for r in ys if "error" in r],
        }
    return {"papers": len(rows), "per_year": per_year,
            "unknown_titles": len(unknown), "unknown_titles_most_common": dict(unknown.most_common(200))}


def main() -> None:
    ap = argparse.ArgumentParser(description="Label every section: study, limits, prior work and so on.")
    ap.add_argument("--year", choices=config.YEARS, help="one year only (default: all)")
    args = ap.parse_args()

    rows = []
    for year in ((args.year,) if args.year else config.YEARS):
        out_dir = ZONES_DIR / year
        out_dir.mkdir(parents=True, exist_ok=True)
        files = sorted((SECTIONS_DIR / year).glob("*.json"))
        if not files:
            raise SystemExit(f"no sections for {year}: run sections.py first")
        for f in files:
            try:
                result = build(json.loads(f.read_text(encoding="utf-8")))
                (out_dir / f.name).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
                rows.append(summary_row(result))
            except Exception as e:  # noqa: BLE001 - a paper we cannot label is a finding
                rows.append({"pid": f.stem, "year": year, "error": type(e).__name__ + ": " + str(e)[:120]})
        print(f"  {year}: {len(files)}", flush=True)

    summary = summarize(rows)
    suffix = f"_{args.year}" if args.year else ""
    with open(config.OUTPUT / f"zones_summary{suffix}.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1)

    print()
    print(f"{'year':<6}{'papers':>8}{'study':>8}{'limits':>8}{'unclear':>9}{'text read':>11}"
          f"{'no rule':>9}{'no study':>10}{'errors':>8}")
    for year, s in summary["per_year"].items():
        print(f"{year:<6}{s['papers']:>8}{s['sections']['study']:>8}{s['sections']['limits']:>8}"
              f"{s['sections']['unclear']:>9}{s['read_share']:>11.1%}{s['rules']['none']:>9}"
              f"{len(s['no_study_section']):>10}{len(s['errors']):>8}")
    print(f"\n-> {ZONES_DIR}")
    sys.exit(1 if any(s["errors"] for s in summary["per_year"].values()) else 0)


if __name__ == "__main__":
    main()
