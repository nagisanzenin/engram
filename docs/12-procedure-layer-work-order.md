# 12 · The Procedure Layer: Architecture & Work Order (v1.1.0)

> The buildable form of `docs/11-the-procedure-gap.md`, in the `docs/10` discipline: why /
> what / done-when / selftests / risk, shippable by someone who has never seen the repo.
> **Binding constraint: Engram runs on thousands of machines. Every change below is additive;
> a v1.0.8 learner state, graph, or receipt log replays with identical BEHAVIOR (schedule,
> grades, flow — new receipts gain a `node_kind` stamp and read payloads gain additive keys),
> and a topic built by a v1.0.8 architect behaves exactly as before on the v1.1.0 engine
> and skills.**

## 0 · The compatibility doctrine (read first, check last)

0. **Engram stays a GENERAL learning system — this layer must never narrow it.** (Founder
   directive, 2026-07-22.) There is no math mode, no STEM branch, no domain routing
   anywhere in engine, skills, or agents. What ships is a third *knowledge kind* that any
   topic can exercise — a `procedure` node is `git rebase -i`, a jazz voicing drill, or
   Vietnamese tone-mark placement exactly as it is integration by parts. The **content
   declares the kind per node** (the architect, per Willingham's rule — the same covenant as
   `viz`), and a topic with zero procedure nodes behaves exactly as on v1.0.8. Math &
   STEM are the layer's hardest customers, not its scope.
1. **No new commands, no changed flags' meanings, no schema migration.** The layer rides the
   `viz` extension pattern: architect-declared node metadata, stored opaquely, skills own
   semantics, receipts measure.
2. **Absence is the old behavior.** A node without `kind` is a `concept`; a graph without
   procedure nodes produces a `stats.by_kind` that says so and changes nothing else; a
   procedure node without `practice` degrades to concept-style review (stored probe verbatim)
   and says so in the skill, not in an error.
3. **Two names, two meanings, never shared:** a receipt's `kind` (encode/review/pretest/
   transfer/audit — the *event*) is untouched. The new field is `node_kind` (concept/
   procedure/fact — the *knowledge*) everywhere the engine surfaces it (receipts, `due`
   payload, export, stats). The node's own JSON carries the architect's `kind` field, in node
   namespace, like `viz`. (`RELEASE_PROTOCOL` §4.8 Q6: two denominators never share a key.)
4. **Every new literal is a closed enum validated at ingest** (`NODE_KINDS`,
   `ERROR_CLASSES`), so a typo dies before an append-only write, and export can carry them
   un-hashed under the existing enum rule.
5. **The grader gate travels with the feature:** the gold set gains procedure items in the
   same release that teaches the assessor to grade procedures — never one without the other.

## 1 · Architecture (one page)

```
ARCHITECT (agent)                         ENGINE (engram.py)                SKILLS (tutor)
 declares per node:                        stores opaquely; derives:         read node.kind:
  kind: concept|procedure|fact              node_kind_of(node)                concept -> beats 1-8 (unchanged)
  practice: {problem_frame,                 due payload += node_kind,         procedure -> problem ladder
             discriminates_from?,                          practice           (L1 worked -> L2 completion ->
             verify?, error_bank?}          receipts += node_kind stamp        L3 faded -> L4 solve)
  rubric = STEP RUBRIC for procedures       receipts += error_class           review: fresh instance from
  (setup/method/execution/verify)           stats += by_kind (+caveat)         problem_frame; discrimination
       |                                    report += kinds section            beat when siblings co-due;
       v                                    export += node_kind,               verify-by-execution before
  probe = ONE canonical concrete            error_class (enums)                rating; slip -> hard + 
  instance (pretest + fallback)                                                --error-class slip
                                                                              
ASSESSOR (agent, blind)                                                    GOLD (instrument)
 step-shaped rubric -> step grading;                                        +20 procedure items
 MUST execute checkable computations;                                       (wrong-method/slip/
 error_class: conceptual|slip;                                              fluent-wrong-step...)
 method wrong -> lapsed; slip-only ->                                       audited by the same
 partial; right-answer-wrong-method                                         /coach audit flow
 -> capped at partial
```

The load-bearing simplification: **the step rubric IS the `rubric` field.** It already flows
stash → assessor → receipt → gold with zero plumbing, so the assessor contract, the gold
schema (`GOLD_ASSESSOR_KEYS`), and the stash schema need no structural change — the
procedure layer changes what the architect *writes into* the existing fields and what the
graders *do with* them.

## 2 · Work orders

### WO-1 · Engine: `node_kind` (the ontology, made data)

**What.** `NODE_KINDS = ("concept", "procedure", "fact")`; one shared, type-safe
`node_kind_of(node)`: explicit valid `kind` → itself; else `arbitrary: true` → `"fact"`;
else `"concept"`. `add-topic` validates: unknown `kind` string → warning + field dropped
(never a die — an older/newer architect must not brick an add); `practice` non-object →
warning + dropped (the `viz` rule); `kind: "procedure"` without `practice.problem_frame` →
warning (ships, degrades gracefully). `due` payload gains `node_kind` + `practice`;
`cmd_next` already emits the whole node (rides free). `apply_item` stamps `node_kind` into
every receipt at grading time (the `artifact`-stamp discipline: evidence of what the node
*was* when graded, never rewritable by a later graph edit).

**Done when.** A v1.0.8 graph JSON round-trips bit-identically through `add-topic --replace`
minus the documented defaults; a kindless node stamps `node_kind: "concept"`; an
`arbitrary: true` node stamps `"fact"`.

**Selftests.** (a) kind stored + surfaced in `due`; (b) invalid kind dropped with warning;
(c) `node_kind_of` on garbage node types returns `"concept"`, never raises; (d) receipt
carries the stamp; (e) v1.0.8-shaped fixture (no kind anywhere) → every existing behavior
unchanged (assert against captured pre-change output; new receipts add only the stamp).

**Risk.** Payload growth on `due` (practice blocks). Bounded: architect instructed to keep
`error_bank ≤ 3`, `problem_frame` one paragraph.

### WO-2 · Engine: `error_class` (slip ≠ lapse, made data)

**What.** `ERROR_CLASSES = ("conceptual", "slip")`. `validate_item` dies on any other value
(ingest validation, §4.8 Q5); `make_receipt` carries it when present; `rate` gains
`--error-class` (optional; the CLI path must be able to say what the skills say);
`export` gains `error_class` + `node_kind` (both closed enums → leave as themselves;
`EXPORT_RECEIPT_KEYS` + `_EXPORT_ENUM` updated; `stripped` list untouched — no new text).

**Done when.** A receipt written via assessor output or `rate --error-class slip` carries
it; `rate --error-class typo` dies before any write; export payload carries both new enums
and a canary test proves no free text rides them.

**Selftests.** All of the above + mutation test (revert the validate → the typo check fails).

**Risk.** None to old data — absent field stays absent.

### WO-3 · Engine: `stats.by_kind` + dashboard section (the telemetry that arbitrates)

**What.** `compute_by_kind(receipts)` in the exact `compute_modality` mold: one datum per
node (first review), `_outcome` as the shared predicate, per-kind
`{first_review_recall, n}`, floor = `MODALITY_MIN_N` per compared arm, `read` compares
**procedure vs concept only** (`fact` reported, never versus'd), and a `caveat` that ships
*inside the payload*: kinds are different material by construction — never a causal claim;
this is also the instrument for docs/11 §7.3 (FSRS has no published validation on skills;
DAS3H — Choffin et al. 2019 — is the skill-level precedent, and this telemetry is what
would justify moving toward it). Plus
`procedure_slip_share`: among procedure-node review receipts that carry `error_class`,
the slip fraction — with `n_classified` as its own labeled denominator (never `n`).
`report` gains a "Knowledge kinds" section in the modality section's mold (bars + the
caveat in the note; honest insufficient-data branch). `/coach` narrates it as check-in
item 5.5, caveat voiced, only when read ≠ insufficient-data.

**Done when.** §4.8 answered in writing for both new numbers (see §4 below); dashboard grep
finds the caveat string; a kindless state renders the section honestly ("no
procedure-encoded reviews yet") without a crash.

**Selftests.** by_kind arithmetic on a hand-computed fixture where kinds diverge; the floor;
the caveat present in payload AND in rendered HTML (grep the report output); slip-share
denominator = classified receipts only (fixture with mixed classified/unclassified);
fuzz-proof (garbage kinds/receipts → degrade, never brick).

**Risk.** The three-arm read tempts a fabricated comparison metric — refused by design
(procedure-vs-concept only, same Δ>0.10 convention as modality).

### WO-4 · Architect: declare the kind, write the practice

**What** (`agents/engram-curriculum-architect.md` + Codex TOML port in lockstep).
Method step: classify each node `concept | procedure | fact` (fact = today's
`arbitrary: true`, which remains honored; write both for back-compat). For procedures:
`claim` states the procedure's contract; `probe` is ONE fully-specified concrete instance
(pretest + fallback); **`rubric` is the step rubric** — setup / method choice / execution /
verification, written as an exam grader would; `practice.problem_frame` says what varies
and what stays across fresh instances (one paragraph, with bounds that hold difficulty
fixed); optional `practice.discriminates_from` (confusable sibling ids — drives the
interleaved naming beat), `practice.verify` (how to check an answer by execution),
`practice.error_bank` (≤3 seeded bugs, each tagged with its misconception — **from the
domain's documented error catalogs when one exists** (FCI-style force–motion confusions,
natural-number bias, sign errors), which the architect's WebSearch can reach). Self-check
additions: procedure without problem_frame; error_bank invented when a documented catalog
exists; discriminates_from referencing nonexistent ids.

**Done when.** A dogfooded math topic returns kinds + practice blocks that validate, with
step rubrics an assessor can grade against.

**Risk.** Older architect output (no kinds) must stay valid forever — it is, by WO-1.

### WO-5 · Skills: the problem ladder (`_shared/problem-grammar.md`, new) + learn/review/coach deltas

**What.** One new shared file (~80 lines), read on demand exactly like the Explorable
Contract, holding: the ladder (L1 worked example + per-step self-explanation → L2
completion → L3 faded, principle-bearing blanks → L4 cold solve), rung selection from
measured state (pretest result, lapses, node state — the `docs/06` worked-drive signals),
the fresh-instance rule (**algorithmic variants**: new values, same structure and cover
story — the verified retention configuration; full re-clothing stays `transfer_probe`'s
job; NEVER stored numbers; **compute the answer key by execution before showing
anything**), the discrimination beat (confusable `discriminates_from` siblings served
**adjacently, same session** — juxtaposition carries the effect: g 0.73 adjacent vs 0.22
scattered; "which technique, and why — then solve"), the erroneous-example rung (after
instruction, always find-explain-fix-scaffolded, never a default; the clean-solve gate
died in verification), slip handling (method right + execution slip → grade `partial`, rating `hard`,
`--error-class slip`; right answer + wrong/absent method → capped at `partial`,
`--error-class conceptual`; both wrong → `lapsed`), and the PS-I boundary (the *concept*
node that licenses a procedure keeps the native PREDICT→STRUGGLE opening; the ladder is
for the skill nodes).
`learn` step 3: one routing line (node.kind == procedure → ladder replaces beats 2–4;
VERIFY = fresh-instance solve; beats 5–8 unchanged). `review` step 2: procedure items get
fresh instance + execution-verified rating + error-class flag; special-case re-encode
(≥2 lapses) may use an erroneous example. `dialogue-grammar`: one pointer line + the
rating-map footnote for slips. `coach`: check-in item 5.5 (by_kind, caveat voiced).

**Done when.** The §5.5 dogfood (uncontaminated, release-tree agents) walks a procedure
node end-to-end: architect → add-topic → ladder encode → stash → blind assessor with step
rubric → receipt carrying `node_kind` + `error_class` → fresh-instance review → by_kind
telemetry, with concept nodes behaving exactly as on v1.0.8 throughout.

**Risk.** Skill-prose token growth. Budget: `problem-grammar.md` ≤ 95 lines (landed at 93 — the §4.6 review added the grading tiebreak and check-ordering rules); net additions
to existing SKILL.md files ≤ 25 lines total; platform-neutral wording per §5.7
(capabilities, never platform names).

### WO-6 · Assessor: step grading + the execution duty

**What** (`agents/engram-assessor.md` + TOML port). New section: when a rubric is
step-shaped, grade per step; **every deterministically checkable claim (arithmetic,
substitution, units/dimensions, limiting cases) must be verified by execution, never by
inspection** — the assessor has tools; if execution is genuinely impossible, say
`unverified-by-execution` in `rubric_notes`. Output items may carry
`error_class: "conceptual" | "slip"` — the *controlling* error; slip-only → `partial`/
`hard`; method wrong → `lapsed`/`again`; **right-answer-wrong-method caps at `partial`**
(the derivable-owes-a-why rule, transposed). `sid`/confidence/blindness rules unchanged.

**Done when.** Gold procedure items (WO-7) are graded correctly across 3 independent runs;
a receipt round-trip preserves `error_class`.

**Risk.** ProcessBench says step-error detection is fallible — which is why WO-7 ships in
the same release, and why execution is a duty, not a suggestion.

### WO-7 · Gold: ≥20 adversarial procedure items (the instrument extension)

**What.** `gold/assessor-gold.jsonl` gains ~20 items (sids continue `g_067+`), same schema
(step-shaped rubrics; no format change), across the traps that matter for solutions:
`right-answer-wrong-method` (the transposed `right-answer-wrong-reason`),
`slip-vs-conceptual` boundary (both directions), `fluent-wrong-step` (confident prose,
broken algebra), `terse-but-correct-solution`, clean `recalled`/`lapsed` anchors, and
partial-credit boundaries. Every item's `rationale` quotes the rubric criterion that
decides it. Domains: algebra/calculus/probability/units — checkable by a grader that
executes.

**Done when.** `/coach audit` flow (3 independent assessor runs on the FULL extended set)
completes; the audit's `by_case_type` carries the new rows; the README badge count is
restated from the actual runs (`0/N graded up` must be re-earned, never extrapolated);
`graded_up` on procedure items == 0 or every exception is investigated as a spec bug
before ship.

**Risk.** Authored-gold circularity — already stamped by the engine
(`gold_adjudication: "authored"`); the badge claim stays the direction count, which
survives imperfect calibration (v0.7 doctrine).

### WO-8 · Docs, README, CHANGELOG, versions

docs/11 §Method updated with G1 verification outcomes; README (version + selftest badges,
gold badge from WO-7's actual runs, "Why it works" gains the problem-practice line, FAQ
gains the math question, Documents table gains this file, export leaves-table gains the two
new enums); CONTRIBUTING-DATA.md field list updated; INSTALL-CODEX selftest count; 4
manifests + `ENGRAM_VERSION` → **1.1.0** (user-visible feature → minor); CHANGELOG with
the honest parts.

## 3 · Order of operations

WO-1 → WO-2 → WO-3 (engine, selftested, mutation-tested, fuzzed) → WO-4/WO-6 (agents) →
WO-5 (skills) → WO-7 (gold + audits) → WO-8 (docs/bumps) → full gate ladder
(`RELEASE_PROTOCOL` §4→§5.7) → **stop before §6 for the founder's mark.**

## 4 · The numbers audit, pre-answered (binding for WO-3)

**`by_kind.first_review_recall`** — (1) cross-consistent by construction: same
`_review_receipts` population and `_outcome` predicate as modality/experiments; (2) fails
pessimistically when kinds are mis-stamped toward concept (dilution), optimistically only
if procedure receipts were stamped concept AND procedures hold worse — bounded by the
ingest-validated enum; (3) denominator = first reviews per kind, labeled `n`, floor
published as `min_n`; (4) read by `/coach` item 5.5 + dashboard section (caveat greppable in
HTML); (5) CLI-reachable only through `stats` (read-only); (6) label states *first-review
recall*, never "retention".
**`procedure_slip_share`** — (1) consistent with receipts by definition; (2) optimistic
failure = assessor over-calling `slip` (flattering: "you knew it, you just slipped") —
capped by WO-7's slip-vs-conceptual gold items, and the caveat names it; (3) denominator
`n_classified` (receipts carrying `error_class`), never all procedure receipts, said in the
label; (4) read by coach + dashboard note; (5) `rate --error-class` is enum-validated; (6)
labeled "of classified errors", with `n_classified` beside it.

## 5 · What could still stop the ship (owned risks)

- **G1 fallout: RESOLVED 2026-07-22** — the three-verifier pass ran (docs/11 §Method):
  5 corrections, 1 inverted rule (isomorphs → algorithmic variants), 1 regated rule
  (erroneous examples), all applied to docs/11, this file, the problem grammar, and the
  agent specs in the same branch. Two hard requirements were promoted out of it: review
  format stays congruent (the solve IS the review) and every grading carries elaborated
  feedback — without both, transfer prices near zero (Pan & Rickard, bias-adjusted).
- **Gold reveals a grading hole:** a `graded_up > 0` on procedure items is a spec bug in
  WO-6 — fix the spec, re-run all three audits, only then restate the badge.
- **Dogfood contamination:** all agent tests run against the release tree by absolute path
  (the installed plugin cache is v1.0.8 and MUST NOT be the test subject — §5.5 second rule).
- **The §5.6 user session verdict is binding.** If the ladder feels like homework-theater in
  a real session, it does not ship, whatever the tests say.
