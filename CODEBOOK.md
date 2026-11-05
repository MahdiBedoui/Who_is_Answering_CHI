# Codebook

The rules the annotators, the detectors (Phase 2) and the judge (Phase 3)
all apply. Agreed at the annotation workshop of October 2026 and used in the
round 2 annotation pages. Round 1 was coded under v1 (Q1 = "did the authors
run an online survey"); see "Changes from v1".

The unit is a **study**: a paper can report several (Study 1, Study 2, a
formative survey and a lab study). Each is judged on its own. A paper is Yes
on Q1 if any of its studies is Yes.

## Q1: Did the authors collect data online, with no researcher present, and do the study results rest on that data?

Three checks, in order. Q1 is Yes only if all three are Yes. It is No as
soon as one is No.

| Check | Yes | No |
|---|---|---|
| 1. Did the authors collect data from participants for this study's results? | Survey answers, ratings, task performance, logs, diary entries that feed the results | No participant data (a system paper, a dataset someone else collected, a literature review), or only a screener or demographic form used to pick who takes part |
| 2. Was that data collected online? | Prolific, MTurk, CloudResearch, a Qualtrics or Google Forms link, an online experiment, a diary or ESM app, app or interaction logs sent from participants' own devices | On paper, in person, on a lab machine |
| 3. Was it unmoderated? | Nobody from the research team present: participants did it on their own, at their own time | A researcher present in the room or on a call: Zoom, Teams, a lab session, a workshop, an interview, a think-aloud, a focus group |

Clarifications from annotators' questions:

- **Check 1 is about any data collection, not only surveys.** Participants
  testing a device in a lab: check 1 Yes, check 2 No.
- **A screener is not the study.** An online survey used only to recruit or
  pick interviewees fails check 1, even when it was online and unmoderated.
  (Designing for the Bittersweet, CHI 2022.) A formative survey whose
  answers are reported as findings is a study in its own right.
- **Online is not unmoderated.** An interview over Zoom is online and
  moderated: check 3 No.
- **A questionnaire inside a moderated session** (a post-task questionnaire
  filled in during a lab or Zoom session) fails check 3. The same
  questionnaire sent as a link to fill in later passes.
- **Field deployments and diaries** pass when participants used the system
  or wrote entries on their own and the data reached the authors online.

Added while validating the judge on round 1, and part of its prompt from
version q1-v2.2 and q1-v2.3 on:

- **Each data collection is judged on its own,** even inside one study. A
  study with an online survey and interviews has two: the survey can pass
  while the interviews fail.
- **Sessions around a data collection do not moderate it.** An in-person
  onboarding, a training session, or an exit interview are separate data
  collections. Two weeks of app use at home after an onboarding session
  passes; the onboarding does not.
- **An interview is moderated whatever the medium:** in person, video,
  phone, chat, or messages exchanged with a researcher over days.
- **Data that existed before the study fails check 1:** posts, app reviews,
  a public dataset, or the authors' own field notes.
- **Recruiting on a platform is not collecting data there.** Recruited on
  Prolific, then interviewed over Zoom: check 3 No.
- **Crowd platform tasks** (MTurk, Prolific) are done by the worker alone:
  check 3 Yes unless a session with a researcher is described.

Evidence: verbatim quotes, as many as needed, separated by ";". A best-guess
flag replaces Unsure. If Q1 is No, the annotator writes how the data was
collected instead.

## Q2: Did the authors report any data-quality check on the online data?

Asked only when Q1 is Yes. Tick every check found, with a quote for each:
attention check / IMC, comprehension check, CAPTCHA, reputation filter
(approval rate, number of HITs), qualification / screener, duplicate / IP /
VPN check, speed filter, straight-lining / pattern check, open-text quality
review, bot detection / honeypot, consistency items, manual review, other
(say what it is). Or tick "No data-quality checks reported". Record
separately whether the paper says explicitly that no checks were used.

## Q3: Where did participants come from?

Asked only when Q1 is Yes. Tick every source, with a quote for each:
Prolific, MTurk, CloudResearch, Qualtrics panel, university pool, social
media, mailing lists, snowball, community / forums, company-internal, other
(describe), not reported.

## Changes from v1

| | v1 (round 1) | v2 (round 2, the detectors) |
|---|---|---|
| Q1 asks about | an online survey | any online data collection |
| Moderated online sessions | not addressed; varied by annotator | No (check 3) |
| Screeners | "a screening questionnaire alone does not count" | same, now check 1 |
| Unit | per study, Q1 ticked directly | per study, Q1 derived from three checks |
| Unsure | allowed | replaced by best guess |
| Evidence | one quote | one or more quotes per check |

Round-1 labels stay valid for papers whose only online data collection is a
survey. Papers whose v1 No could flip under v2 (online data that is not a
survey) are re-labelled under v2 before scoring (see RQ 1).
