# Changelog

## 0.4.0 — 2026-07-09 · the affective layers (motivation + wisdom)

Two new layers around the unchanged engine, for the part the first four pillars
implied but never voiced: *why the learner returns tomorrow*, and *how a wise tutor
carries them through the part where learning is supposed to hurt*. Every load-bearing
claim was assembled by an adversarial research pass (100+ searches, primary sources
fetched, each number verified by a voter told to refute it) and is cited in the new
theory doc. The design rule throughout: **surface what is already true; invent nothing.**

### Theory
- **`docs/05-affective-layers.md`** — the constitution extension. Two new pillars:
  **P13 Competence salience** (making *real* progress visible is a reward without
  gamification's risks — Harkin 2016 d=0.40; Deci/Koestner/Ryan 1999 competence
  feedback d=+0.33 for adults, but d=−0.78 when *controlling*) and **P14 The mentor
  stance** (struggle-as-encoding, absolve-don't-pity, self-generated relevance,
  return-after-absence amnesty — Silverman & Barasch 2023; D'Mello 2014; Graham 1984).
  Includes the adversarial backbone (why *not* to gamify: Sailer & Homner 2020;
  Hanus & Fox 2015; over-helpful AI harms — Bastani 2025) and the ADHD resolution.

### Engine (additive, default-safe — the FSRS core is untouched)
- **`stats.momentum`** — the deterministic core (never the model — Article 10) now
  computes a weekly competence-growth block from real receipts: reviews cleared,
  **days of durability added** (`stability_gained_7d`), genuine recalls, and the
  most-durable memory now. Purely additive to the `stats` JSON; ignored safely if unused.
- **Two self-healed settings keys:** `settings.momentum` (`on`/`off`) and
  `settings.profile` (`null`/`adhd`). A pre-0.4 model missing them is repaired on load
  (as every settings key already is) — behavior is byte-for-byte v0.3 with momentum off.
- Selftests 63 → **68** (durability arithmetic in isolation, in-window filtering, the
  no-negative-growth rule, the momentum block in `stats`, and the settings self-heal).

### Behavior (skills & dialogue grammar — prose, no new commands)
- **Naming real growth** (`/learn`, `/review`): on a genuine stability gain, one flat
  informational line from the engine's own `s_before → s_after` ("holds ~9 days now,
  up from ~2") — never a score, streak, or should-statement; silent when
  `settings.momentum=off` or the gain isn't real.
- **The mentor register** (dialogue grammar): a bounded stance fired only at specific
  moments (difficulty, lapse, return-after-absence, sagging motivation), silence by
  default. Two new lines in the anti-sycophancy oath: *encouragement is information,
  never pressure*; *after a lapse, absolve — never pity*.
- **Return-after-absence amnesty** (`/review`): a large post-gap queue is met with
  amnesty + load renegotiation and a capped catch-up choice — the highest-evidence
  Layer-2 move — instead of dumping the debt.
- **Momentum in the coach** (`/coach`): the check-in opens by *reporting* real progress
  (the intervention itself — Harkin 2016), honestly saying so when nothing grew.
- **ADHD Focus profile** (`settings.profile=adhd`): turns up dials the skills already
  read (Sprint default, immediate growth surfacing, earlier boredom response, optional
  if-then plan, always-on amnesty). No new pedagogy, no game; a declared need, honored.
- README: v0.4 science paragraph, new pillar #5, docs table entry, version → 0.4.0.

## 0.3.0 — 2026-07-06 · bulletproof-foundation hardening + Codex support

A deep hardening pass before new features: every reported bug fixed, plus a full
adversarial sweep of the boundary where LLM/human text enters the deterministic
core. Two independent security audits, two code reviews, and a QA pass fed this;
every fix is locked by a selftest (33 → **63 checks**) and re-verified live.

### Fixes for the reported issues (#1, #2)
- **FSRS-4.5 difficulty anchor corrected.** `next_difficulty` mean-reverted toward `D0(4)` (the FSRS-5 rule) under an otherwise-4.5 engine, inflating interval growth ~21% and silently undershooting the 90% retention target. Now reverts toward `D0(3)`, per the open-spaced-repetition reference. Pinned by a fixed-point selftest. (#1)
- **Evidence before state.** `apply_item` now appends the receipt *before* saving the graph, so a crash (or a bad-type confidence that made `make_receipt` throw) can only ever cost a harmless re-review — never advance mastery with no receipt. (#1)
- **`refit --force` on empty data** no longer divides by zero. (#1)
- **Corrupt state is quarantined, not discarded.** A malformed JSON file is renamed to `<file>.corrupt.<date>` and surfaced by `doctor`, instead of being silently overwritten with defaults. (#1)
- **Calibration scores partial credit correctly.** It now reads the assessor `grade` (recalled=1.0 / partial=0.5 / lapsed=0.0), not the scheduler `rating` — a `hard`/`partial` answer was being scored as a total miss, flipping the verdict to "maximally overconfident". Confidence is clamped to 0–100; a min-n floor (10) replaces definitive verdicts on thin data with `insufficient-data`; encode-time confidences are split into their own pool instead of polluting review calibration. (#2)
- **`next` is stash-aware.** It skips a node whose production is already stashed, and treats a stashed-but-ungraded prerequisite as provisionally met — so the batch-graded `/learn` flow keeps advancing instead of re-serving one node or dead-ending on a chain. Payload now carries `pending_verify` and `provisional_requires`. (#2)
- **`--add-goal`** writes the previously orphan `goals` field; long productions carry a `production_truncated` marker instead of clipping silently. (#2)

### Hardening (found in the sweep)
- **Path-traversal / arbitrary-write closed.** Topic slugs and node ids are validated at every ingress (`add-topic`, `receipt`, `--topic`), and all state writes are confined to the state dir (`report --out` too, unless `--allow-outside`); appends refuse to follow symlinks. An absolute/`..` topic could previously write attacker-controlled JSON anywhere — including a malicious `~/.claude/settings.json`.
- **Shell-injection channel removed.** The skills now pass learner text through a file or stdin (`stash add --file`, `rate --production-file`, `--json -`) and never inline it into a command; a hard rule was added to the dialogue grammar. A production (or a document being taught) containing `'` or `$(…)` can no longer execute.
- **`add-topic` no longer trusts LLM-supplied mastery.** Payload `state`/`fsrs` are ignored (the engine owns scheduling — no mastery without receipts); `--replace` now *preserves* surviving nodes' schedule and writes a `.bak` instead of wiping it; `order` is deduped and requires-cycles are flagged.
- **`model --set` can't brick the install** — it refuses to overwrite an object with a scalar and clamps known numerics (a bad `desired_retention` no longer crashes every `rate`); the learner model self-heals a deleted/mistyped subtree on load.
- **Batch receipts are atomic** — every item is validated (and every node confirmed to exist) before any is applied; the stash self-drains as receipts land.
- **Crash-proofing:** malformed dates, unknown node states, ghost `order` ids, and one corrupt graph no longer brick `topics`/`stats`/`report`/`due`/`session-start`; the session hook only ever echoes validated slugs (closing an indirect prompt-injection vector) and degrades to silence on any failure.
- **Report XSS closed** — every interpolated field (incl. `due`/`lapses`) is escaped.
- **Portability:** dropped the hardcoded personal fallback path; cross-platform dashboard open (`open`/`xdg-open`/`explorer.exe`); scoped the "nothing leaves your machine" claim (the engine never egresses; the curriculum architect uses web search on the topic/goal). `doctor` gained checks for bad states, unparseable dates, and quarantined files.

### Codex support (omni-repo)
- Engram now runs on **OpenAI Codex** from the same repo — `skills/` and `scripts/engram.py` are shared verbatim. Added `.codex-plugin/plugin.json`, `.agents/plugins/marketplace.json`, TOML ports of the three subagents (`codex/agents/*.toml`), a self-resolving SessionStart hook, `scripts/install-codex.sh`, and `INSTALL-CODEX.md`. The Claude Code path is unchanged.

### Known limitation
- Re-running the exact same `receipt --file` twice still double-applies (the settle flow clears the stash after, so the documented path is safe; batch *atomicity* is fixed). Full cross-invocation idempotence is deferred — it needs a stash-id threaded through the assessor contract.

## 0.2.0 — 2026-07-05 · release-hardening after first live dogfood

Every change below traces to something observed in a real `/learn` session.

### Integrity
- **Confidence is never invented.** The dialogue grammar and assessor now hard-require: ask in the same breath as the probe, one casual retry, then record `null`. Calibration counts only numbers the learner actually said. (Found: the tutor had estimated confidences during the first session, silently poisoning calibration.)
- **Pending-verification stash** (`engram.py stash add|list|count|clear`): learner productions are persisted to disk the moment they exist. A crashed or compacted session can no longer lose ungraded work; the session-start hook surfaces leftover items. (Found: the tutor was hand-maintaining scratch files.)

### New capabilities
- **`engram.py report`** — deterministic, self-contained HTML dashboard (per-topic mastery maps with progress bars, retention-by-strength vs. the 85% band, honest calibration, open misconceptions, next-7-days forecast; light+dark, no network, no JS). `/coach dashboard` now uses it.
- **`engram.py refit`** — coarse per-user schedule fit (v1): compares predicted vs. observed recall over ≥50 review receipts and rescales intervals via a clamped multiplier along the FSRS forgetting curve. Guarded and honest about thin data; full FSRS parameter optimization remains future work.
- **`engram.py doctor`** — state/environment diagnostics for troubleshooting installs.

### Bug fixes
- `model --add-interest` dropped all but the last value when passed multiple times in one call (argparse `append` missing). Now keeps every value.
- Streak computation returned 0 when yesterday had activity but today didn't (broken grace-day loop). Rewritten and tested.
- Receipt ids could collide within a fast batch (millisecond timestamps). Now suffixed with a monotonic sequence.

### UX
- `topic-status` renders a progress bar and plain-language legend ("retained / learning / untouched").
- Session ticket and receipt-strip display formats standardized in the dialogue grammar; per-item progress markers in `/review` (`[3/6]`).
- Park-and-resume protocol: mid-session subject changes are parked cleanly; re-anchoring is always from disk.
- Pretest capped at 3 probes (a diagnostic, not an exam); unanswered probes stay untouched without nagging.
- Session-start nudge now also surfaces ungraded pending work.

### Packaging
- MIT LICENSE (swap if you prefer another).
- `ENGRAM_ROOT` env var respected as a dev-clone fallback path in all skills.
- Selftest grown from 18 → 33 checks (stash, refit direction+guard+persistence, report self-containment, doctor, streak cases, id uniqueness, interest append, interval multiplier).

## 0.1.0 — 2026-07-05

Initial build: FSRS-4.5 deterministic core (`engram.py`, 18-check selftest), three skills (/learn, /review, /coach), three agents (curriculum-architect, assessor, artifact-smith), SessionStart hook, theory docs (foundations, prior art, architecture, roadmap), Explorable Contract.
