# 14 · The Road to 2.0 — Executable Work Orders

`docs/10-roadmap-to-1.0.md` carried the project from an encoding tool to a measured
instrument, and it is done: the loop is visible (v0.6), the oracle is audited (v0.7), the
capability claim is real (v0.8), the method is sound (v0.9), the Commons is consented
(v1.0), and the procedure layer made the system general across knowledge kinds (v1.1).

This document is the next road. Its evidence base is [`13-the-adaptive-instrument.md`](13-the-adaptive-instrument.md)
— a live probe of v1.2.2 plus seven refute-first research passes — and its destination is
the founder's v2.0 charge: **the most robust generalized learning system — anything, any
level of mastery — that is smart and adaptive and evolves with the user, honoring needs
and preferences, on evidence and never on vibes.**

Same discipline as docs/10: each release below is a **complete work order** — Why (the
evidence or verified defect that forces it) / What (the exact surface) / Done
(oracle-checkable) / Selftests (must fail without the change) / Risk (what it could break,
and the invariant that guards it). A model that has never seen this repository should be
able to ship any one of them from its section alone, plus `RELEASE_PROTOCOL.md` — and
**[`15-target-architecture-2.0.md`](15-target-architecture-2.0.md) is the schema
authority**: every field, payload, and signature named below is specified there; where
the two disagree, 15 wins (two such spots existed and are resolved there: receipt
retry-stamping and retirement's representation).

---

## 0 · The compatibility doctrine (read first, check last)

Engram runs daily on thousands of machines. This outranks every ambition below.

1. **Additive or invisible.** Every schema field is additive with a safe default via
   `_deep_heal`/`setdefault`; a v1.2.2 state directory works untouched under every
   release below. Deviations from byte-equivalence come in exactly two disclosed
   classes, each named in its own work order with its off-switch or proof:
   **(a) schedule-affecting** — v1.3's capped-session ordering (uncapped behavior
   untouched; old order one keystroke away), v1.5's dose caps (newly encoded nodes only;
   `settings.relearning: off`), v1.6's scheduler migration (replay-proven, escape hatch,
   disclosed); **(b) ambient-surface and teeth** — v1.3's plan line, hook reframe, and
   one-time audit offer fire on existing states (each rationed, each with an off-path),
   and v1.4's staleness check can flip a previously-audited state to
   `grader_unvalidated` on a platform upgrade (correct, disclosed, canary-recoverable —
   its Risk section owns it). Nothing outside these two lists may change observable
   behavior for a learner who exercises no new feature.
2. **The invariants of docs/09 §2 bind unchanged** — stdlib-only no-network engine; the
   engine owns every number; receipts append-only; state advances only through receipts;
   the assessor never sees the dialogue; confidence picked or null; learner text never on
   a command line; mutating commands take the lock; defaults self-heal; every engine
   change ships a selftest that fails without it.
3. **Three verbs, forever.** Everything below lands inside `/learn`, `/review`, `/coach`,
   or the engine.
4. **Every adaptive behavior is: engine-computed, consent-gated, evidence-cited,
   ledger-logged, reversible.** (This becomes constitutional in v1.8.) No silent
   steering. No trait taxonomy. Preferences choose among evidence-valid options; they
   never select pedagogy (docs/13 §2.7 rank 5).
5. **Model-derived vs evidence-derived is labeled in the payload**, not just in docs —
   the ordering formula, fitted parameters, and every proposal carry their grade the way
   `modality.caveat` already does.
6. **The gates travel with the features.** A release that adds a new receipt stream adds
   its audit surface in the same release (v0.7's lesson, generalized).

---

## How to execute a release from this document

Identical to docs/10, and it still matters more than the document: branch per release
(`release/vX.Y.Z`), invariants outrank work orders, selftest → adversarial review → fuzz
→ numbers audit → live test → uncontaminated dogfood → user session → merge `--no-ff`,
tag, release. (Bare §-references below — §4.8, §5.6, §5.7 — are `RELEASE_PROTOCOL.md`
sections; pre-answer §4.8 in writing for every new number.) **If the exit criteria
cannot be met, do not ship and claim them.**

---

# v1.3 — **The Kept Word** *(the return release)*

> *The strongest licensed adherence intervention in the codebase is stored and has never
> once been shown back. The shipped catch-up order is the one order the evidence ranks
> last. The hook presents the full debt to the exact learner the amnesty protocol exists
> to protect.*

**Why.** Return is still the binding constraint (docs/08 §2; founder's live state:
loop_closure 0.393, 28 past due). The live probe (docs/13 §1.B) found the adherence layer
half-wired: G1 (commitment never read back — implementation intentions at d = 0.65 for
goal attainment broadly, an honest d ≈ 0.14–0.31 in behavior-specific metas, and still
the largest licensed lever on this list; plan-*reminder* RCTs Messmer 2022 / Prestwich
2010 are the direct evidence for the read-back itself), G8 (debt-blind hook framing), G9
(most-overdue-first contradicted by every budgeted analysis found — docs/13 §2.2), plus
the licensed moves from the adherence pass (docs/13 §2.1): anchor-quality coaching,
honest automaticity expectations, and `retire` as the missing autonomy verb.

### What

**A · The commitment is shown back and renewable (G1).**
1. `cmd_session_start`: when reviews are due AND `settings.commitment` is set, print one
   additional line — the learner's own words, verbatim, no parsing, no paraphrase:
   `[engram] your plan: "when I open the terminal in the morning — I clear one review"`.
   Rationed by **exactly** the decay line's return-event rules (fires only on a
   never-closed loop or a ≥7-day absence; no daily fallback — steady-state read-back is
   the renewal offer's job, and a line that fires every session is the nagging this
   release's Risk section forbids). Slug-safety does not apply (free text): the line is
   emitted with a `[engram] your plan:` prefix and the cue/action JSON-escaped — hook
   output is injected into agent context, so the commitment text must be rendered inert
   (printed as a quoted literal, never as an instruction).
2. `/review` step 1: on a return-after-absence, the amnesty block gains the plan line
   (shown back once, before the capped offer).
3. **Renewal:** `/review` close and `/coach` check-in — when a commitment exists and is
   ≥28 days old (or on any return-after-absence ≥7d), offer arrow-key once:
   *keep / rephrase / drop*. Drop is one keystroke, unremarked, never re-raised that
   session. Cadence is labeled inference in the skill text (the RCTs support
   plan-reminding across 4 weeks; re-formation cadence is untested — docs/13 §4.5).
4. `commit --clear` exists already (verified); `commit` additionally stamps `renewed`
   dates so the offer logic is engine-readable (`commit` emits `age_days`).

**B · Anchor-quality coaching at commit time.** In `/learn` §6 prose only: if the
learner's cue is a clock time ("at 9pm"), suggest — once, in one line, declinable without
comment — anchoring to an existing routine instead ("after I make coffee"), and prefer
*after*-placements (Judah 2013; Stawarz/Renfree: event cues build automaticity, time cues
don't). Their sentence still wins verbatim, whatever they choose.

**C · Savings-per-minute ordering for capped sessions (G9).**
0. **The truth about today first** (the work order's own §4.8 duty): `due_items` already
   sorts most-overdue-first within topic and round-robin-interleaves topics, and `due
   --limit N` truncates that order — so every capped queue Engram has ever served was
   already ordered by the policy the evidence ranks worst-tier. G9 is engine-implemented,
   not just skill prose; the blast radius of this fix is every `--limit` caller.
1. Engine: `due` gains `--cap N` (top-N *after* ordering; `--limit` becomes its
   deprecated synonym — one meaning, two spellings, said in `--help`) and
   `--order overdue|savings` (`overdue` = today's shipped order, named truthfully;
   uncapped default stays `overdue` — byte-identical behavior; **when `--cap`/`--limit`
   is present, the default becomes `savings`**). `savings` ranks by
   `(R_horizon_if_reviewed − R_horizon_no_review) / expected_minutes`, computed from the
   same FSRS projections `decay` already emits; `expected_minutes` prices a low-R item
   slower (piecewise constant is fine; constants documented). The payload carries
   `order` **and** `order_basis: "model-derived (FSRS projection); no human RCT ranks
   backlog orders — docs/13 §2.2"` — the honesty label inside the payload, per doctrine
   §0.5. **⚠ SHIPPED CORRECTION (v1.3):** the claim below that this formula "deprioritizes
   the nearly-lost (little savable)" is **false as written** — reviewing a near-dead concept
   *resurrects* it, so the raw ratio ranks it highest. Measured, the curve is an inverted U
   peaking at R ≈ 0.34 (reproducing Lindsey's θ ≈ 0.33 — a real convergence). The fix is a
   floor, not a new formula: items below R = 0.10 are flagged `effectively_relearn` and sort
   last regardless of score. Also amended: `--limit` is **not** a synonym for `--cap` — it
   keeps the v1.2.2 list shape and order, so an un-updated skill file cannot break.
2. `/review`: the amnesty protocol's capped set uses `--cap <review cap> --order savings`
   (review caps: `quick` 5, Standard ≈12 — the shipped numbers; Sprint uses `quick`'s);
   "most-overdue first" becomes the explicitly-offered alternative, not the default.
   Items with near-zero savings (R below a floor — functionally relearn material) are
   named as such in the close ("3 items are effectively re-learns — they lose nothing by
   waiting; want them in a Deep session?") rather than silently burning the cap.
3. `decay` output unchanged (it already computes the ingredients; the ordering reuses its
   functions — one implementation, §4.8 Q1).

**D · The hook stops presenting the wall (G8).** `cmd_session_start`, when
`due > 2 × review cap` (review cap per C2: the default mode's — Standard 12, Sprint via
`quick` 5) or `settings.profile == "adhd"`: the line leads with the capped path, keeps
the full count — `[engram] 28 due · /review quick clears the 5 most urgent (~3 min) ·
full queue ~17 min.` Below the threshold, unchanged. Nothing new fires when nothing is
due.

**E · The first-audit offer (half of G3).** `/coach` §0.5, `verdict: "unaudited"` branch:
when total receipts ≥ 20, the one calm line becomes a one-time arrow-key offer (*audit
now (~4 min) / later*), recorded in the model (`settings.audit_offered: date`) so it is
never repeated. Declining costs nothing and is never mentioned again. (The founder's own
machine sits at 42 unaudited receipts — the friction is real and measured.)

**F · `retire` — the missing autonomy verb.** Engine: `retire --topic T --node N`
(and `--topic T` for a whole topic) writes an engine-owned `retired: {ts, restored:
null}` block on the node — **`state` is untouched** (docs/15 §2.2: a new state-enum
value would ripple through every state reader and block the capstone forever; a block +
one shared `is_retired` predicate does the same job safely; retired prerequisites count
as satisfied for `requires_met`, and the capstone requires every *non-retired* node).
Reversible: `retire --restore` stamps `restored`, keeps the block. **Why this is exempt
from "state advances only through receipts" (docs/09 §2.4), said rather than assumed:**
receipts guard *mastery* claims; retirement advances nothing — it is an administrative
learner decision, recorded on the node it governs, and once v1.8's ledger exists,
`retire` writes there too. Retired nodes: excluded from `due`/`next`/decay projections;
**counted, labeled, in every denominator they leave** — `adherence` gains
`retired: {nodes, by: "learner"}`, `retention.unmeasured` gains a `retired` count beside
`past_due_now` (they are *chosen*, not abandoned — different words, both honest), `stats`
and the dashboard say "12 due · 40 retired by you." `/review` amnesty offers it during
load renegotiation ("retire what no longer matters — it's your list"). The engine NEVER
proposes retirement of specific nodes (flattery risk: auto-retiring what the learner
keeps failing). Evidence: value-directed remembering (Castel line); the adherence link is
open and says so in the doc (docs/13 §4.3).

**G · One honest line on automaticity.** At first lapse on a topic (once per topic,
`/review` prose): *"habits like this typically take ~2 months to feel automatic — range
is huge, and single misses genuinely don't matter (Lally 2010; PNAS 2023)."* Never a
countdown, never a day-count UI (docs/13 §3: the constant doesn't exist).

### Done (oracle-checkable)

- [ ] `session-start` on a state with due reviews + a commitment prints the plan line,
      rationed per the rules; with `commitment: null`, below D's debt threshold, and no
      focus profile, output is byte-identical to v1.2.2 (D and E are the only other
      ambient deltas, per doctrine §0.1b).
- [ ] `due --cap 8` returns the 8 highest-savings items with `order_basis` in the payload;
      `due` uncapped is byte-identical to v1.2.2 ordering.
- [ ] A retired node appears in zero queues and in every labeled denominator; retire →
      restore round-trips; `adherence`/`retention` fixtures with retired nodes report
      them, never drop them.
- [ ] The hook line at 28 due / Sprint profile leads with the capped path and still
      states the full count.
- [ ] On the founder's real state: the commitment set 2026-07-23 is visible in the next
      session's hook output. **The system finally says the sentence back.**

### Selftests

Plan line fires only under the return-event/day ration and never when no reviews are due ·
commitment text is emitted escaped (a cue containing `$(rm -rf)` or an
instruction-shaped string arrives as an inert quoted literal) · savings ordering
arithmetic on a hand-computed 3-node fixture (high-R barely-due, mid-R near-threshold,
near-zero-R deeply-overdue → mid ranks first) · `--cap` without `--order` defaults to
savings; explicit `--order overdue` honored · retired nodes excluded from `due`/`next`
and present in `adherence.retired` + `retention.unmeasured.retired` (fixture) · restore
reverses cleanly · mutation: revert the ordering change → the capped-default test fails ·
v1.2.2-shaped state with none of the new fields behaves identically (captured-output
comparison).

### Risk

Three lines were added to ambient surfaces, and ambient surfaces are where nagging is
born. The guards: every new line has a ration rule and an off-path (`commitment` deletable,
`decay_notice` untouched, retire is learner-initiated only), and the §5.6 user session
must specifically answer *"did any new line read as pressure?"* — if yes, cut it, ship
the rest. The ordering change alters which items a capped session serves (real behavior
change): it is engine-labeled model-derived, the old order remains one keystroke away,
and uncapped behavior is untouched.

---

# v1.4 — **The Audited Tutor** — ✅ SHIPPED 2026-07-24

> **RESULT.** The tutor is measured (`stats.self_grading`, agreement with the blind
> assessor, direction published, limits in the `read`); audit receipts persist and
> reschedule nothing; the badge **expires** on a grader swap and `export` refuses behind
> it; the canary re-licenses in 15 items and can never mint a `pass`; audits report
> `by_gold_band`; and `docs/ADJUDICATION.md` + `adjudication-stats` finally make an
> outside human's work countable.
>
> **Three build-time corrections to this work order**, each caught by a gate:
> (1) the canary must be **quota-stratified across all three bands** — the specified
> "oversample partial" produced a 100% mid-band set, structurally blind to a grader
> failing the clear cases; (2) `_latest_audit` must **skip canary files**, or running a
> canary replaces an 86-item verdict with a 15-item one and `canary-pass` reads as
> `unreadable`, voiding a good badge; (3) `export` needed its **own** `--grader-context`
> to inherit staleness — the gate it most needs to be behind.

# v1.4 — the original work order *(the instrument keeps its edge)*

> *The tutor writes every review receipt and every `error_class`, and nothing audits it.
> The assessor's audit never expires — a model upgrade silently inherits a badge it never
> earned. And the literature now says the fragile band is exactly `partial`.*

**Why.** docs/13 §2.4: judge drift on model change is measured and leniency-shaped (60/60
detection, uniformly lenient after a silent model swap; a 2026 longitudinal study needed
weekly recalibration); mid-band validity degrades where headline QWK looks fine (47/48
GPT results >2 categories off at mid-range gold); self-consistency without a bias probe
is a named anti-pattern at 541k-judgment scale; multi-model panels are refused with
numbers (~2 effective votes from 9). And G2 (live probe): the `/review` §3 audit results
— the only measurement of the tutor that exists — evaporate as prose.

### What

**A · Audit receipts persist (G2).** The stash→assessor audit flow's output is applied via
`receipt --file` with `kind: "audit"`: `apply_item` writes the receipt (carrying
`tutor_rating`, the assessor's independent `grade`/`rating`, `agree`, `error_class` when
step-shaped) and **touches no FSRS state, no node state, no schedule** — audits inform,
they never reschedule (the existing doctrine, now with a paper trail). The receipt's
`source: "assessor"`, plus a new `audited_rating` field naming what the tutor had
committed. `/review` §3 updates: apply the audit output (it is no longer "log a note").

**B · `stats.self_grading` — the tutor's number.** Computed from audit receipts:
`{n, qwk_vs_assessor, signed_bias, by_band: {partial: {...}}, read}` where `signed_bias`
> 0 means the tutor rates above the blind grader. The `read` ships the limitation
verbatim: *"agreement with the blind assessor, whose own validity is what `/coach audit`
measures — tutor validity is bounded by that chain, never better."* Floors: n ≥ 20 before
any rate; counts below. `/review` §3 gains the oversampling rule: audit triggers now
**always include every `partial` in the session** (the band where graders diverge —
docs/13 §2.4). `/coach` check-in voices it when n clears the floor; "drift is the coach's
monthly business" finally has a number.

**C · Audits expire (G3).**
1. `assessor-audit` accepts and stores `--grader-context "<platform>/<model-label>"`,
   supplied by the `/coach audit` skill from what its platform actually knows; the engine
   stores it verbatim and never invents one (absent → `"unknown"`).
2. `grader-health` takes the *current* context the same way (the skill passes it): a
   context mismatch with the latest audit → verdict `stale-model`, `grader_unvalidated:
   true`, with a `read` that says which model earned the badge. Unknown context on either
   side → age-only staleness: audits older than 90 days → `stale-age` (same teeth).
3. **The canary path.** `gold --canary` emits a fixed, seed-stable ~15-item subset —
   oversampling `partial`-band gold and always including the historical-inflation items —
   shaped exactly like `gold` output. `assessor-audit` accepts a canary-scoped payload
   (`scope: "canary"` in the result): its ONLY possible verdicts are `canary-pass`
   (restores nothing by itself but licenses continuing under the prior badge, recorded)
   or `canary-fail` (any `graded_up` > 0 or leniency shift beyond the ceiling → full
   re-audit demanded, teeth engage now). A canary can never mint a `pass` — only the full
   set can. `/coach audit` runs the canary automatically when `grader-health` says
   `stale-model`, before offering the full ceremony.
4. `export` refusal logic inherits staleness (a stale grader is an unvalidated grader).

**D · Band-stratified audit reporting.** `assessor-audit` output gains `by_gold_band`
(per gold grade: n, exact, QWK contribution, signed bias) beside `by_case_type`. The
README badge stays the direction count (`0/N graded up`); the audit's `read` names the
weakest band. Gold set: verify `partial`-gold coverage ≥ 25 items; grow with
partial-boundary items if short (parallel track feeds this).

**E · The spec-paraphrase gate (optional, early, labeled).** `gold/spec-paraphrases/`
ships 3–5 semantically-equivalent renderings of the grading spec's load-bearing rules
(authored, reviewed). `/coach audit deep` (same verb, an argument — not a fourth verb)
runs one assessor pass per paraphrase on the canary subset and `assessor-audit --file`
computes `spec_flip_rate` (fraction of items whose grade changes across paraphrases).
≥ 0.90 consistency expected (JudgeSense threshold); below → `warn`, named in
`grader-health`. The doc says plainly: Engram is early here — both of its real measured
inflations were spec-ambiguity, and this is the class's only known mitigation shape.

**F · The external-adjudication kit.** `docs/ADJUDICATION.md`: the full protocol from
docs/13 §2.4 — one external adjudicator, blind to author labels/audit history; 10-anchor
calibration gate (≥80% exact before proceeding; anchors quarantined from stats);
independent pass over all 86; pre-adjudication stats are the only independent ones;
thresholds α ≥ 0.80 corroborated / 0.667–0.80 tentative / below contested; unresolved
items marked contested and excluded from the audit denominator (said aloud). Engine:
`adjudication-stats --file <rater.jsonl>` — read-only; computes exact, QWK, ordinal
Krippendorff's α with bootstrap CI, per-category confusion with signed direction, against
the shipped gold; refuses to run if the anchor gate items are absent or failed. The
engine keeps printing the circularity caveat until a passing adjudication file exists in
`gold/adjudications/` — then the caveat *names the corroboration and its α* instead of
disappearing (one external rater corroborates; only ≥2 externals replace — docs/13 §2.4).

### Done

- [ ] An audit-kind receipt round-trips: applied once, schedule untouched (fixture
      asserts s/due byte-identical), visible to `stats.self_grading`.
- [ ] `stats.self_grading` on a hand-built fixture (tutor systematically +1 band on
      partials) reports positive signed bias and the by-band split; below-floor n
      reports counts only.
- [ ] An audit stored under context A + `grader-health` under context B → `stale-model`,
      `grader_unvalidated: true`, export refuses.
- [ ] `gold --canary` is deterministic (same seed → same sids), includes the historical
      inflation sids, and a canary payload can produce `canary-fail` but never `pass`.
- [ ] `assessor-audit` reports `by_gold_band`; the gold set's partial-band count reaches
      ≥ 25 — the shipped set carries **17**, so this release authors ≥ 8 new
      partial-boundary items under the existing gold discipline (adversarial by design,
      rationale quoting the deciding criterion, execution-verified where checkable,
      `gold_adjudication: "authored"` stamped, sids continuing the sequence) before the
      gate is claimed.
- [ ] `adjudication-stats` on a synthetic perfect-agreement file reports α = 1.0 with its
      CI; on a synthetic coin-flip file, α ≈ 0 and the verdict text says contested.
- [ ] A real `/coach audit` run on the founder's machine writes the first audit this
      state has ever had, with its context stamped. *(The human half of E/F — a real
      external adjudicator — stays an open checkbox, exactly like v0.6's human criterion.)*

### Selftests

Audit-kind receipts never mutate fsrs/state (mutation: make apply_item schedule them →
fixture fails) · self_grading QWK/bias arithmetic vs hand-computed values · staleness:
context mismatch flips the flag; age > 90d with unknown context flips it; matching
context within window does not · canary determinism and its verdict ceiling
(`canary-pass` can never satisfy the export gate on its own) · spec_flip_rate arithmetic
on a fixture where one paraphrase flips two items · adjudication α/QWK against known
matrices · v1.2.2 states (no audit receipts, no contexts) behave identically everywhere.

### Risk

The staleness teeth can flip long-time users to `grader_unvalidated` on the day they
upgrade their platform — which is **correct** and will feel like a regression. The
mitigation is the canary: a ~15-item single pass instead of the full 86×3 ceremony,
offered automatically, and the `read` says *why* ("the model that earned this badge is
not the model grading you today"). The risk section of docs/10 v0.7 applies verbatim: publish
whatever it says.

---

# v1.5 — **The Relearning Loop** — ✅ SHIPPED 2026-07-24

> **RESULT.** Retrieval-to-criterion (one correct recall, ≤3 passes, never an immediate
> re-ask) for concepts and facts; procedures refused at the engine, per the measured
> boundary. The dose guarantee ships as a labeled policy layer: 3d/9d caps on the first two
> post-encode intervals, new nodes only, off-switchable — measured 4d → 3d → 9d → 128d, so
> it graduates rather than trapping. G11 closed: `relearn` rows touch no schedule, no
> retention population, and no fit, excluded by one line in the shared predicate.
>
> **One work-order correction:** `retries_to_criterion` cannot be "stamped on the day's
> first receipt" as §B originally said — that receipt is already on disk and receipts are
> append-only. Retry data lives on the retry rows; the aggregate is derived at read time.

# v1.5 — the original work order *(retrieval to criterion)*

> *Engram grades one retrieval and books a date. The best-supported unexploited finding
> in the retention literature says the session should not end at a failed retrieval.*

**Why.** docs/07 §2 flagged successive relearning as "the most promising unexploited item
in the retention literature for this codebase" and ordered it specified against primary
sources before building. docs/13 §2.5 is that specification pass. Independently, the FSRS
audit (docs/13 §2.6) found G11: same-day re-attempts currently record `retrievability =
1.0` and pollute `refit`'s sample — the exact defect a relearning loop would make routine,
so the guard ships in the same release as the loop.

The evidence (docs/13 §2.5, primary-source verified): the dose-response on spaced
relearning sessions is the largest effect in the entire audit (3 vs 1 sessions: +60%
relative recall at one month; spaced-vs-massed at equal retrieval counts: 68% vs 26% at
one week); the honest exposure-controlled effect is d ≈ 0.7; the criterion is **one**
correct recall (the relearning override kills criterion-3); re-asks are back-of-queue,
never immediate; the protocol is **concept/fact only** (the measured procedure boundary,
Rawson/Dunlosky/Janes 2020); transfer claims are banned (d ≈ 0.15 under exposure
control); and no study combines SR with an adaptive scheduler — Engram extrapolates,
labels it, and lets its own receipts validate.

### What

**A · The same-day guard (G11 — ships whatever else does).** Same-day re-attempts after
a node's first graded retrieval of the day are their own receipt rows, stamped
`relearn: true`. Rules: the day's **first** attempt alone drives `apply_rating` and
enters `_review_receipts` / retention / calibration / modality / `refit`; `relearn` rows
are recorded append-only (receipts-or-it-didn't-happen applies to the criterion claim
too) and excluded from FSRS state transitions and every retention-family population by
the shared predicates — **one predicate change, every reader inherits it** (the v0.6.4
lesson). The exclusion adopts the upstream *optimizer's fitting filter*
(`i > 1 AND delta_t > 0`) and — conservatively, since FSRS-4.5 has no same-day model at
all — applies the same rule to state transitions; that second half is Engram's own
conservative extension, labeled as such.

**B · Retry-to-criterion at the moment of failure — concepts and facts only.** When a
VERIFY or review retrieval on a `concept`/`fact` node grades `lapsed` (or `partial` with
the core absent — the grammar's judgment): feedback → the re-derivation or another queue
item intervenes (**never an immediate verbatim re-ask**) → re-attempt, graded as ever
(blind at encode, tutor at review), until **one** success — capped at **3 passes**
(Higham's cap); an unreached criterion is recorded, never chased past the cap. The mode
budget and the two-minute floor outrank the criterion, always — in a Sprint with one
node, the intervening activity is the re-derivation itself. **Procedure nodes are
exempt** and keep the problem grammar's lapse path (erroneous-example re-encode on
repeat lapses); the skill says why in one line (the boundary is measured, not cautious).
Stash entries and `rate` gain the additive fields: `relearn: true` + `attempt: n` on
retry rows (docs/15 §2.3 — the day's first receipt is already on disk when retries
happen and receipts are append-only, so retry data lives ON the retry rows;
`criterion_met` and `retries_to_criterion` are *derived at read time* from the day's
row group, never stamped retroactively and never payload-supplied).

**C · The dose guarantee — a labeled policy layer over FSRS.** New-node scheduling gains
the deterministic cap: first post-encode interval = min(FSRS, **3d**), second =
min(FSRS, **9d**) — inside the Cepeda 10–30%-of-RI band against the 30-day north star,
guaranteeing ≥3 spaced sessions in the first month for material the learner keeps
answering. FSRS state still updates from true elapsed time (the cap moves the date, not
the math). Scope: **newly encoded nodes only** (existing schedules untouched — the
compatibility doctrine's third disclosed exception is bounded to new material);
`settings.relearning: "on"|"off"` (self-healed default `on`), coach-explained; the `due`
payload marks capped items `schedule_policy: "relearning-dose (policy over FSRS; see
docs/13 §2.5 — SR × adaptive scheduling is unstudied)"`.

**D · The savings signature becomes telemetry.** `stats.relearning`: per-node
trials-to-criterion trajectory summarized ({nodes_with_retries, mean_retries_first_vs_
latest, criterion_met_rate}), floors before rates, counts below. The coach may voice the
one honest encouraging fact the literature hands us: *relearning gets cheap* (.24 → .82
first-pass recall across three sessions in the exposure-controlled study) — information,
never pressure.

### Done

- [ ] A lapsed concept review in the dogfood reaches criterion within the cap, produces
      relearn rows + a stamped first receipt, and the node's FSRS state reflects ONLY the
      first attempt (fixture asserts s/due/reps byte-identical to a no-retry run).
- [ ] `refit`'s sample on a fixture with relearn rows is byte-identical to the same
      fixture without them (G11 closed; mutation: remove the exclusion → test fails).
- [ ] A procedure-node lapse takes the problem-grammar path, untouched (fixture +
      dogfood).
- [ ] New-node first two intervals never exceed 3d/9d while FSRS would have booked
      longer; `settings.relearning: off` restores pure FSRS; pre-v1.5 nodes never capped.
- [ ] `stats.relearning` renders honestly at n=0 ("no retry data yet") and on a seeded
      fixture.

### Selftests

Relearn rows excluded from `_review_receipts`/`_retrieval_receipts`/calibration/modality
(population predicate fixtures) · first-receipt stamping is engine-computed (a payload
carrying `retries_to_criterion` is stripped — the add-topic stripping discipline) ·
cap arithmetic (FSRS says 15d → capped 3d; FSRS says 2d → stays 2d) · the off-switch ·
new-nodes-only scoping (a pre-v1.5 node's interval never capped — golden fixture) ·
the 3-pass cap is skill-side by decision (honest recording beats engine refusal: a 4th
relearn row, if a skill ever sends one, is recorded truthfully — the engine test asserts
that; the §5.5 dogfood asserts the skill stops at 3) · v1.2.2 replay byte-identical when
no relearn rows exist.

### Risk

Two real ones. (1) **Workload**: the dose cap makes more early reviews for new material
— disclosed, off-switchable, new-nodes-only, and the amnesty/cap machinery (v1.3) already
bounds any session. If the §5.6 user session reads the early cadence as nagging-by-
schedule, the caps loosen toward the band's top (9d/…) before the feature ships. (2)
**Homework-theater**: retry-to-criterion could feel like being held after class — the
guards are the 3-pass cap, the budget outranking the criterion, the absolve-not-pity
register at every retry, and the §5.6 question asked verbatim: *"did the retry feel like
the system helping you keep it, or making you pay for missing it?"* The wrong answer
blocks the ship, whatever the tests say.

---

# v1.6 — **The Fitted Learner** — ✅ SHIPPED 2026-07-24 (item B deferred, with reasons)

> **RESULT.** The fitting ladder shipped (tier 1 at 64 usable reviews, tier 2 at 400, both
> behind an acceptance check that refuses a fit which does not beat the learner's current
> parameters), plus the workload trade-off curve with no recommendation attached.
>
> **⚠ ITEM B — the FSRS-6 replay migration — WAS DELIBERATELY NOT SHIPPED**, and this
> supersedes the work order below. Measured: *fitted* 4.5 matches or beats *default* 6 and
> 7 on the benchmark, and Engram's users run near-defaults — so the migration is real risk
> (every due date on every machine) for no announceable benefit. Its one genuine argument
> (same-day modelling) is moot while v1.5 keeps relearn rows out of the model. And the 21
> default weights would need primary-source verification before entering a scheduler that
> governs other people's memories; unverified constants are fabricated data. **Revisit when
> the ecosystem case changes or same-day modelling is actually wanted — never on a hunch.**

# v1.6 — the original work order *(the scheduler earns its parameters)*

> *One coarse multiplier, never yet earned by a real user, is the entire "fits your
> memory" story. Production Anki fits four parameters at 8 reviews and the full vector at
> 64 — with a framework-free optimizer. The version race, meanwhile, is a distraction:
> fitted 4.5 beats default 6.*

**Why.** docs/13 §2.6. The honest sequence is fit-first, version-second: fitting is worth
about as much as two version upgrades; FSRS-6 becomes worth shipping *because* it is the
ecosystem reference (py-fsrs/fsrs-rs differential-testing) and the sanctioned home for
same-day dynamics (v1.5) — never as a user-facing accuracy claim at defaults.

### What

**A · The fitting ladder (stdlib, gated, refuse-if-not-better).**
- Tier 0 (exists): interval multiplier, ≥50 review receipts. Unchanged.
- Tier 1: **S0-only fit** (first 4 parameters — initial stability per first rating) at
  ≥64 usable receipts (`usable` = the upstream filter: not-first, elapsed > 0), with the
  upstream recipe: per-rating curve fit, Laplace-style smoothing, L1 pull toward
  defaults, monotonicity repair across ratings. Captures ~half the fitting benefit at a
  fraction of the risk. (Upstream's S0 floor is 8; Engram adopts 64 — upstream's
  *full-fit* floor — as a deliberate conservative margin for a system whose brand is
  never shipping a fit it can't stand behind; the gap is policy, not evidence, and says
  so here.)
- Tier 2: **full-vector fit** at ≥400 usable receipts (the conservative gate; upstream
  legality starts lower, Engram's brand doesn't) — hand-coded gradient descent on the
  FSRS loss (analytic like fsrs-rs, or finite-difference: n is tiny), parameter clamps
  from upstream bounds, and the acceptance check: **a fit ships only if its log loss on
  the fitting data beats the current parameters; otherwise `refit` says so and changes
  nothing** (Anki's "parameters appear optimal" behavior).
- All tiers run inside `refit` (no new verb), report which tier ran, its n, the
  before/after loss, **and the doctrine §0.5 label** (`basis: "fitted from N usable
  receipts (tier T); flashcard-derived model — no published validation on this material
  class, docs/13 §2.6"`) — the same label rides `memory.fsrs_params` when tier 2 writes
  it (plus `fsrs_version` stamps).
- Selftests pin the implementation to **published py-fsrs reference vectors** (same
  inputs → same S/D trajectories within tolerance) — the differential-testing dividend
  of adopting the ecosystem version.

**B · FSRS-6 by replay, with the receipts as ground truth.** The engine gains FSRS-6
formulas (21 params, trainable decay) behind a per-state `scheduler.version` field.
Same-day semantics do NOT change: v1.5's exclusions stand — FSRS-6's short-term formula
is where same-day dynamics *would* live if a validation ever earned them a place in the
model, and until then relearn rows stay out by construction (the sanctioned-slot clause
in Why is a location, not a plan).
Migration is **replay**: recompute every node's s/d from its append-only receipts under
FSRS-6 defaults, reset `interval_multiplier` to 1.0 (a 4.5-curve multiplier is
meaningless under a trainable decay), stamp the version, write one honest CHANGELOG/coach
line ("due dates may shift modestly; your history re-derived them"). No reinterpretation
of stored state, ever. `ENGRAM_FSRS=4.5` env escape hatch for one release cycle.
Migration selftest: replay determinism (same receipts → same state, twice), and a
v1.2.2-state golden fixture whose post-migration due dates are asserted against
hand-replayed values.

**C · The workload chart, not the recommendation.** `report` gains a
retention-vs-workload section: simulated reviews/day and projected retention across a
desired-retention grid `{0.80…0.95}` from the learner's own parameters, guardrails
stated (default 0.9; never > 0.97). `/coach` presents it as a trade-off the learner may
act on via the existing consented `model --set`. **No auto-recommendation — Anki removed
theirs, and ours would be theater on top of unmeasured review durations** (docs/13 §2.6).

**D · The kind-divergence watch stays a watch.** `by_kind` remains the instrument; if a
learner's procedure nodes systematically diverge (floors met), `refit` tier 1+ may fit
per-kind S0 groups — labeled, consent-gated, reversible — and DAS3H stays the roadmap
direction *only if* fleets show kinds diverging at scale. Nothing else is built on the
skills question this release.

### Done

- [ ] `refit` on synthetic receipt sets: tier selection honors the gates; tier-2 fit on a
      generated learner with known parameters recovers them within tolerance; a fit that
      does not beat current loss is refused with the reason in `read`.
- [ ] S/D trajectories match py-fsrs reference vectors on the shared test set.
- [ ] Replay migration: golden v1.2.2 fixture → asserted post-migration state; running
      migration twice is a no-op; `ENGRAM_FSRS=4.5` bypasses.
- [ ] `report` renders the workload section from real state; no path auto-writes
      `desired_retention`.
- [ ] A learner with < 64 usable receipts sees byte-identical scheduling behavior under
      defaults (modulo the disclosed replay shift).

### Selftests

Tier gates (63 usable → tier 0 only; 64 → tier 1; 400 → tier 2 eligible) · acceptance
check (a sabotaged fit with worse loss is refused — mutation-test by inverting the
comparison) · monotonicity repair (S0(again) ≤ S0(hard) ≤ S0(good) ≤ S0(easy) after fit
on adversarial data) · replay determinism · same-day receipts (v1.5 guard) excluded from
the fitting sample (fixture: adding relearn rows changes nothing) · version stamp
self-heals; unknown future version refuses rather than guesses.

### Risk

**This is the release that touches every user's schedule**, and the doctrine's exception
clause exists for it. The guards: replay (never reinterpretation), determinism selftests,
the golden fixture, the escape hatch, one honest disclosure line, and sequencing *after*
v1.5 so same-day semantics are already clean. The fitting ladder's risk is silent bad
fits at low n — guarded by the tier gates, the refuse-if-not-better check, and `refit`'s
existing honesty about what it did. If the §5.6 user session finds due-date shifts
alarming in practice, the migration can ship default-off for one release
(`scheduler.version` opt-in via coach) without changing anything else in this order.

---

# v1.7 — **The Open Frontier** — ✅ SHIPPED 2026-07-24

> **RESULT.** `--extend` (arcs, byte-identical preservation of every existing node, collision
> refused), `next --frontier-of` (the adaptive pretest that credits nothing), `doctor --fix`
> (validated, one at a time, no `--yes`), and two-phase authoring in the skills where the
> platform supports it. Both ends of "any level of mastery" are now open.

# v1.7 — the original work order *(any level of mastery)*

> *An expert entering a 20-node topic gets a novice's walk; a finished topic dead-ends at
> its capstone; and the one slow step in the product still greets first-time users with
> seven silent minutes.*

**Why.** The founding question's "any level of mastery" clause, unmet at both ends (G7,
G10). The evidence frame: frontier diagnosis is knowledge-space's home turf (docs/01 P8);
mastery stays receipts-only (Constitution art. 10 applies to *skipping* exactly as to
advancing); the expertise-reversal asymmetry ("when unsure, assist" — but its mirror:
demonstrated knowledge earns the cold end) is the one replicated ATI (docs/13 §2.7).

### What

**A · The adaptive frontier walk (G7).** Replaces the fixed first-3 pretest for new
topics, entirely inside `/learn` §2 plus one engine helper:
- Intake keeps prior-exposure (never touched / shaky / comfortable). *Comfortable* (or a
  learner who says "I know the basics — test me in") triggers the walk: pretest a
  mid-`order` node; **solid → offer a batched pretest sweep of its `requires` chain**
  (each ancestor gets its own probe, its own confidence pick, its own `pretest` receipt —
  efficiency in collection, never inference); miss → drop to the standard frontier below
  it. Bound: ≤ 6 probes per sitting (more feels like an exam — the §5.6 record), **and
  the bound's consequence is owned:** at probe 6 the session teaches from the deepest
  receipted frontier, says so ("we'll test deeper next time if you want"), and the walk
  resumes on request in a later session — an expert whose frontier sits deeper is never
  taught below their receipts, only asked to spread the pretesting across sittings.
  Every credited node is credited by its own receipt, scheduled far out exactly as solid
  pretests are today. The learner can decline the walk and get today's behavior.
- Engine: `next --topic T --frontier-of <node>` (read-only helper returning the
  `requires` chain not yet receipted) — or the skill computes it from the graph payload;
  prefer the engine (one implementation of DAG logic).

**B · Topics extend instead of dead-ending (G10).** `add-topic --extend --file F`: merges
new nodes into an existing graph (new nodes only; existing nodes' engine-owned fields
untouched — stricter than `--replace`), appends to `order`, re-mints the capstone to
require the union (idempotent, the v0.8 machinery), records `arc: N` on new nodes.
Architect contract gains the extension mode (input: existing graph summary + "what's
next" goal; output: same schema, new nodes only). `/learn`: when a topic's frontier
empties *and* its capstone is done, offer once: *extend this topic (Arc N+1) / new topic
/ done*. The founder's hand-written "Arc 1 of 2" titles become a mechanism.

**C · The architect's seven minutes (G10).** Two-phase authoring, opt-in per platform
capability: the architect may return `{phase: 1, nodes: <first 4–6 + capstone-pending
marker>, outline: [...]}`; the skill starts teaching node 1 immediately and spawns the
continuation (same architect, extension mode) in the background; `add-topic --extend`
lands the rest mid-session. Fallback (no background capability): exactly today's flow
with the load-bearing warning line. The §5.6 gate owns the feel; the capstone is only
minted once the full arc lands (no capstone on a half-map).

**D · Recovery paths (G10 leftovers).** `doctor` gains `--fix`: offers (never auto-runs)
the exact commands for its findings — re-registering an orphaned artifact, restoring a
quarantined file after human repair (`doctor` validates the JSON before un-quarantining).
Still read-only by default; `--fix` takes the lock and applies only what the human
confirmed item-by-item (AskUserQuestion in the skills; `--yes` refused, deliberately).

### Done

- [ ] A "comfortable" learner on a 20-node fixture topic reaches their true frontier —
      in ≤ 6 probes when it lies within reach, else across resumable sittings — with a
      receipt for every credited node and teaching never below the receipted frontier;
      a "never touched" learner's flow is byte-identical to v1.2.2.
- [ ] `--extend` on a live graph adds nodes without touching any existing node's
      fsrs/state/artifact (fixture asserts byte-equality of old nodes), re-mints the
      capstone idempotently, and preserves every schedule.
- [ ] Phase-1 authoring teaches node 1 while the outline completes in the background on a
      platform with background spawning; on one without, the fallback is today's behavior
      (omni-repo gate, §5.7).
- [ ] `doctor --fix` un-quarantines only a file that now parses, and only on per-item
      confirmation.

### Selftests

Frontier-walk helper returns exactly the unreceipted `requires` chain (DAG fixture with a
diamond) · probe-count bound enforced in the skill contract (prose-testable via dogfood
script) · `--extend` refuses on id collisions with a differencing error; never writes
engine-owned fields from payload (the add-topic stripping test, extended) · capstone
re-mint idempotent (twice → one capstone requiring the union) · quarantine restore
validates before moving · v1.2.2 flows untouched when no new flag/mode is used.

### Risk

The frontier walk is where an unearned-mastery bug would live — the guard is structural:
credit requires a receipt, the walk only changes *which probes get asked in what order*.
Batch pretesting can still feel like an exam; the bound, the decline path, and the §5.6
verdict guard the feel. `--extend` touches the graph file under the lock and must never
brick an existing topic: the byte-equality fixture for old nodes is the tripwire.

---

# v1.8 — **The Steering Mirror** — ✅ SHIPPED 2026-07-24

> **RESULT.** Article 12 is constitutional; `propose` (read-only, floored, ≤3, evidence and
> grade on every row) and `adaptations` (the append-only ledger) ship; `rhythms` is retired
> in favour of description that cannot steer. The closed families are the safety argument:
> session shape, assistance level (the one surviving ATI), the workload curve (no number
> proposed), and one fading metacognitive prompt.

# v1.8 — the original work order *(the consented adaptation loop — the v2.0 thesis)*

> *The measurement layer is complete; the adaptation policy is prose. v2.0's claim —
> "the system evolves with the user" — becomes real here, as proposals the engine
> computes, the learner consents to, the ledger remembers, and the receipts re-judge.*

**Why.** The founding question, held against docs/13 §2.7's ranked evidence: adapt
assistance to demonstrated knowledge (the surviving ATI), prompt metacognition
specifically and fadingly (g ≈ 0.4 with those moderators), offer small real choices
(motivation, never method) — and nothing else. Plus G4/G5: `rhythms` dead,
`challenge_band` static, the docs/03 §5 adaptation table unimplemented prose.

### What

**A · The adaptation ledger (Article 12).** `adaptations.jsonl`, append-only:
`{ts, field, from, to, evidence: "<the engine-computed numbers quoted>", source:
"consented|learner", reversible: true}`. Every `model --set` the skills apply on consent
writes one. `/coach` explains current settings *from the ledger* ("Sprint default since
07-30, because 5 of your last 6 Standard sessions ended early — revert any time").
Constitution gains **Article 12: every adaptation is proposed by the engine's numbers,
consented by the learner, logged with its evidence, and reversible. The system never
steers silently, and never on traits.**

**B · `propose` — the engine computes, the coach offers.** New read-only command
emitting at most 3 proposals, each `{field, current, proposed, evidence, grade:
"evidence-backed|model-derived|heuristic"}`, drawn ONLY from these validated families:
1. **Scaffold entry** (the flagship — docs/13 §2.7 rank 2): per-kind ladder-rung /
   worked-drive entry from measured first-attempt rates (e.g., "procedure entries at L1
   have been 9/9 clean for 3 weeks → propose L2 entry"; the asymmetry rule — when unsure,
   assist — stays the tiebreak).
2. **Session shape**: default_mode from completion telemetry (sessions ending early /
   running over, from `sessions.jsonl`).
3. **Desired retention**: only ever *pointing at* the v1.6 workload chart, never a number
   invented outside it.
4. **SRL prompt cadence** (see C).
   `challenge_band.hint_budget` joins only with a telemetry basis: stash entries gain an
   optional `hints_used` count (tutor-reported, factual), and until n clears a floor the
   engine proposes nothing about it (the honest gap in docs/13 §2.7 rank 5 stays open).
   `stats` embeds `proposals_pending: N` by **re-running the same deterministic proposal
   computation** (one implementation, read-only twice — nothing persists a pending
   queue). **`propose` never writes**; the consent flow is the only writer, and it
   writes the ledger.

**C · The SRL prompt layer, fenced by its own moderators.** At `/review` close (not
mid-queue), when the learner's own receipts show a live pattern — calibration gap
(said-90-graded-lapsed ≥ 3 in the window), slip-share concentration, a kind divergence —
one specific, feedback-paired line quoting the numbers, with its fade rule: the prompt
family goes silent after 2 consecutive clean weeks, returns only if the pattern does
(Guo 2022 moderators as hard constraints; the FAFSA null as the banned shape — docs/13
§2.7 rank 4). Never generic, never a second prompt per session, `settings.srl: off`
silences.

**D · `rhythms` is resolved honestly (G4).** The dead field is **removed** from the model
(self-heal drops it); in its place `stats.sessions` computes *descriptive* pattern facts
on demand (sessions by daypart/weekday, completion by mode — description, never
scheduling; chronotype adaptation stays killed, docs/13 §3). `/coach schedule` narrates
description and takes consent for any change the learner draws from it.

**E · The return machinery's last two licensed moves.** Fresh-start offer: on
return-after-absence ≥ 14 days *and* a natural landmark within ±2 days (Monday, month
start — computed, never pushed), the amnesty close may add one arrow-key option: *"treat
this as a fresh start?"* → resets nothing but the framing (a ledger entry and a clean
session ticket; schedules and history are untouched — resets that delete progress are
banned, and offers to active learners are banned, Dai 2018). Preference surface: `/coach`
gains one screen listing every dial (visuals, mode, focus, momentum, decay_notice,
commitment, srl) with its current value and its ledger line — the open learner model,
finally one page.

### Done

- [ ] `propose` on a fixture with a clean 3-week L1 streak proposes the L2 entry with the
      streak quoted; on a v1.2.2-shaped state it proposes nothing and says why (floors).
- [ ] A consented proposal round-trips: applied via `model --set`, ledger line written,
      `/coach` narrates it from the ledger, revert writes its own line.
- [ ] The SRL line fires on a seeded calibration-gap fixture, quotes the real counts, and
      goes silent on the clean-weeks fixture (fade rule in the engine's pattern
      detector, prose in the skill).
- [ ] `rhythms` absent after heal; `stats.sessions` renders descriptive facts; nothing
      anywhere schedules by daypart.
- [ ] Fresh-start appears only on the lapsed+landmark fixture and changes no schedule
      state (byte-equality assertion).

### Selftests

`propose` is read-only (lock not taken; mutation: make it write → the read-only-commands
test from v0.6.4 fails) · proposal floors (below-n fixtures propose nothing) · ledger
append-only and self-healing · SRL pattern detector arithmetic + fade window ·
fresh-start guards (active learner fixture: never offered; no landmark: never offered) ·
model heal drops `rhythms` without touching neighbors · every proposal payload carries
`grade` and `evidence` (schema test).

### Risk

This is the release where Engram could quietly become a horoscope — the exact failure
docs/13 §5 names. The fences are structural: proposals only from the validated families,
grades in the payload, floors before any pattern is claimed, consent as the only writer,
the ledger as the audit trail, and Article 12 making silent steering unconstitutional.
The §5.6 user session must answer one question above all: *"did any proposal feel like
the system knows me, or like it's guessing?"* Guessing → the floor was too low → raise
it and re-run.

---

# v1.9 — **The Sharper Question** — ✅ SHIPPED 2026-07-24

> **RESULT.** Four metrics, each on its own population, each with its own floor, all read
> through the predicates `stats` already uses; absent evidence yields no datum rather than a
> zero; and the two designs the evidence audit licensed-as-experiments ship as checked-in
> pre-registrations naming their own threats to validity.

# v1.9 — the original work order *(the experiment engine grows real arms)*

> *The n-of-1 machinery is sound and can ask exactly one question. The audit found two
> review-format candidates the evidence licenses only as experiments — and the engine
> cannot currently run either.*

**Why.** G6 (single-metric ceiling) meets docs/13 §2.3's two gated candidates: probe
variation (PNAS 2024 — direction strong, Engram's material class untested) and
whole-topic reconstruction (strong single-session science, zero spaced-session studies).
Both belong in the randomized, stratified, pre-registered machinery — that is what it is
for (Article 7).

### What

1. **The metric registry.** `experiment start` accepts `metric: first_review_recall |
   retention_7d | transfer_fired | slip_share` — each computed by the engine from the
   same shared predicates stats uses (§4.8 Q1: one implementation), each with its own
   honest floor (`min_per_arm` defaults per metric; retention_7d needs the elapsed-day
   machinery, transfer_fired needs maturity — the engine refuses arms that cannot reach
   their metric's population and says why).
2. **Two shipped presets** (`experiment start --preset probe-variation |
   topic-reconstruction`): pre-registered design files in the repo — question, arms,
   metric, stratification (`threshold`, `viz.affordance`, `kind`), `min_per_arm`,
   analysis — filled with the learner's seed on start. Probe-variation arms: `stored-probe`
   vs `varied-probe` (tutor paraphrases the probe, rubric byte-identical), **and the
   grading condition docs/13 §2.3 licensed is enforced structurally: every
   experiment-arm review production is stashed and blind-assessor-graded — a 100% audit
   for arm receipts, riding v1.4's machinery — so the metric's receipts come from the
   blind grader in both arms, never from the tutor mid-dialogue** (the skill carries the
   paraphrase rules and the ban on difficulty drift);
   topic-reconstruction arms at the session grain (a low-frequency reconstruct-the-
   skeleton session vs standard queue), with the design file honest that session-grain
   randomization is thinner inference than node-grain.
3. **Review-side arm honoring.** `/review` reads the active experiment's arm for the
   served node (the v0.9 machinery already assigns; the skill now honors format arms at
   review time, not just teaching-strategy arms at encode time).
4. **Settle unchanged** — engine-computed, once, refusing `--verdict` forever.

### Done

- [ ] `experiment start` with each new metric validates or refuses per its floor;
      `settle` computes each from fixtures with known answers.
- [ ] The probe-variation preset round-trips: start → assignments honor strata → a
      varied-probe review receipt carries the arm → settle reads the pre-registered
      metric. On a state with no eligible nodes, start refuses with the reason.
- [ ] Presets are byte-stable pre-registrations (a checked-in file, hash-asserted, so
      "what was registered" is never a matter of memory).

### Selftests

Metric registry: unknown metric still dies; each metric agrees with the stats
implementation on shared fixtures (cross-consistency, §4.8 Q1) · per-metric floors ·
preset files validate against the design schema · arm honored at review time in the
receipt (`arm` stamped, already engine-side — extend the fixture to format arms) ·
settle-once and `--verdict` refusal unchanged (regression).

### Risk

Format arms put the experiment inside the retrieval act itself; the guard is what it has
always been — the rubric and the blind grader are identical across arms, difficulty
drift is named in the preset as the threat to validity, and an underpowered read says
`underpowered`. The presets are offers; a learner who never runs one loses nothing.

---

# v2.0 — **The Proof** *(the instrument demonstrates itself)*

> *Not a feature release — the release where the claims the roadmap has been earning get
> demonstrated, in public, on real learners, with the confounds stated.*

**Why.** docs/08 §6's final state was never "more features": downward, the
best-verified findings as default behavior (v1.3–v1.9 complete that); upward, the honest
receipts flowing into an evidence base that can settle open questions. v2.0 is the
upward half plus the declaration criteria.

### What

1. **The fleet questions, pre-registered in public.** In `engram-data`: analysis scripts
   (they live beside the corpus, not in the engine) plus pre-registered questions with
   their designs: does AI-tutored encoding survive 30 days (the Kestin gap — the field's
   open question); explorable-vs-dialogue within affordance class; derivation-first vs
   example-first by domain; the adherence funnel at fleet scale. Every analysis states
   its confounds in the same voice as `modality.caveat`.
2. **Cohort give-back.** Contributors' dashboards gain the honest cohort comparison
   (docs/09 §4.6's unshipped promise): your retention/adherence beside the contributed
   cohort's, confounds stated always — computed by the `engram-data` analysis scripts,
   *run* by the agent, narrated never calculated by the model (invariant #2); the engine
   still never touches the network.
3. **The dropout-curve paper.** The parallel track's flagship (docs/13 §4.6): the first
   rigorous SRS abandonment/review-debt analysis from the public FSRS-Anki-20k corpus —
   convertible from folklore to evidence without a single Engram user's data, and the
   strongest possible external validation of the amnesty design if it holds (or the
   honest correction if it doesn't).
4. **The badge regime, consolidated.** README: selftest count · `0/N graded up` with its
   staleness stamp (v1.4) · grader context beside the badge · self-grading n · the
   adaptation ledger's existence as a linked artifact. Docs refresh: 04's constitution
   appends Articles 11 (docs/08) and 12 (v1.8); 03 architecture delta for the new
   surfaces; this file and 13 marked history where superseded.
5. **Version 2.0.0 is declared** when the exit criteria below hold — not when a feature
   lands. A 2.0 that ships before its criteria is the exact unearned claim this
   repository exists to refuse.

### Done (the declaration criteria — each oracle-checkable, none negotiable)

- [ ] **The loop closes for real users:** the founder's own `adherence.loop_closure ≥
      0.6` sustained across 30 days, and `retention.buckets["30d"].n > 0` with the
      grader audited and unexpired on that machine. (The v0.6 human criterion, finally
      met or honestly still open — the release waits.)
- [ ] **The adaptive loop has receipts:** ≥ 3 ledger adaptations consented, evidence-
      cited, alive ≥ 30 days without reversal, on ≥ 1 real learner.
- [ ] **The tutor is measured:** `stats.self_grading.n ≥ 20` on a real state, voiced by
      the coach.
- [ ] **An external human has adjudicated the gold set** per docs/ADJUDICATION.md, α
      published whatever it says.
- [ ] **One fleet question has a published, confound-stated answer** from N ≥ 100
      learners — or the release notes say plainly that the fleet has not yet earned it
      and 2.0 ships without the claim. (Honesty outranks the milestone; the criterion is
      the *public statement either way*.)

### Risk

The temptation at 2.0 is narrative — declaring the vision achieved because the version
number says so. The declaration criteria exist so that 2.0 is a measurement, not a
press release. If they hold, the README's first sentence may finally change from what
Engram *does* to what it has *demonstrated*; if they don't, the number waits.

---

## The parallel track (any release, any time)

- **Gold-set growth** — especially `partial`-band and procedure boundary items (v1.4
  needs ≥ 25 partial-band; every real disputed grade is a candidate).
- **Widget vocabulary** for the Explorable Contract; the Contract does not bend.
- **`doctor` coverage** for every new schema field the moment it ships.
- **Codex/OpenCode/OpenClaw parity** — `codex/agents/*.toml` and the hook ports track
  `agents/*.md` and `hooks/` in the same release that changes them; the omni-repo gate
  (§5.7) is the check.
- **Platform requests** (OpenCode Desktop #7, the OpenClaw port PR #10) — welcome, glue
  only, never engine.
- **npm publish hygiene** — the OpenCode package tracks tags (2FA permitting).
- **The dropout-curve paper** (v2.0 §3) can start any time; it needs no Engram code.

## What is deliberately NOT on this roadmap

Refusals, each carrying its evidence from docs/13 §3:

- **A fourth verb.** Three, forever.
- **Streaks, XP, badges, leaderboards, loss-aversion stakes** — re-killed with vendor-
  marketing forensics this time.
- **Cloud, accounts, sync, telemetry** — the engine still has no network code,
  structurally.
- **FSRS-7** — unshipped anywhere, moving spec; revisit when the ecosystem ships it.
- **Auto-recommended desired retention (CMRR)** — Anki removed theirs; ours would be
  theater on unmeasured durations.
- **DKT/BKT learner models** — simple receipts-based estimates are evidence-preferred at
  Engram's n, not a compromise.
- **Chronotype/time-of-day adaptive scheduling** — killed; description only.
- **Learning styles in any clothing, including ML-inferred** — the corpse does not get a
  neural network.
- **Multi-model judge panels** — ~2 effective votes from 9; same-model multi-run stays.
- **Social features, cohorts, body doubling** — still surveys and vendor stats; the
  refusal stands on evidence.
- **Visual retrieval formats** — unchanged; the licensed candidate class (mapping-from-
  memory) adds nothing over free recall.
- **Sub-step tutoring granularity** — VanLehn's own data says the plateau is the step.
- **Daily reminders / notification optimization** — habituation is measured; the ceiling
  is ~2% at someone else's scale; engagement optimization is constitutionally out.

---

## The one-glance sequence

```
v1.3  THE KEPT WORD      commitment shown back · savings ordering · retire · capped hook
      ↓                  the return release: the binding constraint, again, cheaply
v1.4  THE AUDITED TUTOR  audit receipts persist · self_grading · staleness + canary ·
      ↓                  band-stratified audits · adjudication kit
v1.5  THE RELEARNING LOOP  retry-to-criterion · same-day guard (G11) · relearn receipts
      ↓                  the strongest unexploited retention finding, finally specified
v1.6  THE FITTED LEARNER  S0/full fitting ladder · FSRS-6 by replay · workload chart
      ↓                  "fits your memory" becomes literally true
v1.7  THE OPEN FRONTIER  adaptive frontier walk · --extend · two-phase architect
      ↓                  any level of mastery, both ends of the topic
v1.8  THE STEERING MIRROR  propose · ledger · Article 12 · SRL prompts · rhythms resolved
      ↓                  the measurements start steering — with consent, on receipts
v1.9  THE SHARPER QUESTION  metric registry · probe-variation & reconstruction presets
      ↓                  the licensed unknowns become experiments
v2.0  THE PROOF          fleet questions · cohort give-back · declaration criteria
                         the instrument demonstrates itself, or says it hasn't yet
```

Each layer still load-bearing for the next: you cannot steer (1.8) on numbers you have
not audited (1.4) or fitted (1.6); you cannot experiment on formats (1.9) before the
receipt semantics are clean (1.5); and you cannot declare 2.0 until the loop has closed
on a real human — which has been the whole point since the exhibit in docs/08.
