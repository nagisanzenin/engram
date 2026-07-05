# 03 · Architecture: The Plugin Design

Design DNA inherited from `claude-code-production-grade-plugin`, transposed from software verification to learning verification:

| Parent pattern | Engram transposition |
|---|---|
| **Oracle-driven loops** — run executable checks, never trust agent claims | **Retrieval oracles** — mastery is only ever established by graded free recall / application / transfer under test conditions; never by the learner's (or tutor's) claim that it "makes sense" |
| **Receipt enforcement** — JSON proof of work gates every phase | **Mastery receipts** — every assessment writes `(item, production, confidence, grade, misconceptions)`; state transitions require receipts |
| **Re-anchoring** — re-read specs from disk at phase transitions | **Session re-anchoring** — SessionStart hook loads learner model + due queue from disk; the tutor never trusts its conversational memory of the learner |
| **Modes** (Express → Meticulous) | **Session modes** (Sprint 5-min / Standard 25-min / Deep 60-min) |
| Zero open-ended questions, arrow-key navigation | **Menus for navigation, never for knowledge** — logistics are arrow-key; retrieval is always open-ended production (the exact inverse of the parent, deliberately, where it matters) |

---

## 1. Layout

```
engram/
├── .claude-plugin/plugin.json          # + marketplace.json for distribution
├── skills/
│   ├── learn/SKILL.md                  # /learn — acquire (diagnose→derive→verify→schedule)
│   ├── review/SKILL.md                 # /review — due retrievals, 2-min friction-free
│   ├── coach/SKILL.md                  # /coach — dashboard, strategy, experiments, schedule
│   └── _shared/                        # dialogue grammar, rubrics, FSRS reference, contract
├── agents/
│   ├── engram-curriculum-architect.md  # topic → first-principles DAG (typed edges)
│   ├── engram-assessor.md              # independent grader; rubric-bound; emits receipts
│   └── engram-artifact-smith.md        # explorables under the Explorable Contract
├── hooks/
│   ├── hooks.json
│   └── session-start.sh                # re-anchor: due-count nudge; silent when nothing due
└── scripts/
    └── engram.py                       # THE deterministic core: FSRS-4.5 + state + receipts
                                        #   + stats + selftest, one stdlib-only CLI
```

**Implementation refinements vs. the original sketch** (decided during Phase 1 build): the **tutor is the main conversation itself**, governed by `_shared/dialogue-grammar.md`, not a subagent — the tutoring relationship must persist in-context, and only *grading* needs fresh-context isolation (the assessor). The **coach** likewise runs as the `/coach` skill in the main loop and generates the HTML dashboard directly from `stats --json` (no separate `report.py`). Receipts are written at the moment of grading by `engram.py`, so no `session-end.sh` flush is needed — one SessionStart hook is the entire ambient surface. The explorable widget vocabulary lives in `_shared/explorable-contract.md` rather than a `templates/` directory until real usage shows which templates earn extraction.

**v0.2 additions** (hardening after the first live dogfood): `stash` (crash-safe pending-verification queue — learner productions persist to disk the moment they exist), `report` (deterministic self-contained HTML dashboard), `refit` (guarded coarse per-user interval fit), `doctor` (state diagnostics), and two integrity rules promoted to law in the dialogue grammar: confidence is never invented (null over estimate), and the assessor grades only the learner's actual words.

**Why scripts, not prose:** FSRS math, state validation, and schema migration are deterministic — they run as code (oracle-grade), never as LLM arithmetic. The parent repo's lesson: everything checkable must be checked by something executable.

## 2. State (the learner file system)

Global, project-independent, human-readable, schema-versioned: `~/.claude/learning/` (coexists with the ecosystem convention).

```
~/.claude/learning/
├── learner-model.json        # THE OPEN LEARNER MODEL (user-readable by design)
├── graphs/<topic>.json       # concept DAGs with per-node mastery + FSRS state
├── receipts/<topic>.jsonl    # append-only assessment evidence
├── misconceptions.json       # personal error catalog, tagged to nodes
├── sessions.jsonl            # telemetry: mode, duration, outcomes
├── experiments.json          # n-of-1 strategy trials (design, status, verdict)
└── artifacts/<topic>/<node>.html
```

**learner-model.json** (abridged):
```json
{
  "schema": 1,
  "memory": { "fsrs_params": [/* ~20 floats, refit monthly from receipts */] },
  "calibration": { "brier": 0.19, "bias": "+overconfident", "history": [] },
  "challenge_band": { "target_success": 0.85, "hint_tolerance": 2 },
  "interests": ["distributed systems", "woodworking", "Vietnamese history"],
  "goals": [{ "topic": "kalman-filters", "why": "drone project", "by": "2026-09" }],
  "strategy_weights": { "derivation_first": 0.7, "example_first": 0.3 },
  "rhythms": { "best_slot": "morning", "median_session_min": 22 },
  "accessibility": []
}
```

**Graph node** (abridged):
```json
{
  "id": "bayes-theorem",
  "claim": "P(A|B) = P(B|A)P(A)/P(B)",
  "why_chain": ["conditional-probability-def", "product-rule"],
  "edges": { "requires": ["conditional-probability-def"], "contrasts_with": ["frequency-fallacy"], "analogous_to": ["code-review-priors"] },
  "arbitrary": false,
  "threshold_concept": false,
  "state": "review",
  "fsrs": { "stability": 14.2, "difficulty": 4.1, "due": "2026-07-11" },
  "artifact": "artifacts/probability/bayes-theorem.html",
  "receipts": ["r_0142", "r_0177"]
}
```

`arbitrary: true` routes a node to mnemonic+SRS treatment (no derivation theater for irregular verbs). `threshold_concept: true` triggers explorable-by-default and extra relearning cycles.

## 3. The five loops

**LEARN** (skill: `/learn <topic|continue>`):
1. *Frontier diagnosis* — curriculum-architect builds/loads the DAG; a short pretest walks the frontier (knowledge-space style; also the curiosity trigger — pretesting effect). Never quizzes the whole graph.
2. *Encode one node* — tutor runs the dialogue grammar: **predict → attempt → hint ladder (struggle budget) → resolve → self-explain → connect** (name the why-chain edges out loud). Scaffolding level set by the node's expertise estimate (worked example ↔ cold problem).
3. *Artifact* — for threshold/visualizable nodes, artifact-smith generates an explorable (Contract, §6); the learner *uses* it (gated interactions), doesn't watch it.
4. *Immediate verify* — assessor grades a free-recall production + one application item; confidence collected before feedback; receipt written; FSRS initialized.
5. *Close the loop* — one-line preview that opens the next question (curiosity gap), session logged.

**REVIEW** (skill: `/review`, ≤ session mode budget): due nodes, free recall first, grade → hypercorrection protocol on high-confidence errors (they get the spotlight and a re-derivation, not just the answer) → FSRS update → interleaved ordering across topics by default. Two-minute minimum viable session protects the habit.

**BUILD** (inside `/learn`, per topic arc): the capstone transfer project in the learner's real environment — code in their actual repo (with `TODO(human)` on load-bearing parts), a taught lesson, an explorable the learner authors. Assessor evaluates the artifact against the topic's nodes; receipts mark `transfer: true`.

**COACH** (skill: `/coach`, and weekly cron): reads telemetry, refits FSRS monthly, updates calibration, runs/settles n-of-1 experiments, regenerates the HTML dashboard (mastery map, retention curves, calibration plot, streak), and *explains its adaptations in plain language with the learner's own data as evidence*.

**AMBIENT** (hooks): SessionStart re-anchors + one-line nudge ("7 items due, ~4 min — `/review` when ready"); SessionEnd flushes receipts. Optional opportunistic mode (off by default, the `learning-opportunities` pattern): when real work touches a tracked node, offer a 30-second retrieval — rate-limited to ≤1/session, silent after any decline that session.

## 4. Agent separation of powers

The parent plugin separates `software-engineer` from `code-reviewer` because self-assessment is corrupt. Engram's version is stricter, because the failure mode is subtler — sycophancy dressed as encouragement:

- **tutor** teaches but never grades; it cannot write receipts or advance node state.
- **assessor** grades against `_shared/rubrics/` from a fresh context: it sees the item, the rubric, and the learner's production — *not* the tutoring dialogue, so the tutor's enthusiasm can't leak into the grade. Verdicts: `recalled | partial | lapsed`, misconception tags, rubric citations. It is prompted to be a skeptic ("find what's missing before what's present") and calibrated by spot-audit ("would an exam grader accept this?").
- **coach** adapts but only from receipts and telemetry, never from vibes; every adaptation it makes is written to the open learner model with its evidence.
- **curriculum-architect** and **artifact-smith** create but cannot assess.

The learner can always appeal a grade — the appeal and its resolution are themselves receipts (and calibration data).

## 5. Adaptation policy (signal → response)

| Signal (from receipts/telemetry) | Interpretation | Response |
|---|---|---|
| Success > 92% sustained, low latency | Under-challenged (fluency risk) | Raise difficulty; longer intervals; more transfer probes; offer acceleration |
| Success < 70% on a node's items | Overloaded or prerequisite gap | Drop scaffold level (worked examples); audit `requires` edges with micro-diagnostics |
| Wrong + high confidence | Misconception (gold) | Hypercorrection protocol: spotlight, contrast case, re-derivation; log to misconceptions.json; schedule early re-test |
| Right + low confidence, repeatedly | Underconfidence / calibration bias | Show the learner their own accuracy data; reduce hint dependence gradually |
| Repeated lapses on one node | Wrong encoding, not weak memory | Re-encode differently (new analogy, explorable, contrast pair) — never just re-show the same card |
| Short answers, mode-switching, session abandonment | Boredom / motivation dip | Switch activity type (build > review), reconnect to stated goal, shrink session |
| Hint ladder exhausted often | Struggle budget miscalibrated | Adjust budget; check expertise-reversal direction |
| ≥2 topics in practice state | — | Interleave reviews by default |
| Strategy question ("does derivation-first beat example-first for this learner in this domain?") | n-of-1 experiment | Alternate strategies across comparable new nodes for 2–3 weeks; compare 7-day retention receipts; settle, record verdict, update `strategy_weights` — and tell the learner |

## 6. The Explorable Contract (artifact-smith's binding spec)

Every generated HTML artifact MUST: (1) open with a committed prediction/question — content stays gated until the learner commits; (2) contain ≥1 manipulable model (slider/drag/toggle) whose behavior the learner predicts before first touch; (3) embed ≥2 retrieval prompts inline (mnemonic-medium style) that feed real FSRS state via export/paste-back or session capture; (4) obey Mayer: zero decoration, signaled structure, learner-paced segments, labels on the thing; (5) be fully self-contained offline HTML (no CDNs); (6) end with a blank-page reconstruction prompt ("close this; rebuild the argument skeleton"); (7) carry its node id + version so it regenerates when the learner's model or mastery changes.

`templates/` seeds the widget library: parameter-slider sim, predict-then-reveal plot, drag-to-order causal chain, contrast-pair toggle (variation theory), DAG mastery map, calibration scatter. The library grows; the Contract doesn't bend.

## 7. Convenience doctrine (the "extremely convenient" requirement, made testable)

- **Three verbs total.** `/learn`, `/review`, `/coach`. No sub-command taxonomy to memorize; natural language inside each.
- **Zero-config onboarding.** First `/learn X` *is* the diagnostic; the learner model bootstraps from behavior, not a questionnaire (questionnaires would measure preference folklore anyway).
- **Ambient by hooks, never nagging.** One line at session start; silence after any decline.
- **Two-minute floor.** A review session that fits between compiles; the habit survives busy weeks (consistency dominates — see foundations P10).
- **Everything is a file the learner can read.** Trust through transparency (open learner model).
- **The system teaches itself.** Onboarding is a first lesson *on learning science, using the system* — pretest, explorable, retrieval, schedule — so the learner experiences the method before adopting it.
