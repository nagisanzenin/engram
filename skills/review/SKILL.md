---
name: review
description: Clear due memory reviews with free recall — the two-minute habit that makes learning permanent. Use when reviews are due, or the user wants to review, practice, or "do my engram reviews".
argument-hint: [quick | <topic>]
---

# /review — the retention loop

Read `skills/_shared/dialogue-grammar.md` (hard rules, confidence integrity, park-and-resume, and the rating map apply here verbatim). Set:

```bash
# Resolve the engine. RUN THIS BLOCK VERBATIM — do not substitute a path you guessed.
for d in "$OPENCODE_PLUGIN_ROOT" "$CLAUDE_PLUGIN_ROOT" "$CODEX_PLUGIN_ROOT" "$ENGRAM_ROOT" \
         "${OPENCLAW_STATE_DIR:-$HOME/.openclaw}/extensions/engram" \
         "$HOME/.gemini/config/plugins/engram" \
         "$PWD" "$(git rev-parse --show-toplevel 2>/dev/null)"; do
  [ -n "$d" ] && [ -f "$d/scripts/engram.py" ] && ENGRAM="$d/scripts/engram.py" && break
done
[ -n "$ENGRAM" ] || echo "engram: engine not found — set ENGRAM_ROOT to your engram checkout" >&2
```

If none are set, resolve the plugin root as the directory containing `.claude-plugin/plugin.json` (or `.codex-plugin/plugin.json`). **Never inline a learner's answer into a shell command** — pass productions via `--production-file` (or `--production-file -` on stdin); a stray quote or `$(…)` in what they typed would otherwise execute.

**Spawning agents.** "Spawn **engram-…**" means a *fresh-context* child running that agent's definition — via your platform's subagent/Task tool (the type may be namespaced, e.g. `engram:engram-assessor`). **If your only mechanism is a generic `sessions_spawn`, read `skills/_shared/subagents.md` first.**

## 1 · Load the queue

```bash
python3 "$ENGRAM" session-start   # what the ambient hook ALREADY told them (read-only)
python3 "$ENGRAM" stash count     # a previous session's ungraded work?
python3 "$ENGRAM" due --cap <cap>
```

If stash > 0, settle it first (assessor → `receipt` → `stash clear`, per /learn step 4) with one explanatory line. Caps: `quick` → 5 items; otherwise mode default (Standard ≈ 12). `--topic <t>` if the user named one, but note interleaving across topics is the default *on purpose* — don't undo it for tidiness. Open with the session ticket. Empty queue → one line of honest celebration, then stop (suggest `/learn continue` only if a topic has frontier nodes). Never invent reviews.

**`--cap` picks WHICH items, and it is not the order Engram used to serve (v1.3).** A capped session is a triage decision: with `--cap` the engine ranks by *expected 30-day retention saved per expected minute* and returns `{order, order_basis, items}` (the older `--limit` still returns a bare list in the old most-overdue-first order). Two things to carry into the session, both already in the payload:

- **Say nothing about the ordering unless asked** — it is plumbing, not a lesson. If asked, the honest line is in `order_basis`: it is *model-derived* (an FSRS projection), backed by one strong human RCT for the policy family and by simulations, and **no human RCT has ever ranked backlog orders**. Never present it as proven.
- **Never quote `expected_minutes` as a session estimate.** It is a ranking weight (a cold item is priced as slower), and it disagrees with the ~0.6 min/item the hook and `decay` use *on purpose*. When you need to say how long something takes, use `decay`'s `minutes` or the hook's — one figure to the learner, always.
- **Items flagged `effectively_relearn: true` are functionally re-learns, not reviews.** They sort last on purpose and they lose almost nothing more by waiting. Name them once at the close rather than burning the cap on them: *"three of these are past the point of a quick review — they'd want a re-derivation. Want them in a longer session, or shall I retire any?"*

**Return-after-absence (the amnesty protocol — the highest-evidence Layer 2 move; `docs/05-affective-layers.md` P14).** Fires when `due > 2× the mode cap`, **or** when `adherence.return.days_since_last_session ≥ 7` (the engine's own constant — the same one the hook's amnesty and decay lines use; don't invent a different threshold), **or** when the loop has never closed. Then do **not** dump the debt.

> **The hook already spoke, and it spoke first.** On the same trigger, `session-start` has printed — in this order — amnesty, their plan, and the decay cost, *before the learner typed anything*. **Run `python3 "$ENGRAM" session-start` yourself in step 1** (it is read-only, stateless, and safe to re-run) so you can see what they already read, then **do not repeat any of those three lines.** Your amnesty is a re-frame only if they haven't just read one; repeated, it is padding, and repeating the plan line is exactly the "never twice, never as leverage" the protocol forbids. This is the #1 SRS churn trigger, and a wall of overdue reviews reliably makes people quit (Silverman & Barasch 2023; a single missed day does not actually harm memory — Lally 2010). Instead, one calm line of amnesty + load renegotiation, then a real choice:
- Frame it as normal, owed nothing: *"You've got 40 due after the break — that's just spacing doing its job, not a debt. FSRS handles backlog fine."*
- **Show their own plan back, once, if they have one** (`model` → `settings.commitment`): *"your plan was: when I open the terminal in the morning — I clear one review."* Their sentence, verbatim, no commentary, no "so let's stick to it." It is a reminder of what *they* decided, and it is the highest-evidence thing in this protocol (re-prompting a stated plan is exactly what the RCTs tested). Then move on — never twice, never as leverage.
- Offer (arrow-key): **clear a capped set today** (this mode's cap — recommended) / **a longer catch-up** (`--cap` at ~2× the mode cap; an over-cap clamps to the queue, so it is always safe) / **just one topic** (`--topic <t>`; **drop this option entirely when there is only one topic** — it is identical to the others and reads like a glitch). Never a marathon; the two-minute floor is a floor, not a target.
- Then run only the chosen cap (`due --cap <n>`). What's left stays due and un-guilted. Zero shame in either the offer or the close.
- **`retire` belongs in this conversation, and only here** (v1.3): when the queue is genuinely stale — a topic they've moved on from, a node that no longer matters — offer it plainly: *"anything here you'd rather take off the list? `retire` keeps it in your history, out of your queue."* Then `python3 "$ENGRAM" retire --topic <t> [--node <n>]` (reversible: `--restore`). **You never name which nodes to retire.** Auto-suggesting the ones they keep failing is a flattering denominator wearing a helpful face; the learner decides, the engine records and counts (retired items stay visible in `adherence` and `retention.unmeasured`).

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

The `due` payload gives you `probe`, `claim` (canonical answer), and `rubric` — plus `node_kind` and `practice` (v1.1). Show a progress marker per item: `[3/6] · residual-stream †`. The order of operations is sacred:

**`node_kind: "procedure"` items first take a detour** (Read `skills/_shared/problem-grammar.md` once per session when one appears): serve a **fresh algorithmic variant** generated from `practice.problem_frame` — new values, same structure and cover story; never the stored numbers, and never a re-clothed isomorph (that is `transfer_probe`'s job) — computing the answer key by execution before showing anything. When a `practice.discriminates_from` sibling is co-due (or mature), serve the pair **adjacently** and open with the naming step ("which technique, and why?") — and until it's answered, the progress marker shows the topic, never the node id (the id would answer the question). Grade the solve with the problem grammar's table — method-wrong caps the grade regardless of the answer; a slip-only miss is `partial`/`hard` with `--error-class slip`, a wrong-method one carries `--error-class conceptual`. A procedure node with no usable `practice` falls back to the stored probe, concept-style. Everything below (confidence pick, stash-or-rate flow, transfer, momentum) applies unchanged.

1. Show the **probe only**. Free recall — no options, no hints in the prompt, no "remember when we...". Do **not** ask them to type a confidence number.
2. They produce. (Silence is fine; "no idea" is an answer — treat as lapse, warmly.) **Then collect confidence by calling `AskUserQuestion` (the four-band Confidence picker — exact call in grammar ⚠), BEFORE the reveal.** Skip only if they volunteered a number unprompted; "Other"→exact number; dismiss/skip → null, never estimated.
3. Reveal: canonical `claim` + a one-line gap analysis against `rubric` — specific, about the work. If they gave consequence-only, run the terse-production move (one "and the mechanism?" — grammar file) *before* the reveal. (Confidence picker, if any, comes first — sureness before feedback.)
4. Map to a rating with the shared table (round down when torn) and commit **immediately**. Pass the learner's answer via a file (write it, then reference it) so their text never lands on the command line:

```bash
python3 "$ENGRAM" rate --topic <t> --node <n> --rating <r> --confidence <c-or-omit> \
  --grade <g> --production-file <tmp-answer.txt> --kind review --source self
# procedure items only: append --error-class slip|conceptual per the problem-grammar
# table (omit the flag entirely on concept/fact items and on recalled grades).
# If the engine rejects --error-class (an older engine than these skills), RETRY the
# same command without the flag — the rating must never be lost to a version skew.
```

Relay the returned due date in passing, not ceremonially ("back in 12 days"). **When the `rate` output's durability crosses a threshold** (first reps, or `s_after` clearing ~7 or ~30 days, or roughly a doubling — a milestone, not every review; grammar file, Pillar 13), add *one* flat growth line — *"that jumped from ~4 days to ~17; it'll hold now."* A mature node creeping up says nothing new — stay silent; a `hard`/`again` gets honest task-feedback, never a manufactured win; silent too if `settings.momentum` = `off`.

**If the item comes back `lapsed` (concept/fact): do not move on.** Run the criterion loop in the dialogue grammar — grade it, re-derive, put another item in between, then re-ask, up to 3 passes, stopping at one clean recall. Rate re-attempts with `--relearn --attempt <n>`; they record the loop and change no schedule. The mode budget still outranks the criterion.

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
- **First lapse on a topic, once ever** — if they say anything about the habit not sticking, one flat line and nothing more: *"habits like this typically take about two months to feel automatic, the range is huge, and single misses genuinely don't matter."* (Lally 2010; PNAS 2023.) **Never a day count, never a countdown, never "you're on day 12"** — the constant does not exist, and a countdown is a streak with better manners.
- **Second+ lapse on the same node** (`lapses ≥ 2` in payload) — the encoding failed, not their memory. After rating, re-encode *differently*: new analogy (use their interests), a contrast case, or an explorable — and on a **procedure** node, prefer a find-explain-fix erroneous example (problem grammar). The payload's `artifact` flag tells you which case you're in: `true` → the *current explorable also isn't holding* — offer to regenerate it differently (spawn **engram-artifact-smith** in the background with the node's current state + open misconceptions; it re-registers on completion; hand off at the close, never mid-queue); `false` → offer to build one (same background spawn) if `settings.artifacts` ≠ `off` or the learner asks. Say the move plainly either way: "this card keeps dying, so we're changing the card, not blaming you."
- **Instant + correct + low confidence** — note it aloud; their calibration data will show it at `/coach`.

## 3 · Assessor audit (keep self-grading honest)

If the session had ≥8 items, any disputed grade, or **any `partial`** (v1.4 — the mid-band is where graders measurably diverge, so it is oversampled on purpose): stash `{topic, node, probe, claim, rubric, production, confidence, kind:"audit", tutor_rating:"<r>"}` (plus `node_kind:"procedure"` on procedure items, so the auditor step-grades) (the engine mints the `sid`; the assessor must return it) for each such item, then spawn **engram-assessor** on `stash list` for an audit verdict, and `stash clear` after.

**Then PERSIST the verdict — it is evidence, not conversation (v1.4).** For each audited item:

```bash
python3 "$ENGRAM" rate --topic <t> --node <n> --kind audit \
  --rating <the ASSESSOR's rating> --audited-rating <what YOU committed> \
  --grade <assessor grade> --production-file <tmp-answer.txt>
```

This writes an `audit` receipt and **changes nothing else** — no FSRS state, no due date, no `reps`. Audits inform; they never reschedule (re-rating an item the learner already acted on would let a second opinion silently rewrite their schedule). The receipts feed `stats.self_grading`: how often the tutor agrees with the blind assessor, and **in which direction it differs** — the only measurement of the one grader `/coach audit` cannot reach, since the tutor grades in-context with the dialogue in front of it. Report disagreements to the learner; do **not** re-rate committed items. Disputes from the learner: same path, once.

## 4 · Close

```bash
python3 "$ENGRAM" log-session --kind review --mode <mode> --minutes <est> --items <n>
python3 "$ENGRAM" stats
```

Close with the **receipt strip**: items → outcomes, streak, one meaningful number (e.g., month-bucket recall rate), next due date. Prefer a **momentum** number from `stats.momentum` as that meaningful number when there was real growth — *"+31 days of durability added this week"* or *"most durable now: residual-stream, 42 days"* — informational, never a score (Pillar 13). If the queue was large and they stopped early — fine, say what's left, zero guilt. The two-minute floor exists to protect the habit, not to grow the session.
