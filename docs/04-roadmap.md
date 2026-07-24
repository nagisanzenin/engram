# 04 · Roadmap, Metrics, Risks, Constitution

> **Status: Phases 0–5 are complete** (shipped through v0.5.2). This document is now history —
> a record of how Engram was built, and the source of the ten-article constitution, which
> remains binding.
>
> **The road from here is [`10-roadmap-to-1.0.md`](10-roadmap-to-1.0.md)**, driven by
> [`08-vision.md`](08-vision.md) (what to maximize, and which appealing metrics are traps) and
> specified in [`09-target-architecture.md`](09-target-architecture.md).
>
> One correction this document earned the hard way: the north star below — *"7-day and 30-day
> retention on scheduled reviews"* — was **named in Phase 0 and never implemented**. `stats` has
> no time-based retention metric to this day. Naming a metric is not measuring it. `docs/08`
> §2 and `docs/10` v0.6 exist to fix exactly that, and the constitution gains an eleventh
> article (`docs/08` §7) that this document was missing.

The plan is phased so that **every phase ends with a measurable learning outcome, not a feature list** — oracle-driven development applied to the product itself. Timeless by construction: the constitution and schemas survive model upgrades; content is generated fresh per learner, so nothing rots.

---

## Phases

### Phase 0 — Ratify (this document set)
Theory locked, constitution adopted, name chosen. **Exit:** founder signs off on the four pillars, the rejections (no learning styles), and the three-verb surface.

### Phase 1 — The Engine (core loop, no frills)
State schemas + `state.py` validation; `fsrs.py` (tested against reference vectors); `/learn` (frontier diagnosis → dialogue grammar → assessor receipt → schedule); `/review`; session hooks (re-anchor + flush). Text-only artifacts. One real topic learned by the founder end-to-end.
**Exit criteria (oracle):** a topic of ≥15 nodes learned; 7-day-delayed free-recall review ≥80% `recalled|partial`; every mastery state backed by a receipt; zero LLM-computed schedule dates (all from `fsrs.py`).

### Phase 2 — The Medium (explorable engine)
artifact-smith + Explorable Contract + first six widget templates; embedded retrieval feeding FSRS; threshold-concept auto-artifacts; blank-page reconstruction endings.
**Exit criteria:** every threshold node in a test topic ships a Contract-compliant explorable (all seven clauses machine-checklisted); founder A/B on self: artifact-encoded nodes vs. dialogue-only nodes, compare 7-day retention receipts. *(Instrumented in v0.5: receipts stamp the encoding medium at grading time and `stats.modality` computes the comparison — `docs/06-visual-encoding.md`.)*

### Phase 3 — The Mirror (learner model & coach)
Full telemetry; calibration tracking with confidence-before-feedback everywhere; monthly FSRS refit; `/coach` with weekly HTML dashboard (mastery map, retention curves, calibration plot); first n-of-1 experiment run to verdict (derivation-first vs. example-first, per domain).
**Exit criteria:** one experiment settled with a written verdict and an updated `strategy_weights`; dashboard renders from real data; coach explanations cite the learner's own numbers.

### Phase 4 — The World (transfer & situated learning)
BUILD capstones in the learner's real repos (`TODO(human)` pattern); cross-context transfer probes; opportunistic ambient mode (rate-limited); teach-back mode with a naive-student persona; misconception catalog driving contrast cases.
**Exit criteria:** one capstone artifact shipped in a real project and graded `transfer: true`; one week of ambient mode with zero user-reported annoyance.

### Phase 5 — The Gift (packaging)
Marketplace packaging; onboarding-as-first-lesson (the system teaches learning science using itself); docs; privacy statement (all state local, user-owned); migration tooling for schema versions.
**Exit criteria:** clean install on a second machine; a second human completes onboarding and their first scheduled review unaided.

Sequencing note: the engine precedes the medium **deliberately** — beautiful artifacts without the retention engine would be the fluency trap this project exists to defeat.

## Metrics (what "effective" means here)

**North star: 7-day and 30-day retention on scheduled reviews** (free telemetry — the review queue *is* the measurement instrument). Supporting: calibration (Brier score trend), transfer rate (receipts with `transfer: true` / topics completed), time-to-mastery per node (efficiency), consistency (sessions/week — the habit metric that predicts everything else). **Vanity metrics explicitly banned:** completion %, streak length as a goal, minutes spent, cards created.

## Risks

| Risk | Mitigation |
|---|---|
| **Sycophantic drift** — tutor caves, assessor inflates | Separation of powers; assessor sees no dialogue; rubric citations mandatory; periodic audit prompts ("would an exam grader accept this?"); appeals logged as calibration data |
| **Fluency theater** — gorgeous artifacts, no retention | Explorable Contract machine-checklist; Phase 2 exit A/B; retention is the north star, not artifact count |
| **Review abandonment** (the Anki graveyard) | Two-minute floor; ambient one-line nudges; interleaved variety; coach renegotiates load when overdue queue grows (FSRS handles backlog gracefully) |
| **Schema drift** (observed in claude-tutor) | All writes through `state.py` validation; schemas versioned; hooks refuse malformed state |
| **Scope creep** | Constitution + three-verb cap; new features must cite a foundation principle or be rejected |
| **Over-testing turns joy into homework** | Difficulty setpoint includes motivation signals; autonomy preserved (learner picks topics/goals); curiosity-first session openings; BUILD phases deliver intrinsic payoff |
| **LLM grading leniency/variance** | Rubrics with anchor examples; spot audits; grade distribution monitoring in coach |
| **Privacy** | Everything local files; nothing leaves the machine; stated in README |

## The Constitution (twelve articles)

1. **Retrieval is the interface.** Knowledge is claimed by producing, never by recognizing. "Makes sense" is zero evidence.
2. **Nothing is learned until it is scheduled.** Every concept carries a future date or it doesn't exist.
3. **Difficulty is a setpoint, not an accident.** Boredom and frustration are both bugs; ~85% is the cruising altitude.
4. **Every artifact demands action.** No reveal without a committed prediction. Beauty that permits passivity is a defect.
5. **Derive the derivable; memorize only the arbitrary.** Chain-of-necessity for structure, mnemonics for the rest, and the DAG knows which is which.
6. **Confidence is data.** Collected before feedback, tracked forever, shown to its owner. High-confidence errors are treasure.
7. **Adapt on evidence, never taxonomy.** No learning styles. The learner model is fitted from receipts; strategies win n-of-1 trials or lose their weights.
8. **Meet the learner in their real work.** Examples from their world; transfer into their projects; presence where knowledge is used.
9. **The learner sees their own model.** Open files, explained adaptations, taught science. No pedagogy behind the learner's back.
10. **Receipts or it didn't happen.** Every mastery claim has a grade trail; every adaptation has its evidence; the oracle is never a vibe.
11. **The system's success is measured by what the learner can do without it.** (Added in `docs/08` §7 — an AI tutor that makes you dependent has rented you a capability, not taught you one. The review is structurally a test of independence.)
12. **Adaptation is proposed, consented, logged, and reversible.** (Added in v1.8.) Every change the *system* suggests to how it teaches is **computed by the engine from receipts**, **offered with its evidence quoted**, **applied only on an explicit yes**, **written to an append-only ledger with that evidence**, and **undoable**. The engine never infers a trait, never applies a change itself, and steers only on the handful of adaptivity families that survived their own literature — assistance level from demonstrated prior knowledge, scheduling from individually fitted forgetting, metacognitive prompts that are specific and fading, and small real choices. *A system that adapts to you is one hallucinated correlation away from a horoscope; the ledger is what keeps the difference visible.*
