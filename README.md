<p align="center">
  <img src="assets/banner.png" alt="Engram — learn anything. keep it." width="100%">
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-0.3.0-6D4AA8.svg" alt="Version 0.3.0">
  <img src="https://img.shields.io/badge/license-MIT-yellow.svg" alt="MIT License">
  <img src="https://img.shields.io/badge/selftest-33%2F33-3E7D5A.svg" alt="33/33 checks">
  <img src="https://img.shields.io/badge/scheduler-FSRS--4.5-6D4AA8.svg" alt="FSRS-4.5">
  <img src="https://img.shields.io/badge/data-100%25%20local-3E7D5A.svg" alt="100% local">
</p>

<h3 align="center">Claude can explain anything. Engram makes sure you still know it next month.</h3>

```bash
claude plugin marketplace add nagisanzenin/engram
claude plugin install engram@engram
```

Then, inside Claude Code:

```
/learn kalman filters        ← or music theory, or Rust lifetimes, or anything
```

That's the whole onboarding. No config, no account, no cards to write. Requires `python3` (stock macOS/Linux one is fine — stdlib only).

> **On OpenAI Codex?** Engram is an omni-repo — the same skills and engine run there too (`codex plugin marketplace add nagisanzenin/engram`). See **[INSTALL-CODEX.md](INSTALL-CODEX.md)**.

---

## Wait — what *is* this?

You already ask Claude to explain things. It explains beautifully. You nod, you feel smart, and **ten days later it's gone** — because a chat has no memory of you, no test of whether you really got it, and no plan for the forgetting that starts the moment you close the terminal.

Engram is what's missing around the explanation: **a tutor that makes you do the thinking, an examiner that checks you actually got it, and a scheduler that brings each idea back right before your brain drops it.**

| Engram **is** | Engram is **not** |
|---|---|
| a tutor that makes you produce answers *before* it explains | a chatbot that explains while you nod along |
| a memory system — every concept gets a future review date | notes and summaries you'll never reopen |
| an independent examiner that grades you blind, in writing | self-assessed *"yeah, makes sense"* |
| plain JSON files on your machine | a cloud service, account, or subscription |

**Concretely, installing it gives you:** three slash commands (`/learn`, `/review`, `/coach`), a quiet session hook that tells you when reviews are due (and says nothing otherwise), and a state folder at `~/.claude/learning/` that you own and can read.

```
 recall
 100% ─┐ just reading                100% ─┐ with engram
       │\                                  │\      ●╌╌╌●╌╌╌╌╌●╌╌╌╌╌╌╌●╌╌
       │ \                                 │ \    ╱    ╲╱      ╲╱
       │  \__                              │  ●──╱
       │     \____                         │
       │          \_______                 │   each ● = a 2–4 minute /review,
   0% ─┴──────────────────── day 30    0% ─┴─  booked just before you'd forget
```

---

## The loop

```
  YOU ──→  /learn transformers
            │
            ▼
  ┌────────────────────────────────────────────────────────────────┐
  │  CURRICULUM ARCHITECT                                          │
  │  breaks the topic into a first-principles concept map:         │
  │  "what must be understood before what" — never chapter order.  │
  │  flags the few THRESHOLD concepts † that unlock everything.    │
  └────────────────────────────────────────────────────────────────┘
            │
            ▼
  ┌────────────────────────────────────────────────────────────────┐
  │  THE TUTOR  (your normal Claude chat, under strict rules)      │
  │                                                                │
  │  per concept:  open a question → you PREDICT → struggle a      │
  │  little (hints, not answers) → resolve → you EXPLAIN IT BACK   │
  │                                                                │
  │  threshold concepts get a generated interactive HTML           │
  │  explorable — sliders and prediction gates, not more text.     │
  └────────────────────────────────────────────────────────────────┘
            │   your answers, verbatim (crash-safe stash on disk)
            ▼
  ┌────────────────────────────────────────────────────────────────┐
  │  THE ASSESSOR  (separate agent — grades blind)                 │
  │  sees only the rubric and your words, never the lesson.        │
  │  every grade becomes a receipt on disk. no receipts,           │
  │  no mastery claim.                                             │
  └────────────────────────────────────────────────────────────────┘
            │   receipts
            ▼
  ┌────────────────────────────────────────────────────────────────┐
  │  THE SCHEDULER  (engram.py — deterministic code, not vibes)    │
  │  FSRS-4.5 fits your personal forgetting curves and books       │
  │  each concept's next review just before you'd lose it.         │
  └────────────────────────────────────────────────────────────────┘
            │
            ▼
  next session:  [engram] 6 reviews due (transformers: 6) · ~4 min
                     │
                     ├──→  /review   2–4 minutes of free recall
                     └──→  /coach    weekly: stats · dashboard · tuning
```

---

## A real session, condensed

From the first live topic taught with Engram (transformer internals). Note who does the thinking:

```
◆ node 6/13 · nonlinearity-necessity †

engram   Delete σ for a second. The FFN is now just W₂·(W₁·x).
         What is W₂·W₁ — and what has the two-layer FFN collapsed into?

you      i dont know really

engram   Fine — that's a commitment. Forget matrices. W₁ = "×2",
         W₂ = "×3". Run a number through both, nothing in between.
         Two steps of computation… or secretly one?

you      basically 2x3

engram   That's the whole secret, and you just said it. ×2 then ×3 = ×6:
         two linear layers fuse into ONE. Fifty of them? Still one matrix.
         Depth means nothing until a nonlinearity blocks the fuse —
         and that's why σ is not optional.
```

At session end, the assessor — which never saw that dialogue — graded the learner's six answers: **1 recalled · 4 partial · 1 first-retrieval**, while the tutor was convinced the session went great. The schedule believed the assessor. That separation is the point: your future reviews are built on verified evidence, not on the tutor's enthusiasm (or yours).

---

## Three commands, one habit

| Command | What happens | Time |
|---|---|---|
| `/learn <topic>` | Intake (your goal, your background) → concept map → pretest → generation-first teaching → blind grading → everything scheduled | 5–60 min, you pick |
| `/review` | Due concepts, free recall, interleaved across topics. The habit that makes it all permanent | **2–4 min** |
| `/coach` | Retention stats, calibration, local HTML dashboard, schedule tuning, n-of-1 experiments | weekly-ish |

Everything else is ambient: the session hook nudges when reviews are due and is silent otherwise.

---

## Why it works (the science, in one breath)

Engram implements the four most-replicated findings in learning science — and deliberately skips the popular myths (no "learning styles"; that theory failed every controlled test):

1. **Structure** — knowledge is a graph, so topics are decomposed by *chains of necessity* ("why must this be true?"), never by chapter order.
2. **Generation** — the mind keeps what it makes. You predict, attempt, and explain back before being told. Even failed attempts measurably improve what sticks next (the pretesting effect).
3. **Retention** — testing *is* the learning (not the measurement of it), and spacing beats bingeing. Free recall on an FSRS schedule fitted to your own review history.
4. **Honest adaptation** — it adapts from your *measured* retention, calibration, and error patterns. Confidence is only recorded when you actually state it; grades only exist as written receipts.

<details>
<summary><b>Citations & full theory</b> (for the skeptical — click)</summary>

The load-bearing evidence: retrieval practice (Roediger & Karpicke 2006; Karpicke & Blunt 2011, <i>Science</i>; Dunlosky et al. 2013 "high utility"), distributed practice (Cepeda et al. 2006; Rawson & Dunlosky 2011), desirable difficulties & the fluency illusion (Bjork 1994; Koriat & Bjork 2005), pretesting (Richland, Kornell & Kao 2009), the ~85% difficulty sweet spot (Wilson et al. 2019), self-explanation & ICAP (Chi et al. 1994; Chi & Wylie 2014), multimedia principles behind the explorables (Mayer; Paivio), step-level tutoring ≈ human tutors (VanLehn 2011), FSRS scheduling (open-spaced-repetition, Anki's modern default), and the learning-styles refutation (Pashler, McDaniel, Rohrer & Bjork 2008).

Full treatment with design consequences: [docs/01-foundations.md](docs/01-foundations.md) · what exists and what's missing in every other tool: [docs/02-prior-art.md](docs/02-prior-art.md) · system design: [docs/03-architecture.md](docs/03-architecture.md) · roadmap & constitution: [docs/04-roadmap.md](docs/04-roadmap.md)

</details>

---

## What it looks like

**Your mastery map**, any time (`/learn` shows it, `/coach` renders the full dashboard):

```
transformers — Transformers from first principles
██▒▒▒▒▒▒▒▒▒▒▒░░░░░░░░░░░  1 retained · 6 learning · 6 untouched

● contextual-meaning        due 2026-07-09   S=3.7d
◐ residual-stream        †  due 2026-07-06   S=1.4d
◐ nonlinearity-necessity †  due 2026-07-06   S=1.4d
· depth-necessity        †  due —            S=—
```

**Interactive explorables** for threshold concepts — self-contained HTML with prediction gates (content stays locked until you commit a guess), manipulable models, and embedded retrieval prompts. **A local HTML dashboard** (`/coach dashboard`) with per-topic maps, retention-by-strength bars vs. the 85% target band, honest calibration, and your next-7-days forecast. Both live in `~/.claude/learning/artifacts/` — no network, ever.

---

## FAQ

**How is this different from just asking Claude to explain?**
Asking produces understanding; understanding decays on the same curve as everything else. Engram adds the three things a chat can't: verification (did you *actually* get it?), memory across sessions (a learner model in files, not context), and a future (every concept has a scheduled next encounter). The explanation is the easy 20%.

**Is this Anki?**
Anki schedules cards *you* write and grades *yourself*. Engram teaches the material, writes the assessment from the dialogue, grades it blind, and schedules concepts on the same family of algorithm (FSRS) — with an actual tutor attached. If you love Anki, think: Anki where the deck builds itself from a Socratic lesson and the grader isn't you.

**Non-code topics?**
Yes — the engine doesn't care. History, music theory, statistics, anatomy (it routes memorization-heavy content to mnemonics instead of derivation-theater).

**What if I just want the answer?**
Say "just tell me" — it complies immediately, no lecture. It also quietly schedules that concept for earlier review, because told-not-derived decays faster. Your call, honestly priced.

**Where's my data?**
`~/.claude/learning/` — learner model, concept graphs, grade receipts, misconception log, artifacts. Human-readable JSON. Your learning **state never leaves your machine**: the engine (`engram.py`) is stdlib-only with no network code, and the dashboard is a local file. The one exception is the curriculum architect, which uses web search on the *topic and goal you give it* when building a new map — so keep secrets out of the goal line, or ask for an offline map. (Override the location with `ENGRAM_HOME`.)

**Why does it keep testing me?**
Because retrieval is the treatment, not the measurement. A century of memory research in four words: testing is the learning.

---

<details>
<summary><b>CLI reference</b> — <code>scripts/engram.py</code>, the deterministic core</summary>

The model never does calendar math; this does:

| Command | Purpose |
|---|---|
| `init` / `doctor` / `path` | create state · diagnose problems · print state location |
| `topics` / `topic-status --topic T` | list topics · mastery map with progress bar |
| `next --topic T` / `due` | next frontier concept · due review queue (interleaved) |
| `rate` / `receipt --file F` | apply one rating · apply assessor receipt batch |
| `stash add\|list\|count\|clear` | crash-safe queue of answers awaiting grading |
| `model` / `misconception` / `experiment` | open learner model · error catalog · n-of-1 trials |
| `stats` / `report` | telemetry JSON · self-contained HTML dashboard |
| `refit` | fit review intervals to your measured recall (guarded, ≥50 reviews) |
| `session-start` / `log-session` | ambient nudge (hook) · session telemetry |
| `selftest` | 63 checks over the FSRS math, state machine, and every hardened boundary |

</details>

<details>
<summary><b>Troubleshooting & updating</b></summary>

- Anything weird → `python3 scripts/engram.py doctor` (checks state files, paths, python, quarantined files).
- Update: `claude plugin marketplace update engram && claude plugin update engram@engram`, then restart or `/reload-plugins`.
- Skills resolve the plugin root via `${CLAUDE_PLUGIN_ROOT}` (or `${CODEX_PLUGIN_ROOT}` on Codex); for a dev clone outside the plugin cache, set `ENGRAM_ROOT=/path/to/engram`.
- Corrupt a state file by hand? It's quarantined to a `.corrupt.<date>` sibling (never silently discarded) and `doctor` will point at it — your other topics keep working.

</details>

<details>
<summary><b>Repository layout & design lineage</b></summary>

```
.claude-plugin/     plugin.json, marketplace.json          (Claude Code)
.codex-plugin/      plugin.json                            (Codex)
.agents/plugins/    marketplace.json                       (Codex marketplace)
skills/             learn / review / coach  (+ _shared: dialogue grammar, Explorable Contract)
agents/             engram-curriculum-architect · engram-assessor · engram-artifact-smith  (Claude Code)
codex/agents/       *.toml ports of the three subagents     (Codex)
hooks/              SessionStart re-anchor (self-resolving; silent when nothing is due)
scripts/engram.py   deterministic core: FSRS-4.5, state, receipts, stats, dashboard, selftest
docs/               theory · prior art · architecture · roadmap  ·  INSTALL-CODEX.md
```

One codebase, two agents: `skills/` and `scripts/engram.py` are shared verbatim; each agent gets its own thin manifest + subagent format. See [INSTALL-CODEX.md](INSTALL-CODEX.md).

Separation of powers, enforced by construction: the **tutor** teaches but never grades; the **assessor** grades from a fresh context without seeing the lesson; the **coach** adapts only from receipts; and `engram.py` — never the model — computes every date and stability value. Verification patterns (oracle-driven loops, receipts, re-anchoring) inherited from [claude-code-production-grade-plugin](https://github.com/nagisanzenin/claude-code-production-grade-plugin), transposed from software verification to learning verification.

</details>

---

## Documents

| Doc | Contents |
|---|---|
| [docs/01-foundations.md](docs/01-foundations.md) | The science: 12 principles in 3 tiers, each with evidence and its design consequence; the neuromyths Engram refuses to build on |
| [docs/02-prior-art.md](docs/02-prior-art.md) | Literature review: SRS engines, mastery platforms, explorables, ITS research, AI tutors, the Claude Code ecosystem — and the gap |
| [docs/03-architecture.md](docs/03-architecture.md) | State schemas, the five loops, agent separation of powers, the Explorable Contract, adaptation policy |
| [docs/04-roadmap.md](docs/04-roadmap.md) | Phased plan with measurable exit criteria, metrics, risks, and the ten-article constitution |

---

## More from the same workshop

Two sibling plugins share Engram's discipline — deterministic cores, blind grading, receipts:

- **[claude-code-production-grade-plugin](https://github.com/nagisanzenin/claude-code-production-grade-plugin)** — turns "build me X" into a gated multi-agent pipeline: architecture decisions, tests, security audit, CI/CD, and verifiable receipts for every phase.
- **[effortmining](https://github.com/nagisanzenin/effortmining)** — benchmark-calibrated reasoning-effort dispatch for Claude Code subagents: 64.7% fewer output tokens at equal quality versus effort inheritance, pre-registered A/B with published failures. Its blind grader is Engram's assessor, transposed.

---

## Stars

If Engram earned its keep, a star helps the next person find it.

[![GitHub stars](https://img.shields.io/github/stars/nagisanzenin/engram?style=for-the-badge&logo=github&label=Stars&color=gold)](https://star-history.com/#nagisanzenin/engram&Date)

<sub>GitHub restricted the stargazer-timeline API to repo collaborators, so the live history chart no longer renders inline. Click the badge for the interactive graph.</sub>

---

<sub>*An <b>engram</b> is the physical trace a memory leaves in neural tissue (Semon, 1904; experimentally located by Josselyn, Tonegawa et al. in the 2010s). Building durable ones is literally this plugin's job.* · MIT license · [changelog](CHANGELOG.md)</sub>
