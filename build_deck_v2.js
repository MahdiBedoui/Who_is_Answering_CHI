/*
 * Build "Who's Answering CHI? — Progress" as a .pptx (8 slides).
 *
 * Run from this folder:
 *     npm install pptxgenjs
 *     node build_deck_v2.js
 * Produces: WhosAnsweringCHI_Deck_v2.pptx  (import into Google Slides via
 *           File -> Import slides, or open directly in PowerPoint/Keynote).
 */
const pptxgen = require("pptxgenjs");

// ---- palette --------------------------------------------------------------
const NAVY = "15233B", NAVY2 = "1E2D4D", TEAL = "00A896", TEALD = "037D6F";
const ICE = "CADCFC", INK = "1E293B", MUTE = "64748B", WHITE = "FFFFFF";
const CARD = "F1F5F9", BORDER = "E2E8F0", GREEN = "15803D", AMBER = "B45309";
const HFONT = "Georgia", BFONT = "Calibri";

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.33 x 7.5
pres.author = "Mahdi";
pres.title = "Who's Answering CHI? — Progress";
const W = 13.33;
const sh = () => ({ type: "outer", color: "000000", blur: 7, offset: 2, angle: 135, opacity: 0.10 });

function title(s, t, color = INK) {
  s.addText(t, { x: 0.6, y: 0.42, w: W - 1.2, h: 0.85, fontFace: HFONT, fontSize: 30, bold: true, color, valign: "middle", margin: 0 });
}
function sub(s, t) {
  s.addText(t, { x: 0.6, y: 1.28, w: W - 1.2, h: 0.45, fontFace: BFONT, fontSize: 14, color: MUTE, valign: "middle", margin: 0 });
}
function card(s, x, y, w, h, fill = CARD, line = BORDER) {
  s.addShape(pres.shapes.RECTANGLE, { x, y, w, h, fill: { color: fill }, line: { color: line, width: 1 }, shadow: sh() });
}
function chip(s, x, y, w, text, lineColor, fill = NAVY2, txt = WHITE) {
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h: 0.5, rectRadius: 0.08, fill: { color: fill }, line: { color: lineColor, width: 1.25 } });
  s.addText(text, { x, y, w, h: 0.5, fontFace: BFONT, fontSize: 12.5, bold: true, color: txt, align: "center", valign: "middle", margin: 0 });
}
function arrow(s, x, y) {
  s.addText("→", { x, y, w: 0.5, h: 0.9, fontFace: BFONT, fontSize: 26, bold: true, color: TEAL, align: "center", valign: "middle", margin: 0 });
}
function fstep(s, x, y, w, h, head, body) {
  card(s, x, y, w, h, CARD, BORDER);
  s.addText([
    { text: head, options: { fontSize: 14.5, bold: true, color: TEALD, breakLine: true } },
    { text: body, options: { fontSize: 12.5, color: INK } },
  ], { x: x + 0.18, y, w: w - 0.36, h, align: "left", valign: "middle", fontFace: BFONT, lineSpacingMultiple: 1.05, margin: 0.05 });
}

// ===========================================================================
// 1 — TITLE
// ===========================================================================
let s = pres.addSlide();
s.background = { color: NAVY };
s.addText("RESEARCH PROGRESS  ·  STAGE 2", { x: 0.75, y: 0.7, w: 10, h: 0.4, fontFace: BFONT, fontSize: 12, bold: true, color: TEAL, charSpacing: 3, margin: 0 });
s.addText("Who's Answering CHI?", { x: 0.7, y: 1.45, w: 12, h: 1.3, fontFace: HFONT, fontSize: 54, bold: true, color: WHITE, margin: 0 });
s.addText("A field-scale audit of online-survey integrity practices across ~16,000 ACM SIGCHI papers (2022–2026)", { x: 0.75, y: 2.95, w: 10.6, h: 1.0, fontFace: BFONT, fontSize: 18, color: ICE, margin: 0 });
chip(s, 0.75, 4.45, 3.7, "Corpus   ✓ Built & validated", GREEN);
chip(s, 4.65, 4.45, 3.7, "Extraction   ◐ In progress", AMBER);
s.addText("Mahdi   ·   June 4, 2026", { x: 0.75, y: 6.45, w: 8, h: 0.4, fontFace: BFONT, fontSize: 15, bold: true, color: WHITE, margin: 0 });
s.addText("Advisor / committee — [edit]", { x: 0.75, y: 6.9, w: 8, h: 0.35, fontFace: BFONT, fontSize: 11, color: MUTE, margin: 0 });

// ===========================================================================
// 2 — RESEARCH QUESTIONS
// ===========================================================================
s = pres.addSlide();
s.background = { color: WHITE };
title(s, "Our research questions");
sub(s, "Asked of every SIGCHI paper in the corpus.");
const rqs = [
  ["1", "Did the authors run an online survey?", "Detect whether the paper collected data through an online survey."],
  ["2", "If so, did they use any fraud-detection methods?", "Attention checks, CAPTCHA, IP / duplicate filtering, panel-native safeguards."],
  ["3", "Which participant-source platform did they recruit from?", "Prolific, MTurk, CloudResearch, social media, mailing lists, university pools."],
];
let yy = 1.95; const rh = 1.55, rg = 0.22, rx = 0.7, rw = 11.93;
rqs.forEach(([n, h, d]) => {
  card(s, rx, yy, rw, rh);
  s.addShape(pres.shapes.RECTANGLE, { x: rx, y: yy, w: 0.7, h: rh, fill: { color: TEAL } });
  s.addText(n, { x: rx, y: yy, w: 0.7, h: rh, fontFace: HFONT, fontSize: 28, bold: true, color: WHITE, align: "center", valign: "middle", margin: 0 });
  s.addText([
    { text: h, options: { fontSize: 18, bold: true, color: INK, breakLine: true } },
    { text: d, options: { fontSize: 13, color: MUTE } },
  ], { x: rx + 0.95, y: yy, w: rw - 1.2, h: rh, fontFace: BFONT, align: "left", valign: "middle", lineSpacingMultiple: 1.08, margin: 0.05 });
  yy += rh + rg;
});

// ===========================================================================
// 3 — DATA COLLECTION + VALIDATION
// ===========================================================================
s = pres.addSlide();
s.background = { color: WHITE };
title(s, "Building the corpus: scrape, then validate");
const fw = 3.55, fy = 1.75, fh = 1.7;
fstep(s, 0.7, fy, fw, fh, "1 · Scrape", "Harvest DOIs per venue & year from the ACM Digital Library search facets.");
arrow(s, 0.7 + fw + 0.08, fy + fh / 2 - 0.45);
fstep(s, 0.7 + fw + 0.66, fy, fw, fh, "2 · Validate", "Pull the same venue/year DOIs from Crossref; compare count and exact DOI set.");
arrow(s, 0.7 + 2 * fw + 0.74, fy + fh / 2 - 0.45);
fstep(s, 0.7 + 2 * fw + 1.32, fy, fw, fh, "3 · Reconcile", "Investigate every discrepancy by hand; OpenAlex as a third cross-check.");
card(s, 0.7, 4.0, 11.93, 2.2, CARD, BORDER);
s.addText([
  { text: "Why this validation holds up\n", options: { fontSize: 15, bold: true, color: TEALD, breakLine: true } },
  { text: "Crossref is the independent DOI registry that ACM deposits to — a different pathway from the web scrape — so agreement between the two catches both missed papers (scraper / pagination gaps) and spurious ones (editorials, front-matter). OpenAlex adds a third independent source, and quirky tracks (PACMHCI, biennial GROUP, ISS) were spot-checked by hand.", options: { fontSize: 14.5, color: INK } },
], { x: 0.95, y: 4.0, w: 11.4, h: 2.2, fontFace: BFONT, align: "left", valign: "middle", lineSpacingMultiple: 1.12, margin: 0 });

// ===========================================================================
// 4 — ABSTRACTS
// ===========================================================================
s = pres.addSlide();
s.background = { color: WHITE };
title(s, "Abstracts: OpenAlex API, GROBID fallback");
sub(s, "Clean, canonical abstract text — with a safety net when the API comes up empty.");
const aw = 5.5, ay = 1.95, ah = 2.1;
fstep(s, 0.7, ay, aw, ah, "Primary · OpenAlex API", "Query by DOI -> the publisher's canonical abstract. No PDF artifacts: no hyphenation breaks, header/footer noise, or two-column reflow errors.");
arrow(s, 0.7 + aw + 0.15, ay + ah / 2 - 0.45);
fstep(s, 0.7 + aw + 0.73, ay, aw, ah, "Fallback · GROBID", "If OpenAlex has no abstract for that DOI (or the call fails), parse the PDF and take the GROBID TEI <abstract> element.");
s.addText([
  { text: "Every record stores abstract_source (openalex / grobid), so the path is auditable.", options: { bullet: true, breakLine: true } },
  { text: "OpenAlex responses are cached on disk by DOI — re-runs never re-fetch, keeping the dataset reproducible.", options: { bullet: true } },
], { x: 0.8, y: 4.4, w: 11.7, h: 1.6, fontFace: BFONT, fontSize: 15, color: INK, align: "left", valign: "top", paraSpaceAfter: 10, margin: 0 });

// ===========================================================================
// 5 — METHODS ISOLATION
// ===========================================================================
s = pres.addSlide();
s.background = { color: WHITE };
title(s, "Isolating the methods section");
sub(s, "GROBID parses each PDF into TEI section headings; a lexicon/regex classifier tags every heading, then we slice the methods region verbatim.");
const lex = [
  ["methods", TEAL, "method(s), methodology, materials & methods, study / experimental / research design, procedure, participants, subjects, materials, apparatus, measures, stimuli, data collection, data analysis, recruitment, survey design, questionnaire, protocol, setup, conditions, user study, field study, evaluation, task(s), \"Study N\" / \"Experiment N\""],
  ["ends region", AMBER, "results, findings, discussion, limitations, conclusions, future work, acknowledgements, references, bibliography, appendix"],
  ["front", MUTE, "introduction, related work, background, motivation, prior work, literature review"],
];
let ly = 1.95; const lh1 = 1.05, lh2 = 0.62, lh3 = 0.62;
lex.forEach(([tag, color, terms], idx) => {
  const lh = idx === 0 ? lh1 : (idx === 1 ? lh2 : lh3);
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.7, y: ly, w: 1.7, h: 0.42, rectRadius: 0.06, fill: { color }, line: { color, width: 1 } });
  s.addText(tag, { x: 0.7, y: ly, w: 1.7, h: 0.42, fontFace: BFONT, fontSize: 12, bold: true, color: WHITE, align: "center", valign: "middle", margin: 0 });
  s.addText(terms, { x: 2.55, y: ly - 0.05, w: 10.1, h: lh, fontFace: BFONT, fontSize: 11.5, color: INK, align: "left", valign: "top", lineSpacingMultiple: 1.05, margin: 0 });
  ly += lh + 0.12;
});
card(s, 0.7, 4.62, 11.93, 0.72, CARD, BORDER);
s.addText([
  { text: "Region:  ", options: { bold: true, color: TEALD } },
  { text: "first methods heading -> first ends-region heading, sliced verbatim (numbered headings like \"3.1 Participants\" match; unusually-named subsections inside the run are kept).", options: { color: INK } },
], { x: 0.95, y: 4.62, w: 11.4, h: 0.72, fontFace: BFONT, fontSize: 13, align: "left", valign: "middle", lineSpacingMultiple: 1.05, margin: 0 });
card(s, 0.7, 5.5, 11.93, 1.15, NAVY, NAVY);
s.addText([
  { text: "Fallback:  ", options: { bold: true, color: TEAL } },
  { text: "low-confidence papers (no methods heading, region too short, multi-study truncation) are escalated — the whole paper's section list goes to a GPT model that picks the methods sections by index (it selects, never writes text). Fewer than ~10% reach the LLM.", options: { color: WHITE } },
], { x: 0.95, y: 5.5, w: 11.4, h: 1.15, fontFace: BFONT, fontSize: 13, align: "left", valign: "middle", lineSpacingMultiple: 1.08, margin: 0 });

// ===========================================================================
// 6 — NEXT STEPS
// ===========================================================================
s = pres.addSlide();
s.background = { color: WHITE };
title(s, "Next steps");
s.addText([
  { text: "Finish methods extraction across the full corpus", options: { bold: true, breakLine: true } },
  { text: "Run the GROBID + classifier pipeline over all ~16,000 papers, with LLM rescue on the flagged minority.", options: { breakLine: true, color: MUTE, fontSize: 14 } },
  { text: " ", options: { breakLine: true, fontSize: 8 } },
  { text: "Land the validated records (abstract + methods) in PostgreSQL, ready for the detection stages.", options: { bullet: true, breakLine: true } },
  { text: "Move into Stage 3: regex + NLP detection of online-survey usage — the first research question.", options: { bullet: true } },
], { x: 0.8, y: 2.0, w: 11.7, h: 4.0, fontFace: BFONT, fontSize: 17, color: INK, align: "left", valign: "top", paraSpaceAfter: 12, lineSpacingMultiple: 1.1, margin: 0 });

// ===========================================================================
// 7 — COMPUTE + EC2
// ===========================================================================
s = pres.addSlide();
s.background = { color: WHITE };
title(s, "Scaling up: from a laptop to AWS");
card(s, 0.7, 1.8, 5.85, 3.2, CARD, BORDER);
chip(s, 0.95, 2.05, 2.6, "The constraint", AMBER, AMBER);
s.addText([
  { text: "Local machine (4-core / 8 GB) — GROBID + ~16,000 PDFs is the bottleneck.", options: { bullet: true, breakLine: true } },
  { text: "A full extraction pass takes hours and ties up the machine.", options: { bullet: true } },
], { x: 1.0, y: 2.8, w: 5.3, h: 2.0, fontFace: BFONT, fontSize: 14.5, color: INK, align: "left", valign: "top", paraSpaceAfter: 10, margin: 0 });
card(s, 6.75, 1.8, 5.85, 3.2, CARD, BORDER);
chip(s, 7.0, 2.05, 2.0, "The plan", TEAL, TEAL);
s.addText([
  { text: "Migrate extraction to an AWS EC2 instance.", options: { bullet: true, breakLine: true } },
  { text: "More cores / RAM -> run many GROBID workers in parallel.", options: { bullet: true, breakLine: true } },
  { text: "Finish the corpus faster, and free up local compute.", options: { bullet: true } },
], { x: 7.05, y: 2.8, w: 5.3, h: 2.0, fontFace: BFONT, fontSize: 14.5, color: INK, align: "left", valign: "top", paraSpaceAfter: 10, margin: 0 });
card(s, 0.7, 5.3, 11.9, 1.0, CARD, BORDER);
s.addText("The pipeline is already built for this: resumable and circuit-breakered, so it can run unattended on a remote box and pick up exactly where it stopped.", { x: 0.95, y: 5.3, w: 11.4, h: 1.0, fontFace: BFONT, fontSize: 14.5, color: INK, align: "left", valign: "middle", lineSpacingMultiple: 1.05, margin: 0 });

// ===========================================================================
// 8 — INPUT WANTED
// ===========================================================================
s = pres.addSlide();
s.background = { color: NAVY };
s.addText("Where I'd value your input", { x: 0.7, y: 0.6, w: 12, h: 0.9, fontFace: HFONT, fontSize: 32, bold: true, color: WHITE, margin: 0 });
const asks = [
  ["Methods isolation", "Is the lexicon + GPT-fallback approach the best way to isolate the methods section, or is there a stronger method?"],
  ["Scope", "Should we also include the results / discussion sections, or keep the focus on methods?"],
  ["Next steps", "Does the sequencing (finish extraction -> detection) make sense, and what would you prioritize?"],
];
let ky = 1.95;
asks.forEach(([h, d]) => {
  s.addShape(pres.shapes.RECTANGLE, { x: 0.7, y: ky + 0.05, w: 0.12, h: 1.0, fill: { color: TEAL } });
  s.addText([
    { text: h + "  —  ", options: { bold: true, color: ICE } },
    { text: d, options: { color: WHITE } },
  ], { x: 1.0, y: ky, w: 11.5, h: 1.1, fontFace: BFONT, fontSize: 17, align: "left", valign: "middle", lineSpacingMultiple: 1.05, margin: 0 });
  ky += 1.35;
});
s.addText("Mahdi   ·   Who's Answering CHI?   ·   June 4, 2026", { x: 0.7, y: 6.85, w: 12, h: 0.4, fontFace: BFONT, fontSize: 12, color: MUTE, margin: 0 });

const out = process.argv[2] || "WhosAnsweringCHI_Deck_v2.pptx";
pres.writeFile({ fileName: out }).then(() => console.log("WROTE " + out));
