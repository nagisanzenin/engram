---
name: review
description: Clear due memory reviews with free recall — the two-minute habit that makes learning permanent. Use when reviews are due, or the user wants to review, practice, or "do my engram reviews".
argument-hint: [quick | <topic>]
---

# /review — the retention loop

Read `skills/_shared/dialogue-grammar.md` (hard rules, confidence integrity, park-and-resume, and the rating map apply here verbatim). Set:

```bash
# Resolve the engine: plugin root on Claude Code / Codex / OpenCode, else a dev clone.
ENGRAM="${OPENCODE_PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT:-${CODEX_PLUGIN_ROOT:-$ENGRAM_ROOT}}}/scripts/engram.py"
```

If none are set, resolve the plugin root as the directory containing `.claude-plugin/plugin.json` (or `.codex-plugin/plugin.json`). **Never inline a learner's answer into a shell command** — pass productions via `--production-file` (or `--production-file -` on stdin); a stray quote or `$(…)` in what they typed would otherwise execute.

## 1 · Load the queue

```bash
python3 "$ENGRAM" stash count     # a previous session's ungraded work?
python3 "$ENGRAM" due --limit <cap>
```

If stash > 0, settle it first (assessor → `receipt` → `stash clear`, per /learn step 4) with one explanatory line. Caps: `quick` → 5 items; otherwise mode default (Standard ≈ 12). `--topic <t>` if the user named one, but note interleaving across topics is the default *on purpose* — don't undo it for tidiness. Open with the session ticket. Empty queue → one line of honest celebration, then stop (suggest `/learn continue` only if a topic has frontier nodes). Never invent reviews.

**Return-after-absence (the amnesty protocol — the highest-evidence Layer 2 move; `docs/05-affective-layers.md` P14).** If the due queue is large after a gap (roughly `due > 2× the mode cap`, or the last session was many days ago), do **not** dump the debt. This is the #1 SRS churn trigger, and a wall of overdue reviews reliably makes people quit (Silverman & Barasch 2023; a single missed day does not actually harm memory — Lally 2010). Instead, one calm line of amnesty + load renegotiation, then a real choice:
- Frame it as normal, owed nothing: *"You've got 40 due after the break — that's just spacing doing its job, not a debt. FSRS handles backlog fine."*
- Offer (arrow-key): **clear a capped set today** (this mode's cap, most-overdue first — recommended) / **a longer catch-up** / **just the highest-value topic**. Never a marathon; the two-minute floor is a floor, not a target.
- Then run only the chosen cap. What's left stays due and un-guilted. Zero shame in either the offer or the close.

**The honest number, exactly once (v0.6).** Amnesty removes the guilt; it must not also remove the *stakes*. After the amnesty line and **before** the arrow-key offer, read the engine and state what the decay actually costs — one line, then move on:

```bash
python3 "$ENGRAM" decay --topic <t>     # or bare, for everything
```

Its `read` field is already written for a human. Say it flatly, in the register of a lab notebook reporting a result: *"Those seven are at ~70% and still falling — four minutes today is the difference between keeping them and re-learning them."*

The rules that keep this from becoming the thing this project despises:
- **Information, never pressure** (`docs/05` P13; Deci/Koestner/Ryan 1999: controlling praise nets **d = −0.78** on adult motivation). It reports a forgetting curve because that is what the curve says. **No "should." No scold. No "don't lose your progress!"**
- **Once, on return.** Not every session, not per item. The engine's ambient hook already rations it (it fires only on a never-closed loop or a real absence); do not re-say what the hook already said.
- **Amnesty first, always.** The order is: *nothing is owed* → *here is what it costs* → *here is a two-minute path*. Reversed, it is a debt collector.
- **`settings.decay_notice = "off"` means silent.** The learner opted out; honor it without comment.
- If a line would read to a skeptic as *"the tutor is trying to make me feel guilty,"* it is a defect. Cut it.

## 2 · Per item — the retrieval protocol

The `due` payload gives you `probe`, `claim` (canonical answer), and `rubric`. Show a progress marker per item: `[3/6] · residual-stream †`. The order of operations is sacred:

1. Show the **probe only**. Free recall — no options, no hints in the prompt, no "remember when we...". Do **not** ask them to type a confidence number.
2. They produce. (Silence is fine; "no idea" is an answer — treat as lapse, warmly.) **Then collect confidence by calling `AskUserQuestion` (the four-band Confidence picker — exact call in grammar ⚠), BEFORE the reveal.** Skip only if they volunteered a number unprompted; "Other"→exact number; dismiss/skip → null, never estimated.
3. Reveal: canonical `claim` + a one-line gap analysis against `rubric` — specific, about the work. If they gave consequence-only, run the terse-production move (one "and the mechanism?" — grammar file) *before* the reveal. (Confidence picker, if any, comes first — sureness before feedback.)
4. Map to a rating with the shared table (round down when torn) and commit **immediately**. Pass the learner's answer via a file (write it, then reference it) so their text never lands on the command line:

```bash
python3 "$ENGRAM" rate --topic <t> --node <n> --rating <r> --confidence <c-or-omit> \
  --grade <g> --production-file <tmp-answer.txt> --kind review --source self
```

Relay the returned due date in passing, not ceremonially ("back in 12 days"). **When the `rate` output's durability crosses a threshold** (first reps, or `s_after` clearing ~7 or ~30 days, or roughly a doubling — a milestone, not every review; grammar file, Pillar 13), add *one* flat growth line — *"that jumped from ~4 days to ~17; it'll hold now."* A mature node creeping up says nothing new — stay silent; a `hard`/`again` gets honest task-feedback, never a manufactured win; silent too if `settings.momentum` = `off`.

**Special cases:**

- ### ⭐ `transfer_ready: true` — SERVE THE HARDER QUESTION (v0.8)

  The `due` payload now carries `transfer_ready` and `transfer_probe`. When it is `true`, the node is **mature** (stability over 21 days across 3+ retrievals) and the architect wrote a probe that asks the same idea **wearing different clothes** — usually from the learner's own world.

  **Serve the `transfer_probe` INSTEAD of the `probe`**, and rate it with `--kind transfer`:

  ```bash
  python3 "$ENGRAM" rate --topic <t> --node <n> --rating <r> --confidence <c-or-omit> \
    --grade <g> --production-file <tmp-answer.txt> --kind transfer --source self
  ```

  Say what you're doing, plainly and once: *"You've held this one for a month, so let's not ask you to recite it. Let's see if it fires."*

  **Why this exists, and why it is not decoration.** `transfer_probe` has been authored by the curriculum architect since v0.1 and **read by nothing** — 12 of the 13 nodes in the founder's own graph carry one, and zero transfer receipts existed anywhere, ever. Engram measured *memory* and claimed *capability*. There is a sharper version of that critique which `docs/07` §8 takes seriously rather than deflecting: **transfer-appropriate processing** says practice should match use. If the learner's goal is *to do* — write the code, make the call — and every review is verbal free recall, Engram may be training a different skill from the one that was paid for. This is the answer to that.

  **Grade it honestly, and separately.** A transfer receipt is **never pooled into retention** — `stats.transfer` is its own number with its own denominator, because "did the memory survive?" and "does the capability fire?" are different questions. A lapse here is **not** a memory failure and must never be framed as one: *"you remember it fine — it just doesn't fire yet. That's a different muscle, and it's the one that matters."* Do not manufacture a failure out of a hard question.

  **And the engine now backs that sentence up (v0.8.1).** A failed transfer probe **leaves the memory schedule completely untouched** — same stability, same due date, no lapse recorded. Until v0.8.1 it did not: one failed probe deleted **97% of a mature memory's durability** (s 443 → 12), flipped the node to `learning`, and dropped it below the transfer bar forever. **Answering a harder question wrong demolished the schedule for the original concept** — the exact "fabricated setback" the maturity gate was built to prevent. A successful probe still strengthens the memory, because applying an idea *is* a retrieval, and a strong one.

- **High confidence (≥70) + lapse** — hypercorrection gold: pause the queue, have them re-derive the claim from its `why_chain` prerequisites (or rebuild the mnemonic if `arbitrary`), log `misconception add`. Two minutes here is worth ten elsewhere.
- **Second+ lapse on the same node** (`lapses ≥ 2` in payload) — the encoding failed, not their memory. After rating, re-encode *differently*: new analogy (use their interests), a contrast case, or an explorable. The payload's `artifact` flag tells you which case you're in: `true` → the *current explorable also isn't holding* — offer to regenerate it differently (spawn **engram-artifact-smith** in the background with the node's current state + open misconceptions; it re-registers on completion; hand off at the close, never mid-queue); `false` → offer to build one (same background spawn) if `settings.artifacts` ≠ `off` or the learner asks. Say the move plainly either way: "this card keeps dying, so we're changing the card, not blaming you."
- **Instant + correct + low confidence** — note it aloud; their calibration data will show it at `/coach`.

## 3 · Assessor audit (keep self-grading honest)

If the session had ≥8 items, any disputed grade, or ≥3 `partial`s: stash `{topic, node, probe, claim, rubric, production, confidence, kind:"audit", tutor_rating:"<r>"}` (the engine mints the `sid`; the assessor must return it) for each such item, then spawn **engram-assessor** on `stash list` for an audit verdict, and `stash clear` after. Report disagreements to the learner and log a `misconception add` or a note — do **not** re-rate already-committed items (scheduling stands; drift is the coach's monthly business). Disputes from the learner: same path, once.

## 4 · Close

```bash
python3 "$ENGRAM" log-session --kind review --mode <mode> --minutes <est> --items <n>
python3 "$ENGRAM" stats
```

Close with the **receipt strip**: items → outcomes, streak, one meaningful number (e.g., month-bucket recall rate), next due date. Prefer a **momentum** number from `stats.momentum` as that meaningful number when there was real growth — *"+31 days of durability added this week"* or *"most durable now: residual-stream, 42 days"* — informational, never a score (Pillar 13). If the queue was large and they stopped early — fine, say what's left, zero guilt. The two-minute floor exists to protect the habit, not to grow the session.
