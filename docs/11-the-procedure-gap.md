# 11 · Math & STEM: The Procedure Gap, Audited

> **Status: theory, adversarially verified.** First drafted 2026-07-22 from a search-level
> pass; then put through the house gauntlet (§Method) the same day, which **corrected five
> claims, deflated two effect sizes, and inverted one design rule** — all folded in below,
> with the original errors kept on the record. The buildable form is
> `docs/12-procedure-layer-work-order.md`.

The founder's question, verbatim-ish: *"Math and STEM are incredibly important and will only
grow in importance. Is Engram braced for math & STEM learning as-is? If not — is there room
to add that specialization? Should we? How? On which grounding studies?"* — with the binding
scope directive that followed: **Engram stays a general learn-anything system; this is an
enhancement that activates when the content calls for it, never a pivot.**

The verdict, stated up front so the rest can be checked against it:

> **Engram is braced for the *conceptual* half of STEM and structurally blind to the other
> half.** Its encoding grammar — chain-of-necessity derivation, prediction-before-resolution,
> self-explanation — is close to optimal for *why-knowledge* in derivational domains; the
> strongest external validation (Kestin 2025) is literally a physics tutor. But STEM mastery
> is half *procedure* — differentiate the function, balance the equation, size the resistor —
> and Engram's ontology has no such kind. Every node is a declarative claim, every probe is
> verbal free recall, every receipt grades prose. The literature is blunt about what that
> trains: transfer of retrieval practice runs **d = 0.58 when practice format matches use
> format, d = 0.28 when it doesn't — and ≈ 0 after publication-bias adjustment when neither
> congruency nor elaborated feedback is present** (Pan & Rickard 2018, verified to the
> subgroup CIs). A learner who *recites how* integration by parts works has practiced
> reciting, not integrating. The fix is one new knowledge kind, `procedure`, with an
> example-ladder acquisition grammar and a solving-based retrieval format — spaced, mixed
> with its confusable siblings, step-graded, execution-verified. **And none of this narrows
> Engram: the kind is declared per node by the content itself — a `procedure` is a git
> workflow or a pronunciation drill as readily as an integral — and topics without procedure
> nodes behave exactly as today. Math & STEM are where the layer earns its keep, not what
> Engram becomes.**

---

## Method — three refute-first verifiers, and what they changed

The first draft's evidence came from a search-level pass (16 sources checked against
abstracts). Per the house discipline (`docs/05`/`docs/06`), it was then handed to **three
independent adversarial verification agents** — acquisition claims, retention claims,
grading/frontier claims — instructed to *break* each claim against primary sources. Between
them they read ten full-text PDFs (Rohrer 2020; Pan & Rickard 2018; Brunmair & Richter 2019;
Lyle et al. 2022; Yeo & Fazio 2019; Arthur et al. 1998; Yang et al. 2021; Barbieri et al.
2023; Sinha & Kapur 2021; Atkinson et al. 2003; McLaren et al. 2015; KLI; ProcessBench) and
triangulated the rest. Scorecard, kept honestly:

| Outcome | Count | The load-bearing ones |
|---|---|---|
| **Confirmed, numbers exact** | 7 | Pan & Rickard moderators; Tetzlaff ±0.505/−0.428; Arthur skill decay (−1.4 at a year; cognitive > motor); Hake 0.48/0.23; Sinha & Kapur g = 0.36; Bisra self-explanation g = 0.55; ProcessBench |
| **Corrected** | 5 | Rohrer 2020 is 61% vs **38%** (not 37); its d = 0.83 is 7th-graders — **adult magnitude is g ≈ 0.3–0.4**; worked-example g = 0.48 → **0.44 after trim-and-fill, math-only, I² = 94%**; "no procedural cost" for PS-I is a *non-significance*, CI reaching −0.20; Yeo & Fazio's worked-example win on novel problems is **immediate-test** — at a week it attenuates to parity |
| **Inverted (design rule died)** | 1 | "Always serve fresh isomorphs" — the retention benefit lives in **algorithmic variants** (new values, same structure and cover story: Yeo & Fazio exp 2 d = .89; Lyle 2022 g_av = 0.32); fully re-clothed isomorphs erase the advantage and belong to the transfer machinery |
| **Gate rewritten** | 1 | "Erroneous examples only after first clean solve" was too strict: the prior-knowledge gate did not replicate under interactive find-explain-fix scaffolding (McLaren n = 390: no PK interaction; Booth/Barbieri: incorrect examples helped *low*-PK) — new gate: after instruction, always scaffolded, never a default |
| **Citation fixes** | 2 | The faded-step mechanism is **Renkl, Atkinson & Große 2004**; Yeo & Fazio is *J. Educational Psychology* |

One claim from the wider field is now on a **do-not-cite list**: Wang & Fan's AI-tutoring
meta (g = 0.867) was retracted; its 35-study successor lands at g = 0.670. And Sinha &
Kapur's p-curve "true effect 0.87" is not a pooled estimate — never quote it.

## 1 · The audit: what is already braced (more than expected)

`docs/01` names math, physics, CS, and engineering as the home turf of chain-of-necessity
encoding, and several Tier-1 citations are math studies. What exists and holds:

| Capability | STEM relevance | Where it lives |
|---|---|---|
| Derivation-first encoding (`derives_from`, `why_chain`, PREDICT→STRUGGLE→RESOLVE) | The native grammar of proof and mechanism | `docs/01` P5/P8; dialogue grammar |
| `arbitrary: true` → mnemonic + spacing | Notation, constants, conventions, units | architect spec |
| Threshold concepts + explorables | The sims meta (g+ = 0.62, D'Angelo/SRI 2014) *is* science simulations | `docs/06` P15 |
| Concreteness fading; scaffolding dial | New formalisms enter concrete-first | `docs/01` P7 |
| Pretesting; productive failure | Attempt-before-instruction, g = 0.36 for conceptual/transfer (Sinha & Kapur 2021, verified) | `docs/01` P5 |
| Interleaved due queue across topics | The spacing half of the practice literature | `engram.py due` |
| Transfer probes at maturity (v0.8) | **Now also the home of far-transfer problem clothing** (§4) | `/review` ⭐; `docs/07` §8 |
| Misconception log + hypercorrection | STEM has *catalogued* misconceptions to feed it (§6.7) | `misconception add` |
| Calibration telemetry | Spaced math practice also fixes overconfident self-forecasts (Emeny, Hartwig & Rohrer 2021) | confidence-before-reveal |
| The flagship external result is physics | Kestin et al. 2025: ~2× gains, 0.73–1.3 SD, AI tutor on this dialogue grammar — **immediate post-test** | README |

None of this needs replacing. The gap is one level down.

## 2 · The gap: Engram knows two kinds of knowledge; STEM runs on three

Constitution article 5: *"Derive the derivable; memorize only the arbitrary — and the DAG
knows which is which."* Two kinds: derivable claims, arbitrary facts. The
**Knowledge-Learning-Instruction framework** (Koedinger, Corbett & Perfetti 2012,
*Cognitive Science* 36, 757–798 — read against the published PDF) taxonomizes knowledge
components along four dimensions (application-condition variability × response variability ×
verbal × rationale) and pairs them with distinct learning processes — *memory & fluency*,
*induction & refinement*, *understanding & sense-making* — and matching instructional
treatments. **Facts / concepts / skills is KLI's own "rough mapping" of that space onto
common terms, and KLI flags the treatment alignments as tentative hypotheses** — which is
the correct epistemic weight for this layer too: a workable ontology under measurement, not
settled law. What matters is uncontested: spacing-and-testing is the treatment for the
constant cells, sense-making for concepts, **worked examples and practice-with-feedback for
variable-response skills** — and Engram routes *everything* through the first two.

The cost, in verified numbers:

- **Response-format congruence** (Pan & Rickard 2018, *Psych Bulletin*, full-text):
  transfer of retrieval practice overall d = 0.40; **congruent d = 0.58 vs incongruent
  d = 0.28; with neither congruency nor elaborated feedback, the bias-adjusted estimate is
  ≈ 0.015 — effectively zero.** Verbal recall about procedures, which is all Engram can
  currently do, is the incongruent-and-thin cell. `docs/07` §8 called this "the sharpest
  critique of Engram's core loop" and answered with one transfer probe at maturity; for
  procedures, congruence is a property every retrieval event needs.
- **The math-specific asymmetry, stated against ourselves:** in mathematics, testing-vs-
  restudy per se is *weak* (Murray, Horner & Göbel 2025 math meta: g = 0.18, CI crossing
  zero) while **spacing of problem-solving practice is the robust lever** (same meta:
  g = 0.28; the Lyle–Ralston engineering-calculus line: spacing, not amount, carried
  retention into the *next course*, g_av = 0.32, and the retrieval events were genuine
  problem-solving). Classroom quizzing across 222 studies: g ≈ 0.50, with problem-solving
  content at g = 0.45 (Yang et al. 2021) — against *restudy* g = 0.33, against elaborative
  strategies ≈ 0. So the honest framing of this layer is **spaced, feedback-carrying
  problem-solving practice** — not "the testing effect, applied to math."
- **Skill decays worse, not better** (Arthur et al. 1998, verified verbatim): to
  d ≈ −1.4 past a year of nonuse, with *cognitive, accuracy-based* tasks — exactly
  procedures executed correctly — decaying **more** than physical/speed ones. A scheduler
  is not optional for procedures; Engram has one and doesn't aim it at them.

## 3 · Pillar 16 — The third kind of knowing: procedures enter by the example ladder

**Claim.** A procedure is encoded by *studying and progressively completing worked
solutions* at first exposure, sliding to independent solving as competence is measured —
and once instruction has happened, the practice act is solving, not re-studying.

**Evidence — the license.**
- **Worked-example effect, honestly sized:** novices learn more from studying solutions
  than solving cold (Sweller & Cooper 1985); in mathematics, meta-analytic **g = 0.48
  [0.36, 0.60], trim-and-fill 0.44, I² = 94%, math-only, Egger-significant** (Barbieri et
  al. 2023, full-text) — a real effect with wide implementation variance, not a constant.
- **Fading beats example-problem pairs — for near transfer, one research program:**
  backward fading > EP pairs (Renkl, Atkinson, Maier & Staley 2002; near-transfer robust,
  far-transfer *not* reliable across their experiments); adding principle-level
  self-explanation prompts with feedback lifted near AND far transfer with **no extra
  time** (Atkinson, Renkl & Merrill 2003, N = 78 university + N = 40 school). The mechanism
  is pinned: **learners learn most about precisely the step that was faded** (Renkl,
  Atkinson & Große 2004) — fade the principle-bearing step, not the arithmetic.
- **The ladder must retract, asymmetrically:** expertise reversal is confirmed and
  disordinal — assistance helps novices **d = +0.505** and harms knowledgeable learners
  **d = −0.428** (Tetzlaff et al. 2025, 176 effects, N = 5,924; *strongest in higher
  education*), with the meta-analysts' own asymmetry note adopted as the default: when
  unsure, provide assistance.
- **Attempt-first survives, in its lane:** PS-I beats instruction-first for conceptual
  understanding and transfer at **g = 0.36 [0.20, 0.51]** with **no detected procedural
  cost (g = −0.03, n.s. — the CI admits a small cost; say it this way)** (Sinha & Kapur
  2021, full-text). The solo-product levers that carried the effect: elicit *multiple*
  solution attempts, then build the instruction on the learner's own attempts. So the
  *concept* node licensing a procedure keeps Engram's native PREDICT→STRUGGLE opening; the
  skill nodes open with the ladder.
- **The post-instruction pivot (the sharpest new evidence):** with adults, once initial
  instruction exists, **retrieval practice beats re-studying worked examples for
  generalization** (Cao & Carvalho 2026, preregistered, adults 19–69) — and Yeo & Fazio's
  worked-example advantage on novel problems is an *immediate-test* result that attenuates
  to parity at a week (their own exp 3 null). The ladder is therefore steep by design:
  examples own **first exposure**; solving owns everything after.
- **Erroneous examples, regated:** find-explain-fix error study produced **delayed**-test
  advantages (Adams et al. 2014 d = .62; McLaren, Adams & Mayer 2015 replication n = 390,
  d = .33 delayed, no immediate effect) — and under that interactive scaffolding the
  prior-knowledge gate did **not** replicate (no PK interaction; low-PK benefited d = .35).
  The unscaffolded adult result that motivated the original gate (Große & Renkl 2007)
  stands *for the unscaffolded case*. Affect honesty: error-hunting raises
  confusion/frustration even while delayed learning improves (Richey et al. 2019) — frame
  it, ration it.

**Evidence — the leash.**
- Fading is titrated by *measured* state (pretest, lapses, node state), and pace adapts to
  prior knowledge — fixed slow fading measurably hurts higher-PK adults (Reisslein 2006).
- Within the Barbieri corpus, prompt-bearing example conditions *underperformed* prompt-free
  ones on average (β = −0.24, descriptive) while controlled experiments and the
  self-explanation meta (Bisra et al. 2018: g = 0.55 overall; **g = 0.35 against
  instructor-provided explanations**; multiple-choice prompts ≈ nothing) show real positive
  effects. Reconciliation shipped as design: prompts are **generative, principle-level,
  feedback-carrying, never menu-shaped, never redundant** with what's on screen — and never
  stacked on every step.
- Erroneous examples: never before instruction; always scaffolded; a repair tool, not a
  diet (correct examples beat error-seeded ones on average performance, Barbieri β = +0.26).

**Design consequence.** For `kind: "procedure"` nodes the dialogue grammar gains the
**problem ladder**, replacing beats 2–4 when the node's practice state is novice:
(L1) worked example, learner self-explains each step's *why*; (L2) completion — learner
executes the final step(s); (L3) faded — the *principle-bearing* interior step blank;
(L4) full solve, cold. Beats 1, 5–6, 8 unchanged; VERIFY keeps its confidence-pick → stash
flow but its *production* becomes a worked solution to a fresh algorithmic variant (never
the canonical instance whose solution L1 just displayed), blind-graded like any production. Rung selection
from the same measured signals as `docs/06`'s worked-drive gate; when unsure, assist.
Concept nodes keep today's grammar byte-for-byte.

## 4 · Pillar 17 — The problem is the probe: procedural retrieval is solving, varied and juxtaposed

**Claim.** A procedure node's review is *solving a fresh algorithmic variant* — new values,
same structure — spaced by the scheduler, juxtaposed with its confusable siblings so the
learner must *choose* the technique, graded at step level with execution-verified
arithmetic, and priced gently when the only error is a slip.

**Evidence — the license.**
- **Interleaved problem practice:** the flagship RCT (Rohrer, Dedrick, Hartwig & Cheung
  2020, preregistered, n = 787, cluster-randomized): one-month-delayed test **61% vs 38%,
  d = 0.83 [0.68, 0.97]** — *7th-grade math*, mostly-vs-mostly dose contrast, time-on-task
  not equated, feedback always present. **For adults, quote g ≈ 0.3–0.4:** the meta-analytic
  math subgroup is g = 0.34 (Brunmair & Richter 2019, k = 238), the college-lab result
  d = 1.34 on n = 18 (Rohrer & Taylor 2007 — direction, not magnitude), and the university-
  physics classroom replication showed ~50–125% median improvements on novel-problem tests
  (Samani & Pan 2021). The mechanism carries the design: blocked practice tells you the
  strategy; test errors under blocking are overwhelmingly wrong-*formula-selection* —
  learners knew *how*, not *which*.
- **The juxtaposition condition (verified moderator, adopted as a rule):** the interleaving
  effect concentrates under **immediate succession** (g = 0.73) and collapses when the
  contrasted items are temporally spread (g = 0.22, n.s.) (Brunmair & Richter 2019) — and
  it pays only between *confusable* types (words: negative). So discrimination is a
  **within-session** lever (serve confusable siblings adjacently, ask "which technique, and
  why?") and spacing a **between-session** lever; a scheduler that scatters single problems
  across days implements neither.
- **Spaced problem-solving in real adult STEM coursework:** the Lyle–Ralston program
  (Hopkins et al. 2016; Lyle et al. 2020; Lyle et al. 2022, N = 180 calculus, preregistered
  within-Ss): spacing retrieval of course objectives — the retrieval events being genuine
  procedure execution on algorithmic variants — lifted retention **g_av = 0.32** at
  semester's end and carried into the next course, while adding *amount* without spacing
  bought nothing long-term. The practice cost is real, short, and front-loaded (first
  question per objective per quiz; gone by the third) — name it to the learner.
- **Fresh means algorithmic variant** (the corrected rule): changed numbers, kept structure
  and cover story — the configuration where solving beat re-studying at a week (Yeo & Fazio
  exp 2, d = .89) and which Lyle 2022 used. Full cover-story re-clothing serves *far
  transfer* and belongs to the `transfer_probe`, at maturity, exactly where v0.8 put it.
  Identical re-serving (same numbers) has no evidence *for* it and every reason against;
  it stays banned.
- **Step-level tutoring is the ITS result:** VanLehn 2011 d ≈ 0.76 step-based; the one
  at-scale effectiveness RCT of a mature math ITS delivered **≈ +0.20** in year two
  (Cognitive Tutor Algebra I; Pane et al. 2014) — the honest ceiling to quote for "an ITS
  at scale," which is what this layer makes Engram.

**Evidence — the leash.**
- **The grader is the weak joint, now with pinned numbers.** Finding the earliest wrong
  step in math solutions: o1-mini 87.9 F1, GPT-4o 61.9, most PRMs worse — several below
  random on PRMBench's subtle-fault dimensions; error detection in long reasoning chains
  tops out at F1 ≈ 41 (ProcessBench; PRMBench; DeltaBench — all read). LLM grading of
  student math work is bimodal: near-human agreement **only** with a reference solution
  plus an engineered rubric (70–80% agreement, ≥ human-human, in physics explanation
  grading), ~42–47% exact-score accuracy on free-form handwritten work without them.
  Engram's shape — canonical instance + authored step rubric + blind grader — is exactly
  the good cell, and the 2025 verifier literature's convergent fix is the layer's standing
  rule: **verification converged on execution** (GenPRM; PAL/PoT +12–15 points; "LLMs
  cannot self-correct reasoning by reading alone"). Every checkable claim is executed,
  never eyeballed; the v0.7 gold set gains procedure items so the grader is *measured* on
  solutions before its procedure verdicts count (docs/12 WO-7).
- **Generated problems fail at a known rate:** ~3–5% wrong answer keys even in
  execution-checked pipelines (MATHWELL: 96.9% answer accuracy *with* program-of-thought
  keys), 10–25% of instances pedagogically defective pre-filter, and **text-predicted
  difficulty barely beats a dummy regressor** (BEA 2024). Consequences: the tutor computes
  every key by execution before serving; `problem_frame` bounds hold difficulty near the
  canonical instance; drift is caught empirically (lapse-rate telemetry), never assumed
  calibrated.
- **Slip ≠ lapse remains an engineering inference** — consistent with Arthur et al.'s
  task taxonomy, not demonstrated by it; receipts now carry `error_class` so it is
  n-of-1-testable. The flattering failure mode (over-calling "slip") is named in the gold
  set's slip-vs-conceptual items and in the grading rule: torn → `conceptual`.

**Design consequence.** For `kind: "procedure"` nodes, `/review` serves a fresh algorithmic
variant from `practice.problem_frame` (key computed by execution first); when a
`discriminates_from` sibling is co-due, the pair is served **adjacently** behind the naming
beat; productions are step-graded against the authored rubric with slips priced
`partial`/`hard` + `error_class: slip` and right-answer-wrong-method capped at `partial`.
Concept and fact nodes review exactly as today. **Hard requirements inherited from Pan &
Rickard: congruent format (the solve IS the review) and elaborated feedback (the gap
analysis against the step rubric) — without both, the literature prices this near zero.**

## 5 · What this deliberately does not build

- **A "math mode" or domain toggle.** Kinds are declared per node by the architect from
  the content, exactly as `viz` affordance is. Engram remains general; a topic with zero
  procedure nodes behaves exactly as on v1.0.8 (the only trace: an additive `node_kind`
  stamp on new receipts, which v1.0.8 code paths never read).
- **MCQ problem banks.** Recognition stays banned (Constitution art. 1). The discrimination
  *naming* beat is open production, immediately followed by the solve.
- **CAS/SymPy in the engine.** `engram.py` stays stdlib-only, network-free, does no math.
  Execution-verification is the *agents'* duty with their own tools; receipts record it.
- **Proof-assistant integration** (Lean/Coq). Promising, different project. Proofs grade as
  step productions under P17's leash with the DeltaBench caveat (long-chain error detection
  F1 ≈ 41) stated at double volume.
- **Timed fluency drills.** Real dimension (KLI's fluency processes), no honest input path
  (latency in chat is noise), and speed pressure collides with `docs/05`. Open, not shipped.
- **K-12 arithmetic pedagogy.** The audience is self-directed adults; the effect sizes
  quoted here are deliberately the adult ones.
- **A math-anxiety layer.** Real (r ≈ −0.25…−0.34 across five metas, Barroso et al. 2021);
  one cheap RCT-backed micro-move exists (pre-test expressive writing, Ramirez & Beilock
  2011); belongs to `docs/05`'s machinery after its own audit. Parked with citations.

## 6 · The machinery

Specified as work orders in **`docs/12-procedure-layer-work-order.md`** (WO-1…WO-8):
node `kind` + `practice` metadata riding the `viz` opaque-storage pattern; `error_class`
enums; `stats.by_kind` telemetry with its confound caveat in the payload; the problem
grammar (`skills/_shared/problem-grammar.md`); architect and assessor spec extensions
(misconception seeding from documented catalogs — FCI/mechanics, DIRECT/circuits, CAOS-SCI/
statistics, natural-number bias/rational arithmetic, progmiscon.org/programming — with the
CCI used only alongside its psychometric critique); ≥20 adversarial procedure items in the
v0.7 gold set; export gains two closed enums. Seven of nine pieces need zero engine change.

## 7 · What remains honestly open (with its gate or its instrument)

1. **G1 — adversarial verification: DONE** (§Method). Five corrections, one inversion, one
   regate — all applied to the pillars and the shipped prose in the same release.
2. **G2 — the grader on procedures.** Gold extension passes `assessor-audit` on procedure
   items, or procedure receipts stay unvalidated. Non-negotiable; v0.7's whole lesson.
3. **Does the scheduler fit skills?** FSRS has *zero published validation* beyond
   declarative flashcards; the citable precedent for skill-level decay-plus-spacing models
   is **DAS3H** (Choffin et al. 2019, EDM best paper — skill-level curves on real math
   data). Shipped stance: FSRS as unfitted prior for procedure nodes, `stats.by_kind` +
   `refit` as the per-learner instrument, DAS3H as the roadmap direction if kinds diverge.
4. **Isomorph difficulty drift** — now with known rates (§4 leash). Bounded frames +
   lapse-rate monitoring; open until measured.
5. **Slip-vs-lapse pricing** (the labeled inference). n-of-1-testable once `error_class`
   accumulates.
6. **The durability question is open for the entire field:** no delayed-retention
   AI-tutoring RCT in math exists in the 2024–2026 record (the first registered trials are
   in the field now). Engram's receipts — now kind-split — are precisely the missing
   instrument, which extends the v1.0 Commons thesis to procedures.
7. **Transitive-inference boundary:** the one replicated case where retrieval practice
   *impairs* learning is relational-structure integration — architects should keep such
   nodes `concept` (study/examples), not `procedure`. Noted in the architect's kind rules.
8. Proof grading, timed fluency, math anxiety — parked in §5, each wanting its own pass.

## 8 · The founding question, answered

**Is Engram braced for math & STEM as-is?** Half of it, genuinely: the conceptual half is
not just compatible with STEM, it was designed on STEM examples and validated by a physics
study. The procedural half is a structural gap: there is no knowledge kind for *can-do*, so
the system converts every skill into an essay about the skill — and the congruence
literature prices that conversion at half the transfer effect, or near zero without
elaborated feedback.

**Is there room?** Yes, by construction — the `viz` pattern (architect-declared,
engine-opaque, skill-owned, receipt-measured) carries the whole layer; seven of nine pieces
need zero engine change.

**Should we?** Yes — bounded and general. The audience is self-directed adults on technical
material; the verified adult evidence (spaced problem-solving g ≈ 0.3, worked examples
g ≈ 0.44 in math, expertise reversal strongest in higher education, PS-I g = 0.36) sits
exactly on this layer; and declining would leave Engram a system that schedules what STEM
learners *say* and never what they *do*. But: no math mode, no new pedagogy, no fourth
verb — one new kind, two new pillars, the same constitution, and every effect size quoted
at its adult magnitude.

**How, on which grounding?** P16 (acquisition: the example ladder) on Sweller & Cooper
1985 · Barbieri 2023 (g = 0.44–0.48, math) · Renkl-Atkinson fading + Renkl-Atkinson-Große
2004 mechanism · Tetzlaff 2025 reversal · Sinha & Kapur 2021 PS-I · Cao & Carvalho 2026
post-instruction pivot · Adams/McLaren erroneous examples. P17 (retention: varied,
juxtaposed, step-graded solving) on Rohrer 2020 (child) + Brunmair & Richter 2019 and
Samani & Pan 2021 (adult) · the Lyle–Ralston line (2016–2022) · Yeo & Fazio 2019 ·
Pan & Rickard 2018 congruence+elaboration · Yang 2021 · Arthur 1998 decay · VanLehn 2011 /
Pane 2014 · ProcessBench/PRMBench/DeltaBench and the execution-verification literature.
In one sentence, the slogan gains a clause: **derive what can be derived, memorize only the
arbitrary — and practice what must be *performed*, on fresh instances of the same problem,
next to the problems it is mistaken for, until the schedule says it holds.**
