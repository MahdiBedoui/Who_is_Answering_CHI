"""Module 7: Q1 judge.

Contract
  in:  output/q1_evidence/<year>/<pid>.json   (module 6: routes and cue hits)
       output/sentences/<year>/<pid>.json     (module 5)
  out: output/q1_judge/<prompt version>/<model>/<year>/<pid>.json
         one per paper module 6 sent to the judge: the prompt's sentence
         numbers, the raw answer, the checked answer, tokens used
       output/q1_final.jsonl
         one row per paper of the corpus: pid, year, q1 (yes or no),
         source (rule or judge), and per study the three checks with the
         sentences each rests on

What it establishes
  - a Q1 answer for every paper module 6 could not settle, made by an LLM
    that applies CODEBOOK.md to the paper's own sentences
  - every answer points at numbered sentences of the paper. The model
    answers with numbers, the text is looked up here, so a quote cannot be
    invented. An answer that cites a number it was not shown is rejected.
  - Q1 per study is derived here from the three checks, not taken from the
    model: Yes only if all three are yes. The paper is Yes if any study is.

What it does not do
  - It does not re-decide papers module 6 settled.
  - It does not answer Q2 or Q3.

Pinned model, temperature 0, versioned prompt, every answer kept on disk.
Safe to rerun: papers already answered under the same prompt version and
model are not asked again.

Run from the repo root:
    py "Phase 3 - LLM-as-Judge/q1_judge.py" --dry                  prompts + cost estimate, no API
    py "Phase 3 - LLM-as-Judge/q1_judge.py" --reference            judge only the reference papers
    py "Phase 3 - LLM-as-Judge/q1_judge.py"                         judge every paper sent on
    py "Phase 3 - LLM-as-Judge/q1_judge.py" --final                 merge rules + judge, score on the reference
Options: --model NAME (default: JUDGE_MODEL in .env, else gpt-4o-mini), --year, --limit N
"""
import argparse
import collections
import hashlib
import json
import os
import pathlib
import re
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))   # the repo root, where config.py is
import config  # noqa: E402

PROMPT_VERSION = "q1-v2.3"
# v2.0  first run on the reference (2026-11-01): 8% of answers rejected by the gate
# v2.1  gate accepts filler after a no and a c3 yes resting on absence; prompt says so, and that crowd
#       platform tasks are unmoderated unless a session with a researcher is described
# v2.2  reference run of v2.1: 19 of 74 human Yes lost, mostly a study with an online survey AND interviews
#       judged as one block and failed on the interviews. Each data collection is now judged on its own.
#       Existing online data and the authors' own notes fail c1. Context units sent on for an unmarked
#       survey now show their survey sentences (v2.1 showed nothing for 4 papers).
# v2.3  reference run of v2.2: of 10 human Yes still lost, most had a real online collection cancelled by a
#       session around it (onboarding, setup, a follow-up interview). Sessions around a collection no longer
#       moderate it; interviews are moderated in any medium; a formative survey reported as findings is a
#       data collection. Reasoning models are called without a temperature (they accept only the default).
DEFAULT_MODEL = os.environ.get("JUDGE_MODEL") or "gpt-4o-mini"
EVIDENCE_DIR = config.OUTPUT / "q1_evidence"
SENTENCES_DIR = config.OUTPUT / "sentences"
JUDGE_DIR = config.OUTPUT / "q1_judge"
FINAL = config.OUTPUT / "q1_final.jsonl"
REFERENCE = config.ANNOTATIONS / "q1_reference_400_2026-10-18.json"   # round 1, v1 question; optional

MAX_SENTENCES = 400          # per paper; above this, keep the cue sentences and their neighbours
NEIGHBOURS = 3
STUDY_LABELS = ("study", "unclear")
CONTEXT_LABELS = ("abstract", "limits", "appendix")
SURVEY = re.compile(r"\bsurvey(?:ed|s)?\b|\bquestionnaires?\b|\brespondents\b", re.I)

SYSTEM = """You code HCI research papers for a study of how they collect data. You read numbered sentences
from one paper, grouped by the study they belong to, and answer one question per study.

Q1: Did the authors collect data online, with no researcher present, and do the study's results rest on
that data? Answer it through three checks. Q1 is Yes only if all three are yes.

check c1 - Did the authors collect data from participants for this study's results?
  yes: survey answers, ratings, task performance, logs, diary entries that feed the results.
  no:  no participant data (a system description, someone else's dataset, a literature review), or the
       only data is a screener or demographic form used to choose who takes part.
       Participants testing a device in a lab: c1 is yes (c2 then decides).
check c2 - Was that data collected online?
  yes: Prolific, MTurk, CloudResearch, a Qualtrics or Google Forms link, an online experiment, a diary or
       experience-sampling app, logs sent from participants' own devices.
  no:  on paper, in person, on a lab machine.
check c3 - Was it unmoderated, with nobody from the research team present while the data was produced?
  yes: participants did it on their own, at their own time.
  no:  a researcher in the room or on a call: Zoom, Teams, a lab session, a workshop, an interview, a
       think-aloud, a focus group. A questionnaire filled in during such a session is no. The same
       questionnaire sent as a link to fill in later is yes.

Rules:
- Judge each data collection separately, even inside one study. A study that ran an online survey and
  also interviews has two data collections: report them as two entries (e.g. "Study 1 survey" and
  "Study 1 interviews"). The survey can be yes while the interviews are no; the interviews never make the
  survey no. The paper is yes if any one entry passes all three checks.
  If the sentences show a study the grouping missed (for example a formative survey inside "main"),
  report it as its own entry with a short name.
- Sessions around a data collection do not moderate it. An in-person onboarding or setup, a training
  session, or a debrief or follow-up interview are separate entries. Example: after an onboarding session,
  participants used an app at home for two weeks and answered daily prompts in it. The app data is online
  and unmoderated (yes); the onboarding and the exit interview are their own entries (no).
- An interview is moderated whatever the medium: in person, Zoom, phone, chat, or messages exchanged with a
  researcher over days. A questionnaire is moderated only if a researcher was there while it was filled in.
- A formative or preliminary survey whose answers are reported as findings is a data collection like any
  other. Only a survey used to recruit or select participants fails c1.
- Data that existed before the study (Reddit posts, app reviews, a public dataset) fails c1: the authors
  did not collect it from participants. So do the authors' own field notes or autoethnography.
- Recruiting people on a platform is not data collection. "Recruited on Prolific, then interviewed over
  Zoom" fails c3.
- A survey used only to recruit or select participants fails c1, even if it was online.
- Online does not mean unmoderated: a Zoom interview is online and moderated.
- Sentences from the abstract, limitations or appendix can support an answer about a study but say
  nothing on their own about what the authors did; related work is not shown.
- When the sentences do not say, decide from what they make most likely and set best_guess to true.
- Cite evidence by sentence number only. A yes on c1 or c2 needs at least one number; a yes on c3 may have
  none when it rests on nobody being mentioned. A no needs a number when
  a sentence shows it (an interview, a lab, a screener); when nothing in the text supports the check,
  give an empty list.

Answer with JSON only, in this shape:
{"studies": [{"study": "<name as given, or a short new one>",
              "c1": "yes|no", "c1_ids": [numbers],
              "c2": "yes|no", "c2_ids": [numbers],
              "c3": "yes|no", "c3_ids": [numbers],
              "best_guess": true|false,
              "how_collected": "<a few words: e.g. online survey on Prolific; Zoom interviews; lab study>"}],
 "reason": "<one or two sentences>"}
Stop at the first no: once a check is no, write the later checks of that study as "no" with empty ids.
A crowd platform task (MTurk, Prolific) is done by the worker alone: c3 is yes unless a session with a researcher is described."""


# ------------------------------------------------------------------ prompt
def candidates(evidence: dict, paper: dict) -> list[dict]:
    """The sentences the judge is shown, in reading order: every sentence of
    the study units module 6 could not settle, plus the cue sentences of the
    context unit and their neighbours. Very long papers keep only cue
    sentences and their neighbours."""
    sents, secs = paper["sentences"], paper["sections"]
    unit_of = {}
    for i, s in enumerate(sents):
        sec = secs[s["section"]]
        if sec["label"] in STUDY_LABELS:
            unit_of[i] = sec.get("study") or "main"
        elif sec["label"] in CONTEXT_LABELS:
            unit_of[i] = "context"
    judged = {u["unit"] for u in evidence["units"] if u["route"] == "judge"}
    hit = {h["s"] for u in evidence["units"] for h in u["hits"]}
    near = {j for i in hit for j in range(i - NEIGHBOURS, i + NEIGHBOURS + 1)}
    survey = {i for i, u in unit_of.items() if u == "context" and SURVEY.search(sents[i]["text"])}
    near_survey = {j for i in survey for j in range(i - 1, i + 2)} if "context" in judged else set()
    keep = [i for i, u in unit_of.items()
            if (u in judged and u != "context") or (u == "context" and (i in near or i in near_survey))]
    if not keep:                                     # nothing marked: show what is read, rather than nothing
        keep = [i for i, u in unit_of.items() if u != "context"][:MAX_SENTENCES]
    if len(keep) > MAX_SENTENCES:
        keep = [i for i in keep if i in near]
    return [{"n": i, "unit": unit_of[i], "section": secs[sents[i]["section"]].get("title") or "",
             "text": sents[i]["text"]} for i in sorted(keep)]


def build_prompt(cands: list[dict]) -> str:
    lines, last = [], None
    for c in cands:
        if c["unit"] != last:
            lines.append(f"\n## {'Abstract, limitations, appendix' if c['unit'] == 'context' else c['unit']}")
            last = c["unit"]
        lines.append(f"[{c['n']}] ({c['section'][:50]}) {c['text']}")
    return "Sentences of the paper, numbered, with their section:\n" + "\n".join(lines) + \
        "\n\nAnswer Q1 for each study. JSON only."


# ------------------------------------------------------------------ gate
def parse_and_check(raw: str, cands: list[dict]) -> tuple[dict | None, str | None]:
    """The model's answer -> (checked answer, None) or (None, why it was rejected)."""
    try:
        d = json.loads(raw)
    except Exception:
        m = re.search(r"\{.*\}", raw or "", re.S)
        try:
            d = json.loads(m.group(0)) if m else None
        except Exception:
            d = None
    if not isinstance(d, dict) or not isinstance(d.get("studies"), list):
        return None, "unparseable"
    if not d["studies"]:                             # the model found no data collection at all: c1 fails
        return {"q1": "no", "studies": [], "reason": str(d.get("reason") or "")[:400]}, None
    shown = {c["n"]: c["text"] for c in cands}
    studies = []
    for st in d["studies"]:
        if not isinstance(st, dict):
            return None, "study is not an object"
        row = {"study": str(st.get("study") or "study")[:60], "best_guess": bool(st.get("best_guess")),
               "how_collected": str(st.get("how_collected") or "")[:200]}
        stopped = False
        for k in ("c1", "c2", "c3"):
            v = st.get(k, "")
            v = v.strip().lower() if isinstance(v, str) else ""
            ids = st.get(k + "_ids") or []
            if stopped and v not in ("yes", "no"):
                v, ids = "no", []            # after a no the later checks are not asked; any filler is fine
            if v not in ("yes", "no"):
                return None, f"{k} is not yes or no"
            if not isinstance(ids, list) or any(not isinstance(i, int) or i not in shown for i in ids):
                return None, f"{k} cites a sentence it was not shown"
            # c3 yes can rest on an absence (nobody present is rarely written down), the others cannot
            if v == "yes" and not ids and k != "c3":
                return None, f"{k} is yes with no sentence"
            row[k], row[k + "_ids"] = v, ids
            stopped = stopped or v == "no"
        row["q1"] = "yes" if all(row[k] == "yes" for k in ("c1", "c2", "c3")) else "no"
        studies.append(row)
    q1 = "yes" if any(s["q1"] == "yes" for s in studies) else "no"
    return {"q1": q1, "studies": studies, "reason": str(d.get("reason") or "")[:400]}, None


# ------------------------------------------------------------------ model
def ask(client, model: str, prompt: str) -> tuple[str, dict]:
    kw = {} if re.match(r"o\d|gpt-5", model) else {"temperature": 0}    # reasoning models: default only
    resp = client.chat.completions.create(
        model=model, response_format={"type": "json_object"},
        messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}], **kw)
    usage = getattr(resp, "usage", None)
    return resp.choices[0].message.content or "", {
        "prompt_tokens": getattr(usage, "prompt_tokens", None), "completion_tokens": getattr(usage, "completion_tokens", None)}


def judge_paper(client, model: str, evidence: dict, paper: dict) -> dict:
    cands = candidates(evidence, paper)
    prompt = build_prompt(cands)
    record = {"pid": evidence["pid"], "year": evidence["year"], "model": model, "prompt_version": PROMPT_VERSION,
              "prompt_sha": hashlib.sha256((SYSTEM + prompt).encode()).hexdigest()[:16],
              "shown": [c["n"] for c in cands], "attempts": []}
    for _ in range(2):                                   # one retry when the answer fails the check
        raw, usage = ask(client, model, prompt)
        answer, why = parse_and_check(raw, cands)
        record["attempts"].append({"raw": raw, "usage": usage, "rejected": why})
        if answer:
            record["answer"] = answer
            break
    return record


# ------------------------------------------------------------------ files
def judge_path(model: str, year: str, pid: str) -> pathlib.Path:
    return JUDGE_DIR / PROMPT_VERSION / re.sub(r"[^\w.-]", "_", model) / year / f"{pid}.json"


def load_reference() -> dict[str, str]:
    """The round-1 reference labels, or {} when the annotations are not on this machine. They answer v1's
    narrower question, so --final's score is a quick check; the v2 validation is RQ 1's evaluate_q1.py."""
    if not REFERENCE.exists():
        return {}
    raw = json.loads(REFERENCE.read_text(encoding="utf-8"))
    raw = raw.get("reference", raw)
    return {p: str(v).strip().lower() for p, v in raw.items() if str(v).strip().lower() in ("yes", "no")}


def queue(years, only: set | None = None) -> list[pathlib.Path]:
    out = []
    for y in years:
        for f in sorted((EVIDENCE_DIR / y).glob("*.json")):
            if only is not None and f.stem not in only:
                continue
            if json.loads(f.read_text(encoding="utf-8"))["route"] == "judge":
                out.append(f)
    return out


def final_rows(model: str, years) -> list[dict]:
    rows = []
    for y in years:
        for f in sorted((EVIDENCE_DIR / y).glob("*.json")):
            ev = json.loads(f.read_text(encoding="utf-8"))
            if ev["route"] in ("yes", "no"):
                rows.append({"pid": ev["pid"], "year": y, "q1": ev["route"], "source": "rule", "why": ev["reason"]})
                continue
            jp = judge_path(model, y, ev["pid"])
            rec = json.loads(jp.read_text(encoding="utf-8")) if jp.exists() else None
            if rec and rec.get("answer"):
                a = rec["answer"]
                rows.append({"pid": ev["pid"], "year": y, "q1": a["q1"], "source": "judge",
                             "studies": a["studies"], "why": a["reason"]})
            else:
                rows.append({"pid": ev["pid"], "year": y, "q1": None, "source": "pending" if not rec else "rejected"})
    return rows


def score(rows: list[dict], ref: dict[str, str]) -> None:
    on = [r for r in rows if r["pid"] in ref]
    t = collections.Counter((r["q1"], ref[r["pid"]]) for r in on)
    tp, fp, fn, tn = t[("yes", "yes")], t[("yes", "no")], t[("no", "yes")], t[("no", "no")]
    pend = sum(v for (q, _), v in t.items() if q is None)
    p = tp / (tp + fp) if tp + fp else float("nan")
    r = tp / (tp + fn) if tp + fn else float("nan")
    f1 = 2 * tp / (2 * tp + fp + fn) if tp else float("nan")
    print(f"\nreference papers: {len(on)}  (no answer yet: {pend})")
    print(f"TP {tp}  FP {fp}  FN {fn}  TN {tn}")
    print(f"precision {p:.3f}  recall {r:.3f}  F1 {f1:.3f}  accuracy {(tp + tn) / max(1, tp + fp + fn + tn):.3f}")
    for (label, want_q, want_r) in (("judge or rule said yes, reference No", "yes", "no"),
                                    ("judge or rule said no, reference Yes", "no", "yes")):
        miss = [x for x in on if x["q1"] == want_q and ref[x["pid"]] == want_r]
        if miss:
            print(f"\n{label} ({len(miss)}):")
            for x in miss:
                print(f"  {x['year']}  {x['pid']}  [{x['source']}]  {str(x.get('why', ''))[:110]}")


# ------------------------------------------------------------------ main
def main() -> None:
    ap = argparse.ArgumentParser(description="Ask an LLM to decide Q1 for the papers module 6 sent on.")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--year", choices=config.YEARS)
    ap.add_argument("--reference", action="store_true", help="only the reference papers")
    ap.add_argument("--limit", type=int, help="at most N papers")
    ap.add_argument("--dry", action="store_true", help="write the first prompts and estimate the size, no API")
    ap.add_argument("--final", action="store_true", help="merge rules and judge, score on the reference")
    args = ap.parse_args()
    years = (args.year,) if args.year else config.YEARS
    ref = load_reference()

    if args.final:
        rows = final_rows(args.model, years)
        with open(FINAL, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        c = collections.Counter((r["source"], r["q1"]) for r in rows)
        print("source/q1:", dict(c))
        print(f"-> {FINAL}")
        if ref:
            print("\nagainst the round-1 reference (v1's question; the v2 validation is evaluate_q1.py):")
            score(rows, ref)
        return

    if args.reference and not ref:
        raise SystemExit(f"--reference needs the round-1 reference labels at {REFERENCE}")
    todo = queue(years, set(ref) if args.reference else None)
    rechecked = 0
    for f in todo:
        jp = judge_path(args.model, f.parent.name, f.stem)
        if jp.exists():
            rec = json.loads(jp.read_text(encoding="utf-8"))
            if "answer" not in rec:                  # a stored answer may pass a gate fixed since
                ev = json.loads(f.read_text(encoding="utf-8"))
                paper = json.loads((SENTENCES_DIR / f.parent.name / f.name).read_text(encoding="utf-8"))
                cands = candidates(ev, paper)
                for a in rec["attempts"]:
                    answer, _ = parse_and_check(a["raw"], cands)
                    if answer:
                        rec["answer"], rec["rechecked"] = answer, True
                        jp.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
                        rechecked += 1
                        break
    if rechecked:
        print(f"stored answers that pass the current check: {rechecked}")
    todo = [f for f in todo if not (judge_path(args.model, f.parent.name, f.stem).exists() and
                                    "answer" in json.loads(judge_path(args.model, f.parent.name, f.stem)
                                                           .read_text(encoding="utf-8")))]
    if args.limit:
        todo = todo[:args.limit]
    print(f"papers to judge: {len(todo)}  (model {args.model}, prompt {PROMPT_VERSION})")

    if args.dry:
        chars, shown = 0, []
        out = JUDGE_DIR / "dry"
        out.mkdir(parents=True, exist_ok=True)
        for k, f in enumerate(todo):
            ev = json.loads(f.read_text(encoding="utf-8"))
            paper = json.loads((SENTENCES_DIR / f.parent.name / f.name).read_text(encoding="utf-8"))
            cands = candidates(ev, paper)
            prompt = build_prompt(cands)
            chars += len(SYSTEM) + len(prompt)
            shown.append(len(cands))
            if k < 3:
                (out / f"{f.stem}.txt").write_text(SYSTEM + "\n\n" + prompt, encoding="utf-8")
        if todo:
            tok = chars / 4
            shown.sort()
            print(f"sentences shown per paper: median {shown[len(shown) // 2]}, max {shown[-1]}")
            print(f"about {tok / 1e6:.1f}M input tokens ({tok / len(todo):,.0f} per paper)")
            print(f"three example prompts -> {out}")
        return

    try:
        from openai import OpenAI
    except ImportError:
        raise SystemExit("the openai package is missing: py -m pip install openai")
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is not set in .env")
    client = OpenAI()
    done = rejected = 0
    used = collections.Counter()
    for k, f in enumerate(todo, 1):
        ev = json.loads(f.read_text(encoding="utf-8"))
        paper = json.loads((SENTENCES_DIR / f.parent.name / f.name).read_text(encoding="utf-8"))
        for attempt in range(4):
            try:
                rec = judge_paper(client, args.model, ev, paper)
                break
            except Exception as e:  # noqa: BLE001 - rate limits and network: wait and retry
                if "insufficient_quota" in str(e) or "credit_balance" in str(e):
                    raise SystemExit(f"\nOpenAI credits are used up after {done} papers this run. Add credits, then "
                                     "rerun the same command: papers already answered are not asked again.")
                if attempt == 3:
                    raise
                time.sleep(5 * 2 ** attempt)
                print(f"  retry {f.stem}: {type(e).__name__}", flush=True)
        jp = judge_path(args.model, f.parent.name, f.stem)
        jp.parent.mkdir(parents=True, exist_ok=True)
        jp.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
        done += 1
        rejected += "answer" not in rec
        for a in rec["attempts"]:
            used.update({k2: v or 0 for k2, v in a["usage"].items()})
        if k % 25 == 0 or k == len(todo):
            print(f"  {k}/{len(todo)}  rejected {rejected}  tokens in {used['prompt_tokens']:,} out "
                  f"{used['completion_tokens']:,}", flush=True)
    print(f"\njudged {done}, rejected after retry {rejected} -> {JUDGE_DIR / PROMPT_VERSION}")
    print('next: py "Phase 3 - LLM-as-Judge/q1_judge.py" --final')


if __name__ == "__main__":
    main()
