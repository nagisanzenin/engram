# 13 · The Adaptive Instrument: The Evidence Audit for v2.0

> **Status: theory, adversarially verified — the buildable form is
> [`14-roadmap-to-2.0.md`](14-roadmap-to-2.0.md).** Drafted 2026-07-24 from a live probe of
> v1.2.2 (the founder's real state plus a full-lifecycle sandbox under `ENGRAM_TODAY` time
> travel) and **seven independent refute-first research passes** (successive relearning ·
> the FSRS ecosystem · LLM-grader validity 2025–26 · adherence round two · retrieval
> formats · time-budgeted review ordering · adaptivity-that-works), each instructed to hunt
> the strongest refutation of every claim before letting it stand. Load-bearing numbers
> were spot-verified against primary sources a second time during synthesis. What was
> killed is listed as prominently as what survived, per house rule.

The founding question, in the founder's own words (2026-07-24):

> *"The most robust generalized learning system, where a learner can learn anything at any
> level of mastery. The system itself must be smart and adaptive and evolve with the user,
> to meet their needs and preferences, to improve their learning effectiveness."*

The verdict, stated up front so the rest can be checked against it:

> **Engram v1.2.2 is a complete, honest MEASUREMENT system bolted to an adaptation layer
> that is still mostly prose.** The instrument half is genuinely done: adherence, retention
> with its unmeasured denominator, decay, transfer, kinds, modality, calibration, momentum,
> and an audited (if locally-unrun) grader. What does not exist is the CLOSED LOOP the
> founding question asks for: measurements → engine-computed adaptation → consent → applied
> → re-measured. The learner model has exactly **one** fitted parameter (a coarse interval
> multiplier, never yet earned by any real user); `challenge_band` has never moved;
> `rhythms` is written by nothing; `strategy_weights` can be moved by exactly one
> experimental question; the pretest walks three nodes whatever the learner already knows;
> and the strongest licensed adherence intervention in the codebase — the
> learner's own if-then plan (d = 0.65 for goal attainment broadly; an honest
> d ≈ 0.14–0.31 in behavior-specific metas, still the largest lever on this list) — is
> stored and **never once shown back**. v2.0 is not a
> smarter tutor (docs/07 §1 still stands: the ceiling is behavioral, not cognitive). It is
> the system finally *steering* on the numbers it already computes — every adaptation
> engine-owned, consent-gated, and honest about which of its rules are evidence and which
> are model-derived engineering.

---

## 0 · Method, and the scorecard

Two instruments, same discipline as docs/05/06/07/11:

1. **The live probe.** Read-only diagnostics on the founder's real state (3 topics, 62
   nodes, 42 receipts) plus a full lifecycle in an isolated `ENGRAM_HOME` — encode →
   blind-shaped settle → double-apply → reviews at +4/+13/+29 days → transfer probe at
   maturity → experiment start/assign/settle → export → deliberate corruption. Every guard
   held (§1.A). Ten defects/gaps found (§1.B), each verified in code, not inferred from
   docs.
2. **Seven refute-first research passes**, each a separate uncontaminated agent with the
   standing instruction to *break* every claim against primary sources before keeping it.
   Between them: ~40 full-text/PDF reads, ~200 sources checked. Synthesis re-verified the
   claims that became load-bearing (e.g. the PNAS 2024 cue-variability effect sizes were
   re-fetched and re-read during authoring).

Scorecard, kept honestly (counts are per-pass verdict lists):

| Pass | Confirmed | Killed / weakened | The kills that matter most |
|---|---|---|---|
| Successive relearning | 10 | 7 | initial criterion 3 (the 2011 abstract's own prescription — the fuller data kills it); SR for procedures (boundary condition); the d = 4 headline sizes (exposure-confounded; honest size d ≈ 0.7); immediate re-asks |
| FSRS ecosystem | 8 | 7 | FSRS-7 adoption (unshipped, moving spec); auto-recommended optimal retention (**Anki itself removed it**); the "400 reviews before fitting" floor; "fitting needs an ML framework" (production fsrs-rs is framework-free) |
| LLM-grader validity | 7 | 5 | multi-model judge panels (validity theater); "consistency ≈ trustworthiness" at 541k-judgment scale |
| Adherence round two | 8 | 6 | streak-freeze "science" (vendor marketing); habit-stacking branding; "66 days" as a constant; cohort/body-doubling claims |
| Retrieval formats | 7 | 4 | delayed feedback (preregistered 38-class null); teach-back superiority (expectancy artifact); "identical probes = answer memorization" (overstated) |
| Review ordering | 6 | 5 | **most-overdue-first (Engram's own shipped order)**; the 85% rule as an ordering license (category error); MEMORIZE as a triage warrant |
| Adaptivity | 7 | 9 | the general ATI program (one survivor: prior-knowledge × guidance); the 85% rule as a human-learning law; learner control over method (worse than non-personalized); DKT/BKT at Engram's n; chronotype scheduling |

---

## 1 · The live audit of v1.2.2

### 1.A What is solid (verified by execution, not by reading)

selftest 234/234 · receipt idempotency under double-apply · a failed transfer probe leaves
the memory schedule byte-identical (s 71.15 → 71.15) while `transfer.state` advances ·
immature-transfer ingest refusal · experiment guards (unknown metric dies; assignment
seeded, stratified, sticky; settle refuses `--verdict`; below-power settle returns nulls) ·
export refusal on an unaudited grader, constitution in the error text · corruption
quarantine with degrade-not-brick reads and a doctor that names the file · the
decay/adherence/retention triad computing honest numbers on real state, unmeasured
denominator populated. **None of this is up for renegotiation in v2.0.** The invariants of
docs/09 §2 carry forward whole.

### 1.B The gaps (each verified in code or live state, none inferred)

| # | Gap | Evidence | Class |
|---|---|---|---|
| G1 | **The commitment is stored and never shown back.** `commit` writes `settings.commitment`; no *surface* ever displays it — not the hook, not `/review`, not `/coach` (`/learn` §6 reads it only to avoid re-asking). The founder's own plan (*"tomorrow / i wil clear these"*, set 07-23) came due during this probe; the ambient surface said nothing. docs/09 §3.1 promised "shown back at the moment it names." | `grep commitment` → one writer, no display path | transfer_probe-class: authored, displayed by nothing — on the strongest licensed adherence lever in the repo (d = 0.65 broad / 0.14–0.31 behavior-specific — §2.1) |
| G2 | **The self-grading audit trail evaporates.** `/review` §3 spawns assessor audits (tutor rating vs blind grade, `agree` per item) and then "logs a note." Nothing structured persists; `KINDS` has an `audit` slot the receipts never use for this; `stats` has no tutor-vs-assessor number; coach prose says "drift is the coach's monthly business" with no number to read. v1.1.1 already named the tutor "the one grader `/coach audit` never measures" — and the tutor writes **all** review receipts and every `error_class` in `procedure_slip_share`. | skills/review §3; `grep` | measurement hole under a shipped number |
| G3 | **Grader audits never expire.** No model identity, no staleness check: an audit passed under one model silently vouches for its successor after a platform upgrade. Compounding: even the founder's machine is unaudited — 42 receipts, every retention figure stamped unearned, because the 4-minute audit has no offered-at-the-right-moment path. | `_latest_audit` reads newest, unconditionally | validity hole (§2.4 makes it urgent) |
| G4 | **`rhythms` is authored and dead.** The engine defines `rhythms: {}`; nothing writes it; `/coach schedule` "reads" a permanently empty dict. | `grep rhythms` | honesty defect: a promised adaptation surface that cannot fire |
| G5 | **`challenge_band` never adapts.** Bounded, settable, read by dialogue prose — and no mechanism ever proposes a change from measured receipts, despite docs/03 §5 promising exactly that ("hint ladder exhausted often → adjust budget"). | `grep challenge_band` → schema + bounds only | the adaptation policy is prose |
| G6 | **The experiment engine can ask exactly one question.** `metric` supports only `first_review_recall`; `strategy_weights` can therefore only ever be moved by that one comparison. | `unknown metric` error text lists one | adaptivity ceiling |
| G7 | **The pretest walks the first 3 nodes of `order`, whoever you are.** An expert entering a 20-node topic gets a novice's walk; "any level of mastery" currently means "any level, after you sit through the frontier from node one." | skills/learn §2 | the founding question's "any level" clause, unmet |
| G8 | **The hook presents the full debt every session.** "28 reviews due · ~17 min" — cap-blind, profile-blind; amnesty framing exists only inside `/review`. The v0.6 "offer, not announcement" landed as announcement-only. | `cmd_session_start` | tension with docs/05 P14 (the wall of debt) |
| G9 | **The catch-up order is the one order with evidence against it.** `/review`'s amnesty serves "most-overdue first" — and the order is engine-implemented, not just prose: `due_items` sorts overdue-descending and `--limit` truncates it, so **every capped queue ever served was ordered by the policy the evidence ranks worst-tier**. One strong human RCT for the rival policy family, convergent simulations against due-date-ascending (§2.2). | skills/review §1 + `due_items` sort feeding `--limit` | shipped heuristic, engine-deep, now contradicted |
| G10 | **Structural dead-ends.** The architect's ~7 silent minutes remain the most likely first-session abandonment point (RELEASE_PROTOCOL §5.6 user-session record); a finished topic dead-ends at ~20 nodes with no extension flow (the founder hand-labels topics "Arc 1 of 2"); quarantine has no guided repair; a failed artifact registration waits for a human to notice a doctor note. | live state + the §5.6 session reports | robustness/UX |

**The shape of the list is the finding.** G1, G2, G4, G5 are all the same species — *a
surface the docs promised, the schema holds, and nothing computes* — which is exactly what
docs/09 §1 found in v0.5.2 (`transfer_probe` authored, read by nothing). The instrument
layer got built because v0.6–v1.0 hunted that species deliberately. The adaptation layer
never got its hunt. v2.0 is that hunt.

---

## 2 · The evidence

### 2.1 Adherence, round two — what is licensed beyond what shipped

v0.6 shipped the implementation intention (`commit`), amnesty, the honest decay line, and
the two-minute floor. The refute-first pass on everything since:

**Confirmed, and buildable:**

- **Showing the learner's own plan back, and renewing it, is direct-RCT-licensed.**
  Messmer et al. 2022 (*Applied Cognitive Psychology*, 2×2×4 RCT, N=118 analyzed):
  implementation intentions AND reminders-of-the-plan each carried significant effects
  across four weeks. Prestwich et al. 2010 (*Health Psychology*, N=149): SMS *plan*
  reminders sustained the effect; plan-reminder recipients remembered their plans better.
  Boundary honesty: the celebrated d = 0.65 (Gollwitzer & Sheeran 2006) is goal-attainment
  broadly; behavior-specific metas run d ≈ 0.14–0.31 — assume the small number. Effects
  decay over weeks; renewal cadence is untested (inference, labeled). → **G1's fix is not
  just spec-compliance; it is the evidenced half of the intervention Engram already
  bought.**
- **Anchor quality matters: event cues beat time cues.** Judah, Gardner & Aunger 2013
  (flossing *after* brushing > before); Stawarz/Renfree (CHI 2016 line): event-based cues
  built automaticity, time-based reminders supported repetition but *hindered* habit
  formation. → a one-time, declinable coaching move at `commit` time ("after [an existing
  routine]" > "at 9pm"), never re-raised.
- **Honest expectation-setting.** Lally et al. 2010: median 66 days to automaticity, range
  18–254, half never plateaued; Buyalskaya et al. 2023 (*PNAS*, 12M gym observations):
  ~68–78 days for gym-class behavior, duration behavior-dependent. Single misses don't
  matter (already Engram's amnesty line). → one flat line at first lapse; **never** a
  countdown, because the constant doesn't exist.
- **The fresh-start effect survived, with a sharp boundary.** Beshears, Dai, Milkman &
  Benartzi 2021 (*OBHDP*, field RCT, N=6,082): fresh-start framing raised contributions
  ~25% over 8 months. Dai 2018: resets help strugglers and *demotivate high performers*.
  → a restart offer is licensed **for lapsed learners only**, at the moment they show up,
  never as outbound push, never countdown-framed.
- **The return-after-a-miss moment is the highest-leverage moment measured anywhere in
  this literature.** Milkman et al. 2021 (*Nature* megastudy, 61k gym members, 53 arms):
  the top arm rewarded *returning after a missed workout* (+27% visits), beating every
  conventional incentive. The token is constitution-forbidden; the mechanism — make the
  return cheap, positively marked, never debt-laden — is shipped amnesty, externally
  validated. → v2.0 extends it (G8, G9) rather than inventing anything.
- **Retiring items is honest and evidence-adjacent.** Value-directed remembering (Castel
  line, through 2025): learners are already strategic droppers; selectivity is a
  competence, not a failure. The causal link retire-mechanics → adherence is **untested**
  (open). → `retire` ships as an autonomy verb with honest denominators ("12 due · 40
  retired by you"), never as an auto-suggestion to flatter metrics.

**Killed, and staying dead:** streak freezes as science (the published record is one KDD
2020 notification-bandit paper with +0.5% DAU / +2% new-user retention; everything else is
vendor marketing); "habit stacking" as a branded method (the kernel — anchor to existing
routines — is the evidenced part); "66 days" as a usable constant; cohort/body-doubling
completion claims (marketing selection effects; the 2024–26 record is self-report surveys
and lab task performance, not longitudinal adherence); microlearning completion statistics
(untraceable vendor numbers); daily reminders (habituation is directly measured — weekly
beats daily; and at-scale text coaching produced a null on real outcomes, Oreopoulos 2020).
Reminders in general: true effect d ≈ 0.29 and habituating — if Engram ever adds any, they
are user-scheduled, sparse, plan-quoting, self-attenuating, and the frequency can only
ratchet *down*. Nothing here reopens streaks, XP, or social features.

### 2.2 Review ordering under a time budget — the one shipped heuristic the evidence contradicts

The question a capped session actually asks: the learner will clear K of N due items —
*which K?* Evidence, graded ruthlessly (HE = human experiment · SIM = simulation · CH =
community heuristic · INF = inference):

- **[HE] Model-based selection under an equal, budget-matched review allocation beat both
  massed and one-size-fits-all spacing in a real semester-long classroom.** Lindsey,
  Shroyer, Pashler & Mozer 2014 (*Psychological Science*, N=179, within-subject,
  counterbalanced, equal review trials per arm): +16.5% vs massed (d = 1.42) and +10.0% vs
  generic spacing (d = 0.88) on a 28-day-delayed exam. The deployed policy family:
  *serve the item whose predicted recall is closest to a threshold* (θ ≈ 0.33 came from
  the companion simulations). One study, vocabulary, one population — say so.
- **[HE] Hardest-first loses.** Eglington & Pavlik 2020 (*npj Science of Learning*):
  scheduling practice at high predicted success beat hardest-first *and* easiest-first on
  retention per unit time — failures are slow, and the budget is time, not items.
- **[SIM] The FSRS world's own answer.** The open-spaced-repetition sort-order simulations:
  with no budget, order doesn't matter; under a budget, **descending retrievability** wins
  and **due-date-ascending (most-overdue-first) is worst-tier** — a deeply overdue item
  sits on the flat tail of its forgetting curve and loses almost nothing more by waiting,
  while the near-threshold item is the one still cheap to save. Circularity stated: the
  simulator's ground truth is FSRS itself.
- **[TH] MEMORIZE (Tabibian et al. 2019, PNAS) licenses none of this** — it is a
  single-item *timing* result with no budget construct; citing it for triage would be a
  misuse. **And Wilson et al. 2019 (the "85% rule") licenses nothing here either** — it is
  a gradient-descent learning-speed derivation, not a human motivation or adherence
  result. Both stay in the codebase's vocabulary only where they already honestly sit.
- **[OPEN] No human RCT of backlog-clearing order exists.** Anyone claiming otherwise is
  wrong as of 2026-07. The session-composition → return-tomorrow link is unmeasured in
  either direction.

**Design consequence (the honest composite, labeled as such):** for capped sessions and
amnesty catch-ups, rank due items by **expected 30-day retention saved per expected
minute** — the exact quantity `decay` already computes per node, divided by an expected
time cost that prices failures as slower (Eglington & Pavlik's point) — **with an explicit
floor under the hopeless**. *(Corrected in the v1.3 build, and the correction is the
interesting part: the raw ratio does NOT deprioritize the nearly-lost, because reviewing a
near-dead concept resurrects it. Measured, the curve is an inverted U whose peak sits at the
mid-band boundary of the engine's own `DUE_MINUTES_BY_R` constants — **not a derived
optimum**. An earlier draft called this an independent reproduction of Lindsey's
θ ≈ 0.33; it is a coincidence of calibration, and claiming otherwise would be the
circularity this document spends a section warning about. The peak is kept; items
below R = 0.10 are parked as `effectively_relearn`, since a one-shot horizon knapsack cannot
see that a resurrection consumes several more reviews of future budget.)* The ranking
therefore deprioritizes both the nearly-lost (parked explicitly, un-guilted, or retired) and
the barely-due (little at stake). The formula is a synthesis [INF] inside an evidenced
family [HE+SIM]; the engine must label it model-derived, and most-overdue-first should
survive only as a user-selectable completeness option. **This is a rare case of the
evidence demanding a change to shipped behavior** (G9) — the current default is the one
order every budgeted analysis ranks at the bottom.

### 2.3 Retrieval formats for concepts — what varies, what doesn't

- **Identical probes are not the catastrophe intuition says — but varied cues are
  measurably better, and the benefit compounds with spacing.** Repeated identical-question
  testing itself transfers (Butler 2010; Pan & Rickard 2018: format-shift transfer
  d = 0.58). The sharpening: Butowska-Buczyńska, Kliś, Zawadzka & Hanczakowski 2024
  (*PNAS*, 7 experiments — numbers re-verified against the paper during synthesis):
  varied contextual retrieval cues beat constant ones for the *same* target — immediate
  d = 0.81 / 0.67; and the spacing benefit was larger under varied cues (d = 0.87) than
  constant (d = 0.52). Learners' metacognition inverted (they judged constant cues more
  effective, d = 0.73). **Boundary, stated plainly:** materials were Finnish vocabulary
  and one lecture experiment; nobody has tested probe variation for *rubric-graded
  conceptual free recall*. → licensed as a **pre-registered n-of-1 experiment**, not a
  default: paraphrase/context-shift the probe, rubric held fixed, graded by the same
  blind assessor — the experiment engine is the right tool and needs G6 fixed to run it.
- **Teach-back is an equal-strength variant, not an upgrade — and the upgrade numbers
  belong to a different effect.** Kobayashi 2024 (*Educ Psych Review* meta, 39 studies):
  teaching-after-study g = 0.27 overall, but **with teaching expectancy at encoding
  g = 0.48 vs without g = −0.02** — the headline effects are carried by *expecting to
  teach while learning*, which a review-time teach-back does not have. Koh, Lee & Lim
  2018: teaching-without-notes = plain retrieval practice at one week. → "explain this to
  a student who has never seen it" is licensed as an occasional probe *reframe* (it is
  still free recall, same rubric) and as cue variability — never marketed with the
  expectancy numbers.
- **Whole-topic free recall ("rebuild the argument skeleton") is strong within-session
  science with zero spaced-session studies.** Roediger & Karpicke 2006: 61% vs 40% at one
  week over rereading; Karpicke & Blunt 2011 held up through the replication era;
  O'Day & Karpicke 2021: adding concept mapping to retrieval added nothing over retrieval.
  Weakened honestly: Mayrhofer et al. 2023 (N=230) shows the retrieval-vs-*elaboration*
  margin shrinks under matched time-on-task (the retrieval-vs-restudy result stands). →
  a low-frequency topic-level recall session is an n-of-1 candidate, not a default.
- **Feedback timing: keep immediate, and stop wondering.** ManyClasses 1 (Fyfe et al.
  2021 — preregistered across 38 real college classes): timing effect 0.002 [−0.05,
  0.05], all 40 preregistered moderators null. The lab delayed-feedback advantage was
  always confounded with spaced re-exposure (Kulik & Kulik 1988).
- **Typed production is a verification cost, not a memory tax or a memory boost.** Smith,
  Roediger & Karpicke 2013: covert retrieval retains as well as overt. Engram requires
  typed production *so the blind grader can exist* — the honest label is "cost of
  receipts," and the license is that it costs the memory nothing.
- **No retrieval-induced-forgetting guards needed.** Murayama et al. 2014 (*Psych
  Bulletin*): RIF overall g = 0.35 but **g = 0.01 under high integration** (and can flip
  to facilitation at delay, Chan 2009). Engram's first-principles DAGs are the
  high-integration cell; the risk concentrates in isolated list-like facts, which the
  `arbitrary` flag already marks.
- **One new hard rule, imported from a bias-robust negative result:** interleaving
  retrieval of *old* material into the middle of *new* encoding hurts the new learning —
  interleaved designs g = **−0.56** (Boustani & Shanks 2022 reanalysis of the
  test-potentiated-new-learning corpus; the forward-testing effect itself survives
  bias-correction only in pre-testing designs, and dies with a lag). Engram's shipped
  review-before-learn ordering is the right side of this; the rule "reviews first or
  after, never interwoven mid-encode" gets written into the grammar as law rather than
  habit.

### 2.4 The grader, round two — the instrument ages, and the mid-band is soft

v0.7/v1.1 built the audit; the 2025–26 literature says three things the audit does not yet
know:

- **The validity picture is quality-conditioned, and the fragile band is exactly
  `partial`.** The Weizmann/ETS quality-conditioned ASAS study (2026): rubric-anchored
  LLM graders near-perfect at the extremes and **>2 rubric categories off in 47/48
  GPT-model results for mid-range gold scores**, while the second human showed no
  mid-band degradation at all. Engram's headline QWK vs authored gold is not evidence of
  mid-band validity unless the audit *stratifies by band*. → audit gains per-band
  reporting; the gold set's partial-boundary items become their own reported row.
- **Self-consistency without a bias probe is now a named anti-pattern at 541k-judgment
  scale.** "Reliability without Validity" (2026, 21 judges, ~541k judgments): production
  judges with test-retest > 0.95 coexisting with position bias > 0.10; exact-match
  agreement overstates κ by 33–41 points. Engram's paradox gate predates this and is
  vindicated by it; the audit should cite it and never loosen.
- **Judge drift on model change is real, measured, and leniency-shaped.** "Who Drifted?"
  (2026): a silent judge-model swap was detected 60/60 as judge drift, running uniformly
  *more lenient* — precisely Engram's dangerous direction; naive rolling z-tests
  false-alarmed on 75% of drift-free streams. A PLoS ONE 2026 longitudinal study needed
  *weekly* judge recalibration to hold human agreement. → **audits must expire.** Stamp
  the grader context (platform/model label, supplied by the skill that spawned the runs);
  hard-expire the badge on a context change; offer a cheap **canary re-audit** (a fixed
  ~12–15-item subset oversampling `partial` gold and the two historical-inflation items)
  before demanding the full 86×3 ceremony; time-expire (90d) when the context is unknowable.
- **Multi-model panels are refused, with numbers.** "Nine Judges, Two Effective Votes"
  (2026): a 9-frontier-judge panel delivers ~2 effective independent votes; the best
  single judge matched or beat the panel in all conditions. Engram keeps same-model
  multi-run (its 3 independent runs match the field's majority-of-3 practice) and spends
  the saved budget on the two upgrades with measured payoff: band-stratified reporting,
  and —
- **Spec-paraphrase consistency: the failure class that actually bit us, now
  benchmarked.** JudgeSense (2026): flip rates under semantically-equivalent grader-prompt
  paraphrases range 0.8%–61.3% across models; deployment threshold ≥0.90 consistency.
  Both of Engram's real measured inflations were instruction-ambiguity, not model
  leniency. → the audit gains an optional **spec-mutation pass**: 3–5 paraphrases of the
  grading spec over the gold set, flip rate reported. Engram would be early here, and
  says so, rather than claiming precedent.
- **The tutor gets an honest audit path at last (G2).** The tutor cannot be spawned blind
  — dialogue context is a permanent confound, so no blindness property is ever claimed.
  What CAN be measured is operational scoring's *read-behind*: persist the existing
  `/review` §3 audit outcomes as non-scheduling receipts; compute **tutor-vs-assessor
  agreement (QWK) and signed tutor bias relative to the assessor**, oversampling
  `partial`s (the band where graders diverge); surface disagreements to the learner
  instead of resolving them silently. The limitation line ships with the number: *tutor
  grades are audited for agreement with the blind assessor, whose own validity is what
  the 86-item audit measures — tutor validity is bounded by that chain, never better.*
- **The external-human adjudication kit gets a real protocol** (the repo has asked for
  one human since v0.7; now it has a defensible procedure): one external adjudicator,
  blind to author labels and audit history; a 10-anchor calibration gate (≥80% exact on
  anchors before proceeding); independent pass over all 86; report exact agreement, QWK,
  ordinal Krippendorff's α with bootstrap CI, per-category confusion with signed
  direction; α ≥ 0.80 → "externally corroborated," 0.667–0.80 → "tentative," below →
  contested and the circularity disclosure stays at full strength; pre-adjudication
  numbers are the only ones that count as independent. Context printed beside it: trained
  human experts average ~60% exact / QWK ≈ 0.65 on 5-point rubrics — chance-corrected or
  nothing. One external rater *corroborates* the authored gold; only ≥2 independent
  externals with α ≥ 0.80 among themselves would *replace* it. Said out loud, as always.

### 2.5 Successive relearning — the strongest unexploited retention finding

docs/07 §2 flagged it and ordered it specified against primary sources before building.
The pass read the primaries (Rawson & Dunlosky 2012 EPR full text carrying the 2011
protocols; Higham et al. 2022 accepted manuscript; Badali & Greve 2023; Karpicke &
Roediger 2008 *Science*) and hunted the exposure-confound critique deliberately.

**The protocol, exactly (Rawson & Dunlosky 2011, *JEP: General*, N=533 across 3
experiments):** cued recall → feedback → failed items go to the **back of the queue**
(dropout; never an immediate verbatim re-ask) → session ends when each item reaches
**one** correct recall; then **spaced relearning sessions** (first at +2 days, then a few
days apart), each again to criterion 1.

**Confirmed, with numbers:**

- **Relearning sessions are the dominant lever; the dose-response is the largest effect
  in this entire audit.** 3 vs 1 relearning sessions: +60% relative recall at one month;
  5 vs 1: +86% at one month, +64% at four. Same-count comparison — one initial correct +
  three spaced relearning vs three initial corrects + one relearning (four successful
  retrievals either way): **53% vs 40%** at one month. Rawson et al. 2018: one correct in
  each of three spaced sessions vs three corrects massed in one: **68% vs 26%** at one
  week.
- **Initial criterion above one buys almost nothing once relearning follows** ("the
  relearning override," Vaughn et al. 2016): criterion-3's early advantage closes after
  relearning; nonsignificant at 1/4 months in the fuller analyses; ~2 extra minutes per
  concept not recouped.
- **Relearning gets cheap fast — the savings signature.** ~5 min/concept initially →
  <1 min by the fifth session; Higham 2022: first-pass recall .24 → .68 → .82 and
  trials-to-criterion 1.95 → 1.37 → 1.20 across three sessions. (Telemetry worth
  surfacing per node: the "relearning gets cheap" curve.)
- **Real-course replications:** ≥10-point exam gains in four independent implementations
  (Sciartelli 2013; Janes 2020 d = 0.54–1.10; Badali & Greve 2023 d ≈ 0.65–0.69 on
  *application* questions; Higham 2022 under exposure control).
- **Diminishing returns after ~3 sessions at few-day gaps** — more sessions pay only at
  widening gaps (which an FSRS-shaped schedule naturally produces). Across-session gaps
  of 2–7 days all worked; the Cepeda et al. 2008 ridgeline puts the optimum near 10–30%
  of the retention interval — ~3–9 days against a 30-day north star.
- **Retrieval, not restudy, is the active ingredient** (Karpicke & Roediger 2008,
  *Science*: keeping items in *testing* after first recall ≈ 80% at one week; dropping
  testing → 33–36%; ~80 extra study trials bought nothing).
- **Self-scored criterion is a documented hazard** (Dunlosky & Rawson 2012: overconfident
  self-scoring quietly never reaches criterion and retention suffers) — direct external
  evidence for Engram's blind-assessor constitution.

**Weakened and killed, honestly:**

- **The headline effect sizes carry an exposure confound.** The only exposure-controlled
  SR study (Higham 2022) finds the pure relearn-vs-restudy effect **d ≈ 0.7** on
  practiced items — large, not the d = 4 of confounded designs. Quote 0.7.
- **Transfer under exposure control is near zero** (d ≈ 0.15, n.s.): SR's verified
  benefit is item-specific durability. The honest claim is "you will still have the
  practiced idea," never "it will generalize" — generalization stays the transfer
  machinery's job.
- **KILLED for procedures:** Rawson, Dunlosky & Janes 2020 (3 experiments, N=431,
  problem-solving): "only meager benefits… relatively low retention." Retry-to-criterion
  is a **concept/fact protocol**; procedure lapses keep the problem-grammar path.
- **No study exists** on SR for rubric-graded conceptual free recall in self-directed
  adults, and none combining SR with an adaptive scheduler. Engram's use is an
  extrapolation, labeled, with the north-star metric as its own validator.

**Design consequence (the buildable rule):** a session should not end at a failed
retrieval. On a lapsed VERIFY or review of a concept/fact node: feedback → re-derivation
or another item intervenes (never an immediate verbatim re-ask) → re-attempt, to **one**
graded success, capped at 3 passes (Higham's cap); the day's first attempt alone feeds
FSRS (the lapse stays honest); retries are recorded as their own receipt rows, excluded
from every retention population (and from `refit` — §2.6's G11 guard). And because the
evidence's real quantity is *spaced sessions in the first weeks* (≥3 before day 30), a
deterministic policy cap on the first two post-encode intervals (min(FSRS, ~3d), then
min(FSRS, ~9d) — inside the Cepeda band) guarantees the dose for new material — a labeled
policy layer over FSRS, engine-owned, off-switchable, applied to newly encoded nodes
only.

### 2.6 The scheduler — FSRS in 2026, and what an honest upgrade looks like

The pass read the live repos (srs-benchmark, py-fsrs, fsrs-rs, fsrs4anki, anki-manual,
Anki releases) rather than summaries — and re-read Engram's own engine against them.

**The ecosystem, verified:** FSRS-6 (21 params, trainable forgetting-curve decay `w20`)
ships in Anki since 25.07 and is what py-fsrs 6.3.1 / fsrs-rs 6.6.2 implement. **FSRS-7
exists** (35 params, dual power-law curve, honest same-day predictions — benchmark
flagship since 2026-03) and ships **nowhere**; the spec moved three times in three months.
Benchmark (anki-revlogs-10k, ~350M reviews, 99% CIs): fitted 4.5 → fitted 6 is
−4.5% log loss / −14.5% RMSE(bins) — real, modest. The row that matters for Engram:
**fitted FSRS-4.5 (0.3624) matches or beats default-parameter FSRS-6 (0.3664) and
default FSRS-7 (0.3629)** — *the fitting is worth about as much as two version upgrades.*
Engram's users run near-defaults today, so a version bump alone buys them nothing
honest to announce.

**The fitting ladder is settled practice, not research:** production fsrs-rs fits
**S0-only (first 4 params) at ≥8 usable items** and the **full vector at ≥64**; the
"400 reviews" floor died in Anki 24.06 (the research behind it: optimizing beats defaults
from ~16 reviews on average). S0-only alone captures **~56% of the default→full-fit gap**.
And the framework myth is dead: **fsrs-rs replaced its ML framework with hand-derived
analytic gradients — the production optimizer inside Anki is framework-free.** A
stdlib-only fit in `engram.py` is therefore not a compromise; the genuinely hard part is
the safety scaffolding (tier gates, S0 priors and monotonicity repair, per-parameter
clamps, and a refuse-if-not-better acceptance check — Anki's "parameters appear optimal"
behavior).

**Optimal retention: Anki removed it.** CMRR — the auto-recommended desired-retention —
was deleted in Anki 25.07 in favor of a workload simulator plus human judgment; py-fsrs's
version demands ≥512 logs *all carrying review durations*, which Engram receipts neither
have nor can honestly attribute (reviews are embedded in tutoring dialogue). → Engram
refuses auto-recommendation and may ship the honest substitute: a workload-vs-retention
trade-off chart from the learner's own parameters, guardrails stated (0.9 default, never
>0.97).

**The migration rule, and the live defect the pass found in our engine:**
- Stored `s`/`d` must never be reinterpreted under new parameters — the correct migration
  is **replaying each user's append-only receipts through the new engine** (receipts as
  ground truth is Anki's own revlog-replay pattern), resetting `interval_multiplier` to
  1.0 (a multiplier fitted against the 4.5 curve is meaningless under a trainable decay).
- **Live defect (G11, found by this audit):** under 4.5 semantics a same-day re-attempt
  records `retrievability = 1.0` (elapsed 0), and a successful one inflates both
  `predicted` and `observed` in `refit`'s sample — biasing the multiplier the moment a
  learner re-tries a lapsed item the same day, which is exactly what §2.5's relearning
  protocol will make routine. The upstream filter is `(i > 1) & (delta_t > 0)`; Engram
  needs the same rule: first attempt of the day is the graded review; same-day re-attempts
  are their own receipt kind, excluded from state transitions and from `refit`'s sample.
- **The validity boundary survives unchanged:** as of 2026-07 there is still zero
  published human validation of FSRS beyond self-graded flashcards; DAS3H (Choffin et al.
  2019) remains the skill-level precedent, and nothing supersedes it. `stats.by_kind`
  stays the per-learner instrument, and per-kind divergence is watched, not presumed.
- **Refused:** FSRS-7 (unshipped, unstable spec); full-vector fits below the gate;
  auto-CMRR; any claim that a version bump improves a near-default user's schedule.

### 2.7 Adaptivity that works — the spine of the founding question

The founder's goal is a system that is "smart and adaptive and evolves with the user."
The refute-first pass on forty years of adaptivity research returns a short, sharp list of
what that may honestly mean — and a long graveyard.

**Confirmed, ranked by evidence strength:**

1. **Step-level tutoring and mastery gating are the proven core — protect them.**
   VanLehn 2011: answer-based CAI d ≈ 0.31, **step-based d = 0.76**, human tutors d = 0.79
   — and substep-based d = 0.40, so *finer is not better*; the granularity gain plateaus
   at the step. Corbett & Anderson 1994 isolate the mastery/knowledge-tracing component:
   ~30% faster to criterion, ~43% better posttest with it. Adaptive **spacing**
   specifically beats yoked same-average schedules (Mettler, Massey & Kellman 2016) — the
   gain is the individualization, which is what FSRS is. Engram already owns this whole
   rank; v2.0's first duty is not to break it.
2. **Prior-knowledge × guidance is the ONE aptitude-treatment interaction that survived
   the graveyard — make it the flagship.** Tetzlaff et al. 2025 (60 experiments, 176
   effects, N = 5,924): the disordinal crossover stands — assistance helps novices
   **d = +0.505** and harms the knowledgeable **d = −0.428**, asymmetry favoring
   assistance when unsure. Adaptive fading of worked examples beat *fixed* fading on
   delayed transfer (Salden/Aleven line; two modest-n experiments, direction consistent).
   Engram's scaffolding dial and problem-ladder rungs already read the right signals
   (pretest, lapses, node state); v2.0's job is to close the loop *per learner over time*
   — and to say, precisely: *Engram runs the only ATI that survived Cronbach & Snow, on
   receipts, never on traits.*
3. **At Engram's per-node n (2–10 retrievals), simple learner models are the
   evidence-PREFERRED choice, not a compromise.** Khajah/Lindsey/Mozer 2016 (BKT+
   extensions match DKT); Xiong 2016 (the original DKT edge was partly a duplicated-rows
   artifact); Gervet 2020 (logistic-family wins at moderate data; deep models need scale);
   BKT is unidentifiable on sparse data. → lapse counts, success rates, FSRS state, at
   most an Elo-style running estimate. The deterministic engine owning every number is
   the *architecture the evidence recommends*.
4. **A self-regulated-learning prompt layer is worth building — under hard constraints.**
   SRL interventions in university students: g ≈ 0.38–0.50 (Theobald 2021, N = 5,786;
   Zheng 2016; Guo 2022 — outcomes g = 0.40 with *adaptive, specific, feedback-paired*
   prompts as the significant moderators). The cautionary tale is nudging-at-scale
   (FAFSA campaigns, ~800k students: **zero**). → prompts must be specific to the
   learner's own receipts ("you said 90 on X and lapsed it — that pattern is 4-for-6 this
   month"), paired with feedback, and *fade as the learner's own monitoring appears*.
   Engram's calibration data is the natural substrate; a generic "remember to
   self-monitor!" line is the banned failure mode.
5. **Choice buys motivation, never method.** Patall 2008: choice raises intrinsic
   motivation (d ≈ 0.3), strongest at 2–4 real choices; the TUM 2024 meta is the fence —
   **fully learner-controlled environments underperformed even non-personalized ones**,
   and learner control per se is worth g = 0.05 (Karich 2014). → preferences pick among
   evidence-valid options (session length, order, example domain, visuals eagerness);
   they never select the pedagogy. The visuals-dial pattern was already exactly this.

**Killed, and named in full because the founding question walks right past this
graveyard:** learning styles (unchanged verdict, now with the ML corollary — *inferring*
"styles" from telemetry is the same corpse in ML clothing); the general ATI program
(Cronbach's own 1975 verdict; prior-knowledge × guidance is the sole survivor); the 85%
rule as a human-learning law (SGD derivation; for declarative retrieval the evidence
points the other way — keep success HIGH, >75%, Rowland 2014, with spacing stretched
toward the edge); learner control as a learning enhancer; adaptive difficulty as
universally superior (split/null record outside spacing and scaffolding); DKT-class
models at Engram's n; chronotype scheduling (>80% of adult studies: no main effect; no
intervention study exists — `rhythms` stays inert as a *driver*, at most descriptive
per-learner stats); generic prompting/nudging; sub-step granularity.

**The one-sentence synthesis the roadmap builds from:** *the evidence says a "smart,
adaptive, evolving" system adapts assistance to demonstrated prior knowledge, schedules by
individually fitted forgetting, prompts metacognition specifically and fadingly, and
offers small real choices — everything else that "adapts to the learner" is either
decoration or a graveyard.*

---

## 3 · Killed in this audit — do not build on these

Consolidated from all seven passes; each entry died against primary sources.

- **Streaks, streak freezes, loss-aversion stakes** — the "science" is vendor analytics;
  the one peer-reviewed engagement result at that company is +0.5% DAU. (Constitution
  already forbade them; now the evidence file does too.)
- **Multi-model grader panels** — ~2 effective votes from 9 judges; validity theater.
- **Delayed feedback** — preregistered 38-class null (0.002 [−0.05, 0.05]).
- **"85% rule" as a motivation/ordering license** — gradient-descent derivation; category
  error outside it.
- **MEMORIZE as a triage warrant** — single-item timing result; no budget construct.
- **Most-overdue-first as a catch-up default** — worst-tier in every budgeted analysis
  found; no evidence for it.
- **Teach-back marketed with Kobayashi's g = 0.48** — that number is
  teaching-expectancy-at-encoding; review-time teach-back without expectancy: g = −0.02.
- **"66 days to form a habit"** — median of an unstable small-N fit; range 18–254.
- **Habit stacking / Tiny Habits as branded science** — RCTs absent; the kernel (event
  cues beat time cues) is the evidenced part.
- **Cohorts, accountability partners, body doubling** — still surveys and vendor stats;
  the social-features refusal stands on evidence, not taste.
- **Daily reminders, bandit-optimized notifications** — habituation directly measured;
  published ceiling ~2% retention at 300M-user economics; engagement optimization is
  constitutionally out anyway.
- **Covert-retrieval "quick mode"** — no memory gain available (covert = overt), total
  verification loss.
- **MCQ/recognition** — recall-practiced knowledge already transfers across formats
  (d = 0.58); recognition buys nothing and stays banned.
- **Interleaving old-material retrieval into new encoding** — g = −0.56, bias-robust.
- **Progress resets offered to active learners** — demotivates exactly the people doing
  well (Dai 2018); fresh-start offers are for the lapsed only.
- **Visual retrieval formats** — unchanged verdict; the one licensed candidate class if
  ever revisited is closed-book mapping-from-memory, which adds nothing over free recall
  (O'Day & Karpicke 2021).
- **FSRS-7** — benchmark-only, 35 parameters, spec changed three times in three months;
  nothing ships it, neither does Engram.
- **Auto-recommended desired retention (CMRR)** — Anki, holding the world's largest
  review dataset, removed the feature in 25.07; Engram auto-setting it for conceptual
  material would be theater. A trade-off chart is the honest ceiling.
- **A scheduler version bump sold as an accuracy win** — fitted 4.5 ≈ default 6/7; the
  gain lives in fitting, and users must never be told otherwise.
- **The general ATI program** — Cronbach's own verdict stands; prior-knowledge × guidance
  is the sole replicated survivor, and Engram adapts on nothing else.
- **Styles inferred from telemetry** — the learning-styles corpse in ML clothing; banned
  with the same force as the questionnaire version.
- **DKT / full BKT learner models** — DKT's edge was partly a data artifact, loses at
  small n, and BKT is unidentifiable at 2–10 observations; simple receipts-based
  estimates are the evidence-preferred architecture, not a compromise.
- **Chronotype / time-of-day adaptive scheduling** — >80% of adult studies find no main
  effect; no intervention study exists. `rhythms` never becomes a driver.
- **Sub-step feedback granularity** — VanLehn's own data: substep d = 0.40 < step 0.76.
- **Adaptive difficulty as universally superior** — split/null outside spacing and
  scaffolding; the two survivors are already Engram's core.
- **Full learner control over instructional method** — fully-adaptable environments
  underperformed non-personalized ones; choice picks among valid options, never pedagogy.
- **Initial retrieval criterion above one** — the relearning override closes the gap and
  the cost is never recouped; three-massed-corrects lost to one-plus-spaced 26% to 68%.
- **Immediate verbatim re-asks after feedback** — zero-effort parroting; every successful
  protocol interposed items or delay.
- **Successive relearning for procedure nodes** — the measured boundary condition
  (Rawson, Dunlosky & Janes 2020); procedures keep the problem grammar.
- **Within-session spacing optimizers / expanding-schedule machinery** — the relearning
  override eliminates the payoff; complexity with no return.
- **SR marketed as transfer** — exposure-controlled transfer d ≈ 0.15; the honest claim
  is durable retention of the practiced items.

---

## 4 · What remains honestly open (each with its gate or instrument)

1. **Probe variation for rubric-graded conceptual recall** — direction strongly evidenced
   (PNAS 2024), never tested on this material class. Instrument: the n-of-1 engine, once
   G6 (single-metric ceiling) is fixed. Ships as an experiment, never as a silent default.
2. **Whole-topic reconstruction as a spaced session type** — strong single-session
   science, zero spaced-session studies. Same instrument.
3. **Retire/suspend → adherence** — VDR is solid memory science; the adherence link is
   untested. Instrument: Engram's own `adherence` telemetry, before/after `retire` ships.
4. **Session composition → return-tomorrow** — no published evidence in either direction.
   Engram's fleet is better positioned than any lab to answer it (the Commons question,
   again).
5. **Renewal cadence for implementation intentions** — reminding works across 4 weeks
   (RCT); *re-forming* at week 4/8 is untested. The renewal flow ships with its cadence
   labeled inference.
6. **The SRS dropout curve** — still unpublished as of 2026-07, and the raw material now
   exists in public (FSRS-Anki-20k, ~1.7B reviews). This is a paper Engram's authors could
   write *without* Engram data, and it would convert two founding assumptions from
   inference to evidence.
7. **The 30-day durability of AI-tutoring gains** — the field's question (docs/08 §6),
   still unanswered by anyone, still the Commons' reason to exist.
8. **The default-vs-default 4.5→6 delta** — the benchmark carries default-parameter rows
   for FSRS-6 (0.3664) and FSRS-7 (0.3629) but none for default FSRS-4.5, so that
   specific delta is unmeasured; "defaults are roughly equivalent across versions" is
   inference from the adjacent rows (fitted-4.5 ≈ default-6/7) and is labeled so
   wherever the migration cites it.
9. **What fitting buys at exactly 50 / 100 / 400 reviews** — the tier constants (8/64)
   and the ~16-review threshold are published; the continuous curve is not.
10. **The optimal retrieval-success band, and whether it should personalize** — bracketed
    (high success >75%, spacing stretched to the edge) but never pinned by an adult RCT;
    a per-learner adaptive band ships only as an n-of-1 experiment, if ever.
11. **Preference accommodation → adherence, measured directly** — the SDT record is
    large-N correlational; no RCT tests "honoring pace/length preferences → retention or
    persistence in self-directed adults." Engram builds cheap and measures in-house.
12. **Successive relearning × adaptive scheduling** — no published study combines them;
    every SR schedule in the literature is fixed-calendar. Engram's policy-cap design is
    the extrapolation, labeled, and its own receipts are the validator.
13. **The optimal SR gap** — never factorially manipulated inside an SR design; the
    Cepeda ridgeline (10–30% of the retention interval) is the best available anchor.
14. **Whether relearning-session criterion should ever exceed one** — untested; every
    protocol used one; Engram does not exceed it.

---

## 5 · The founding question, answered

**Q: "The most robust generalized learning system — anything, any level of mastery — that
is smart and adaptive and evolves with the user, honoring needs and preferences, to
improve their learning effectiveness."**

**A: Split it into its four clauses and the audit answers each:**

- **"Anything"** — already true and defended: the kind system (concept/procedure/fact) is
  content-declared per node, never domain-routed; nothing in v2.0 adds a domain mode.
- **"Any level of mastery"** — currently false at the front door (G7: a three-node fixed
  pretest) and at the back (G10: topics dead-end at ~20 nodes). v2.0 opens both ends:
  an adaptive frontier walk that is still 100% receipts-backed pretesting (never inferred
  mastery — the constitution's no-unearned-claims article applies to *skipping* exactly as
  it applies to advancing), and a topic-extension flow so depth never dead-ends.
- **"Smart and adaptive, evolves with the user"** — the honest version is the closed loop:
  the engine already computes the learner's numbers; v2.0 makes it *propose* adaptations
  from them (challenge band from measured success rates, schedule from fitted memory,
  session shape from completion patterns, ordering from savings-per-minute), every
  proposal consent-gated, engine-computed, logged with its evidence, reversible, and
  labeled evidence-vs-model-derived. Never taxonomy, never silent, never a style. The
  founding question's word "evolve" is Article 7 plus time.
- **"Needs and preferences"** — the visuals-dial pattern generalizes: preference is
  honored as autonomy and motivation (dials the learner can always move), evidence
  arbitrates outcomes (receipts decide whether the preference costs retention, and the
  learner sees both facts and chooses). The Focus profile stays the template: needs are
  declared and honored; nothing is ever diagnosed.

And one sentence for the tension the founding question does not name but v2.0 must hold:
**a system that adapts to you is one hallucinated correlation away from a horoscope** —
which is why every adaptive move in the roadmap is either backed by the strongest
evidence this audit could not kill, or runs as a pre-registered n-of-1 inside the
learner's own receipts, or does not ship.
