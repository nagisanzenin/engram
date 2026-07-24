# The Problem Grammar (read when a node carries `kind: "procedure"` — surfaced as `node_kind` in due payloads)

Activates **per node**, only where the architect declared a skill executed on instances —
any domain; concepts and facts keep the ordinary grammar untouched. Theory: `docs/11`.
Every dialogue-grammar rule still binds — confidence integrity, stash-immediately, menus-
never-for-knowledge, the oath. This file changes only *what the practice act is*.

## Encoding a procedure node (replaces beats 2–4; beats 1, 5–6, 8 unchanged)

The **ladder** — worked example → solving, faded by measured competence, never by vibes:

- **L1 · worked example.** Show a complete worked solution to ONE instance (the node's
  `probe` is the canonical instance). Before each step is revealed, the learner predicts
  the next move; after it, they explain *what licenses it*.
- **L2 · completion.** A fresh instance, worked until the last step(s); the learner
  executes the ending.
- **L3 · faded.** A fresh instance with the *principle-bearing* interior step blank — fade
  the step that carries the idea, not the arithmetic.
- **L4 · cold solve.** A fresh instance, nothing given.

**Rung selection** = the worked-drive signals (docs/06): failed/skipped pretest or weak
`requires` → start L1; comfortable prior exposure → start L3. A lapse drops one rung on the
next instance; a clean solve climbs. Never hold a competent learner at L1 — assistance
flips harmful with expertise — **and when the signals are ambiguous, start one rung lower:
the measured asymmetry favors assisting.** The concept node that *licenses* a procedure
keeps the native PREDICT→STRUGGLE opening; the ladder is for the skill nodes.

**VERIFY changes its production, not its flow:** confidence pick → stash, exactly as beat 7
orders — but the production is a **fresh-instance solve** at the highest rung reached,
never the canonical `probe` instance (its solution was just displayed; re-serving it grades
answer-recall). Stash their steps verbatim; note omissions factually.

## Fresh instances (the algorithmic-variant rule)

- **The unit of novelty is the ALGORITHMIC VARIANT: new values, same structure and cover
  story** — the configuration where solving measurably beats re-studying at a delay. Do not
  wander the cover story at reviews: far-transfer clothing is the `transfer_probe`'s job,
  at maturity. Never re-serve the stored numbers verbatim.
- **Compute the answer key by EXECUTION before serving — and never surface the key or the
  check beside the problem.** Run the arithmetic/code quietly (a wrong key becomes a false
  lapse on the learner's schedule; generated problems carry a real wrong-key rate even in
  execution-checked pipelines). Use the frame's `verify` when it says how. If execution is
  impossible — content not executable, or your platform has no execution tool — solve the
  instance fully in private notes before serving and write `unverified-by-execution` into
  the rating's notes.
- **Stay inside the frame's bounds** — they hold difficulty roughly fixed, and text-judged
  difficulty is unreliable. If the learner's lapse pattern says instances drift hard, say
  so and regenerate closer to the canonical instance.

## The discrimination beat (interleaving's active ingredient)

When a due procedure node's `practice.discriminates_from` sibling is also due (or mature),
serve the confusable items **adjacently in the same session** — juxtaposition carries the
effect; scattering forfeits it — and open with the **naming step**: *"which technique
applies here, and what in the problem tells you?"* — then the solve. Never a menu (it is
knowledge). **Until the naming step is answered, the progress marker shows the topic, not
the node id** — `[3/6] · u-substitution` answers the question for them.

## Grading a procedure production (tutor at /review; assessor everywhere else)

**Order:** the confidence pick comes first, always — execution checks are correctness
signals, so run them only *after* the pick, then locate the controlling error. Verify the
answer and every checkable intermediate by execution; **learner-derived expressions reach
the interpreter via stdin or a file, never inlined into a `-c` command line** (the shell-
safety oath applies to arithmetic too).

| Observed | grade | rating | `--error-class` |
|---|---|---|---|
| Method right, execution right | `recalled` | `good`/`easy` | — |
| Method right, arithmetic/transcription slip only | `partial` | `hard` | `slip` |
| **Right answer, wrong/absent method** | at best `partial` | `hard` | `conceptual` |
| Method wrong or missing, wherever the answer landed | `lapsed` | `again` | `conceptual` |

**Tiebreak when rows 3–4 both match, and it applies ONLY when the final answer is right:**
≥1 rubric criterion genuinely met → `partial` (row 3 outranks); zero criteria met →
`lapsed` — an answer with no work meets no criterion.

**⚠ Counting criteria never overrides a wrong core.** That tiebreak is not a general rule.
**When the final answer is wrong, or when the criterion that failed IS the node's central
claim, the grade is `lapsed` however many peripheral criteria were met.** Setting up
correctly and then blowing the defining step is a lapse, not a partial — the claim is what
is being tested, and credit for scaffolding does not buy credit for the thing itself. (This
is measured, not theoretical: a grader awarded `partial` for "u/dv chosen correctly" on an
integration-by-parts answer whose *formula sign* was wrong and whose result was therefore
wrong. **You are the grader for every procedure review, and only a sampled audit ever
second-guesses you** — `/review` §3 escalates any `partial` to the blind assessor, and
`stats.self_grading` reports which direction you differ in — so read this rule as written.) A slip is never logged as a misconception; a
*recurring* slip pattern is its own entry. Torn between `slip` and `conceptual` →
`conceptual`: "you just slipped" is the flattering direction, and the schedule cannot
afford flattery.

## The erroneous-example rung (after instruction, scaffolded, never a default)

Never before the node's RESOLVE. After instruction, any learner may get one, **always as
find → explain → fix with feedback** (the scaffolding is what removed the prior-knowledge
gate in the replication evidence): one seeded bug — from `practice.error_bank` or, better,
the learner's own misconception log. Grade the find-and-fix as an ordinary production.
Expect the payoff on *later* reviews, and expect the moment to feel worse than it works —
frame it, and never stack two in a session. It is the preferred re-encode on a second
lapse. A repair tool, not a diet: on average performance, correct examples beat
error-seeded ones.

In Sprint mode, one procedure item is a full session; the two-minute floor and mode budget
outrank completeness, as everywhere in Engram.
