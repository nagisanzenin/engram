# Engram

> A learning system for Claude Code that builds durable knowledge, not the feeling of it.

**Engram** (working title¹) is a Claude Code plugin that turns the agent and everything it can produce — dialogue, code, markdown, interactive HTML — into a complete, evidence-based learning system. It teaches anything, verifies understanding the way a compiler verifies code, schedules memory like an engineer schedules maintenance, and fits itself to the individual learner from measured outcomes rather than folk taxonomy.

It is inspired architecturally by [claude-code-production-grade-plugin](https://github.com/nagisanzenin/claude-code-production-grade-plugin): its oracle-driven loops, receipt enforcement, and re-anchoring patterns are transplanted here from software verification to *learning verification*. The learner's claim "I get it" is never the oracle. Retrieval, application, and transfer under test conditions are.

---

## The four pillars

Everything in this system hangs on four load-bearing principles, each backed by the strongest evidence in cognitive science (full citations in [docs/01-foundations.md](docs/01-foundations.md)):

| Pillar | What it does | Core science |
|---|---|---|
| **1. Structure** | Decompose any subject into a first-principles DAG: claims linked by *chains of necessity* ("why must this be true?"), prerequisites made explicit, arbitrary facts flagged as arbitrary. | Schema theory (Ausubel), knowledge spaces (Doignon & Falmagne → ALEKS), elaborative interrogation, threshold concepts |
| **2. Encoding** | First contact with every idea is *generative*: predict before reveal, derive before read, manipulate before memorize. Interactive HTML explorables are a first-class medium, governed by a strict anti-passivity contract. | Generation effect, self-explanation (Chi), ICAP (Chi & Wylie), dual coding (Paivio), multimedia principles (Mayer), prediction-error learning |
| **3. Retention** | Nothing counts as learned until it is scheduled. Free-recall retrieval practice + FSRS-scheduled spacing + interleaving. This is the engine; without it, pillars 1–2 produce insight that evaporates. | Testing effect (Roediger & Karpicke), distributed practice (Cepeda), desirable difficulties (Bjork), successive relearning (Rawson & Dunlosky) |
| **4. Adaptation** | A multi-dimensional learner model fitted from performance data — prior knowledge, personal forgetting curves, calibration, challenge band, interests — updated by n-of-1 experiments. *Not* "learning styles," which are a debunked neuromyth. | Expertise reversal (Kalyuga), per-user memory models (FSRS, Lindsey et al.), metacognition (Zimmerman), self-determination theory (Ryan & Deci) |

## On the founding question

> *"I really like first-principles & chain-of-necessity learning, and visualized interactive HTML. Can this be the central theory, or is it just me?"*

**It is half the theory — the good half of encoding — and it is not just you.** Chain-of-necessity learning is elaborative interrogation plus the generation effect plus coherent schema construction; interactive visual explanation is dual coding plus ICAP's interactive tier. Both are backed for *all* learners, not a personal quirk. Every derivation step is a forced prediction, and the brain learns from prediction error — your preference has a real mechanism.

But it cannot be the *whole* theory, for two evidence-backed reasons:

1. **Understanding decays like everything else.** Karpicke & Blunt (2011, *Science*) showed retrieval practice beats even excellent elaborative study on later inference tests — while learners predicted the opposite. Beautiful, fluent artifacts are dangerous precisely because they feel like learning (the fluency illusion, Koriat & Bjork). Pillar 3 exists because pillars 1–2 alone produce insight with a half-life of days.
2. **Not all knowledge is derivable, and not every learner state can bear derivation.** Vocabulary, anatomy, syntax, historical particulars are arbitrary mappings — they need mnemonics and spacing, not necessity chains. And for true novices, derivation-first overloads working memory (cognitive load theory; the worked-example effect): sometimes the right sequence is concrete example → manipulation → *then* derivation (concreteness fading). It feels natural to you partly because you're rarely a true novice in the domains you study — the system must notice when that stops being true.

So: first-principles + explorables is the **default encoding spine** of Engram, held accountable by the retention engine and adjustable by your own retention data. Full argument in [docs/01-foundations.md](docs/01-foundations.md), §"The founding question."

## What exists vs. what this adds

The 2026 ecosystem already has tutor plugins (SM-2 quizzes, dashboards), language kits, and retrieval-practice nudges. Full review in [docs/02-prior-art.md](docs/02-prior-art.md). Engram's gap-filling combination:

- **Verification-grade assessment** — free recall graded by an independent assessor agent with rubrics and receipts, not MCQ recognition or tutor self-grading
- **Modern per-user scheduling** — FSRS (fits ~20 memory parameters to *your* review history), not one-size SM-2
- **Generated explorables under an anti-passivity contract** — the mnemonic medium (Quantum Country) made generative: custom interactive HTML per concept, regenerated as your model updates
- **Honest adaptation** — n-of-1 strategy experiments on real retention outcomes, replacing learner-type folklore
- **Situated transfer** — it lives where you work; examples come from your code, transfer tasks are your actual tasks

## Install & quickstart

Requires Claude Code and `python3` (stdlib only — no pip installs). From a terminal:

```bash
claude plugin marketplace add nagisanzenin/engram
claude plugin install engram@engram
```

(Developing locally? Point the marketplace at your clone instead: `claude plugin marketplace add /path/to/engram`.)

Then, inside any Claude Code session:

```
/learn kalman filters        # new topic: goal intake → first-principles DAG → pretest → first nodes
/review                      # clear due retrievals (2-minute floor; interleaved)
/coach                       # telemetry check-in, dashboard, strategy experiments
```

There is no other configuration. The first `/learn` **is** the diagnostic; the session-start hook will quietly tell you when reviews are due and stays silent otherwise. All state lives in `~/.claude/learning/` as human-readable JSON — it is your data and your open learner model.

Verify the deterministic core anytime:

```bash
python3 scripts/engram.py selftest    # FSRS math + state machine, 33 checks
```

## What a session feels like

```
you    /learn kalman filters
engram [30-second intake: your goal, your prior exposure, your interests]
       [curriculum agent builds a first-principles concept map — shown as a progress-bar map]
       [3-probe pretest — attempting before learning measurably improves retention]
       [per concept: predict → struggle a little → resolve → explain it back → verified cold]
       [an independent assessor grades your answers blind; a receipt strip closes the session]

next day
engram [engram] 6 reviews due (kalman-filters: 6) · ~4 min · /review to clear
you    /review          ← free recall, ~2 minutes, everything reschedules itself
weekly /coach dashboard ← retention curves, calibration, mastery maps (local HTML)
```

Threshold concepts additionally get a generated **interactive explorable** (self-contained HTML: prediction gates, a manipulable model, embedded retrieval) under `~/.claude/learning/artifacts/`.

## CLI reference (`scripts/engram.py`)

The deterministic core — the model never does calendar math, this does:

| Command | Purpose |
|---|---|
| `init` / `doctor` / `path` | create state · diagnose problems · print state location |
| `topics` / `topic-status --topic T` | list topics · mastery map with progress bar |
| `next --topic T` / `due` | next frontier concept · due review queue (interleaved) |
| `rate` / `receipt --file F` | apply one rating · apply assessor receipt batch |
| `stash add\|list\|count\|clear` | crash-safe queue of productions awaiting grading |
| `model` / `misconception` / `experiment` | open learner model · error catalog · n-of-1 trials |
| `stats` / `report` | telemetry JSON · self-contained HTML dashboard |
| `refit` | fit review intervals to your measured recall (guarded, ≥50 reviews) |
| `session-start` / `log-session` | ambient nudge (hook) · session telemetry |
| `selftest` | 33 checks over the FSRS math and state machine |

## Troubleshooting

- Anything weird → `python3 scripts/engram.py doctor` (checks state files, paths, python).
- Skills resolve the plugin root via `${CLAUDE_PLUGIN_ROOT}`; for a dev clone outside the plugin cache, set `ENGRAM_ROOT=/path/to/engram`.
- Update to the latest release: `claude plugin update engram`.

## Your data

Everything lives in `~/.claude/learning/` as human-readable JSON you own — the learner model, concept graphs, receipts, misconceptions, artifacts. Nothing is ever sent anywhere. Two honesty guarantees are enforced by design: **confidence is only recorded when you actually state one** (never estimated for you), and **no mastery claim exists without a graded receipt**.

## Repository layout

```
.claude-plugin/     plugin.json, marketplace.json
skills/             learn / review / coach (+ _shared: dialogue grammar, Explorable Contract)
agents/             engram-curriculum-architect · engram-assessor · engram-artifact-smith
hooks/              SessionStart re-anchor (due-review nudge; silent when nothing is due)
scripts/engram.py   the deterministic core: FSRS-4.5 scheduling, state, receipts, stats, selftest
docs/               theory, prior art, architecture, roadmap (below)
```

Separation of powers, enforced by construction: the **tutor** (the main conversation, disciplined by `skills/_shared/dialogue-grammar.md`) teaches but never grades; the **assessor** grades from a fresh context without seeing the lesson; the **coach** adapts only from receipts; and `engram.py` — never the model — computes every date and stability value.

## Documents

| Doc | Contents |
|---|---|
| [docs/01-foundations.md](docs/01-foundations.md) | The science: 12 principles in 3 tiers, each with evidence and its design consequence; the prediction-error throughline; neuromyth hygiene and the honest learner model |
| [docs/02-prior-art.md](docs/02-prior-art.md) | Literature review of learning systems: SRS engines, mastery platforms, explorables, intelligent tutoring systems, AI tutors, and the Claude Code plugin ecosystem; gap analysis |
| [docs/03-architecture.md](docs/03-architecture.md) | Plugin design: state schemas, the five loops, agent roster, command surface, the Explorable Contract, adaptation policy, receipts |
| [docs/04-roadmap.md](docs/04-roadmap.md) | Phased build plan with measurable exit criteria, metrics, risks, and the ten-article constitution |

---

¹ *An engram is the physical trace a memory leaves in neural tissue (Semon 1904; experimentally located by Josselyn, Tonegawa et al. in the 2010s). Building durable engrams is literally this plugin's job. Alternative names considered: Paideia, Myelin, Chisel, Dojo.*

*License: MIT. Changelog: [CHANGELOG.md](CHANGELOG.md).*
