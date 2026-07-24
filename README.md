<p align="center">
  <img src="assets/banner.png" alt="Engram — learn anything. keep it." width="100%">
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-1.5.0-6D4AA8.svg" alt="Version 1.5.0">
  <a href="https://www.npmjs.com/package/opencode-engram-learning"><img src="https://img.shields.io/npm/v/opencode-engram-learning?label=npm&color=6D4AA8" alt="npm package"></a>
  <img src="https://img.shields.io/badge/license-MIT-yellow.svg" alt="MIT License">
  <img src="https://img.shields.io/badge/selftest-253%2F253-3E7D5A.svg" alt="253/253 checks">
  <a href="gold/assessor-gold.jsonl"><img src="https://img.shields.io/badge/grader%20inflations-0%2F258-3E7D5A.svg" alt="0 of 258 blind judgments graded up, on the shipping spec"></a>
  <img src="https://img.shields.io/badge/scheduler-FSRS--4.5-6D4AA8.svg" alt="FSRS-4.5">
  <a href="CONTRIBUTING-DATA.md"><img src="https://img.shields.io/badge/data-100%25%20local-3E7D5A.svg" alt="100% local — the engine has no network code, proven by a permanent selftest"></a>
  <a href="https://discord.gg/temm1e"><img src="https://img.shields.io/badge/discord-community-5865F2.svg" alt="Discord community"></a>
</p>

<h3 align="center">Your AI can explain anything. Engram makes sure <em>you</em> still know it next month.</h3>

> **The mix-up worth clearing first: Engram is not an agent-memory plugin.** It doesn't give your agent persistent memory, context, or knowledge of your codebase — memory MCPs and context tools do that, *for the agent*. Engram points the other way: **it's a learning system for the human.** Your agent becomes a tutor that makes you do the thinking, a blind examiner that checks you actually got it, and a scheduler that brings each idea back right before your brain drops it. The agent doesn't get smarter. **You do — measurably, with receipts.**

Born as a Claude Code plugin; the same skills and engine now run on six agentic platforms — including, as of v1.0.8, one that puts the tutor in your chat app:

```bash
claude plugin marketplace add nagisanzenin/engram
claude plugin install engram@engram
```

| Platform | Install | Then |
|---|---|---|
| **Claude Code** (born here) | the two commands above | `/learn` `/review` `/coach` |
| **OpenAI Codex** | `codex plugin marketplace add nagisanzenin/engram` then `codex plugin add engram@engram` → [INSTALL-CODEX.md](INSTALL-CODEX.md) | `$learn` `$review` `$coach` |
| **OpenCode** | `"plugin": ["opencode-engram-learning"]` in `opencode.json` ([npm](https://www.npmjs.com/package/opencode-engram-learning)) | `/learn` `/review` `/coach` |
| **Hermes Agent** | clone + `skills.external_dirs` → [INSTALL-HERMES.md](INSTALL-HERMES.md) — verified live on v0.18.2 | `/skill learn` (or `/study`) `/review` `/coach` |
| **Google Antigravity** | `agy plugin install https://github.com/nagisanzenin/engram` | `/learn` `/review` `/coach` |
| **OpenClaw** | `openclaw plugins install engram --marketplace nagisanzenin/engram` → [INSTALL-OPENCLAW.md](INSTALL-OPENCLAW.md) — verified on 2026.7.1-2 | `/learn` `/review` `/coach` |

<sub>OpenCode: `opencode.json` is read globally (`~/.config/opencode/opencode.json`) or per-project; pin to source instead of npm with `"plugin": ["git+https://github.com/nagisanzenin/engram.git"]`.</sub><br>
<sub>Antigravity: The due-review session nudge isn't ported yet, and the `architect` and `smith` subagents are currently dropped by AG 1.1.4's strict installer. Everything else works the same.</sub><br>
<sub>OpenClaw: the nudge needs `openclaw config set hooks.internal.enabled true` (OpenClaw ignores plugin hooks until internal hooks are switched on), and it fires on `/new` and `/reset` rather than every session. Engram's agents aren't registered — the skills spawn them through `sessions_spawn` with isolated context instead, which keeps the assessor blind. Details in [INSTALL-OPENCLAW.md](INSTALL-OPENCLAW.md).</sub>

Then, inside your coding assistant (command spelling per your platform's row above):

```
/learn kalman filters        ← or music theory, or Rust lifetimes, or anything
```

That's the whole onboarding. No config, no account, no cards to write. Requires `python3` (stock macOS/Linux one is fine — stdlib only). One state folder, every platform: learn in one tool, review in another, same schedule.

---

## Wait — what *is* this?

You already ask Claude to explain things. It explains beautifully. You nod, you feel smart, and **ten days later it's gone** — because a chat has no memory of you, no test of whether you really got it, and no plan for the forgetting that starts the moment you close the terminal.

Engram is what's missing around the explanation: **a tutor that makes you do the thinking, an examiner that checks you actually got it, and a scheduler that brings each idea back right before your brain drops it.**

| Engram **is** | Engram is **not** |
|---|---|
| **a learning system for the human — *you* end up knowing things** | **agent memory — tools that persist what the *agent* knows (different job entirely)** |
| a tutor that makes you produce answers *before* it explains | a chatbot that explains while you nod along |
| a memory system — every concept gets a future review date | notes and summaries you'll never reopen |
| an independent examiner that grades you blind, in writing | self-assessed *"yeah, makes sense"* |
| plain JSON files on your machine | a cloud service, account, or subscription |

**Concretely, installing it gives you:** three commands (`/learn`, `/review`, `/coach` — exact spelling per platform in the table above), a quiet session nudge that tells you when reviews are due (and says nothing otherwise — on every platform except Antigravity, whose hook port is pending; on OpenClaw it needs one config flag and fires on `/new`), and a state folder at `~/.claude/learning/` that you own, can read, and share across every platform you use.

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
5. **Motivation & wisdom, honestly** — it makes your *real* competence growth visible at the moment it happens (the memory that now lasts 4× longer — not points or streaks, which backfire on motivated adults), and it carries you through the hard part: struggle named as encoding, lapses absolved not pitied, backlogs met with amnesty. Two new layers, every claim adversarially verified against the primary source — [docs/05-affective-layers.md](docs/05-affective-layers.md).
6. **Visuals that earn their keep** (v0.5) — interactive explorables are built when the *content* rewards manipulation (a parameter to drag, a process that unfolds — declared per concept by the curriculum architect, never inferred from a "visual learner" label), always wrapped in predict → act → explain guidance, because the guidance is what carries the effect (scaffolded simulations beat identical unscaffolded ones, g+ = 0.60). You choose the eagerness (`visuals eager|threshold|off`), and your own review receipts then measure whether the medium actually holds better *for you* — [docs/06-visual-encoding.md](docs/06-visual-encoding.md).
7. **Procedures are practiced, not recited** (v1.1) — some knowledge is a *skill executed on instances* (an integral, a `git rebase`, a statistical-test choice — any domain, declared per node by the content, never by a topic label). Those nodes enter by the **worked-example ladder** (study → complete → faded → solve; examples first is the best-replicated novice result in math, g ≈ 0.44) and are reviewed by **solving a fresh variant** — new numbers, same structure — next to the problems they're confused with, because practice format must match use format (transfer d = 0.58 congruent vs 0.28 not). Solutions are step-graded with the arithmetic **verified by execution**, and a slip is priced gentler than a wrong method. Engram stays a general learn-anything system; this layer wakes only where the content is a skill — [docs/11-the-procedure-gap.md](docs/11-the-procedure-gap.md).

<details>
<summary><b>Citations & full theory</b> (for the skeptical — click)</summary>

The load-bearing evidence: retrieval practice (Roediger & Karpicke 2006; Karpicke & Blunt 2011, <i>Science</i>; Dunlosky et al. 2013 "high utility"), distributed practice (Cepeda et al. 2006; Rawson & Dunlosky 2011), desirable difficulties & the fluency illusion (Bjork 1994; Koriat & Bjork 2005), pretesting (Richland, Kornell & Kao 2009), the ~85% difficulty sweet spot (Wilson et al. 2019), self-explanation & ICAP (Chi et al. 1994; Chi & Wylie 2014), multimedia principles behind the explorables (Mayer; Paivio), step-level tutoring ≈ human tutors (VanLehn 2011), FSRS scheduling (open-spaced-repetition, Anki's modern default), and the learning-styles refutation (Pashler, McDaniel, Rohrer & Bjork 2008).

The affective layers (v0.4): competence-as-information (Deci/Koestner/Ryan 1999 — verbal competence feedback lifts *adult* intrinsic motivation d=+0.33, but flips to d=−0.78 when controlling), progress salience (Harkin et al. 2016, 138 RCTs, d=0.40), curiosity's reward circuit (Gruber, Gelman & Ranganath 2014), return-after-absence amnesty (Silverman & Barasch 2023; Lally et al. 2010) — and the refusals it's built on: gamification's motivational effect is the *least* robust (Sailer & Homner 2020) and backfires on already-motivated adults (Hanus & Fox 2015), streaks install a proxy goal, growth-mindset framing is small and context-specific (Sisk 2018; Yeager 2019), sympathy-after-failure reads as a low-ability cue (Graham 1984), and over-helpful AI tutoring harms retention (Bastani 2025). ADHD is honored as an opt-in *Focus profile* that turns up the same universal dials — not a new pedagogy, and pointedly not a game.

The visual-encoding audit (v0.5): interactive simulations carry the largest verified interactivity effect (g+=0.62, D'Angelo/SRI 2014) but *guidance inside the artifact is the active ingredient* (scaffolded versions of the same simulation g+=0.60; guidance in inquiry d=0.50, Lazonder & Harmsen 2016); dynamic-vs-static is modest and moderator-driven (g=0.226, Berney & Bétrancourt 2016 — concentrated where the motion *is* the content, d=0.40 representational vs ≈−0.05 decorative); learner control per se is worth ≈nothing (g=0.05, Karich 2014); seductive details reliably hurt (Sundararajan & Adesope 2020); and expertise reversal is a confirmed disordinal crossover (novices +0.505 with assistance, knowledgeable learners −0.428; Tetzlaff 2025) — which is why explorables are content-triggered, guidance-wrapped, scaffold-faded, and measured against your own receipts rather than assumed to work. What didn't survive verification is stated as open, not assumed — [docs/06-visual-encoding.md](docs/06-visual-encoding.md).

Full treatment with design consequences: [docs/01-foundations.md](docs/01-foundations.md) · what exists and what's missing in every other tool: [docs/02-prior-art.md](docs/02-prior-art.md) · system design: [docs/03-architecture.md](docs/03-architecture.md) · roadmap & constitution: [docs/04-roadmap.md](docs/04-roadmap.md) · the motivation & wisdom layers: [docs/05-affective-layers.md](docs/05-affective-layers.md) · the visual-encoding audit: [docs/06-visual-encoding.md](docs/06-visual-encoding.md) · the measured loop: [docs/07-the-measured-loop.md](docs/07-the-measured-loop.md)

</details>

**And the strongest external result, stated honestly.** [Kestin et al., *Scientific Reports*, June 2025 (Harvard, n=194)](https://www.nature.com/articles/s41598-025-97652-6): an AI tutor built on exactly this dialogue grammar — one step at a time, never reveal the solution, make them attempt first — produced **roughly double the learning gains of an active-learning physics classroom, in less time.** The caveat is the whole reason Engram exists: **its outcome was an immediate post-test.** Nobody has ever measured whether AI-tutoring gains survive to thirty days. That is the question this tool is built to answer, on you, with receipts.

---

## The grader is graded (v0.7)

Engram's central claim is separation of powers: a **blind assessor** grades your free recall, and its receipts drive mastery, retention, calibration, and the schedule itself. Which raises the question nobody in this space likes: **who grades the grader?**

Until v0.7, nobody. The oracle was a vibe — an excellent one, unmeasured. And that hole sat directly under the foundation, because *if the grader is lenient, every number Engram has ever shown you is inflated, and the system has no way to find out.*

So we built the audit and ran it. **Then the gold set failed before the grader did**, and that turned out to be the more important result.

### The one number that survives, and it is the one that matters

| | |
|---|---|
| **0 of 258** | blind judgments — 86 adversarial items × 3 independent runs — where the grader awarded **more** credit than the strict rubric reading. **Zero, on the spec that ships — and it is a repaired zero, not an untested one.** Extending the set to procedure items ran the audit three times over 774 judgments and caught **3 real inflations**, each traced to an ambiguity in the grader's own instructions (one of them introduced by this release). All three are closed; the number was re-earned, not extrapolated. The full account, including what the fixes cost: [docs/release-audits/v1.1.0-grader-audit.md](docs/release-audits/v1.1.0-grader-audit.md). |

That is a claim about **safety**, and it is the reason the badge above says what it says. A grader that errs low makes you re-drill something you had earned — annoying, and it costs you time. A grader that errs *high* tells you that you know something you do not, and **you stop reviewing.** Only one of those is a trap, and this grader has never walked into it.

### And now the part we would rather tell you than have you find

v0.7.0 shipped this section with a **QWK 0.93** badge. Then an independent post-release reviewer ran the one test nobody had thought to run: it graded the gold set with a *correct* grader and with a deliberately *fooled* one.

**The fooled grader scored higher.** (1.000 vs 0.990.) **The gold set was rewarding leniency.** The instrument was inverted.

The cause was five lenient adjudications by the gold set's own author, every one of the same species: **crediting an adjacent fact as partial credit.** Majority is not intersection. Consonance is not pitch-set arithmetic. The history of a theory is not its mechanism. The grader had caught all five, three runs out of three — *including on a `fluent-but-empty` item*, which means the author was fooled by fluency **in the very category built to catch being fooled by fluency.**

Correcting them moves agreement from 0.889 to 0.965 and QWK to **0.978**. And here is the thing:

> **That rise is not evidence the grader got better. It is evidence the instrument had been measuring the author's inconsistency.**

Worse — the corrections were *prompted by the grader's own disagreements*. So the QWK that follows is **circular**: an authored gold set cannot validate a grader from the same model family, because when the two disagree and the author concedes, the agreement that follows measures only the author's willingness to concede. **The engine now says so on every single audit**, in the `read` string, until someone who is not the author has adjudicated the set.

That is why the badge is no longer a QWK. **`0/258 graded up` is a safety property that does not depend on the gold being perfectly calibrated** — and correcting the gold *downward* only made it a stronger claim, because it lowered the bar the grader had to not exceed. It still never did.

One genuine disagreement (`g_054`) is **deliberately left in**, because the reviewer read both readings and judged the gold's defensible. *An instrument with no disagreement left in it measures nothing.*

**The gold set is public** — [`gold/assessor-gold.jsonl`](gold/assessor-gold.jsonl), 86 items, **86% adversarial**: *fluent-but-empty*, *terse-but-correct*, *confident-and-wrong*, *right-answer-wrong-reason*, *paraphrase*, *partial-credit boundary*, and — new in v1.1 — *right-answer-wrong-method*, *slip-vs-conceptual*, *fluent-wrong-step*, *terse-but-correct-solution*. Every corrected item carries a `disputed` record with its original grade, so the correction is auditable rather than laundered. Run it yourself: `/coach audit`. **Dispute an item** — drop it in `gold/local-gold.jsonl` and it overrides ours (the audit will say it did).

**What would actually fix this:** one human, who is not us, adjudicating 86 items — and the two categories where the author and the grader now disagree in every run (`right-answer-wrong-method`, `procedure-partial-boundary`) are where that human would earn their keep first. That is the highest-value contribution anyone could make to this repository, and until it happens the engine will keep saying so out loud.

**One more thing the literature insists on, and the engine enforces:** high consistency is *not* correctness. A judge has been measured at test–retest **0.992** with a position bias of **0.192** — perfectly reproducible and systematically wrong ([docs/07](docs/07-the-measured-loop.md) §3). Engram's assessor is *prompted* to be a skeptic, so it is self-consistent by construction — precisely the profile that failure mode wears. So the engine **refuses to certify on consistency**: above 0.95 test–retest it demands the leniency bias be strictly under the ceiling, fewer than three runs cannot pass at all, and three *identical* runs are flagged as measuring nothing.

---

## The Commons (v1.0)

The evidence base of learning science is built on **undergraduates, word pairs, and 20-minute retention intervals.** Almost nothing tests *self-directed adults*, on *hard conceptual material*, at *30–90 day horizons*, with *blind-graded free recall*.

That is not a gap anyone chose. It is a gap because, until roughly 2026, **grading free recall at scale was impossible** — you needed a human to read every answer.

Engram produces exactly that data as a byproduct of being useful, on hundreds of machines, with a **measured** grader behind every verdict. And the open question is sitting right there: [Kestin et al. (Harvard, *Scientific Reports*, 2025)](https://www.nature.com/articles/s41598-025-97652-6) found an AI tutor built on this exact dialogue grammar produced **~2× the learning gains of an active-learning classroom, in less time** — measured on an **immediate post-test.** **Nobody has ever measured whether AI-tutoring gains survive to thirty days.**

```bash
python3 scripts/engram.py export --contributor "@you"     # writes a FILE. Sends nothing.
```

**Then read the file.** It is short, it is yours, and nothing has left your machine.

| leaves | never leaves |
|---|---|
| grades, ratings, confidence | **your productions** — every word you wrote |
| timings, stability, intervals, retrievability | **probes, claims, rubrics** |
| `kind`, `node_kind`, `error_class`, `artifact`, `arm`, `stratum` | **goals, interests, misconception text** |
| `grader` and its **measured QWK** | **topic names and node ids** — hashed, not carried |

**Four things make that a promise rather than a hope:**

- **The payload is a WHITELIST.** Every field is constructed by name. There is *no code path* by which a production could arrive — not *"we remembered to delete it."* A blacklist is a promise you must keep every release; a whitelist is one you keep by construction.
- **The `stripped` list ships INSIDE the file**, so the promise is verifiable by the person making it, not merely asserted at them.
- **An unaudited grader cannot contribute.** `export` **refuses** — a refusal, not a warning. *A finding aggregated from unaudited oracles is not a finding; it is noise with a schema.* **v0.7 gates v1.0.**
- **The engine has no network code.** Not "none by default" — **none.** A **permanent selftest parses the engine's own AST** (not a grep — the first draft found the word `curl` in its *own comment*) and fails the build if anyone ever adds `import socket` to make one thing convenient. `export` writes a file and stops; the **agent** posts, via `gh`, only on an explicit yes.

**And it is ATTRIBUTED — we are not going to lie to you about that.** `gh` posts from your account. A "salted anonymous hash" riding inside a signed envelope would be theatre the moment the envelope is signed. You cannot have one-keystroke upload *and* anonymity; pick one, and say which out loud. **Attribution is also the stronger science:** a retention study lives on **longitudinal linkage** — following *the same learner across months* **is** the question — so attributed n=100 beats anonymous n=500.

This is not telemetry. **It is a consenting, named, informed participant in an open study** — which is what every good study has always had. **Withdrawal is: it's a GitHub post, delete it.** That is the entire mechanism, deliberately.

**Read the whole thing before you decide: [CONTRIBUTING-DATA.md](CONTRIBUTING-DATA.md).**

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

**Interactive explorables** — self-contained HTML with prediction gates (content stays locked until you commit a guess), guided manipulable models, and embedded retrieval prompts. Built for threshold concepts by default; set `visuals eager` and they're also built whenever a concept's own structure rewards manipulation (the curriculum architect declares this per node — features you can drag, processes that unfold); or just ask mid-lesson: *"make it visual."* **A local HTML dashboard** (`/coach dashboard`) with per-topic maps, retention-by-strength bars vs. the 85% target band, honest calibration, an encoding-medium comparison (do explorable-encoded concepts hold better *for you*? — your own receipts answer), and your next-7-days forecast. Both live in `~/.claude/learning/artifacts/` — no network, ever.

---

## FAQ

**Is this a memory plugin for my agent?**
No — the other direction, and this is the most common mix-up. Agent-memory tools (memory MCPs, context managers, "give Claude persistent memory" plugins) store knowledge *for the agent*. Engram uses the agent to install knowledge *in you*: it tutors, blind-grades your free recall, and schedules reviews against your measured forgetting curve. If you want your agent to remember things, you want a different tool. If you want to still know things a month after the chat, you want this one.

**How is this different from just asking Claude to explain?**
Asking produces understanding; understanding decays on the same curve as everything else. Engram adds the three things a chat can't: verification (did you *actually* get it?), memory across sessions (a learner model in files, not context), and a future (every concept has a scheduled next encounter). The explanation is the easy 20%.

**Is this Anki?**
Anki schedules cards *you* write and grades *yourself*. Engram teaches the material, writes the assessment from the dialogue, grades it blind, and schedules concepts on the same family of algorithm (FSRS) — with an actual tutor attached. If you love Anki, think: Anki where the deck builds itself from a Socratic lesson and the grader isn't you.

**Non-code topics?**
Yes — the engine doesn't care. History, music theory, statistics, anatomy (it routes memorization-heavy content to mnemonics instead of derivation-theater).

**Math and STEM specifically?**
Yes, and since v1.1 with a layer built for the half of STEM that is *doing*: the architect marks skill-type nodes as `procedure`, which swaps in worked-example acquisition and solve-a-fresh-variant reviews, step-graded with execution-checked arithmetic (a dropped sign is priced as a slip, not a forgotten idea; a right answer over a wrong method is capped — the answer is not the knowledge). It is not a "math mode": the same kind fires on a git workflow or a conjugation drill, concepts still run the Socratic grammar, and a topic with no procedure nodes behaves exactly as before. Theory and the adversarial verification behind it: [docs/11-the-procedure-gap.md](docs/11-the-procedure-gap.md).

**What if I just want the answer?**
Say "just tell me" — it complies immediately, no lecture. It also quietly schedules that concept for earlier review, because told-not-derived decays faster. Your call, honestly priced.

**I'm a visual learner — will it build me visuals?**
Careful — two different things are true. "Visual learner" as a *learning style* is a debunked theory (matching instruction to a diagnosed style has failed every controlled test), so Engram will never route content by that label. But interactive visuals as a *medium* are real and measured — strongest exactly when the concept itself is manipulable (a parameter to drag, a process that unfolds) and when the interaction is guided, which is how Engram builds them. So: the **content** decides what qualifies (each concept carries a declared visual affordance), **you** decide the eagerness — say *"build visuals eagerly"* or run `python3 scripts/engram.py visuals eager` (or `threshold`/`off`; you can also just ask *"make it visual"* on any concept mid-lesson) — and then your own review receipts quietly measure whether explorable-encoded concepts actually hold better for you. `/coach` shows the verdict with honest sample sizes. Preference honored, evidence in charge: [docs/06-visual-encoding.md](docs/06-visual-encoding.md).

**I have ADHD / I keep getting bored and quitting — is there a mode for that?**
Yes: an opt-in **Focus profile**. It doesn't add a game — no XP, streaks, or badges (the evidence says those backfire on motivated adults; see [docs/05](docs/05-affective-layers.md)). It turns *up* dials Engram already has: one node per session so you can't drift, your **real** memory-growth surfaced every review (*"this now lasts ~4× longer"* — a true stability number, not points), and amnesty whenever you return to a backlog instead of a guilt pile. Two ways to switch it, whichever you like:
- **Just say so** in `/learn` or `/coach` — *"I have ADHD, turn on focus mode."*
- **Run it** yourself: `python3 scripts/engram.py focus on` (or `off`, or `status`).

It's stored as a declared need in your learner model, honored across all three commands — not a "learning style" (Engram rejects those). Works for anyone who wants it; ADHD just gets the intensity. Full rationale and evidence: [docs/05-affective-layers.md](docs/05-affective-layers.md).

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
| **`adherence`** | **the binding constraint: of concepts taught and scheduled, how many you came back for** (`loop_closure`) · return cadence · the full funnel |
| **`retention`** | **the north star: recall at 7 / 30 / 90 days after encoding** — reported with its `unmeasured` denominator (the concepts that came due and were never reviewed; unknown, not absent) |
| **`decay --topic T`** | what is dying right now, and what N minutes would save — real FSRS numbers, both arms over the same window |
| **`commit --cue … --action …`** | your if-then plan, in your words. Stored, **shown back at the moment it names** (v1.3 — for three releases it was stored and displayed by nothing), renewable, **never enforced** |
| `next --topic T` / `due` | next frontier concept · due review queue (interleaved) |
| **`due --cap N`** | a capped session, ranked by **expected retention saved per minute** rather than most-overdue-first — with `order_basis` stating in the payload that it is model-derived (`--limit` keeps the old shape and order) |
| **`retire --topic T [--node N]`** | take something off your list — out of every queue, **counted in every denominator it leaves**, reversible with `--restore` |
| `rate` / `receipt --file F` | apply one rating · apply assessor receipt batch |
| `stash add\|list\|count\|clear` | crash-safe queue of answers awaiting grading |
| `model` / `misconception` | open learner model · error catalog |
| **`experiment start\|assign\|status\|settle`** | n-of-1 trials done properly: **randomized** (seeded, reproducible) · **stratified** (kills the material-vs-medium confound) · **pre-registered** · **powered** (15/arm) · and **the engine computes the verdict** — `--verdict` is refused |
| `focus on\|off\|status` | toggle the ADHD Focus profile (Sprint default, growth every review, always-on amnesty) |
| `visuals eager\|threshold\|off\|status` | the explorables dial: every high-affordance concept · portal concepts only (default) · none |
| `artifact set\|clear\|list` | register a built explorable on its node (validated; powers regeneration tracking + the medium comparison) |
| **`gold`** | the 86-item adversarial gold set, **answers stripped by construction** — shaped exactly like a real settle payload, so the audit grades the real assessor |
| **`assessor-audit --file F`** | **grade the grader.** QWK (headline) · raw agreement (never quoted alone) · signed leniency bias · test–retest · confusion matrix · per-case-type breakdown |
| **`grader-health [--grader-context S]`** | the latest audit's verdict — **and it EXPIRES** (v1.4): a grader swap voids the badge, because a swapped model grades measurably more lenient. `stats` embeds it, and stamps `grader_unvalidated` on every retention figure until it passes |
| **`transfer [--topic T]`** | the mature concepts ready for the harder question — the `transfer_probe` the architect wrote and nothing ever asked. `/review` serves it automatically |
| **`capstone --topic T`** | materialize the build as a real NODE in the DAG (idempotent). New topics get one from `add-topic`; it requires every concept, so it cannot be silently skipped |
| `stats` / `report` | telemetry JSON (incl. `modality` — explorable vs dialogue retention) · self-contained HTML dashboard |
| `refit` | fit review intervals to your measured recall (guarded, ≥50 reviews) |
| **`export [--topic T]`** | a **text-stripped**, **attributed** receipt bundle written **to a file**. Whitelist-constructed — there is no code path by which a production could leave. **Refuses** if your grader is unaudited |
| `session-start` / `log-session` | ambient nudge (hook) · session telemetry |
| `selftest` | 253 checks| 249 checks| 243 checks| 234 checks| 230 checks| 217 checks| 214 checks| 213 checks| 213 checks| 207 checks| 201 checks| 200 checks| 192 checks| 191 checks over the FSRS math, state machine, adherence/retention arithmetic, the grader-audit statistics, and every hardened boundary |

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
skills/             learn / review / coach  (+ _shared: dialogue grammar, Explorable Contract, subagent spawning)
agents/             engram-curriculum-architect · engram-assessor · engram-artifact-smith  (Claude Code)
codex/agents/       *.toml ports of the three subagents     (Codex)
hooks/              SessionStart re-anchor (Claude Code/Codex) · pre_llm_call port (Hermes) — self-resolving; silent when nothing is due
hooks/engram-due/   HOOK.md + handler.js                    (OpenClaw hook pack — same nudge, same silence)
scripts/engram.py   deterministic core: FSRS-4.5, state, receipts, stats, dashboard, selftest
docs/               theory · prior art · architecture · roadmap
INSTALL-CODEX.md · INSTALL-HERMES.md · INSTALL-OPENCLAW.md    per-platform glue, at the repo root
```

One codebase, many agents: `skills/` and `scripts/engram.py` are shared verbatim; each platform gets its own thin glue (manifest, subagent format, or hook adapter). See [INSTALL-CODEX.md](INSTALL-CODEX.md) · [INSTALL-HERMES.md](INSTALL-HERMES.md).

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
| [docs/05-affective-layers.md](docs/05-affective-layers.md) | The motivation & wisdom layers (v0.4): two new pillars — competence salience and the mentor stance — each evidence-cited and adversarially checked; the ADHD Focus profile; why no gamification |
| [docs/06-visual-encoding.md](docs/06-visual-encoding.md) | The visual-encoding audit (v0.5): P15 — the guided manipulable; when interactive visuals help (and the boundary conditions that are just as robust); the viz affordance taxonomy, visuals dial, and per-learner medium telemetry; what the audit killed and what stays honestly open |
| **[docs/07-the-measured-loop.md](docs/07-the-measured-loop.md)** | **The frontier audit:** why "learning rate" is the wrong vector, what actually determines whether you come back, whether an LLM grader can be trusted, and which memory neuroscience is actionable vs. decoration |
| **[docs/08-vision.md](docs/08-vision.md)** | **The vision:** the one number Engram exists to move, which appealing metrics are traps, and the final state — tutor → instrument → commons. Includes the exhibit: the founder's own memory decaying on schedule |
| **[docs/09-target-architecture.md](docs/09-target-architecture.md)** | **The target engine:** schemas, the nine new commands, the invariants that must never break, and the order of operations |
| **[docs/10-roadmap-to-1.0.md](docs/10-roadmap-to-1.0.md)** | **The road to 1.0:** v0.6 → v1.0 as executable work orders — why / what / done / selftests / risk, each shippable by someone who has never seen the repo |
| **[docs/11-the-procedure-gap.md](docs/11-the-procedure-gap.md)** | **The procedure gap (v1.1's theory):** Engram was braced for the conceptual half of math & STEM and blind to the procedural half — Pillars 16–17 (the example ladder; the problem as the probe), adversarially verified by three refute-first passes that corrected five claims and inverted one design rule before code shipped |
| **[docs/12-procedure-layer-work-order.md](docs/12-procedure-layer-work-order.md)** | **The procedure layer's build:** architecture + work orders (WO-1…WO-8), the compatibility doctrine (no breaking changes, no domain mode — Engram stays general), and the pre-answered numbers audit for `by_kind` |

## More from the same workshop

Five Claude Code plugins from the same workshop. Most share one habit: *let a deterministic core decide, and never let the producer of work grade it.*

- **[effortmining](https://github.com/nagisanzenin/effortmining)** — benchmark-calibrated per-subagent reasoning effort: dispatch the cheapest tier a blind grader still accepts. ~64.7% fewer output tokens at equal quality, pre-registered.
- **[idiolect](https://github.com/nagisanzenin/idiolect)** — human-voice writing engine: 60+ measured voices plus a deterministic AI-tell scanner and a blind auditor, so text reads like a person, not a model.
- **[production-grade](https://github.com/nagisanzenin/claude-code-production-grade-plugin)** — turns "build me X" into a gated multi-agent pipeline (architecture → tests → security → CI/CD) with a receipt for every phase. Engram's verification patterns started here.
- **[less](https://github.com/nagisanzenin/less)** — a minimal comms protocol for Claude: a per-turn hook makes replies answer-first, pick-list-driven, and calm, without touching the work.

---

## Stars

If Engram earned its keep, a star helps the next person find it.

[![GitHub stars](https://img.shields.io/github/stars/nagisanzenin/engram?style=for-the-badge&logo=github&label=Stars&color=gold)](https://star-history.com/#nagisanzenin/engram&Date)

<sub>GitHub restricted the stargazer-timeline API to repo collaborators, so the live history chart no longer renders inline. Click the badge for the interactive graph.</sub>

---

<sub>*An <b>engram</b> is the physical trace a memory leaves in neural tissue (Semon, 1904; experimentally located by Josselyn, Tonegawa et al. in the 2010s). Building durable ones is literally this plugin's job.* · MIT license · [changelog](CHANGELOG.md)</sub>
