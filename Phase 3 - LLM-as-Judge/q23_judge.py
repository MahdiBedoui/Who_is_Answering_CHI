"""Module 9: Q2 and Q3 judge.

Contract
  in:  output/q23_evidence/<year>/<pid>.json   (module 8: cue hits per Q1-Yes paper)
       output/sentences/<year>/<pid>.json      (module 5)
  out: output/q23_judge/<prompt version>/<model>/<year>/<pid>.json
         one per paper module 8 sent on: the sentence numbers shown, the raw
         answer, the checked answer, tokens used
       output/q23_final.jsonl
         one row per Q1-Yes paper: the data-quality checks found (Q2), whether
         the paper says it used none, the participant sources (Q3), each with
         the sentence numbers and text it rests on

What it establishes
  - for every Q1-Yes paper, which data-quality checks the authors report on
    their online data, and where those participants came from, in the
    categories of CODEBOOK.md
  - every category points at numbered sentences of the paper. The model
    answers with numbers; the text is looked up here. A category that cites
    no sentence, or a sentence it was not shown, is rejected.

What it does not do
  - It does not revisit Q1. Papers reach it because module 7 said Yes.
  - It does not judge whether a check was adequate, only whether it is
    reported.

Pinned model, temperature 0, versioned prompt, every answer kept on disk.
Safe to rerun: papers already answered under the same prompt version and
model are not asked again; stored answers are re-checked against the
current gate before anything is asked.

Run from the repo root:
    py "Phase 3 - LLM-as-Judge/q23_judge.py" --dry           prompts + cost estimate, no API
    py "Phase 3 - LLM-as-Judge/q23_judge.py"                  judge every paper module 8 sent on
    py "Phase 3 - LLM-as-Judge/q23_judge.py" --final          merge rules + judge into q23_final.jsonl
Options: --model NAME (default gpt-4.1-2025-04-14, the model validated on Q1), --year, --limit N, --only PIDS_FILE
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

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "Phase 2 - NLP and Regex Detectors"))
import config  # noqa: E402
from q23_evidence import EVIDENCE_DIR, Q2_CHECKS, Q3_SOURCES, candidates  # noqa: E402

PROMPT_VERSION = "q23-v1.0"
DEFAULT_MODEL = os.environ.get("Q23_MODEL") or "gpt-4.1-2025-04-14"
SENTENCES_DIR = config.OUTPUT / "sentences"
JUDGE_DIR = config.OUTPUT / "q23_judge"
FINAL = config.OUTPUT / "q23_final.jsonl"

CHECK_DEFS = {
    "attention check / IMC": "an item with a known correct answer embedded to verify the participant is reading "
                             "(\"select Strongly agree\"), an instructed-response or trap item",
    "comprehension check": "a quiz or question verifying the participant understood the instructions or scenario, "
                           "or a manipulation check",
    "CAPTCHA": "an automated human-verification challenge (reCAPTCHA) gating entry",
    "reputation filter (approval rate / #HITs)": "platform filtering on worker history: approval rate, number of "
                                                 "completed tasks, MTurk Masters",
    "qualification / screener": "an eligibility screener or platform filter deciding who may take part (country, "
                                "language, demographics, a qualification task)",
    "duplicate / IP / VPN check": "detection of repeated or disguised participation: duplicate IDs or IPs, "
                                  "geolocation, VPN or proxy checks, blocking repeat participation",
    "speed filter": "exclusion of implausibly fast completions, by an absolute cutoff or relative to the median",
    "straight-lining / pattern check": "detection of invariant or patterned answers across items, careless responding",
    "open-text quality review": "screening free-text answers for gibberish, irrelevance, copy-paste or AI-written text",
    "bot detection / honeypot": "hidden fields, bot scores, or explicit checks for bots or fraudulent respondents",
    "consistency items": "paired or reverse-coded items compared for contradictory answers",
    "manual review": "researchers inspecting responses one by one and excluding on judgment",
    "other": "any other check on the quality of the online data, e.g. removing incomplete responses, excluding "
             "outliers on task performance, a gold-standard task; say what it is",
}
SOURCE_DEFS = {
    "Prolific": "recruited on Prolific",
    "MTurk": "recruited on Amazon Mechanical Turk",
    "CloudResearch": "recruited through CloudResearch / TurkPrime",
    "Qualtrics": "a Qualtrics panel (Qualtrics recruited the respondents). Qualtrics as the survey tool is NOT a source",
    "University pool": "a university participant pool, SONA, course credit, students of the authors' university",
    "Social media": "posts on Twitter/X, Facebook, Instagram, LinkedIn, WeChat, etc.",
    "Mailing lists": "mailing lists, listservs, newsletters, email invitations",
    "Snowball": "snowball sampling, word of mouth, personal networks, referrals",
    "Community / forums": "Reddit, forums, Discord or Slack communities, Facebook groups, community or advocacy "
                          "organisations",
    "Company-internal": "employees of a company or organisation, recruited inside it",
    "other": "any other source (another panel company, flyers, a partner organisation, an existing user base); say "
             "what it is",
}

SYSTEM = f"""You code HCI research papers for a study of online data collection. Each paper you see collected data
online with no researcher present (that is settled). You read numbered sentences from the paper and answer
two questions about its online data collection(s), which are named at the top.

Q2: Which data-quality checks do the authors report on that online data? Categories:
{chr(10).join(f'- "{k}": {v}' for k, v in CHECK_DEFS.items())}
Rules for Q2:
- Report a check only if the paper says it was applied to its own online data (planned or preregistered criteria
  count). Checks other papers used, or checks on interview or lab data, do not count.
- An exclusion with a stated reason goes in the category of that reason ("excluded 12 who failed the attention
  check" is an attention check). An exclusion with no reason at all is "other" with what "unexplained exclusion".
- A platform setting such as "US residents, approval rate above 95%" gives two categories: qualification /
  screener and reputation filter.
- absence_stated is true only if the paper says in so many words that it used no such checks.

Q3: Where did the participants of that online data collection come from? Categories:
{chr(10).join(f'- "{k}": {v}' for k, v in SOURCE_DEFS.items())}
Rules for Q3:
- Report every source the paper names for the online data collection(s). The tool that hosted the survey is not
  a source.
- If nothing says where they came from, return an empty list.

Cite evidence by sentence number only: every category needs at least one number. Answer with JSON only:
{{"q2": {{"checks": [{{"check": "<category>", "ids": [numbers], "what": "<a few words>"}}],
         "absence_stated": true|false, "absence_ids": [numbers]}},
 "q3": {{"sources": [{{"source": "<category>", "ids": [numbers], "what": "<a few words>"}}]}},
 "reason": "<one or two sentences>"}}"""


# ------------------------------------------------------------------ prompt
def build_prompt(evidence: dict, cands: list[dict]) -> str:
    if evidence.get("online"):
        head = "Online data collection(s) of this paper:\n" + "\n".join(
            f"- {o['study']}: {o['how_collected'] or 'online, unmoderated'}" for o in evidence["online"])
    else:
        head = "Online data collection(s) of this paper: the study sections that report an online, unmoderated " \
               "data collection (settled by rules; find it in the sentences)."
    lines = [f"[{c['n']}] ({c['section'][:50]}) {c['text']}" for c in cands]
    return head + "\n\nSentences of the paper, numbered, with their section:\n" + "\n".join(lines) + \
        "\n\nAnswer Q2 and Q3. JSON only."


# ------------------------------------------------------------------ gate
def _norm(name: str, allowed: list[str]) -> str | None:
    n = (name or "").strip()
    for a in allowed:
        if n.lower() == a.lower():
            return a
    if n.lower().startswith("other"):
        return "other"
    return None


def parse_and_check(raw: str, cands: list[dict]) -> tuple[dict | None, str | None]:
    try:
        d = json.loads(raw)
    except Exception:
        m = re.search(r"\{.*\}", raw or "", re.S)
        try:
            d = json.loads(m.group(0)) if m else None
        except Exception:
            d = None
    if not isinstance(d, dict) or not isinstance(d.get("q2"), dict) or not isinstance(d.get("q3"), dict):
        return None, "unparseable"
    shown = {c["n"] for c in cands}

    def items(lst, key, allowed):
        out = {}
        if not isinstance(lst, list):
            raise ValueError(f"{key} list missing")
        for it in lst:
            if not isinstance(it, dict):
                raise ValueError(f"{key} item is not an object")
            cat = _norm(str(it.get(key) or ""), allowed)
            if cat is None:
                raise ValueError(f"unknown {key}: {str(it.get(key))[:40]}")
            ids = it.get("ids") or []
            if not isinstance(ids, list) or not ids or any(not isinstance(i, int) or i not in shown for i in ids):
                raise ValueError(f"{cat} cites no sentence or one it was not shown")
            what = str(it.get("what") or "")[:120]
            if cat == "other" and not what:
                raise ValueError("other without saying what")
            prev = out.get(cat)
            out[cat] = {"ids": sorted(set(ids) | set(prev["ids"] if prev else [])),
                        "what": "; ".join(x for x in ((prev or {}).get("what"), what) if x)}
        return out

    try:
        checks = items(d["q2"].get("checks", []), "check", Q2_CHECKS)
        sources = items(d["q3"].get("sources", []), "source", [s for s in Q3_SOURCES if s != "Not reported"])
    except ValueError as e:
        return None, str(e)
    absent = bool(d["q2"].get("absence_stated"))
    a_ids = d["q2"].get("absence_ids") or []
    if absent and (not isinstance(a_ids, list) or not a_ids or any(i not in shown for i in a_ids)):
        return None, "absence_stated without a sentence"
    return {"q2_checks": checks, "q2_absence_stated": absent, "q2_absence_ids": a_ids if absent else [],
            "q3_sources": sources, "reason": str(d.get("reason") or "")[:400]}, None


# ------------------------------------------------------------------ model
def ask(client, model: str, prompt: str) -> tuple[str, dict]:
    kw = {} if re.match(r"o\d|gpt-5", model) else {"temperature": 0}
    resp = client.chat.completions.create(
        model=model, response_format={"type": "json_object"},
        messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}], **kw)
    usage = getattr(resp, "usage", None)
    return resp.choices[0].message.content or "", {
        "prompt_tokens": getattr(usage, "prompt_tokens", None), "completion_tokens": getattr(usage, "completion_tokens", None)}


def judge_paper(client, model: str, evidence: dict, paper: dict) -> dict:
    cands = candidates(evidence, paper)
    prompt = build_prompt(evidence, cands)
    record = {"pid": evidence["pid"], "year": evidence["year"], "model": model, "prompt_version": PROMPT_VERSION,
              "prompt_sha": hashlib.sha256((SYSTEM + prompt).encode()).hexdigest()[:16],
              "shown": [c["n"] for c in cands], "attempts": []}
    for _ in range(2):
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


def load(p: pathlib.Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def final_rows(model: str, years) -> list[dict]:
    rows = []
    for y in years:
        for f in sorted((EVIDENCE_DIR / y).glob("*.json")):
            ev = load(f)
            base = {"pid": ev["pid"], "year": y}
            if ev["route"] == "none":
                rows.append({**base, "source": "rule", "q2_any": False, "q2_checks": {}, "q2_absence_stated": False,
                             "q3_sources": {"Not reported": {"ids": [], "what": ""}}, "why": "no Q2, Q3 or recruiting cue"})
                continue
            jp = judge_path(model, y, ev["pid"])
            rec = load(jp) if jp.exists() else None
            if not rec or not rec.get("answer"):
                rows.append({**base, "source": "pending" if not rec else "rejected"})
                continue
            a = rec["answer"]
            sents = load(SENTENCES_DIR / y / f"{ev['pid']}.json")["sentences"]
            def with_text(d):
                return {k: {**v, "text": [sents[i]["text"] for i in v["ids"]]} for k, v in d.items()}
            src = with_text(a["q3_sources"]) or {"Not reported": {"ids": [], "what": "", "text": []}}
            rows.append({**base, "source": "judge", "q2_any": bool(a["q2_checks"]), "q2_checks": with_text(a["q2_checks"]),
                         "q2_absence_stated": a["q2_absence_stated"],
                         "q2_absence_text": [sents[i]["text"] for i in a["q2_absence_ids"]],
                         "q3_sources": src, "why": a["reason"]})
    return rows


# ------------------------------------------------------------------ main
def main() -> None:
    ap = argparse.ArgumentParser(description="Ask an LLM for Q2 (quality checks) and Q3 (sources) on Q1-Yes papers.")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--year", choices=config.YEARS)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--only", type=pathlib.Path, help="a file of paper ids, one per line: judge only those")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--final", action="store_true")
    args = ap.parse_args()
    years = (args.year,) if args.year else config.YEARS

    if args.final:
        rows = final_rows(args.model, years)
        with open(FINAL, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        done = [r for r in rows if "q2_any" in r]
        print(f"Q1-Yes papers: {len(rows)}  answered: {len(done)}  "
              f"pending/rejected: {collections.Counter(r['source'] for r in rows if 'q2_any' not in r)}")
        if done:
            print(f"any Q2 check reported: {sum(r['q2_any'] for r in done)}/{len(done)}")
            c2 = collections.Counter(k for r in done for k in r["q2_checks"])
            c3 = collections.Counter(k for r in done for k in r["q3_sources"])
            print("Q2:", dict(c2.most_common()))
            print("Q3:", dict(c3.most_common()))
        print(f"-> {FINAL}")
        return

    only = set(args.only.read_text().split()) if args.only else None
    todo = [f for y in years for f in sorted((EVIDENCE_DIR / y).glob("*.json"))
            if (only is None or f.stem in only) and load(f)["route"] == "judge"]
    rechecked = 0
    for f in todo:                                    # stored answers may pass a gate fixed since
        jp = judge_path(args.model, f.parent.name, f.stem)
        if jp.exists() and "answer" not in (rec := load(jp)):
            cands = candidates(load(f), load(SENTENCES_DIR / f.parent.name / f.name))
            for a in rec["attempts"]:
                answer, _ = parse_and_check(a["raw"], cands)
                if answer:
                    rec["answer"], rec["rechecked"] = answer, True
                    jp.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
                    rechecked += 1
                    break
    if rechecked:
        print(f"stored answers that pass the current check: {rechecked}")
    todo = [f for f in todo if not (judge_path(args.model, f.parent.name, f.stem).exists()
                                    and "answer" in load(judge_path(args.model, f.parent.name, f.stem)))]
    if args.limit:
        todo = todo[:args.limit]
    print(f"papers to judge: {len(todo)}  (model {args.model}, prompt {PROMPT_VERSION})")

    if args.dry:
        chars, out = 0, JUDGE_DIR / "dry"
        out.mkdir(parents=True, exist_ok=True)
        for k, f in enumerate(todo):
            ev = load(f)
            prompt = build_prompt(ev, candidates(ev, load(SENTENCES_DIR / f.parent.name / f.name)))
            chars += len(SYSTEM) + len(prompt)
            if k < 3:
                (out / f"{f.stem}.txt").write_text(SYSTEM + "\n\n" + prompt, encoding="utf-8")
        if todo:
            tok = chars / 4
            print(f"about {tok / 1e6:.1f}M input tokens ({tok / len(todo):,.0f} per paper); "
                  f"at $2/M in and ~300 tokens out at $8/M: ${tok / 1e6 * 2 + len(todo) * 300 / 1e6 * 8:,.0f}")
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
        ev = load(f)
        paper = load(SENTENCES_DIR / f.parent.name / f.name)
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
    print('next: py "Phase 3 - LLM-as-Judge/q23_judge.py" --final')


if __name__ == "__main__":
    main()
