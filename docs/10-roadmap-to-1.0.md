# 10 · The Road to 1.0 — Executable Work Orders

`docs/04-roadmap.md` planned Phases 0–5. **They are done.** The engine, the medium, the mirror,
the packaging — all shipped, through v0.5.2, in six days. That roadmap is complete and is now
history.

This document is the next one, and it is written differently. Each release below is a
**complete work order**: a model that has never seen this repository should be able to open the
repo, read one section here, and ship that release without asking a question. That means every
entry carries:

- **Why** — the evidence or the verified defect that forces it (never "it would be nice")
- **What** — the exact surface: commands, schemas, prose changes, file paths
- **Done** — exit criteria that are *oracle-driven*, i.e. checkable by something executable
- **Selftests** — the checks that must fail without the change (Release Protocol §1)
- **Risk** — what this could break, and the invariant that guards it

Read `docs/08-vision.md` for *why this order*, and `docs/09-target-architecture.md` for the
schemas. Follow `RELEASE_PROTOCOL.md` for *how to ship* — including step 4.5 (adversarial review)
and step 5.5 (agent dogfood), both of which exist because they each caught a defect that
selftests structurally could not.

---

## How to execute a release from this document

1. `git checkout -b release/vX.Y.Z` — never work on `main` (Protocol §0).
2. Read the work order below **and** the invariants in `docs/09` §2. The invariants outrank the
   work order. If a work order seems to require breaking one, the work order is wrong — stop and
   say so.
3. Build. Every engine change gets a selftest that **fails without it**.
4. `python3 scripts/engram.py selftest` → green, count matches the README badge.
5. `/code-review high` on the branch diff. **Check that no agent errored** before believing a
   clean verdict (this has burned us).
6. Agent dogfood in a throwaway `ENGRAM_HOME` if any skill, agent, or contract changed.
7. Ship per Protocol §6 — merge `--no-ff`, annotated tag, `gh release create --latest`.

**The one rule that matters more than this document:** if the exit criteria cannot be met, do
not ship and claim them. Engram's entire value is that its numbers are true.

---

# v0.6 — **The Loop Closes**

> *The binding constraint. Engram's own author encoded seven concepts and reviewed zero. The
> product's failure mode, executing perfectly, on the person most invested in it.*

**Why.** `docs/08` §The exhibit. Adherence multiplies every other term to zero, and Engram
cannot currently *see* it: there is no metric anywhere for "was this encoded concept ever
reviewed?" Meanwhile the declared north star (7/30-day retention) has never been computed. You
cannot fix what you cannot measure, and you cannot claim what you never measured.

**This is the most important release in the project's history.** Everything downstream is
worthless without it.

### What

**A · Measurement first (read-only; no schema change; ship this even if nothing else lands)**

| Command | Emits | Spec |
|---|---|---|
| `adherence` | `loop_closure`, `return`, `funnel` | `docs/09` §4.1 |
| `retention [--at 7\|30\|90]` | recall at elapsed-day buckets **+ the `unmeasured` block** | `docs/09` §4.2 |
| `decay --topic T` | what is dying now; what N minutes saves | `docs/09` §4.3 |

All three are pure functions over `receipts/*.jsonl` + `sessions.jsonl` + `graphs/*.json`. No
new state. No migration. **`stats` embeds `adherence` and `retention`.**

The `unmeasured` block in `retention` is not optional and not cosmetic: a retention figure
computed only over *completed* reviews silently drops exactly the concepts the learner abandoned.
That is survivorship bias with a progress bar, and shipping it would make Engram a liar in the
one place it cannot afford to be.

**B · Close the loop (the behavior change)**

1. **The hook offers instead of announcing.** Today: `[engram] 7 reviews due · /review to clear`
   — then the learner must remember to type it. That is friction at the exact moment the
   evidence says friction is fatal. Make accepting the review a single keystroke. Declined once
   → silent for the session (existing rule, unchanged). Never a modal, never a block. It asks;
   it does not start.
2. **`/review` opens with the honest number, once.** On return after a gap: amnesty first
   (`docs/05` P14 — unchanged), then **one line of `decay`** — *"seven concepts from July 5 are
   at ~70% and falling; four minutes holds them at ~80% through August"* — then the capped
   offer. Information, then a real choice. **Never every session. Never a wall of debt.**
   Off-switchable: `settings.decay_notice = "off"`.
3. **`/learn` books the return.** At the close, once, in the learner's own words: *"when will
   you clear these?"* → `engram.py commit --cue "…" --action "…"`. Stored, shown back at the
   moment it names, **never enforced**. It is the learner's own sentence repeated to them, not a
   reminder system. (Implementation intentions: `docs/07` §4.)
4. **`/coach` reports `loop_closure` first.** Before any other number. If it is zero, the coach
   must say plainly that nothing else on the dashboard is real yet.

**C · Fix issue #3 (receipt idempotency)** — `sid` threaded stash → assessor → receipt;
`apply_item` refuses a `sid` already on disk. The fix is fully specified in the issue by the
author; implement it as written.

### Done (exit criteria — all oracle-checkable)

- [ ] `engram.py adherence` on the author's real state reports `loop_closure.rate == 0.0` and
      says so in `read`. **The system can finally see its own failure.**
- [ ] `engram.py retention` reports `unmeasured.past_due_never_reviewed == 7` rather than an
      empty, flattering `{}`.
- [ ] `engram.py decay --topic transformers` reproduces the table in `docs/08` §The exhibit verbatim
      (2.7 → 5.6 of 7 over the next 30 days) from live state.
- [ ] Applying the same `receipt --file` twice leaves `reps == 1` and one receipt on disk.
- [ ] **The human criterion, and the only one that really counts:** the author completes ≥1
      review on ≥20 of the next 30 days, and `stats.retention.buckets["30d"]` reports a real
      number with `n > 0` — **the first time in the project's life that the north star has a
      value.**

### Selftests (must fail without the change)

`adherence` funnel arithmetic on a synthetic ledger (encoded-not-reviewed counted, not dropped) ·
`retention` buckets **partition [0,∞)** (sweep every elapsed day — a disjoint-window bug dropped a real day-11 review in the v0.6 live test) · the `unmeasured` count · `decay` FSRS
projection against a hand-computed R(t) · **double-apply of the same receipt file → `reps == 1`**
· `commit` round-trips and self-heals when absent · `decay_notice=off` silences the line.

### Risk

The decay line is one keystroke from becoming a nag, and a nagging Engram is a deleted Engram.
The guard is constitutional and already written (`docs/05` P13): **information, never pressure.**
It reports a forgetting curve the way a lab notebook reports a result — flatly, because the
result is what it is. No "should." No scold. Surfaced **once on return**, never per-session,
always with amnesty and a two-minute path, always off-switchable. If a line would read to a
skeptic as *"the tutor is trying to make me feel guilty,"* it is a defect — cut it.

---

# v0.7 — **The Audited Oracle** — ✅ SHIPPED 2026-07-11

> *The grader that writes every receipt has never itself been graded.*

> **RESULT (measured, published, and not what the literature predicted).**
> **QWK 0.93** over 66 adversarial items × 3 independent blind runs. **Leniency bias −0.11 —
> the grader is HARSH, not lenient.** **0 of 198 judgments graded UP: it has never once
> inflated a grade.** Test–retest 0.97. Verdict `pass`.
>
> The failure mode this release was built to catch **does not exist in this grader** — it errs
> only in the safe direction. That was not knowable before the audit existed.
>
> **Weakest case type: `right-answer-wrong-reason`, 52% agreement, bias −0.48** — it grades a
> correct conclusion reached by a broken derivation *harsher* than the gold set does. Whether
> the grader or the gold is right there is **open**, and it ships written down.
>
> **The honest limit:** the gold adjudications are **authored, not independently
> human-adjudicated**. Each carries a rationale you can dispute (`gold/local-gold.jsonl`
> overrides by `sid`). Getting a second human through the 66 items is the highest-value item
> on the parallel track.

**Why.** The blind assessor's verdict drives mastery, retention, calibration, and the schedule.
Its agreement with any ground truth is **unmeasured**. If it is lenient — and LLM judges are
known to be (`docs/07` §3) — then every number Engram reports is inflated and the project
has no way to know. The constitution says *"the oracle is never a vibe."* Right now the oracle
**is** a vibe: an excellent one, unaudited. This hole is directly under the foundation.

### What

1. **Ship a gold set.** `gold/assessor-gold.jsonl`, **N ≥ 60**, human-adjudicated
   `(claim, rubric, probe, production, grade)` with a written rationale per item. It must be
   dominated by the adversarial cases, because those are where graders fail (`docs/09` §4.4):
   *fluent-but-empty*, *terse-but-correct*, *confident-and-wrong*, *right-answer-wrong-reason*,
   *paraphrase*, *partial-credit-boundary*. Seed it from the author's real receipts (the
   consequence-without-mechanism pattern is already in the log and is exactly the hard case).
2. **`assessor-audit --file F`** — engine computes **QWK** (the headline), raw agreement (never
   quoted alone — it overstates chance-corrected agreement by 34–41 points), **signed leniency
   bias**, **test–retest over ≥3 runs at temperature 0**, confusion matrix, and per-case-type
   breakdown. Writes `audits/<date>.json`.
3. **`grader-health`** — reads the latest audit; `stats` embeds it.
4. **Audit the consistency–bias paradox — this is the one that matters.** Engram's assessor is
   prompted to be a skeptic, round down, and cite the rubric, so it will be *extremely
   self-consistent*. Self-consistency **is not correctness**: the literature records a judge at
   0.992 test–retest with 0.192 position bias — perfectly reproducible, systematically wrong
   (`docs/07` §3). **When `test_retest > 0.95`, the engine must verify `leniency_bias < 0.15`
   before it is allowed to report `pass`.** High consistency + high bias = `fail`.
5. **Teeth.** If `leniency_bias > 0.15` or `qwk < 0.60` (floor; 0.70 is the conventional
   automated-scoring threshold and the target): `stats` stamps every retention figure
   `grader_unvalidated: true`, and `/coach` **must say so before reporting any number**.
6. **`/coach audit`** — spawns the real assessor on the gold set, pipes to the engine, narrates.

### Done

- [x] `/coach audit` runs end-to-end and writes a real `audits/<date>-NN.json`. *(Append-only:
      `<date>.json` as originally specced would have let a same-day re-audit destroy the first.)*
- [x] A deliberately sabotaged grader is **caught** — a lenient grader **above the QWK target
      (0.72)** still fails on `leniency_bias` alone, and `stats` flips `grader_unvalidated: true`.
      *(That fixture is in the selftest, and it is the one that makes the bias gate
      mutation-testable: the floor and the paradox are both silent on it.)*
- [x] A **highly consistent but lenient** grader is caught by the paradox check, not passed by it.
- [x] The measured QWK is in the README **as a badge, with the gold set public**.
- [x] **The coverage denominator**, which the original work order did not think of: a grader that
      silently drops 20 of 66 `sid`s and nails the rest reports **`incomplete`**, never a
      flattering `QWK 1.00 pass`. That is issue #3's bug class aimed at the audit itself.
- [x] **The contamination guard**, likewise unplanned: an audit payload carrying `gold_grade`
      **dies**. A test that hands the subject the answer is not a test (RELEASE_PROTOCOL §5.5).

### Selftests

QWK computed against a known confusion matrix · raw-vs-QWK divergence surfaced (a synthetic grader
with high raw agreement and low κ must **not** pass) · leniency bias sign convention (positive =
inflating) · **the paradox gate: test_retest 0.99 + leniency 0.20 → `fail`, not `pass`** · the
`grader_unvalidated` flag flips `stats` at the threshold · gold-set schema validation · an audit
with `n < 30` reads `insufficient-data` rather than emitting a verdict.

### Risk

The audit may reveal the assessor is mediocre. **That is not a reason to delay — it is the
reason to build it.** Every retention number Engram has ever shown is currently unverifiable;
finding out is strictly better than continuing not to know. Publish whatever it says.

**What actually happened, for the record:** the assessor came back at QWK 0.93 and *harsh*. The
risk paragraph above was written expecting the opposite, and shipping the instrument anyway is
the only reason we now know which it was. **Build the measurement before you know what it will
say — that is the whole discipline, and it is easy to feel brave about it only in hindsight.**

**The risk this section did NOT anticipate, and it is the real one:** a harsh grader is *safe*
for the dashboard (it can only understate retention) but it is **not free for the learner** — it
makes them re-drill concepts they had actually earned, and it depresses the north star. The
teeth are deliberately asymmetric (`leniency_bias > +0.15` fails; a *negative* bias does not),
because an optimistic number gets believed and stops them reviewing while a pessimistic one only
annoys. That asymmetry is correct and it is also **not costless**, and v0.8+ should watch
`by_case_type` for harshness drift rather than pretend the safe direction is the free one.

---

# v0.8 — **The Capability Claim** — ✅ SHIPPED 2026-07-11

> **RESULT.** `transfer_probe` was authored since v0.1 and read by nothing: **12 of 13 nodes on the
> founder's own graph carry one, and zero transfer receipts existed anywhere, ever.** The engine now
> serves them (`transfer`), records them (`kind: transfer`), states them (`node.transfer`:
> untested → probed → applied, from the LATEST evidence), and reports them (`stats.transfer`) —
> **never pooled into retention**, because "the memory survived" and "the idea is mine" are
> different claims backed by different evidence.
>
> **The capstone is a NODE now, not a paragraph.** It `requires` every other concept, so it unlocks
> exactly when the frontier empties and arrives in `next` like anything else. For four releases the
> skill file said "do not let it silently not happen" — and it silently did not happen, every time,
> because prose is not a DAG.
>
> **§4.8 Q1 caught a two-bar bug before the gate ran:** one loose `rate` counted a `partial` as a
> fired capability while `state: applied` required `recalled`. Now `rate_fired` (strict, the
> headline) and `rate_any` (the same bar retention uses, for comparability). No bare `rate` key.

> *Engram claims to build capability and measures only recall. `transfer_probe` is authored by
> the architect, stored by the engine, and read by nothing.*

**Why.** Constitution article 8 ("meet the learner in their real work") and `skills/learn` §5
("this is the point of the whole topic — do not let it silently not happen"). It silently does
not happen: zero transfer receipts exist, anywhere, ever. Engram is a very good memory system
wearing a capability system's marketing.

There is a sharper version of this critique, and it must be taken seriously rather than
deflected: **transfer-appropriate processing** says practice should match use. If the learner's
goal is *to do* (write the code, make the call) and every review is *verbal free recall*, Engram
may be training a genuinely different skill from the one that was paid for. `docs/07` §8
adjudicates this; v0.8 is the design response.

### What

1. **Wire up `transfer_probe`.** At review time, for a mature node (`s > 21` and `reps ≥ 3`),
   serve the `transfer_probe` instead of the `probe` on a defined cadence. Receipt gets
   `kind: "transfer"`. **This is a free capability measurement using data the architect has been
   writing since v0.1 and nothing has ever read.**
2. **Node-level transfer state** (`docs/09` §3.2): `untested | probed | applied`. A node is
   *retained* when recall survives a month; it is *owned* when it fires on a transfer probe.
   Stop conflating them.
3. **Capstones become nodes, not hopes.** When a topic's frontier empties, the engine
   materializes a `capstone` node **in the graph**, state `new`. It appears in `next` and `due`
   like anything else. It cannot silently not happen, because it is in the DAG.
4. **`stats.transfer`** — transfer-probe recall reported **separately** from ordinary recall.
   Never pooled. The two numbers answer different questions and one of them is the one that
   matters.

### Done

- [x] `stats.transfer` reports capability separately, with its own n and its own denominators.
- [x] A topic materializes a capstone node that appears in `next` when the frontier empties
      (`add-topic` mints it structurally; `capstone --topic T` retrofits a pre-v0.8 graph, idempotent).
- [x] **The capstone gets NO provisional credit** — unplanned, and found by an existing check breaking
      the moment the capstone entered the DAG. An ordinary node advances on a stashed-but-ungraded
      prereq; the capstone may not, because it is the claim that the learner can now USE the topic.
- [ ] **The author's `transformers` topic produces ≥1 `kind: transfer` receipt.** ← STILL OPEN, and
      it is the same open thing as always: nothing on that graph is mature (7 encoded, **0 reviewed**).
      The engine can now ask the question. It cannot make anyone come back to answer it.

### Selftests

`transfer` serves only mature nodes · transfer receipts are excluded from `recall_by_stability`
and counted in `stats.transfer` · capstone materialization is idempotent (runs twice → one node) ·
a node with a null `transfer_probe` is never selected.

### Risk

Capstones are expensive and can feel like homework; the two-minute floor must still outrank them.
Capstone is an **offer with a real "not now"** that costs nothing and does not nag on repeat.

---

# v0.9 — **The Method**

> *`experiment assign` is round-robin, not randomized. Unstratified. Unpowered. Settled by
> narration.*

**Why.** Article 7 ("adapt on evidence, never taxonomy") is the article that replaces learning
styles with real n-of-1 measurement — and the machinery that implements it is not currently
sound enough to support the claims it exists to make. `docs/06` open question 2 already documents
the consequence: `stats.modality`'s two arms are **confounded by construction**, because
explorables are routed to the hardest concepts on purpose, so the comparison carries material as
well as medium. The document disclosed the confound honestly. v0.9 *fixes* it.

### What

Rewrite `experiment` per `docs/09` §4.5 and the protocol in `docs/07` §9:

- **Randomized** assignment with a recorded **seed** (deterministic, auditable, reproducible).
- **Stratified** by the confounders that actually bite — `threshold`, `viz.affordance`,
  node difficulty — so the material stops riding along with the arm.
- **Pre-registered**: question, arms, metric, `min_per_arm`, and **analysis plan**, written
  before a single datum exists. The design file is the pre-registration.
- **Powered**: `min_per_arm: 15` (≈30 observations total) — the SCED alternating-treatments
  literature puts sufficient power at ≈28–30. **Today's value is 6, which is underpowered by
  roughly 2.5×** (`docs/07` §9). `stats.modality`'s identical ≥6 floor inherits the same defect
  and moves with it.
- **Settled by the engine**: effect, interval, and an honest `"underpowered"` read when n is
  short. The model narrates the engine's verdict; it never computes one.
- **First experiment to run:** the modality question, properly — randomize explorable-vs-dialogue
  *within a single affordance class*, which is the only form of the question that can be
  answered without violating the content rule (`docs/06` §Open Q2).

### Done

- [ ] One experiment settled with an engine-computed verdict, an effect size, and an honest
      statement of uncertainty.
- [ ] `stats.modality`'s caveat can finally be *retired for the randomized arm* — replaced by a
      real, if small, result.

### Selftests

Assignment is randomized *and* reproducible from the seed · stratification balances arms within
each stratum · settle refuses below `min_per_arm` and reads `underpowered` · the verdict is
computed by `engram.py`, never accepted from a payload.

---

# v1.0 — **The Commons**

> *The first learning system that is also an experiment the whole field can read.*

**Why.** `docs/08` §6. The evidence base of learning science is built on undergraduates, word
pairs, and 20-minute retention intervals. **Almost nothing tests self-directed adults, on hard
conceptual material, at 30–90 day horizons, with blind-graded free recall.** Engram produces
exactly that data as a byproduct of being useful, on hundreds of machines, and — after v0.7 — with
a *measured* oracle behind every grade. Nobody else has this, because until 2026 grading free
recall at scale was impossible.

### What

- **`export`** (`docs/09` §4.6) — writes a text-stripped receipt bundle **to a file**. Productions,
  probes, claims, rubrics, goals, interests, misconception text, topic strings and node ids never
  leave. The `stripped` list sits *inside the file*, so the promise is verifiable rather than trusted.
- **It is ATTRIBUTED, and the consent step says so out loud.** The obvious transport is `gh` — already
  installed and authenticated on most Claude Code machines — and **a GitHub post carries your
  identity**. A "salted anonymous hash" riding inside a signed envelope would be a lie, so Engram
  does not tell it. Attribution is also the *stronger* design: a retention study needs **longitudinal
  linkage** (following the same learner across months *is* the question), plus dedup, fabrication
  detection, and the ability to credit contributors. A consenting, named participant in an open study
  is what every good study has always had.
- **The engine still contains no network code.** `export` writes a file and stops. `/coach contribute`
  shows the learner the exact file, then — only on an explicit yes that **names the handle it will
  post under** — has `gh` open a Discussion on a separate `engram-data` repo. The *agent* posts;
  `engram.py` never grows a socket.
- **Degrade to silence.** No `gh`, no token, offline → the file is still written, the path is still
  printed, nothing errors and nothing nags. **`gh` is a convenience, never a dependency** — and
  declining must cost the learner nothing, or the consent is not real.
- **Every shared receipt carries its grader's measured QWK.** A finding aggregated from unaudited
  oracles is not a finding. **This is why v0.7 gates v1.0.**
- **Give back:** contributors' dashboards gain honest cohort comparison — confounds stated always,
  in the same voice as `modality.caveat`.

### Done

- [ ] `export` produces a file containing **zero** free text (selftest greps for it).
- [ ] `grep -rE 'socket|urllib|requests|http' scripts/engram.py` → **zero hits.** The promise is
      structural, and it is a permanent selftest.
- [ ] `/coach contribute` works with `gh` **and degrades silently without it.**
- [ ] `CONTRIBUTING-DATA.md` exists and is a real informed-consent document: what leaves, what never
      leaves, that it is **public and attributed**, and how to delete it.
- [ ] First open finding published from N ≥ 100 learners, with its confounds stated in public.

### Selftests

Export contains no field from the stripped list (property-based: put text in every field, assert none
survives) · **the no-network test is a selftest, permanently** · export refuses when
`grader_unvalidated`.

---

## The parallel track (any release, any time)

Small, safe, always welcome — good first work for a cheaper model:

- **Assessor gold-set growth.** Every real disputed grade is a gold-set candidate. This directly
  raises the quality of the audit in v0.7.
- **Widget vocabulary.** The Explorable Contract's library grows; the Contract does not bend.
- **`doctor` coverage** for every new schema field.
- **Codex parity.** `codex/agents/*.toml` must track `agents/*.md`. They drift silently.
- **The `refit` upgrade** — full per-parameter FSRS optimization, replacing the coarse single
  multiplier. Gated on ≥ the review volume the FSRS literature requires (`docs/07` §2); until
  then the honest coarse fit stays and says so.

## What is deliberately NOT on this roadmap

Refusing things is how the constitution stays real:

- **A fourth verb.** Three verbs, forever. Every feature above lands inside `/learn`, `/review`,
  `/coach`, or the engine.
- **Streaks, XP, badges, levels, leaderboards.** (`docs/05`; re-adjudicated adversarially in
  `docs/07` §4, same verdict.)
- **A cloud sync / account / hosted dashboard.** The engine has no network code, and that is a
  structural property rather than a setting.
- **Visual retrieval formats.** Still an open question (`docs/06` §Open Q1). Reviews stay verbal
  free recall until evidence ships, not vibes.
- **A mobile app.** Engram lives where the learner's real work lives. That is the whole point of
  article 8.

---

## The one-glance sequence

```
v0.6  THE LOOP        adherence · retention · decay · commit · idempotent receipts
      ↓               you cannot fix what you cannot see
v0.7  THE ORACLE      gold set · assessor-audit · grader-health · teeth
      ↓               you cannot trust a number a lenient grader produced
v0.8  THE CLAIM       transfer probes · transfer state · real capstones
      ↓               you cannot claim capability while measuring only memory
v0.9  THE METHOD      randomized · stratified · pre-registered · powered
      ↓               you cannot learn from a confounded arm
v1.0  THE COMMONS     consenting export · no network code, ever · the fleet answers
```

Each layer is load-bearing for the next. Skipping ahead produces a beautiful number that is not
true — which is the exact failure mode this project exists to make impossible.
