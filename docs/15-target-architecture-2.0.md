# 15 · Target Architecture for 2.0: Schemas, Surfaces, Invariants

`docs/09` did this job for the road to 1.0, and it is the reason that road was iterable:
five releases built against one schema authority instead of five implementers' guesses.
This document is the same instrument for [`14-roadmap-to-2.0.md`](14-roadmap-to-2.0.md):
every field, payload, and command the work orders name is given here in full, with its
default, its self-heal behavior, and the invariant that guards it.

**How to read it.** A delta over `docs/03` (as built) and `docs/09` (the 1.0 target,
now shipped). Where 14 and 15 disagree, **15 is the schema authority** — and two such
disagreements already exist and are resolved here, deliberately (§2.3 receipt stamping;
§2.2 retirement), because writing schemas is how prose bugs get caught. Sections marked
**[BINDING]** are settled for v1.3–v1.6; sections marked **[RE-ANCHOR]** (v1.7–v2.0
surfaces) give the target shape but must be re-read against accumulated telemetry before
their release builds — the shape is a commitment, the details are not yet.

---

## 1 · Invariants

### 1.1 Carried forward whole (docs/09 §2 — unchanged, still outranking everything)

Stdlib-only, no network code · the engine owns every number · receipts append-only,
never rewritten · state advances only through receipts · the assessor never sees the
dialogue · confidence picked or null · learner text never on a command line · mutating
commands take the lock · defaults backward-compatible and self-healing · every engine
change ships a selftest that fails without it.

### 1.2 New invariants (the 2.0 additions, numbered continuing docs/09)

11. **Read-only commands stay read-only under temptation.** `propose`, `due --cap`,
    `adherence`, `adjudication-stats`, `grader-health` never write and never take the
    lock. (`stats.proposals_pending` re-runs the deterministic proposal computation —
    nothing persists a pending queue.)
12. **A canary audit can never mint a `pass`.** Its verdict domain is
    `{canary-pass, canary-fail}`; only a full-set audit can certify. Any code path that
    lets a canary satisfy the export gate on its own is a defect.
13. **`relearn` rows are excluded from every retention-family population by the shared
    predicates** (`_review_receipts` and friends), never by per-caller filters — one
    predicate change, every reader inherits it (the v0.6.4 lesson, made law).
14. **Every model-derived number carries its label in the payload** (`order_basis`,
    `schedule_policy`, `basis` on fits, `grade` on proposals). A payload a skill can
    read without seeing the label is a defect (doctrine 14 §0.5).
15. **Adaptation is proposed–consented–logged–reversible** (Article 12, v1.8): the only
    writer of a learner-model change offered by the system is the consent flow, and it
    writes `adaptations.jsonl` in the same transaction.
16. **Retirement is a learner decision, not a mastery event.** It is exempt from
    "state advances only through receipts" because it advances nothing; it is recorded
    on the node it governs (§2.2) and — once the ledger exists — there too. The engine
    never proposes retiring a specific node.

---

## 2 · State schema deltas (all additive; every field self-heals)

### 2.1 `learner-model.json` — additions **[BINDING through v1.6; v1.8 fields RE-ANCHOR]**

```jsonc
{
  "schema": 1,
  "memory": {
    "desired_retention": 0.90,
    "interval_multiplier": 1.0,          // RESET to 1.0 by the v1.6 migration (§5.2)
    "last_refit": null,
    "fsrs_params": null,                 // v1.6 tier-2 fit writes {w: [...17], basis: "<label per inv.14>"}
    "fsrs_version": "4.5"                // v1.6: "6" after migration; readers refuse unknown values
  },
  "challenge_band": { "target_success": 0.85, "hint_budget": 2 },   // unchanged; still static (13 §2.7 rank 5)
  "settings": {
    "default_mode": "standard",
    "artifacts": "threshold-only",
    "ambient": "quiet",
    "momentum": "on",
    "profile": null,
    "decay_notice": "on",

    "commitment": {                      // v1.3: gains renewal metadata
      "cue": "...", "action": "...", "set": "2026-07-23",
      "renewed": []                      // ISO dates; commit stamps; emits age_days = today - max(set, renewed)
    },

    "relearning": "on",                  // v1.5: "on"|"off" — the dose caps + retry protocol master switch
    "audit_offered": null,               // v1.3-E: ISO date once the one-time offer was made; never re-offered
    "srl": "on"                          // v1.8 [RE-ANCHOR]: "on"|"off" — the SRL prompt layer
  },
  "rhythms": {},                          // v1.8 REMOVES this key (heal drops it; §2.6 stats.sessions replaces)
  "accessibility": []
}
```

Self-heal: absent `relearning`/`srl` → `"on"`; absent `renewed` → `[]`; absent
`fsrs_version` → `"4.5"`; a v2.x model read by v1.2.2 works untouched (all additions are
in namespaces v1.2.2 never enumerates).

### 2.2 Graph node — additions **[BINDING]**

```jsonc
{
  "id": "...", "claim": "...", "probe": "...", "rubric": [...],
  "state": "new|learning|review",        // UNCHANGED. Retirement is NOT a state value —
                                          //   see below for why.
  "fsrs": {
    "s": 14.2, "d": 4.1, "due": "...", "last": "...", "reps": 3, "lapses": 0,
    "dose": true                          // v1.5: stamped TRUE at first-encode when
                                          //   settings.relearning == "on". The interval caps
                                          //   (min(FSRS,3d) then min(FSRS,9d)) apply only while
                                          //   dose == true AND reps < 3. Pre-v1.5 nodes never
                                          //   gain the stamp → never capped (the new-nodes-only
                                          //   scoping, made mechanical rather than dated).
  },

  "retired": null,                        // v1.3: or {"ts": "2026-08-01", "restored": null}.
                                          //   Engine-owned; written only by `retire`/`--restore`
                                          //   (restore stamps `restored`, keeps the block — the
                                          //   decision's history is auditable, append-only in
                                          //   spirit). RESOLVES 14 v1.3-F, which said
                                          //   `state: "retired"`: mutating the state enum would
                                          //   ripple through every state reader AND block the
                                          //   capstone (which requires every node) forever.
                                          //   Instead: state is untouched; one shared predicate
                                          //   `is_retired(node)` gates due/next/decay/transfer/
                                          //   adherence populations.

  "arc": 1                                // v1.7 [RE-ANCHOR]: extension arcs stamp 2, 3, …;
                                          //   absent → 1.
}
```

**Retirement semantics (the decisions 14 left open, decided):**

- `requires_met` treats a retired prerequisite as **satisfied** — the learner declared
  it not-needed; gating dependents forever would punish the verb. The tutor may still
  brief the gap in prose. (Selftest: retire a mid-DAG prereq → its dependent becomes
  frontier-eligible.)
- The **capstone requires every non-retired node** — enforced *dynamically* in
  `requires_met`, not by filtering at mint time (amended at build: retirement usually
  happens long after the capstone is minted, so a mint-time filter would have missed exactly
  the case that matters). Retiring any node un-blocks, never blocks. Restore re-tightens.
- `retire --topic T` (whole topic) stamps every node; topic listings show
  `retired: true` at topic level when all nodes carry the block.
- Denominators (invariant: counted, labeled, never dropped): `adherence` gains
  `retired: {nodes}`; `retention.unmeasured` gains `retired` beside `past_due_now`
  (retired nodes leave `past_due_now` and enter `retired`); `stats`/dashboard render
  "N due · M retired by you".

### 2.3 Receipt — additions **[BINDING]**

```jsonc
{
  "id": "r_...", "ts": "...", "topic": "...", "node": "...",
  "kind": "encode|review|pretest|transfer|audit",   // enum unchanged
  "grade": "...", "rating": "...", "confidence": 72,
  "production": "...", "probe": "...",
  "source": "self|assessor", "grader": "engram-assessor|null",
  "s_before": 1.4, "s_after": 12.9, "due_next": "...",
  "node_kind": "concept|procedure|fact", "error_class": "conceptual|slip",
  "sid": "s_...", "days_since_encode": 27,

  // ── v1.5 · the relearning fields ─────────────────────────────────────────
  "relearn": true,                        // present (true) ONLY on same-day re-attempt rows.
  "attempt": 2,                           // 2, 3, 4… — the retry ordinal within the day.
                                          //   RESOLVES 14 v1.5-B, which said retries_to_criterion
                                          //   is "stamped on the day's first receipt": that receipt
                                          //   is already on disk when retries happen, and receipts
                                          //   are append-only — retro-stamping is forbidden by
                                          //   invariant. Authority: retry data lives ON the retry
                                          //   rows; `criterion_met` and `retries_to_criterion` are
                                          //   DERIVED at read time (stats.relearning) from the
                                          //   day's row group (first receipt + its relearn rows).

  // ── v1.4 · the audit-kind fields ─────────────────────────────────────────
  "audited_rating": "hard",               // audit-kind rows only: what the tutor had committed.
  "agree": false                          // audit-kind rows only: assessor's verdict vs it.
}
```

`apply_item` rules: `kind: "audit"` writes the receipt and **touches no FSRS state, no
node state, no schedule** (fixture asserts byte-identical node). `relearn: true` rows
likewise never touch state (invariant 13); they are legal only for `concept`/`fact`
nodes (procedure retries are refused with the boundary citation — 13 §2.5). A payload
supplying `retries_to_criterion`/`criterion_met` is stripped (the add-topic stripping
discipline: derived fields are never ingested).

`rate` grows: `--relearn` (marks the row; engine validates same-day-after-first),
`--audited-rating <r>` (audit kind only).

### 2.4 The audit file — additions **[BINDING]**

```jsonc
// audits/<date>-NN.json
{
  "n": 86, "qwk": 0.96, "exact_agreement": 0.97, "leniency_bias": -0.02,
  "test_retest": 0.98, "confusion": {...}, "by_case_type": {...},

  "grader_context": "claude-code/opus-4.8",  // v1.4: verbatim from --grader-context;
                                              //   "unknown" when the skill couldn't supply one.
  "scope": "full",                            // "full" | "canary"
  "by_gold_band": {                           // v1.4: per gold grade — the mid-band exposure
    "recalled": {"n": 34, "exact": 0.99, "bias": 0.00},
    "partial":  {"n": 25, "exact": 0.90, "bias": -0.04},   // the row that matters (13 §2.4)
    "lapsed":   {"n": 27, "exact": 0.98, "bias": -0.01}
  },
  "spec_flip_rate": null,   // ⚠ NOT SHIPPED in v1.4 (deferred — no gold/spec-paraphrases/)                     // v1.4-E: set only by `/coach audit deep`;
                                              //   fraction of canary items whose grade changed
                                              //   across spec paraphrases; ≥0.10 → verdict "warn"
  "verdict": "pass|warn|fail|incomplete|insufficient-runs|canary-pass|canary-fail"
}
```

`grader-health` input gains `--grader-context <current>`; verdict logic adds, before all
existing rules: latest full audit's context ≠ current context (both known) →
`stale-model`; either unknown AND latest full audit older than 90d → `stale-age`; both
flip `grader_unvalidated: true` and the export refusal. `canary-pass` clears staleness
**back to the prior full verdict** (recorded as `relicensed_by: <canary file>`); it
never upgrades a `fail`.

`gold --canary`: emits 15 items, seed-stable (`sha256(sid)` ordering — no RNG), **quota-
stratified across all three bands** (`partial` 7 · `lapsed` 4 · `recalled` 4), preferring
the historically-weak case types within each band; output shape identical to `gold` (a
drop-in for the same skill flow).

**Amended at build time (v1.4), all three forced by gates:**
1. **Quotas, not a difficulty sort.** "Oversample partial" as specified selected 15/15
   `partial` — a canary that cannot see a grader failing the clear cases is a narrower
   badge, not a tripwire.
2. **`_latest_audit` skips canary-scoped files.** Otherwise a canary becomes "the latest
   audit", replacing an 86-item verdict with a 15-item one, and `canary-pass` — correctly
   not a valid *full* verdict — reads as `unreadable` and voids a healthy badge.
3. **The canary needs its own `min_n`.** Held to the full audit's floor it would always
   read `insufficient-data`, i.e. dead code shipped as a feature (bug class #3).

### 2.5 New files **[BINDING at v1.8 shape level; RE-ANCHOR details]**

```
~/.claude/learning/
├── adaptations.jsonl        // v1.8 — append-only ledger:
│   //  {"ts": "...", "field": "settings.default_mode", "from": "standard",
│   //   "to": "sprint", "evidence": "5 of last 6 standard sessions ended early",
│   //   "grade": "model-derived", "source": "consented|learner", "reversible": true}
│   //  `retire`/`--restore` also append here once the file exists (inv. 16).
└── gold/adjudications/<rater>.jsonl   // v1.4 — external adjudication kit input:
    //  {"sid": "g_001", "grade": "partial", "anchor": false}  · one row per item;
    //  rows with "anchor": true are the 10 calibration items (excluded from stats).
```

### 2.6 `stats` payload — additions **[BINDING through v1.6]**

```jsonc
{
  "self_grading": {                      // v1.4 — from audit-kind receipts
    "n": 23, "qwk_vs_assessor": 0.81, "signed_bias": 0.09,   // + = tutor rates above blind grader
    "by_band": {"partial": {"n": 11, "bias": 0.14}},
    "min_n": 20,
    "read": "…bounded by the assessor's own audit chain, never better — see /coach audit"
  },
  "relearning": {                        // v1.5 — derived from relearn rows (§2.3)
    "nodes_with_retries": 7, "criterion_met_rate": 0.86,
    "mean_retries_first_session": 1.9, "mean_retries_latest": 1.2,   // the savings signature
    "min_n": 5
  },
  "sessions": {                          // v1.8 — DESCRIPTIVE ONLY (chronotype stays killed):
    "by_daypart": {"morning": 14, "evening": 9},              //   description, never scheduling
    "ended_early_rate_by_mode": {"standard": 0.42}
  },
  "proposals_pending": 2                 // v1.8 — re-computed, never persisted (inv. 11)
}
```

`retention`/`adherence` gain the `retired` counts (§2.2). All floors follow the house
rule: counts below the floor, rates at or above it, `min_n` published beside every rate.

### 2.7 `due` payload — additions **[BINDING]**

**Amended at build time (v1.3), and both amendments are corrections the code forced:**

1. **`--limit` is NOT a synonym.** It keeps the v1.2.2 *shape* (a bare list) and the old
   order, byte-identically; `--cap` is the new labeled path. Identical semantics would have
   changed the payload shape under any older skill file that had not been updated yet —
   a break the doctrine forbids for a benefit nobody needed.
2. **The savings ranking needs a floor, because the raw metric ranks the hopeless first.**
   Measured: savings/min is an inverted U peaking at R ≈ 0.34 (which reproduces the Lindsey
   `DUE_MINUTES_BY_R` mid-band boundary — a chosen constant, not a derived optimum), but
   reviewing a near-dead concept *resurrects* it,
   so the left tail scores high. Items below `DUE_RELEARN_R` (0.10) are flagged
   `effectively_relearn` and **sort last regardless of score**. docs/14 v1.3-C's prose claimed
   the plain formula did this; it did not.

```jsonc
// due --cap 8            (--limit = legacy: bare list, old order, unchanged)
// order default: uncapped → "overdue" (today's shipped order, named truthfully);
//                capped   → "savings" (peak kept, hopeless tail parked)
{
  "order": "savings",
  "order_basis": "model-derived (FSRS projection); no human RCT ranks backlog orders — docs/13 §2.2",
  "items": [{
    "...": "existing fields unchanged",
    "savings_per_min": 0.041,            // (R_horizon_if_reviewed − R_horizon_no_review) / expected_minutes
    "expected_minutes": 1.4,             // piecewise by R: R≥0.7→0.6 · 0.3≤R<0.7→1.0 · R<0.3→2.0
                                          //   (constants documented here, labeled engineering)
    "schedule_policy": "relearning-dose (policy over FSRS; docs/13 §2.5 — SR × adaptive scheduling is unstudied)"   // ⚠ SHIPPED AS `dose_capped` (a bare bool on the RECEIPT). Invariant 14 wants the label on the due payload; see v1.9.1.
                                          //   present only on nodes whose interval the v1.5 cap shortened
  }]
}
```

Near-zero-savings floor: items with `R < 0.10` are still listed (never dropped) but
flagged `effectively_relearn: true` so the skill can park them honestly instead of
burning the cap.

---

## 3 · Command surface

| Command | New/Changed | Release | Writes? |
|---|---|---|---|
| `due --cap N --order overdue\|savings` | changed (`--limit` aliased) | 1.3 | no |
| `retire --topic T [--node N] [--restore]` | new | 1.3 | yes (lock) |
| `commit` | `renewed` stamping; emits `age_days` | 1.3 | yes (lock) |
| `session-start` | plan line; capped framing | 1.3 | no |
| `receipt` / `rate` | audit-kind persistence; `--relearn`; `--audited-rating` | 1.4/1.5 | yes (lock) |
| `assessor-audit --grader-context S` | context + bands + canary scope + `spec_flip_rate` | 1.4 | yes (audits/) |
| `grader-health --grader-context S` | staleness verdicts | 1.4 | no |
| `gold --canary` | new mode | 1.4 | no |
| `adjudication-stats --file F` | new | 1.4 | no |
| `refit` | tier ladder (0: multiplier ≥50 · 1: S0 ≥64 · 2: full ≥400 + refuse-if-not-better); `basis` labels | 1.6 | yes (lock) |
| `report` | workload-vs-retention section | 1.6 | artifacts/ |
| ~~`doctor --migrate-scheduler`~~ | **not shipped** — see §5.2 | 1.6 | — |
| `add-topic --extend --file F` | merge-only mode; `capstone-<arc>` mint | 1.7 [RE-ANCHOR] | yes (lock) |
| `next --frontier-of NODE` | read-only requires-chain helper | 1.7 [RE-ANCHOR] | no |
| `doctor --fix` | per-item confirmed repairs; `--yes` refused | 1.7 [RE-ANCHOR] | yes (lock) |
| `propose` | new; ≤3 proposals from the validated families | 1.8 [RE-ANCHOR] | **no** (inv. 11) |
| `experiment start --preset P` / metric registry | `EXPERIMENT_METRICS = (first_review_recall, retention_7d, transfer_fired, slip_share)` | 1.9 [RE-ANCHOR] | yes |

Signatures worth pinning now:

```jsonc
// propose  →
{ "proposals": [{
    "id": "p_scaffold_entry_procedure",
    "field": "practice-entry-rung",                 // or settings.default_mode, memory.desired_retention→chart
    "current": "L1", "proposed": "L2",
    "evidence": "9/9 clean L1 entries across 3 weeks (receipts r_…)",
    "grade": "evidence-backed",                      // evidence-backed | model-derived | heuristic
    "floor_met": true }],
  "read": "…" }

// adjudication-stats --file gold/adjudications/rater1.jsonl  →
{ "rater": "rater1", "anchor_gate": {"n": 10, "exact": 0.9, "passed": true},
  "n": 86, "exact": 0.71, "qwk": 0.78,
  "alpha": 0.74, "alpha_ci": [0.63, 0.83],           // ordinal Krippendorff, bootstrap CI
  "confusion": {...}, "direction": {"rater_stricter": 9, "rater_more_lenient": 4},
  "verdict": "tentatively-corroborated" }            // ≥0.80 corroborated · 0.667–0.80 tentative · else contested
```

Metric registry semantics (1.9): each metric names its **population predicate**
(`retention_7d` → `_review_receipts` bucketed by `days_since_encode` 4–14;
`transfer_fired` → `_transfer_receipts`, latest-fire per node; `slip_share` →
`error_class`-classified rows with `n_classified` denominators) — the same shared
predicates stats uses, cross-consistency by construction (§4.8 Q1).

---

## 4 · The populations table, extended (who reads which receipts)

| population | question | reads | v2.0 change |
|---|---|---|---|
| `_review_receipts` | does the memory survive? | retention · recall_by_stability · calibration · modality · adherence · by_kind | **excludes** `relearn` rows and audit-kind rows (inv. 13) |
| `_transfer_receipts` | does the capability fire? | stats.transfer · node.transfer | unchanged |
| `_retrieval_receipts` | how much durability grew? | momentum | excludes `relearn` + audit rows |
| relearn rows (new) | did the session end at criterion, and is relearning getting cheap? | stats.relearning | v1.5 |
| audit-kind rows (new) | does the tutor agree with the blind grader? | stats.self_grading | v1.4 |
| `refit` sample | fit quality | refit tiers | excludes `relearn` rows AND any `elapsed == 0` row (G11) |

One shared `is_retired(node)` predicate gates every node-level population
(due/next/decay/transfer-candidates/adherence funnel/capstone-requires).

---

## 5 · Migration & compatibility mechanics

### 5.1 Self-heal table (every new field, its absence behavior)

| Field | Absent means | Healed to |
|---|---|---|
| `settings.relearning` | pre-1.5 model | `"on"` (caps still bite only dose-stamped nodes) |
| `fsrs.dose` | pre-1.5 node | never capped |
| `node.retired` | active node | `null` semantics (no block) |
| `commitment.renewed` | never renewed | `[]` |
| `settings.audit_offered` | never offered | offer once, then stamp |
| `memory.fsrs_version` | pre-1.6 | `"4.5"` — readers branch on it; unknown value → refuse loudly, never guess |
| `settings.srl` | pre-1.8 | `"on"` |
| `rhythms` | — | v1.8 heal **removes** the key |

### 5.2 The v1.6 scheduler replay — **NOT SHIPPED (superseded by docs/14 v1.6's RESULT)**

> ⚠ v1.6 deliberately did not ship the FSRS-6 migration: fitted 4.5 matches or beats default
> 6/7 on the benchmark, our users run near-defaults, and the 21 weights would need
> primary-source verification before entering a scheduler that governs other people's
> memories. `migrate-scheduler`, `fsrs_version` and `ENGRAM_FSRS` do **not** exist in the
> engine. The procedure below is retained as the design to follow **if** that decision is
> ever revisited — it is not a description of the shipped system.

#### (retained design)

Trigger: explicit (`doctor --migrate-scheduler`, offered once by `/coach`), never
silent. Procedure: for every non-retired node, recompute s/d by replaying its receipts
(first-attempt rows only — relearn rows and `elapsed == 0` rows excluded, which is why
v1.5 must land first) through FSRS-6 defaults in receipt order; set
`fsrs_version: "6"`; reset `interval_multiplier` to 1.0; write one coach-voiced
disclosure. Idempotent (version check). `ENGRAM_FSRS=4.5` forces the old formulas for
one release cycle (env, not state — an escape hatch, not a fork). Golden fixture: a
captured v1.2.2 state whose post-replay s/d/due are asserted against hand-replayed
values; replay-twice = byte-identical.

### 5.3 What v1.2.2 code sees in a v2.0 state

Every addition lives in fields v1.2.2 never enumerates; `_deep_heal` on old code ignores
unknown keys rather than stripping them (verified behavior — reads degrade, never
brick). The one deliberate incompatibility: a v1.2.2 engine reading a `fsrs_version:
"6"` state would compute 4.5 curves over 6-fitted stabilities — acceptable drift for a
downgrade nobody is routed to, and `doctor` names it.

---

## 6 · Order of operations, restated as schema dependencies

```
v1.3  retired block · due order fields · commitment.renewed      (no receipt changes)
v1.4  audit-kind rows · grader_context/bands/canary · adjudications/
v1.5  relearn rows + dose stamp        ← must precede v1.6 (replay excludes them)
v1.6  fsrs_version · fsrs_params · replay                        ← must precede v1.8§3
v1.7  arc · capstone-<arc> · --extend                            [RE-ANCHOR]
v1.8  adaptations.jsonl · propose · srl · rhythms removal        [RE-ANCHOR]
v1.9  metric registry · presets                                  [RE-ANCHOR]
```

The [RE-ANCHOR] rule, stated once: before building v1.7+, re-read this document against
what v1.3–v1.6 actually shipped and what their telemetry said, and amend it **in the
same commit** as the release branch's first commit — the authority stays current or it
stops being one. That is how docs/09 stayed true through five releases, and it is the
iteration contract this document signs.
