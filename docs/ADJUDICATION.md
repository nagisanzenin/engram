# Adjudicating the Gold Set — the contributor kit

Since v0.7 this repository has said, on every audit it prints, that its gold set is
**authored, not independently human-adjudicated**, and that getting *one human who is not
the author* through the 86 items is **the highest-value contribution anyone could make
here**. This document is the procedure that makes that work countable, and
`engram.py adjudication-stats` is the procedure in code.

**Why it matters, in one paragraph.** Engram's blind assessor grades every receipt; the
gold set is what grades the assessor. But the gold's adjudications were written by the
same person who wrote the grader's instructions — and six of them were *corrected after
the grader disagreed*. When the author concedes to the instrument, the agreement that
follows measures the author's willingness to concede, not the instrument's validity. That
circularity is disclosed on every audit and it does not go away by being disclosed
harder. It goes away when someone else reads the items.

---

## What you are being asked to do

Read up to 86 short learner answers. For each one, decide the grade an exam grader would
give it against the stated rubric:

| grade | when |
|---|---|
| `recalled` | every rubric criterion is met |
| `partial` | the core idea is present, one or more criteria missing |
| `lapsed` | the core is absent or wrong |

That is the whole task. **You are not grading the assessor, and you should not be shown
what it said** — you are producing an independent second reading of the same items.

**Time:** roughly 60–90 minutes. **You do not need to be a subject-matter expert in every
topic** — each item ships the canonical claim and the rubric that decides it.

---

## The protocol

### 1 · Get the items (answers stripped, as always)

```bash
python3 scripts/engram.py gold > items.json
```

Each item carries `sid`, `claim`, `rubric`, `probe`, `production`, `confidence`. It does
**not** carry `gold_grade`, `case_type`, or the author's rationale — by construction, so
your reading cannot be anchored by theirs. Do not go looking for them in the repo before
you finish; if you do, say so, and the run does not count as independent.

### 2 · Calibrate on the anchors, and pass the gate

Grade the **first 10 items** as your calibration set and mark them `"anchor": true`.
These are scored against the author's grades and **must reach ≥ 80% exact agreement**
before anything else you produce is scored.

This gate is not a hazing ritual. An untrained rater's disagreement is noise, and noise
published as *"the gold set is contested"* would be worse for this project than no
adjudication at all. If you fail it, read the rubrics again — particularly the rule that
*"cap at partial" is a ceiling, never a floor* — and retry. **Do not lower the bar to fit
the result**; the engine will not let you anyway.

### 3 · Grade the rest independently

One JSON object per item:

```json
[
  {"sid": "g_001", "grade": "partial", "anchor": true},
  {"sid": "g_011", "grade": "lapsed",  "anchor": false}
]
```

Save it as `gold/adjudications/<your-handle>.jsonl` (or anywhere — the path is yours).

### 4 · Score it

```bash
python3 scripts/engram.py adjudication-stats --file gold/adjudications/<you>.jsonl --rater "@you"
```

The engine computes, over your non-anchor items only:

- **exact agreement** — reported, never quoted alone (it overstates chance-corrected
  agreement by 34–41 points in the measured literature)
- **QWK** — quadratic weighted kappa against the authored gold
- **Krippendorff's α (ordinal)** with a bootstrap 95% CI — the statistic an outside reader
  of this repo will expect, published *with its spread*, because a point estimate from 86
  items quoted without its interval is a label lying about its own precision
- **direction** — how often you were *stricter* than the author vs *more lenient*, because
  a mean near zero is also what "disagrees in both directions" looks like
- **the confusion matrix**

### 5 · Read the verdict against thresholds fixed in advance

| α | verdict | what it means |
|---|---|---|
| **≥ 0.80** | `corroborated` | an outside rater independently agrees. The circularity caveat can finally name a corroboration and its α. |
| **0.667 – 0.80** | `tentatively-corroborated` | usable for tentative conclusions only; every disagreement should be adjudicated before any badge language changes. |
| **< 0.667** | `contested` | you and the author do not agree. **This is a real finding about the instrument, not a failure of the rater** — and it is published exactly as loudly as a good result would be. |

**One external rater CORROBORATES the authored gold. It never replaces it.** Replacing the
author would take **two independent externals who agree with each other** at α ≥ 0.80, and
until that exists the engine keeps printing the circularity caveat — with your α beside it
rather than instead of it.

### 6 · Disagreements

For every item where you and the author differ, write one line on *which rubric criterion
decides it and why*. Then:

- If discussion resolves it, the gold is corrected and the item carries a `disputed`
  record with its original grade — corrections are **auditable, never laundered**.
- If it does not resolve, the item is marked **contested and excluded from the audit
  denominator**, and that exclusion is stated. Two such items are already left in on
  purpose: *an instrument with no disagreement left in it measures nothing.*

**Only pre-adjudication numbers count as independent agreement.** Both are published.

---

## What happens to your work

Your file, your α, your disagreements, and your handle go into the repository, and the
grader-audit section of the README stops saying *"nobody has checked this"*. If your
numbers are bad for the project, they are published unchanged — a project whose entire
thesis is honest measurement does not get to hide its own worst measurement.

For context on what to expect from yourself: trained human raters on 5-point writing
rubrics average roughly **60% exact agreement and QWK ≈ 0.65** against each other. Perfect
agreement is not the target and would in fact be suspicious. Honest disagreement, written
down, is the deliverable.
