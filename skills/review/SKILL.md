---
name: review
description: Clear due memory reviews with free recall — the two-minute habit that makes learning permanent. Use when reviews are due, or the user wants to review, practice, or "do my engram reviews".
argument-hint: [quick | <topic>]
---

# /review — the retention loop

Read `skills/_shared/dialogue-grammar.md` (hard rules, confidence integrity, park-and-resume, and the rating map apply here verbatim). Set:

```bash
ENGRAM="${CLAUDE_PLUGIN_ROOT:-${ENGRAM_ROOT:-$HOME/Documents/Github/engram}}/scripts/engram.py"
```

## 1 · Load the queue

```bash
python3 "$ENGRAM" stash count     # a previous session's ungraded work?
python3 "$ENGRAM" due --limit <cap>
```

If stash > 0, settle it first (assessor → `receipt` → `stash clear`, per /learn step 4) with one explanatory line. Caps: `quick` → 5 items; otherwise mode default (Standard ≈ 12). `--topic <t>` if the user named one, but note interleaving across topics is the default *on purpose* — don't undo it for tidiness. Open with the session ticket. Empty queue → one line of honest celebration, then stop (suggest `/learn continue` only if a topic has frontier nodes). Never invent reviews.

## 2 · Per item — the retrieval protocol

The `due` payload gives you `probe`, `claim` (canonical answer), and `rubric`. Show a progress marker per item: `[3/6] · residual-stream †`. The order of operations is sacred:

1. Show the **probe only**. Free recall — no options, no hints in the prompt, no "remember when we...". Ask for **confidence in the same breath**: *"answer + gut 0–100."*
2. They produce. (Silence is fine; "no idea" is an answer — treat as lapse, warmly.) No number after one casual retry → confidence is null, never estimated.
3. Reveal: canonical `claim` + a one-line gap analysis against `rubric` — specific, about the work. If they gave consequence-only, run the terse-production move (one "and the mechanism?" — grammar file) *before* the reveal.
4. Map to a rating with the shared table (round down when torn) and commit **immediately**:

```bash
python3 "$ENGRAM" rate --topic <t> --node <n> --rating <r> --confidence <c-or-omit> \
  --grade <g> --production "<their answer, trimmed>" --kind review --source self
```

Relay the returned due date in passing, not ceremonially ("back in 12 days").

**Special cases:**
- **High confidence (≥70) + lapse** — hypercorrection gold: pause the queue, have them re-derive the claim from its `why_chain` prerequisites (or rebuild the mnemonic if `arbitrary`), log `misconception add`. Two minutes here is worth ten elsewhere.
- **Second+ lapse on the same node** (`lapses ≥ 2` in payload) — the encoding failed, not their memory. After rating, re-encode *differently*: new analogy (use their interests), a contrast case, or flag for an artifact next `/learn`. Say that plainly: "this card keeps dying, so we're changing the card, not blaming you."
- **Instant + correct + low confidence** — note it aloud; their calibration data will show it at `/coach`.

## 3 · Assessor audit (keep self-grading honest)

If the session had ≥8 items, any disputed grade, or ≥3 `partial`s: stash `{topic, node, probe, claim, rubric, production, confidence, kind:"audit", tutor_rating:"<r>"}` for each such item, then spawn **engram-assessor** on `stash list` for an audit verdict, and `stash clear` after. Report disagreements to the learner and log a `misconception add` or a note — do **not** re-rate already-committed items (scheduling stands; drift is the coach's monthly business). Disputes from the learner: same path, once.

## 4 · Close

```bash
python3 "$ENGRAM" log-session --kind review --mode <mode> --minutes <est> --items <n>
python3 "$ENGRAM" stats
```

Close with the **receipt strip**: items → outcomes, streak, one meaningful number (e.g., month-bucket recall rate), next due date. If the queue was large and they stopped early — fine, say what's left, zero guilt. The two-minute floor exists to protect the habit, not to grow the session.
