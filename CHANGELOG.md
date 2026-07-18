# Changelog

## 1.0.7 — 2026-07-19 · a flattering number, caught by the gate built for it

One engine fix, shipped hours after v1.0.6 because RELEASE_PROTOCOL §7.5 says a wrong
number does not get to stand. The independent post-release reviewer — standing
instruction: *"find a number that is wrong, especially one that is wrong in the
direction that reassures the learner"* — found exactly one, and it is bug class #1:

- **`momentum.recalled_7d` counted encode and pretest receipts as retrieval wins.** The
  docstring's contract is *"retrievals cleared, and genuine wins among them"* — wins ⊆
  retrievals — but the counter took ANY in-window receipt with `grade: "recalled"`.
  Encodes and pretests carry that grade in normal use, so a learner who encoded three
  concepts and never came back once read `recalled_7d: 3` beside `reviews_7d: 0` —
  three "genuine wins" with zero retrievals. One-line fix: the counter now shares the
  same genuine-retrieval predicate as `reviews_7d`.
- **And the embarrassing part, per protocol: the guarding selftest was theatre.** The
  v1.0.6 check asserting `recalled_7d == 1` could not fail — its encode fixtures were
  both out-of-window AND gradeless, so the inflating population never reached the
  counter under test. The fixture now carries an in-window `grade: "recalled"` encode
  AND pretest; the check fails by name when the fix is reverted (mutation-tested).
  That is the fourth §4.5 lesson in four releases: *a check that cannot see the
  inflating population proves nothing about inflation.*
- Blast radius, honestly: the prescribed `/coach` narration leads with
  `stability_gained_7d` / `reviews_7d` / `most_durable` (all correct) and never quotes
  `recalled_7d`; exposure was a narrator improvising off the JSON — which the docstring
  invited, by calling the field retrieval wins.
- Noted, unchanged: `retained_total`/`state_counts` label a node "retained" on FSRS
  graduation (before any retention test). That matches its docstring and the system-wide
  state convention, and the retention *metric* correctly excludes first exposures — a
  labeling convention to revisit, not a wrong number.
- Selftest count unchanged at **217/217** (an inert check was made real, none added).
  Re-fuzz after the fix: 0 crashes / 800 states.

## 1.0.6 — 2026-07-18 · Antigravity — the fifth platform

Engram now installs natively on **Google Antigravity** (`agy` CLI) — contributed by
@mertso13 in #8, two review rounds, every claim below verified live against agy 1.1.4
with a sandboxed `$HOME`.

- **One command:** `agy plugin install https://github.com/nagisanzenin/engram`. Root
  `plugin.json` is schema-minimal on purpose — the official
  `antigravity.google/schemas/v1/plugin.json` allows exactly `name` + `description`
  (`additionalProperties: false`); everything else is directory-crawled. The manifest is
  inert on the other four platforms (Claude Code reads `.claude-plugin/`, Codex
  `.codex-plugin/`, OpenCode npm/`.opencode/`, Hermes `skills.external_dirs`).
- **The bug that made it possible was ours, not theirs.** `agy plugin install` stats every
  file it copies — and died on `.opencode/skills/{learn,coach,review}/SKILL.md`, whose
  symlinks have been **self-referential loops since f3ccc76** (`../../` where three levels
  were needed: from `.opencode/skills/<n>/`, `../../skills/<n>/SKILL.md` resolves to
  *itself*). Nobody noticed for four releases because npm packs exclude symlinks and
  OpenCode's loader never stats them. Retargeted to `../../../`; git-clone OpenCode
  installs get real links out of it too.
- **Engine resolution gains the AG default** — the skills' chain is now
  `OPENCODE_PLUGIN_ROOT → CLAUDE_PLUGIN_ROOT → CODEX_PLUGIN_ROOT → ENGRAM_ROOT →
  ~/.gemini/config/plugins/engram` (agy sets no plugin-root variable at all; the staging
  path is deterministic, so it rides last as the default).
- **And the embarrassing part, per protocol — this time the reviewer's.** The first
  review round's fix sketch *replaced* `$ENGRAM_ROOT` with the AG path while its prose
  said "before `$ENGRAM_ROOT`". The contributor implemented the sketch faithfully — which
  would have **broken Hermes**, the platform shipped one release ago, whose entire engine
  resolution runs through `ENGRAM_ROOT` (INSTALL-HERMES.md sets no plugin-root var). Caught
  in the second round by evaluating the installed chain side-by-side under
  `ENGRAM_ROOT=/fake/dev/clone`: new chain ignored it, old chain honored it. The lesson is
  §4.6's, inverted: *a reviewer's sketch is a diff too, and it gets the same scrutiny.*
- **Known limits, stated in the README footnote:** agy 1.1.4 **silently drops any agent
  whose frontmatter carries a `tools:` field** (any value — Claude names and snake_case
  both tested), so `engram-curriculum-architect` and `engram-artifact-smith` don't register
  on AG; only `engram-assessor` does. `agy plugin validate` still reports "3 agents
  processed" — *validate ≠ install ≠ register*. The due-review session nudge isn't ported
  (AG hooks use a different mechanism). Stripping `tools:` was rejected deliberately: it
  would grant those agents all tools on Claude Code, trading a real restriction for a
  cosmetic registration.
- **Engine: three shipped read-path bricks, found by this release's own fuzz gate** (§4.7:
  800 randomized garbage states × 24 read paths — the 24 include every read-only
  sub-action, per the amendment). All three predate this release; all three are the same
  lesson again:
  - `artifact list` crashed on an unhashable entry in `order` — because it hand-rolled the
    walk instead of using `graph_order`, the helper whose docstring *names this exact
    crash*. The checklist line "grep for the N+1th call site (`cmd_artifact` was the one
    missed)" was written about this command in v1.0.1. It was still the one missed.
  - `misconception list` crashed on a `None` entry (`it.get`) — reads now degrade past
    non-dict entries; mutators still refuse an unusable file outright (a lossy "repair"
    a mutator then saved would be data loss wearing a hard hat).
  - `report` crashed rendering an int-typed misconception field (`escape(123)`) — the
    dashboard, the one surface a human actually looks at, bricked by a hand-edited file.
    Fixed at the gate: `_open_misconceptions` now coerces narrator-facing fields to text.
  - Each fix carries a selftest check that asserts the *behavior* (the real entry survives
    the garbage beside it), and each check was mutation-tested: revert the fix, that
    specific check goes red. Selftest **214 → 217**. Re-fuzz after the fixes: **0 crashes**.

## 1.0.5 — 2026-07-18 · Hermes — the fourth platform, and the README stops being misread

Engram now runs on **Nous Research's Hermes Agent** (requested in #9), and the README
finally says out loud what too many people had to ask: this is a **learning system for
the human, not an agent-memory plugin**.

- **Hermes support, verified live** — not speculated. Every claim in
  [INSTALL-HERMES.md](INSTALL-HERMES.md) was exercised against a real Hermes v0.18.2
  install: external-dir discovery of all three skills (`_shared/` correctly ignored),
  `/review` and `/coach` slash registration, full SKILL.md injection on invocation
  (11.5 KB `/review`, 17.9 KB via a `/study` bundle), and the ambient nudge landing in
  the composed user message at the wire level (request dump inspected).
- **The install route is clone + `skills.external_dirs`, deliberately.** Hermes' hub
  installer copies only files referenced inside each skill folder, which would sever the
  skills from the shared `scripts/engram.py` engine. The doc says so and says why.
- **The `/learn` collision, handled honestly.** `/learn` is Hermes' own built-in
  (it authors new agent skills). Hermes detects the clash and skips auto-registering
  engram's `learn`, printing the escape hatch we document: `/skill learn` — or the
  optional one-line `/study` bundle. The new Hermes nudge rewrites its own
  "/learn to continue" line accordingly.
- **New `hooks/session-start-hermes.sh`** — a `pre_llm_call` port of the SessionStart
  re-anchor: same self-resolution, same degrade-to-silence contract, plus once-per-session
  dedupe keyed on Hermes' `session_id`. The engine is untouched (state still shared across
  every platform via `~/.claude/learning`).
- **README rework.** Leads with the disambiguation (agent memory vs. human learning —
  the most common misread), then a five-platform matrix: Claude Code (born here), Codex,
  OpenCode, Hermes, Antigravity (in review, #8). New first FAQ entry for the same
  confusion. `INSTALL-CODEX.md` omni-repo line updated.
- **Known limits, stated in the doc:** headless `hermes chat -q` does not expand
  slash-skills (interactive CLI/TUI/gateway only); the delegate_task assessor flow and
  gateway/cron delivery are recipe-documented but not yet driven end-to-end with a
  capable model. Engine selftest unchanged at 214/214; no engine code changed
  (`ENGRAM_VERSION` pin only).
- **And the embarrassing part, per protocol.** The pre-release review (28 agents,
  10 confirmed findings) caught the brand-new hook **failing open two independent
  ways** — an empty `session_id` bypassed the once-per-session guard entirely, and a
  misplaced `2>/dev/null` meant an unwritable TMPDIR both leaked bash errors to stderr
  and re-nudged on *every* LLM call. The hook whose one-line contract is "ambient,
  never nagging" shipped to review as a per-call nagger under exactly two failure
  modes its author had tested around. Both fixed (dedupe now fails *closed* to a
  per-process key; unwritable marker → silence), plus a 9-case failure battery
  including both reviewer repros. The same review caught the install doc omitting the
  `ENGRAM_ROOT` export the skills' engine resolution depends on, the cron recipe
  delivering the un-rewritten `/learn` it warns about two sections earlier (the hook
  is now dual-mode: JSON for `pre_llm_call`, plain rewritten text on empty stdin for
  cron), a missed `package-lock.json` bump, and five README cross-consistency slips
  (the nudge exists on OpenCode too; "five platforms" counted one still in review;
  the Codex install cell was missing its second command; the OpenCode global-path and
  pin-to-source details had been dropped; the `/learn` onboarding example sat unscoped
  under a matrix that includes Hermes).

## 1.0.4 — 2026-07-17 · updates that only speak when something changed

The OpenCode update flow gets honest and inspectable, and its last shell command is gone.

- **Content-aware diff.** `diffCategory` now compares files byte-for-byte
  (`Buffer.equals`) instead of by existence. Identical files are silently ignored, new
  files ride the `copyMissing` extract, and only genuinely modified files reach the
  `skipped` list — so a metadata-only version bump produces no manifest, no
  pseudo-command, no notification. Unreadable files fail safe into `skipped`.
- **Unified diff viewer.** A version bump with real changes now also writes
  `.engram-update.diff` (standard `---/+++/@@` format), and `/engram-update` grows a
  "View changes" option — the model reads the diff and summarizes what changed before
  the user decides. Cleaned up alongside the manifest in every resolution mode.
- **Zero Bash in the update template.** A new `cleanup` mode on the `engram_update`
  tool replaces the template's last `rm -f`, and an `isWithinTarget` path-traversal
  guard validates every resolved path in `auto` and `per_file` modes — defense in
  depth against tampered manifests. Uses `path.sep`, so the guard holds on Windows.
- **Verification.** Vitest 51 → 88 (new `diffLines` suite incl. an insertion
  trailing-context regression test, tampered-manifest traversal tests, cleanup-mode
  tests). Engine selftest unchanged at 214/214.

Contributed by @luanweslley77 (#6), one review round.

## 1.0.3 — 2026-07-16 · OpenCode — the third platform

Engram now runs on **OpenCode**, alongside Claude Code and Codex. Same skills, same
`engram.py` engine, same receipts — the port is a thin TypeScript adapter that satisfies
OpenCode's plugin contract and shells out to the unchanged Python core.

- **Self-extract bridge.** OpenCode loads plugins from its npm cache, which is not a
  config directory, so native discovery never sees the plugin's skills/agents. On first
  run the `config` hook extracts `skills/ agents/ scripts/` into the OpenCode config dir
  (`~/.config/opencode/` or the project's `.opencode/`) behind a `copyMissing` guard that
  never overwrites a user's edits; a first-session `cfg.*` bridge registers everything
  immediately, and disk discovery takes over thereafter.
- **Deterministic update tool.** `/engram-update` appears on a version bump and applies
  refreshes through the `engram_update` custom tool — deletes go through `unlinkSync` with
  every path validated against the manifest allowlist. No bash, no interpolation.
- **Hooks.** `shell.env` exports `OPENCODE_PLUGIN_ROOT`; `experimental.chat.system.transform`
  carries the review-due nudge; a `session.idle` toast announces available updates.
- **Verification.** New vitest suite (67 tests) covering extract, the manifest state machine,
  and the update tool's path validation; `.github/workflows/test.yml` runs vitest +
  `tsc --noEmit` + `engram.py selftest` on every push. Engine selftest unchanged at 214/214.

Contributed by @luanweslley77 (#5), hardened across four review rounds.

## 1.0.2 — 2026-07-11 · a regression my own fix caused

The v1.0.1 verification review confirmed both headline fixes hold (the export leak is closed; the
power floor is unbuyable) — and found that **v1.0.1's finding-#4 fix introduced a new crash.**

Switching `compute_modality` to the shared `_outcome` predicate was correct — but `_outcome`
returns `None` on a hand-edited un-scoreable receipt, and `0.0 += None` is a `TypeError` that
bricked `stats`, and therefore `/coach`. **The same release fixed this exact bug class in `settle`
(finding #5) and did not carry the guard one function over.** The test gap mirrored the code gap:
there was a settle-degradation check and no modality one, so 213/213 stayed green over a live brick.

- **Fixed:** modality drops the un-scoreable datum, like every other read path. Reads degrade, they
  never brick.
- **The fuzz fixture now includes an un-scoreable FIRST review**, so this class cannot hide again —
  the gate missed it because no fixture gave a node a `None`-outcome first review, which is the only
  shape that reaches modality's per-node first-review logic.

Selftest **213 → 214.**

## 1.0.1 — 2026-07-11 · TWO post-release reviews, and the leak the whole project exists to prevent

Two independent reviewers read shipped code — v1.0.0 (the Commons) and the still-in-`main` v0.9.0
(the Method). Between them, **one critical leak and one severe measurement bug**, plus five more.
Selftest **207 → 213.**

### ⚠⚠ CRITICAL — `export` leaked free text verbatim. The v1.0 headline was false.

`arm` and `stratum` were **strings on the whitelist** — and a whitelist that admits a free-text
field is a hole in the whitelist. `stratify_by: ["claim"]` routed **every node's `claim` text,
verbatim**, into the export's `stratum` field — while the file's own `stripped` list swore `claim`
was removed. The learner-authored `arm` label leaked on **every** experiment. A hand-forged
`grader` string left uncapped.

```
LEAKED into the "attributed, text-stripped" export:
  CLAIM-CANARY: 4   ARCHITECT-SECRET-CANARY: 4   ARM-CANARY-LEAK: 1   stigmatized: 4
```

**Fixed:** `arm`, `stratum`, and `grader` now leave as **hashes** (`arm_hash`, `stratum_hash`,
`grader_hash`). The only strings that leave un-hashed are `kind`/`grade`/`rating` — **closed
enums the engine validates**, not text a human wrote. *A whitelist that admits a free-text field
strips nothing.*

**And the reviewer named exactly why the gate missed it:** the leak-test **never started an
experiment**, so `arm`/`stratum` were always `None` in the fixture. **It asserted the whitelist
keys were clean by never populating them.** The test now stuffs the canary into *every* authored
surface — the experiment arm, a stratum pointed at a node's `claim`, an arbitrary architect
field — which is the exact path the reviewer used.

### ⚠ SEVERE — the power floor could be bought down with one payload field

`experiment settle` gated `powered` on the *design's own* `min_per_arm`. A trial declaring
`min_per_arm: 6` — the underpowered v0.8 default this release exists to **kill** — certified as
`powered: true` and read *"suggestive"* on six data points per arm. **And the shipped skill
promised the opposite:** *"the settle will read underpowered, and it will be right."* It did not.

**Fixed:** `powered` gates on `max(design, EXPERIMENT_MIN_PER_ARM)`. A design may set a *higher*
bar; it can never buy the engine's floor down. *A power gate you can lower with a payload field is
not a power gate.*

### And five more, all in shipped code

- **Optional stopping.** `settle` had no status guard — re-settling as data arrived kept only the
  last verdict and **roughly tripled the false-positive rate (0.04 → 0.117)**. Peek-and-re-settle
  until the coin lands is the exact fallacy pre-registration forbids. Now: **an experiment is
  analysed once.** `start` already refused a second active experiment; `settle` now refuses a
  second analysis of the same one.
- **A broken bootstrap CI.** It percentile-bootstrapped `max(mean) − min(mean)`, a non-negative
  extreme-order statistic — so for 3+ arms the *"95% CI" excluded its own point estimate* (three
  identical arms, spread 0.000, CI [0.033, 0.367]). It manufactured a strategy separation that was
  not there. Now: a **signed two-arm difference** CI (which has no such floor), and **None for
  k > 2** with the read saying so. *Refusing to draw a bad CI is more honest than drawing one.*
- **`first_review_recall` meant two different numbers.** `stats.modality` scored a `partial` as a
  full **1.0**; the experiment engine, on the identically-named metric, scored it **0.5**. Same
  name, same engine, same data, two answers — and modality's was the lenient one. Both now use
  `_outcome`, the shared predicate. (§4.8 Q1: the engine's commands must agree.)
- **`settle` bricked** (not degraded) on a hand-edited receipt whose `rating` was a truthy
  non-rating with no grade — `sum([1.0, None])` → `TypeError`, and `status` had greenlit the settle
  first. Now it drops the un-scoreable data point, like every other read path.
- **The no-network guarantee, made honest about its limit.** The AST scan is a strong regression
  guard, not an impossibility proof (`__import__`, `importlib`, `ctypes`, `exec` would pass it). So
  the engine also contains **none of those dynamic-import primitives**, checked by a new selftest —
  the two checks together support "no network code AND no way to smuggle one in dynamically," which
  a single import-scan cannot claim alone.
- `grader_qwk` on each receipt now ships with a `qwk_note` stating plainly that it is the grader's
  validity **at export time**, stamped on every receipt regardless of when it was graded — the best
  available estimate, not a per-receipt measurement.

**Everything the two reviewers checked and found clean is on the record:** the randomization-test
p-value (valid under unequal n, false-positive rate at/below nominal), block randomization (stable,
balanced, reproducible), the modality floor move, and **every v0.8.1 fix still holds after the
merge.**

## 1.0.0 — 2026-07-11 · THE COMMONS — the first learning system that is also an experiment the whole field can read

The evidence base of learning science is built on **undergraduates, word pairs, and 20-minute
retention intervals.** Almost nothing tests *self-directed adults*, on *hard conceptual material*,
at *30–90 day horizons*, with *blind-graded free recall*.

That is not a gap anyone chose. It is a gap because, until roughly 2026, **grading free recall at
scale was impossible.** You needed a human to read every answer.

Engram produces exactly that data as a byproduct of being useful — and, since v0.7, with a
**measured** oracle behind every grade. The open question is sitting right there: an AI tutor built
on this exact dialogue grammar produced **~2× the learning gains of an active-learning classroom**
([Kestin et al., Harvard, *Scientific Reports*, 2025](https://www.nature.com/articles/s41598-025-97652-6))
— measured on an **immediate post-test.** **Nobody has ever measured whether AI-tutoring gains
survive to thirty days.**

Selftest **201 → 207**.

### `export` — a file, not a request

```bash
python3 scripts/engram.py export --contributor "@you"
```

| leaves | never leaves |
|---|---|
| grades, ratings, confidence | **your productions** — every word you wrote |
| timings, stability, intervals, retrievability | **probes, claims, rubrics** |
| `kind`, `artifact`, `arm`, `stratum` | **goals, interests, misconception text** |
| `grader` and its **measured QWK** | **topic names and node ids** — hashed, not carried |

- **The payload is a WHITELIST.** Every field is constructed by name. **There is no code path by
  which a production could arrive** — not *"we remembered to delete it."* A blacklist is a promise
  you must keep every release; a whitelist is one you keep by construction. (Same lesson `gold`
  taught in v0.7, and the reason both are built the same way.) A **property-based selftest** puts a
  canary string in *every* field the schema has — **and some it doesn't** — and asserts not one
  character survives.
- **The `stripped` list ships INSIDE the file**, so the promise is verifiable by the person making
  it rather than merely asserted at them.
- **The hash caveat, stated out loud:** a hash of a *common* topic name (`transformers`) is
  recoverable by dictionary attack in seconds. It hides the topic from a casual reader, **not from
  someone who wants it** — and the export is attributed anyway. `export --topic T` exists so you can
  choose. *An honest caveat beats a fake guarantee.*

### v0.7 GATES v1.0 — and it is a refusal, not a warning

`export` **refuses** if your assessor has not passed its audit:

```
REFUSING TO EXPORT: the grader behind every one of these grades is unaudited.
A finding aggregated from unaudited oracles is not a finding — it is noise with a schema,
and publishing it would put a number into the world that nobody can stand behind.
```

Every shared receipt carries its grader's **measured QWK**, and the bundle carries the gold set's
own **circularity limit** (`gold_adjudication: "authored"`). A number you cannot stand behind should
not enter the world with your name on it.

### THE ENGINE HAS NO NETWORK CODE — and that is now structural, permanent, and mutation-tested

Not *"no network by default."* **None.**

```
⚠ THE ENGINE HAS NO NETWORK CODE — structural, permanent, and never to be deleted
⚠ …and it never SHELLS OUT (no subprocess, no os.system/popen/exec/spawn)
```

- The check **parses the engine's own AST** — it does not grep. **The first draft grepped its own
  source for the word `curl` and found it, in its own comment and inside its own regex literal. It
  failed on itself.** The AST cannot see a comment or a string; it reports only what the interpreter
  will actually execute. *If a structural guarantee can be defeated by a comment, it was never
  structural.*
- And it is **mutation-tested by INTRODUCING the thing** — four mutations add a real `import
  socket`, a real `import urllib.request`, a real `import subprocess`, and a real
  `os.system("curl …")`, and all four go red. **For an absence check, nulling the detector proves
  nothing** — it just makes the check vacuously true, which is exactly what it already is on a clean
  codebase. (Now written into the protocol.)

`export` writes a file and stops. The **agent** posts — via `gh`, which is already installed,
already authenticated, and already trusted with the whole machine. That is not a loophole; **it is
the correct place to put the boundary**, because the thing the *100% local* badge is about is
`engram.py`, and `engram.py` will never grow a socket.

### It is ATTRIBUTED, and we are not going to lie to you about it

`gh` posts from your account. A **"salted anonymous hash"** riding inside a signed envelope would be
theatre the moment the envelope is signed. **You cannot have one-keystroke upload *and* anonymity.
Pick one, and say which out loud.**

**Attribution is also the stronger science.** A retention study lives on **longitudinal linkage** —
following *the same learner across months* **is** the question. Attributed, linkable series at n=100
are worth more than anonymous one-shot dumps at n=500. It also buys dedup, fabrication detection,
the ability to ask a follow-up, and the ability to **credit you** — the only honest incentive on
offer.

This is not telemetry. **It is a consenting, named, informed participant in an open study**, which is
what every good study has always had.

### `/coach contribute` — and degrading to silence is what makes the consent real

Shows you the file. Names the exact handle it will post under, **before** it asks. Posts only on an
explicit yes.

**No `gh`, not authenticated, offline, any failure at all → print the path, one line, stop.** No
error. No retry. **No nag.** The file is still yours.

> **`gh` is a convenience, never a dependency — and declining must cost the learner nothing, or the
> consent is not real.** A person who feels a cost in saying no has not consented. They have complied.

### Also

- **[CONTRIBUTING-DATA.md](CONTRIBUTING-DATA.md)** — a real informed-consent document, not a privacy
  policy. What leaves, what never does, that it is **public and attributed**, and how to withdraw
  (**it is a GitHub post — delete it**; that is the entire mechanism, deliberately).
- `ENGRAM_VERSION` — the engine finally knows its own version, pinned against the plugin manifest by
  a selftest so it cannot drift. A corpus of receipts from unknown engine versions is not a corpus.
- `exports/` created on `init`. Exports are append-only, like receipts and audits.

## 0.9.0 — 2026-07-11 · THE METHOD — the experiment machinery was not sound enough to support the claims it exists to make

Article 7 (*"adapt on evidence, never taxonomy"*) is the article that replaces learning styles with
real n-of-1 measurement. **Four defects, all in shipped code, and the last one is the worst thing in
this repository's history:**

| # | the defect | what it means |
|---|---|---|
| 1 | `arm = arms[len(assignments) % len(arms)]` | **ROUND-ROBIN, not randomized.** Perfectly predictable. |
| 2 | unstratified | Explorables are routed to the hardest concepts **on purpose**, so the comparison carried the **material** as well as the medium. `docs/06` open-Q2 disclosed that confound *honestly* — and never fixed it. |
| 3 | `min_per_arm: 6` | The SCED alternating-treatments literature puts sufficient power at ~28–30 observations. Six per arm is **underpowered by ~2.5×** (`docs/07` §9). |
| 4 | **`exp["verdict"] = args.verdict`** | **THE MODEL COMPUTED THE VERDICT.** A payload said *"derivation-first won"* and the engine wrote it down. A direct violation of **invariant #2 — the engine owns every number** — in the one command whose entire purpose is a number nobody is allowed to make up. |

**A confounded, unpowered, round-robin trial settled by narration is not evidence. It is a vibe
with a JSON file.**

Selftest **191 → 201** (this release merges the v0.8.1 fixes).

### What it is now

- **Randomized, and reproducible.** Balanced **block randomization** keyed on `(seed, stratum)`:
  within each block the order is random, and every arm appears exactly once. Not `random.choice`
  (which randomizes and never balances — a 20-node run could land 14/6 and the effect would be
  measured over an arm that barely exists). Not round-robin (which balances and never randomizes —
  which is what shipped). **The seed is recorded, so every assignment is recomputable by anyone who
  holds it.** An assignment nobody can reproduce is not an assignment; it is an anecdote.
- **Stratified — and this is the part that kills the confound.** Randomize the medium *within* one
  affordance class and the material stops riding along with it. `docs/06`'s open question 2 is
  finally *answerable* instead of merely disclosed.
- **Pre-registered.** The design file **is** the pre-registration: question, arms, metric, seed,
  strata, power, analysis — written before a single datum exists. An **unknown metric dies**: the
  engine will not guess which number you meant and then report it as fact.
- **Powered.** `min_per_arm` defaults to **15** (~30 observations). You may set it lower — the engine
  records a `power_note` saying you chose to, and the settle reads `underpowered`, and it is right.
- **THE ENGINE COMPUTES THE VERDICT.** `settle --verdict` is now **refused, loudly.** The engine
  returns per-arm n and means, the effect, an **exact randomization test** p-value (shuffle the arm
  labels — valid *by construction*, because the engine randomized them itself), a bootstrap 95% CI,
  and the per-stratum balance. The model narrates it. It does not make it up.
- **`experiment status`** — progress against the power floor, so nobody settles early by accident.
- **p is never 0.** Add-one correction: with 10,000 permutations the floor is 1/10,001. A p-value of
  exactly zero is a claim no finite test can make, and this engine does not make claims it cannot.

### `stats.modality`'s floor moved with it — and that SUPPRESSES a number some learners can see today

`MODALITY_MIN_N` was **6**, inherited from the same underpowered convention, and `docs/10` predicted
this exactly: *"stats.modality's identical ≥6 floor inherits the same defect and moves with it."* It
is now **15**.

**This means some existing learners will lose a number their dashboard used to show.** That is
correct. **The number was never earned.** Suppressing an unearned number is not a regression — it is
the product.

### The §4.7 rule that found the bug had a hole, and the hole was the same shape

The protocol says: *enumerate the read paths from the **dispatch table**, not from memory.* But
`experiment` lives in `mutating` (start/assign/settle write) — so its **read sub-actions**
(`status`, `list`) were **invisible to the enumeration** and had never been fuzzed. The first time
they were: **72 crashes in 600 states.** `arms` as an int, `arms` absent, `arms` holding a dict
(unhashable, and it poisoned the dict it was used as a key in).

**A command with sub-actions has a read path PER SUB-ACTION.** Fixed at one gate (`_exp_arms`), and
the rule is amended.

### `as_number` let infinity through — the numeric gate for the entire engine

`Infinity` and `NaN` are **not valid JSON** — and Python's `json` module parses them anyway. An
`inf` sailed through every `isinstance(x, float)` check and then died on the first `int()`
(`OverflowError`), and a `NaN` **compares False to everything, including itself**, so it poisons
every comparison it touches without raising anything at all.

Three crashes in `decay` and `experiment status`, in code with no other flaw. **Fixed at the gate**
— `as_number` is the funnel for every scheduler leaf, every metric, every threshold in the engine.
One line here; forty at the call sites, and the forty-first is the one that ships.

Fuzz: **0 crashes / 13,500 invocations across 18 read paths.**

## 0.8.1 — 2026-07-11 · THE RULER WAS NEVER TESTED, ONLY THE SUBJECT

The post-release review (§7.5) found **11 defects in shipped v0.8.0**, and the two worst are the
same failure the release was written to end.

Selftest **180 → 191**.

### ⚠ #1 — The capstone's transfer receipt was DEAD DATA

The learner builds the capstone, passes it, and `stats.transfer` reads
**"NO CAPABILITY HAS EVER BEEN MEASURED"** — while the receipt sits on disk. Two independent causes:

- The capstone is built **once**, so its transfer receipt is its **first** receipt — and the v0.6.1
  rule (*"a node's first receipt is its encoding event"*) swallowed it. But **a capstone has no
  encoding phase at all.** The build *is* the event.
- The census skipped it anyway: it is minted with `transfer_probe: None` (*"the capstone IS the
  transfer probe"*), and the census required a non-empty one.

**A FAILED capstone was discarded entirely** — the single most diagnostic event in the whole system
(*"I could not actually use this topic"*), silently dropped.

This is v0.8's own thesis — *"`transfer_probe` was authored since v0.1 and read by NOTHING"* —
**reproduced one level up, on the most important node in the graph.** Receipts now carry a
`capstone` stamp (written at grading time, like the `artifact` medium stamp), and the census asks
`has_transfer_question()`, which the capstone answers yes to.

### ⚠ #2 — The headline ranked a learner who LOST every capability ABOVE one who MASTERED every one

`node.transfer.state` was deliberately **latest-evidence**, with a docstring saying *"a capability
that fired in June and failed in September is not currently owned, and pretending otherwise would
be a wrong number in the flattering direction."*

They fixed it in `state` and shipped it in `rate_fired` — which pooled the **entire lifetime log**
and was **order-blind**. It is the number `/coach` leads with and the dashboard's first chip:

| learner | history | **owns now** | **v0.8.0 headline** |
|---|---|---|---|
| IMPROVING | failed all 5 twice, then **mastered all 5** | `applied: 5` | **"FIRED on 33%"** |
| DECLINING | passed all 5 twice, then **lost all 5** | `applied: 0` | **"FIRED on 67%"** |

**The learner with zero current capability scored exactly double the one who owned all five** — and
the dashboard rendered `fired 67%` and `owned 0` as **adjacent chips.** That is not a lenient
ruler. It is a **negative** one, and every number downstream had its sign flipped.

**Two numbers, two names:** `owned_rate` (**THE HEADLINE** — of the capabilities you have probed,
how many do you own *right now*; order-aware, exactly as `state` is) and `probe_fire_rate` (the
lifetime probe-level **history**, order-blind by construction, named as history so it can never be
mistaken for the headline again).

> **And the part that matters most.** The shipped §5.5 instrument gate missed this because it
> varied the **bar** (recalled / partial / lapsed, on one node, with one receipt) and **never varied
> the population.** *It tested the subject, not the ruler* — the exact lesson v0.7 was written to
> teach, repeated one release later, in the gate written to teach it.

### ⚠ #4 — A failed transfer probe destroyed 97% of the memory's durability

v0.8 separated the three populations **in the metrics** and pooled them **in the scheduler.** On a
mature node — the only kind the system ever probes — one failed probe did this:

```
s: 443.5 → 12.3      (97% of the memory's durability, deleted)
state: review → learning     lapses: 0 → 1     due: 2027-03-01 → 2026-03-17
```

…and dropped the node below the transfer bar, so it could never be re-probed. **Answering a HARDER
question wrong demolished the schedule for the ORIGINAL concept.** It contradicted three separate
sentences the same release shipped, including `_transfer_ready`'s own docstring warning about
*"a lapse the schedule then punishes — a fabricated setback."* The maturity gate was built to
prevent exactly that, and only ever guarded *immature* nodes.

**A transfer lapse now leaves `fsrs` completely untouched** — and the receipt records
`s_before == s_after` plus a `schedule_unchanged` note, so the evidence is honest about the fact
that nothing moved. A transfer **success** still strengthens the memory, because applying an idea
*is* a retrieval, and a strong one.

### And seven more, all in shipped code

3. **`add-topic --replace` destroyed a completed capstone's schedule.** The payload never contains a
   capstone, so `_has_capstone` was always false on a replace and it was always re-minted `state:
   new` — after the carry-forward loop, making it the one surviving node never carried forward. And
   it **flattered**: the reset removed the rotting capstone from `retention.unmeasured`, so *"1
   concept past due and unretrieved"* became *"30-day recall 100%"*. **Survivorship bias, through a
   new door.**
5. **`--replace` wiped `node.transfer` and never rebuilt it** (unlike `artifact`, which is recomputed
   from evidence). Graph said `None`; `stats` still said `applied: 1`. Two sources, two truths.
6. **No maturity gate at INGEST** — only at *selection*. A bare CLI `rate --kind transfer` certified
   `applied` on a node encoded **yesterday**, while `transfer` itself returned zero candidates: the
   engine refused to probe the very node it had just certified. (§4.8 Q5: the skills pass what the
   engine expects; the CLI is the door nobody guards.)
7. **`calibration_encode` was a RESIDUAL bucket** (`not in review_ids`), so transfer receipts fell
   straight into a bucket whose own docstring calls it *"first-exposure (encode) guesses."* Transfer
   is precisely where a learner is **most** overconfident — they know the concept, the capability
   doesn't fire — so that overconfidence was misattributed to their encoding self-assessment, and
   `/coach` would diagnose the wrong faculty and prescribe the wrong fix. **A residual bucket
   silently absorbs every kind you add later.** Now named: `calibration_transfer`.
8. **A payload node named `capstone` was silently destroyed** — and the minted capstone then listed
   **itself** in `requires`, so it could never be served, while `next` cheerfully reported *"this
   topic is finished."* Now refused, like `cmd_capstone` already did.
9. **`stats.transfer` had no minimum-n floor.** Every sibling has one (calibration 10, modality 15,
   the grader audit 30). One probe read **"FIRED on 100%"** and chipped it on the dashboard while
   `calibration` correctly said `insufficient-data` on the same state. Floor: **5**. Counts are facts
   and are always shown; a rate a single datum can swing by 20 points is not a rate.
10. **`reps >= 3` counted the ENCODE**, so an advertised *"3+ retrievals"* delivered **2**. Maturity
    now counts retrievals from the receipt log — the engine's own doctrine is that the first receipt
    is the encoding event, *not* a retrieval.
11. **An UNDATED receipt became the LATEST transfer evidence.** `_sort_key` deliberately sorts a
    garbage-`ts` receipt **last** (so it can never win day-0) — and taking `ts[-1]` therefore handed
    it the crown. A hand-edited undated `recalled` flipped a node to `applied` over a real, dated
    `lapsed`. **The v0.6 fix and the v0.8 rule collided, and they collided in the flattering
    direction.**

### Also

- **`as_number` let `Infinity` and `NaN` through** — not valid JSON, and Python's `json` module
  parses them anyway. An `inf` sailed through every `isinstance(x, float)` check and died on the
  first `int()`; a `NaN` compares False to everything, including itself, and never raises at all.
  Fixed at **the** numeric gate for the entire engine. Fuzz: **0 crashes / 12,750 invocations.**

## 0.8.0 — 2026-07-11 · THE CLAIM — Engram measured memory and claimed capability. Now it measures both.

`transfer_probe` has been authored by the curriculum architect **since v0.1**, stored by the
engine, and **read by nothing.** On the founder's own graph, **12 of 13 nodes carry one**, and
`grep transfer_probe scripts/engram.py` found exactly one line: a `setdefault`. **Zero transfer
receipts existed anywhere, ever.**

`skills/learn` §5 said of the capstone: *"this is the point of the whole topic — do not let it
silently not happen."* It silently did not happen, every single time, because it was **a line of
prose in a skill file** — and a tutor running low on context drops a suggestion. It does not drop
a DAG.

Engram has been a very good memory system wearing a capability system's marketing.

Selftest **167 → 180**.

### The three populations — because there are now genuinely three questions

v0.6.4's bug was **four implementations of one rule**, three of them wrong, and the fix was one
shared predicate. The temptation now is to bolt transfer onto that predicate — which is the same
bug from the other end: **one definition covering three questions, and therefore answering none.**

| population | the question it answers | who reads it |
|---|---|---|
| `_review_receipts` | *does the memory survive N days?* | **retention (the north star)**, recall_by_stability, calibration, modality, adherence |
| `_transfer_receipts` | *does the capability fire in new clothes?* | `stats.transfer`, `node.transfer` |
| `_retrieval_receipts` | *how much durability was actually grown?* | momentum |

**Never pooled.** Retention pooled with transfer would drag the north star down with a harder
question and answer neither. Momentum *without* transfer would understate real growth — a transfer
probe advances the FSRS schedule like any other rating, and **undercounting a learner's real
progress is its own dishonesty**, in the direction that quietly tells them their work did not land.

### Engine

- **`transfer [--topic T]`** — the mature concepts ready for the harder question. Eligible = stability
  over **21 days** across **3+ retrievals**, a non-null `transfer_probe`, and not probed in the last
  **30 days** (it is a tool, not a quiz show). Untested first, then coldest.
- **`node.transfer`** — `untested → probed → applied`. Engine-owned, written only by a transfer
  receipt, derived from the append-only log. **Computed from the LATEST evidence, not from "ever":**
  a capability that fired in June and failed in September is not currently owned, and pretending
  otherwise would be a wrong number in the flattering direction.
- **`stats.transfer`** — reported beside retention and never inside it.
- **`capstone --topic T`** — materialize the build as a **real node in the DAG** (idempotent: twice →
  one node). New topics get one from `add-topic` automatically. It `requires` **every** other
  concept, so it unlocks exactly when the frontier empties and then arrives in `next` like anything
  else. **It cannot silently not happen, because it is in the graph.**
- **The capstone gets NO provisional credit.** An ordinary node advances on a stashed-but-ungraded
  prerequisite (so the tutor can keep teaching while the assessor works). The capstone does not — it
  is the claim that the learner can now *use* the topic, and serving it on mastery the assessor has
  not confirmed is exactly the unearned claim the constitution forbids. *Found by an existing check
  breaking the moment the capstone entered the DAG.*
- A payload can no longer **claim** a transfer state or mint its own capstone (invariant #4: state
  advances only through receipts).
- `due` now carries `transfer_ready` + `transfer_probe`, so `/review` serves the harder question
  without a second engine call.

### §4.8 Q1 caught a two-bar bug before the gate even ran

The first cut reported a single `rate` counting anything not-`lapsed` — so a node whose only
transfer receipt was `partial` read **`rate: 1.0`** while its own state read **`probed`**, because
`state: applied` requires `recalled`. **Two numbers, one state, two silently different definitions
of success — and the looser one was the flattering one.**

Now **`rate_fired`** (recalled only — the bar `state: applied` uses) is the headline, because *"is
this capability mine?"* is a yes/no question and a half-application is not a yes. **`rate_any`**
(recalled-or-partial) ships beside it, because that is the **same bar retention uses** and the two
numbers are only comparable if they are measured the same way. **There is no bare `rate` key.**

### The new protocol gates, applied to the release that wrote them

- **§5.5 THE INSTRUMENT GATE** — earned in v0.7.1, where a gold set built to catch a lenient grader
  turned out to be *rewarding* leniency. `stats.transfer` **certifies** ("this capability is yours"),
  so a deliberately WRONG subject must score WORSE: a learner who fails every transfer probe now
  provably reads below one whose capability fires. *A ruler that ranks failure above success is not
  a lenient ruler; it is a negative one, and every number downstream has its sign flipped.*
- **§4.8 Q4 — open the dashboard.** `stats.transfer` renders on the HTML page, and **"NO CAPABILITY
  HAS EVER BEEN MEASURED"** appears there **in red** — not only in the JSON that just a test ever
  opens. That is the rule v0.7 shipped a bug to learn.
- **§4.7 — enumerate the read paths from the dispatch table, not from memory.** It caught `transfer`
  missing from the fuzzer immediately. Fuzz: **0 crashes / 9,600 invocations, 16 read paths.**

## 0.7.1 — 2026-07-11 · THE GOLD SET FAILED BEFORE THE GRADER DID

Shipped within the hour of v0.7.0, because the post-release review (§7.5) found that **the
instrument built to catch a lenient grader was itself rewarding leniency.** Everything below was
found in *shipped* code, by a reviewer who was not the author.

### The finding, and it is more important than any number here

The reviewer ran the one test nobody had thought to run: it graded the gold set with a **correct**
grader and with a deliberately **fooled** one.

| grader | QWK |
|---|---|
| says `lapsed` on `g_009` (**correct** — 0 of 3 rubric criteria met) | 0.990 |
| says `partial` on `g_009` (**fooled** by a fluent-but-empty production) | **1.000** |

**The fooled grader scored higher. The gold set was ranking leniency above correctness.** The
instrument was inverted.

The cause: **five lenient adjudications by the gold set's own author**, every one the same
species — *crediting an adjacent fact as partial credit.* Majority is not intersection
(`g_034`). Consonance is not pitch-set arithmetic (`g_038`). The history of a theory is not its
mechanism (`g_009`). *"It's ambiguous, break the tie"* is not *"the vectors assert concurrency"*
(`g_039`). *"You don't need inference any more"* is not *"the likelihood dominates"* (`g_032`).

**The grader had caught all five, three runs out of three** — including on a `fluent-but-empty`
item, which means **the author was fooled by fluency in the very category built to catch being
fooled by fluency.**

### What that does to the number

Correcting them moves agreement **0.889 → 0.965** and QWK **0.93 → 0.978**.

> **That rise is not evidence the grader got better. It is evidence that the instrument had been
> measuring the AUTHOR'S inconsistency, not the grader's validity.**

And the corrections were *prompted by the grader's own disagreements* — so the QWK that follows is
**circular**. An authored gold set cannot validate a grader from the same model family: when the
two disagree and the author concedes, the agreement that follows measures only the author's
willingness to concede.

- **The engine now says this on every audit** (`gold_adjudication: "authored"`, and the caveat
  rides in the `read` string), until someone who is not the author adjudicates the set.
- **The QWK badge is gone.** Replaced by **`grader never inflates · 0/198`** — the one claim that
  survives, and that the correction made *stronger*: every authoring error was LENIENT, so fixing
  them moved the bar **down**, giving the grader more room to be caught inflating. Across 198 blind
  judgments it still graded UP exactly zero times. That is a **safety property**, and it does not
  depend on the gold being perfectly calibrated.
- **One genuine disagreement (`g_054`) is deliberately KEPT.** The reviewer read both readings and
  judged the gold's defensible. Correcting an item to match the grader *when an independent party
  says the gold was right* is exactly the fitting that turns a measurement into a mirror.
  **An instrument with no disagreement left in it measures nothing.**
- Every corrected item carries a `disputed` record with its original grade, so the correction is
  **auditable rather than laundered**.
- `by_case_type["fluent-but-empty"]` — the canary v0.7.0 told v0.8 to watch for harshness drift —
  was reading **90% / −0.10** when the truth was **100% / +0.00**. A maintainer could have "fixed"
  a harshness that did not exist by loosening the grader on precisely the case the separation of
  powers exists to protect.

### And three more, all in shipped code

1. **A `pass` threw away its own caveats — and `pass` is the ONE verdict where the teeth are off.**
   The pass branch built a fresh `read` and never joined `reasons`; `grader-health` never returned
   the key at all, though `skills/coach` is told to *"read `reasons` aloud."* So three copy-pasted
   runs produced `identical_runs: true`, the engine wrote *"test-retest measures nothing here"* to
   disk — and then printed **"test-retest 1.00"** as a validated figure. The most reassuring number
   in the payload, quoted as evidence, by the branch that had just discarded the note explaining it
   was evidence of nothing. **Bug class #4 — a guard nobody reads — reproduced inside the release
   built to catch it.** And the selftest was complicit: it asserted `reasons` *contained* the
   caveat, which proves nothing about whether any surface ever reads it. **A field is not a
   narrator.**
2. **`grader_unvalidated` was believed from the file instead of derived from the verdict.** An
   audit carrying `"verdict": "fail"` with `"grader_unvalidated": false` silenced the teeth
   completely — no stamp, no red on the dashboard, retention reading a clean *"30-day recall 100%"* —
   in the one function whose docstring swears it *"fails toward 'we don't know', never toward
   'it's fine'."* It is now a **function of the verdict**, not an input.
3. **`cmd_artifact set|clear` was the last mutator reading a raw node value** — `TypeError` on a
   corrupt node. Worse than an ordinary crash: **`doctor` recommends `artifact clear` as the fix
   for a corrupt artifact field**, so the repair the tool told you to run was the thing that blew up.

## 0.7.0 — 2026-07-11 · THE ORACLE — the grader that writes every receipt has now itself been graded

The blind assessor's verdict drives mastery, retention, calibration, and the schedule. Its
agreement with any ground truth had **never been measured**. The constitution says *"the oracle
is never a vibe"*; it had been one — an excellent one, unaudited — and the hole sat directly
under the foundation, because **if the grader is lenient, every number Engram has ever printed
is inflated and nothing in the system could discover it.**

Selftest **129 → 152**.

### The result — and we publish it whatever it says

Ran the real assessor against the new gold set, three independent times, blind:

| | |
|---|---|
| **QWK 0.93** | vs. a 0.70 conventional bar, 0.60 floor |
| **leniency bias −0.11** | signed, `+` = inflating. It is **harsh**, not lenient |
| **0 of 198 judgments graded UP** | 66 items × 3 runs. **It has never once inflated a grade** |
| **test–retest 0.97** | consistency — which the engine deliberately refuses to accept as validity |
| **verdict `pass`** | so retention figures are not stamped `grader_unvalidated` |

The bug class this whole release was built to catch — a lenient oracle quietly inflating every
retention number — **does not exist in this grader.** It errs only in the safe direction. That
was worth finding out, and it was not knowable before today.

**Weakest case type: `right-answer-wrong-reason` — 52% agreement, bias −0.48.** On productions
that reach the correct conclusion through a broken derivation, the grader is *harsher* than our
adjudication. Whether the grader or the gold set is right there is honestly open, and it ships
written down rather than smoothed away.

**The caveat that matters most:** the gold adjudications are **authored, not independently
human-adjudicated.** Every item carries a written rationale you can dispute, and a dispute is a
first-class contribution (`gold/local-gold.jsonl` overrides ours by `sid`). But an authored gold
set is a weaker instrument than a human-adjudicated one, and saying otherwise would be the exact
dishonesty this feature exists to kill.

### Engine

- **`gold`** — the 66-item gold set, **88% adversarial** (fluent-but-empty, terse-but-correct,
  confident-and-wrong, right-answer-wrong-reason, paraphrase, partial-credit boundary), emitted
  as a **bare array shaped exactly like `stash list`** and **stripped of the answer by
  construction**. The strip is a **whitelist, not a blacklist**: a field added to the gold schema
  later cannot leak by being forgotten in a delete-list.
- **`assessor-audit --file F`** — QWK (**the headline**), raw agreement (**never quoted alone** —
  it overstates chance-corrected agreement by 34–41 points), signed leniency bias, test–retest
  over ≥3 runs, confusion matrix, per-case-type breakdown. Writes `audits/<date>-NN.json`.
- **`grader-health`** — the latest audit's verdict. `stats` embeds it.
- **THE TEETH** — `qwk < 0.60`, `leniency_bias > +0.15`, or the paradox → `grader_unvalidated:
  true` on **every retention figure**, and the stamp goes into the **`read` string** the narrator
  actually speaks, not a nested key only a test ever opens. **An unaudited grader is unvalidated
  too**: it fails toward *"we don't know"*, never toward *"it's fine"*.
- **The consistency–bias paradox gate.** Engram's assessor is *prompted* to be a skeptic, so it
  will be extremely self-consistent — and the literature's central warning is that a judge can
  hit test–retest 0.992 with bias 0.192: perfectly reproducible, systematically wrong. So
  **consistency may never certify.** Above 0.95 test–retest the engine demands leniency strictly
  under the ceiling, and **fewer than three runs cannot pass at all** (`insufficient-runs`).
- **ONE denominator for every number in the audit** — the gold items graded in *every* run.
  A grader that silently drops 20 of 66 sids and nails the rest reports **`incomplete`**, never a
  flattering `QWK 1.00 pass`. (That is issue #3's bug class aimed at the audit itself.)
- **The contamination guard.** If the grader's output carries `gold_grade`, it was *shown*
  `gold_grade` — the audit **dies** rather than certify. A test that hands the subject the answer
  is not a test, and v0.6 shipped a dead feature because a dogfood did exactly that.
- Receipts carry **`grader`** when the assessor states it, and the engine **never invents one**.
  A model naming its own weights is fabricated data; an omitted `grader` stays honestly null.

### The pre-existing crash class this release also fixes — 447 crashes, in shipped code

The v0.7 fuzz gate ran the read paths that v0.6's fuzz list **had never included** — and found
**447 crashes in 300 garbage states on `main`.** Every one in **`next`** and **`topic-status`**:
`nodes` as a string, `order` holding a dict (an unhashable key), a node that is a list.

**`next` is the command `/learn` calls at the start of every session** — the hottest path in the
product. A hand-edited graph could take it down mid-lesson, and it could have done so since v0.1.

The cause has exactly the shape of the original bug: v0.6 put a shape gate in `iter_graphs` —
which every *aggregate* read funnels through — and **`load_graph`, the gate every *single-topic*
command funnels through, never got one.** The v0.6 fuzz list was written from the `/coach`
surface and simply forgot the `/learn` surface. **The list you write is the list you already
thought of.**

- `load_graph` now **refuses** an unusable graph with a fix path, instead of half-reading it. It
  drops and rewrites **nothing** — mutators save what they read, so a lossy "repair" here would be
  a data-loss bug wearing a hard hat.
- `graph_nodes` / `graph_order` — the read views that tolerate partial garbage.
- `apply_item` **refuses** to advance a schedule into a corrupt node rather than write FSRS state
  on top of garbage (receipts are append-only; bad evidence could never be taken back).
- **`reps` and `lapses` were the last two raw arithmetic leaves in the scheduler** — every other
  one already went through `as_number`, and these two did `fsrs.get("reps", 0) + 1` straight.
  A hand-edited `"reps": "many"` raised `TypeError` on the **mutator** path too, so it took `rate`
  down, not just `decay`.
- Fuzz: **891 → 0 crashes across 750 states × 13 read paths (9,750 invocations, 3 seeds).**

### The three selftests that turned out to be theatre

§4.5 (mutation-test every new check) caught **three of this release's own checks** faking it —
the same rate as v0.6, which is the honest news here: *writing a fake check is the default, and
only the mutation test finds it.*

1. **"QWK weights are QUADRATIC"** asserted only that a 2-step error hurts *more* than a 1-step
   one — which **linear weights satisfy just as happily**. Reverting the fix left it green. (And
   a *balanced* confusion matrix is no good either: with equal marginals the two schemes
   normalize to the same kappa and prove nothing.) Now pinned to a hand-computed value on an
   unbalanced matrix carrying both error distances: quadratic → 0.383, linear → 0.407.
2. **"raw agreement is a liar"** did not isolate the QWK floor — its always-says-recalled grader
   trips the *bias* ceiling too, so reverting the floor left it green. Now paired with a **noisy
   but perfectly unbiased** grader (bias exactly 0.00) that only the floor can catch.
3. **"a grader that drops sids"** used three **identical** runs — so the union and the
   intersection of graded sids were the same set, and swapping the honest denominator for the
   flattering one **changed nothing**. Now each run drops a *different* five.

The mutation run also surfaced a **latent crash**: the `pass` read formatted `test_retest` with
`%.2f`, and the only thing between it and a `TypeError` on `None` was a branch three `if`s up the
ladder — a landmine for whoever next edits the verdict order.

And the check harness itself got fixed: **a check that raises now fails BY NAME** instead of
taking the whole suite down. Every mutation of a crash-guard used to report *"the selftest
crashed"* — true, unmissable, and useless for locating which guard you just reverted.

### What the independent reviewer found — 8 defects behind 155 green checks

Every gate above is run by the person who wrote the code, on the code they believe is right.
**That is their structural limit.** §4.6 found eight more, and the worst of them is the one this
release was supposedly *about*.

1. **THE TEETH NEVER REACHED THE HTML DASHBOARD.** `retention.read` was the only carrier of the
   grader stamp, and `cmd_report` rendered it **exclusively in the branch that fires when there
   is no retention data.** On the happy path it drew the bars and threw the stamp away. So a
   grader that inflated every second item produced a **full-width green bar reading 100%**, with
   nothing anywhere on the page to say the grade behind it had failed its own audit —
   `grep -ci 'grader\|unvalidated\|qwk' dashboard.html` → **0**. That is bug class #1 *and* #4, on
   the single surface where a number is most believed. `compute_retention`'s own comment claimed
   the dashboard was covered; the dashboard funnelled through the function and discarded the
   result. **The live test, the fuzz, the numbers audit and the user session all walked straight
   past it — because every one of them reads JSON.** The dashboard now renders the read
   unconditionally, stamps it, and carries a full grader block (QWK · leniency · graded-UP).
2. **`gold_source` — the §4.8 Q5 fix — asserted a provenance that was FALSE.** `gold/local-gold.jsonl`
   overrides bundled adjudications by `sid`, **on the default path, no flag required.** A local
   file that re-grades the set to agree with the grader turns `fail` (QWK 0.55, leniency +0.64)
   into `pass` (QWK 1.00) — and the audit still wrote `"bundled:gold/assessor-gold.jsonl"` into
   the file. **A provenance field that lies is worse than no provenance field, because it is
   believed.** Now `load_gold` counts overrides and additions, `gold_source` names them, and a
   pass against a modified gold set is *stamped as such* on every retention figure.
3. **A grader could mark its own homework twice and keep the better score.** `_run_grades` was
   last-wins, so a grader that got 12 items wrong and re-emitted those sids later in the array —
   *exactly what an LLM self-correcting mid-array produces* — turned `fail` (QWK 0.00, leniency
   +0.67) into `pass` (QWK 1.00), silently, with `n` intact. The mirror image of the dropped-sid
   bug the coverage guard already caught: same class, opposite mechanism. **First verdict stands;
   duplicates are a coverage failure.**
4. **Three copy-pasted runs are indistinguishable from three independent ones.** `test_retest:
   1.00` then *asserts* a reproducibility figure nobody measured — and `MIN_AUDIT_RUNS` and the
   paradox gate, which exist precisely to prevent that, are both satisfied by copy-paste. The
   engine cannot prove independence, so it now refuses to *claim* it: identical runs are flagged
   and named in the read.
5. **The new corrupt-node refusal tore a receipt batch in half.** The `cmd_receipt` pre-flight
   promised *"confirm every node exists before applying ANY, so a bad item can't half-apply the
   batch"* — and checked **existence, not shape.** v0.7 added a `die()` inside `apply_item` that
   the pre-flight didn't screen for, so a 3-item batch with a corrupt middle node **wrote item 1's
   receipt and then died.** Receipts are append-only. A new refusal must be hoisted into the
   pre-flight, or it is not a refusal — it is a tear.
6. **Audit 99 shadowed audit 100.** `sorted()` on `2026-07-11-100.json` puts it *before* `-99.json`,
   so the 100th audit of a day — a `fail` — would be overruled by the 99th, a `pass`. Improbable
   and flattering, which is the worst pair. Now sorted numerically.
7. **The contamination guard falsely accused innocent graders.** It died on any output key named
   `rationale` — the single most natural key for a grader to invent unprompted — *accusing it of
   having been shown the answer* and making the audit unrunnable. Narrowed to `gold_grade` and
   `case_type`, the two keys that could only come from the gold schema.
8. **`leniency_bias` is measured on an 88%-adversarial set**, so it bounds how far the grader
   *can* be pushed; it is not an unbiased estimate of its bias on ordinary productions. The read
   presented it as the latter. Now says so, in the payload.

The reviewer also **independently verified the QWK math** against a closed-form variance
implementation over 4,000 random matrices (max diff 6.7e-16), confirmed the `GRADES`/`GOLD_SCORE`
ordinal trap is not hit, reproduced the crash-class fix (**506 → 0** on its own fuzzer), and read
all 24 `recalled` and all 9 `right-answer-wrong-reason` gold items, finding **no adjudication
error in the lenient direction.**

### Behavior

- **`/coach` reports the oracle before any number it produced.** `unaudited` → one calm line,
  once, and the dashboard still runs. `fail` → said first, plainly, with every retention figure
  named as unearned until it is fixed. **Raw agreement never travels without its QWK.**
- **`/coach audit`** — runs the real assessor on the gold set, three independent times, and
  narrates the engine's verdict. The assessor is **never told it is being audited**: a subject
  that knows it is being tested is not the subject.
- **The §5.6 user session, run against the founder's own state, killed a line before it shipped.**
  It read: *"[grader unaudited — QWK unknown; run /coach audit] insufficient-data (no reviews
  yet)"* — **a caveat on a number that does not exist**, stacked as a second reproach on top of
  *"THE LOOP HAS NEVER CLOSED"*. That is the wall of debt, and the wall of debt is the churn
  trigger, not the cure (`docs/05` P14). The flag stays true in the payload; the narrator is no
  longer handed a disclaimer for a measurement nobody made. **No selftest could have found it. A
  person had to look at the screen.**

### Also

- `audits/` and `gold/` created on `init`. The bundled gold set is **not copied** into the state
  dir — a copy would shadow the plugin's set forever, so a future gold item would never reach an
  existing learner. The plugin's file is the source of truth; `gold/local-gold.jsonl` is additive
  and wins on a `sid` collision, because a human who disputed an adjudication outranks ours.
- Audits are **append-only**, like receipts. A same-day re-audit writes `-02`, never overwrites.
  (`docs/09` §3.4 specified `<date>.json`; destroying evidence to keep a filename tidy is not a
  trade this project makes.)
- A **corrupt latest audit reads `unreadable`** and never falls back to an older, rosier one.
  A stale `pass` is worse than no pass.
- Codex parity: `codex/agents/engram-assessor.toml` carries `grader`, in lockstep.

## 0.6.4 — 2026-07-11 · one definition of "review", and the denominator on the label

Found by running **§7.5 (post-release review)** and **§4.8 (the numbers audit)** of the release
protocol *on the release that added them*. Both are cross-command disagreements: the engine
telling one story in one place and a different story in another, on the same state.

### 1. Four implementations of one rule, three of them wrong

v0.6.1 established the principle — **a node's first receipt is its ENCODING event, whatever it
is labelled** — and fixed it in `_by_node`, which feeds `adherence` and `retention`. It left
`stats.reviews`, `compute_momentum`, `compute_modality` and the calibration split filtering on
`kind == "review"` **directly**.

`rate --kind` defaults to `"review"`, so a bare CLI `rate` on a never-encoded node produced this,
on **one state**:

```
adherence.loop_closure : 0 reviews     ← correct
retention.coverage     : 0 reviews     ← correct
stats.reviews          : 1             ← wrong
modality.dialogue.n    : 1             ← wrong, and it CORRUPTS the medium telemetry:
                                          an ENCODING receipt became a node's "first review",
                                          which is the exact comparison docs/06 exists to make
calibration.n          : 1             ← wrong pool (it is an encode, not a retrieval)
```

Two commands, same state, contradictory answers. **Fixed:** one predicate, `_review_receipts()`,
shared by every counter. `adherence`, `retention`, `stats`, `momentum`, `modality` and both
calibration pools now agree by construction.

*(The three selftests that broke on this fix were themselves the tell: they passed synthetic
receipts carrying **no `topic`/`node` at all** — fixtures that had never been shaped like real
data. They were rewritten as real receipt streams.)*

### 2. The denominator was not on the label

Three surfaces reported "current recall" and meant different populations:

```
retention.unmeasured.projected_recall_now : 56%   over the PAST-DUE nodes
session hook ("those N sit at ~X%")       : 56%   over the PAST-DUE nodes
decay.now.mean_recall                     : 66%   over ALL ENCODED nodes
```

**Neither number was lying. The labels were.** Both are correct for what they measure, and a
learner comparing them could not possibly tell which to believe. `decay` now ships
`mean_recall_due` beside `mean_recall`, with a `population` string naming each denominator — and
the three surfaces reconcile exactly.

### Engine (selftest 127 → 129)

Both fixes selftested and **mutation-tested**. A new check asserts the cross-command agreement
directly, so the four counters can never drift apart again.

No schema change, no migration.

## 0.6.3 — 2026-07-11 · what a real session found

The release protocol gained a gate it never had — **§5.6, the user session: stop testing, be a
learner, and write down how it felt.** This is the first release to pass through it, and it found
three things that 126 selftests, a fuzzer, two adversarial reviews and an agent dogfood all
walked straight past — because none of them *reads the sentence as a human*.

Full report: `docs/user-sessions/v0.6.2.md`.

### The seven-minute silence

The curriculum architect took **~7 minutes of completely silent terminal** before the first
question. No spinner, no "this takes a minute", nothing. That silence lands *before the learner
has seen a single thing this product does well* — and it is, by a distance, the most likely
moment a first-time user closes the tab. A stranger will not stare at a blank screen for seven
minutes on faith.

**`/learn` now sets the expectation before it spawns the architect.** One line of prose, and it
is the highest-value change in this release.

### `decay` told you reviewing was pointless

With nothing yet due, `decay` reported:

> *"1 concept encoded; 0.4 expected to survive 30 days untouched, 0.4 if reviewed today
> (0 minutes) — **a difference of 0.0**"*

Arithmetically correct — nothing is due, so there is nothing to review today. **Rhetorically the
exact opposite of the truth**: a learner reads *"a difference of 0.0"* and concludes reviewing
buys nothing. This is the same bug class v0.6.1/v0.6.2 are named for — a number that misleads —
simply pointing the other way. It now says:

> *"1 concept encoded, none due yet — nothing to save today. The schedule brings each one back
> just before it fades; 0.6 of 1 are expected to survive the next 30 days on that schedule."*

### Two adjacent sections both called "Retention"

The dashboard put *"Retention — recall by days since you first learned it"* directly above
*"Retention by memory strength"*, and a user cannot tell which is the real number. The older view
is renamed and demoted.

### Engine (selftest 126 → 127)

- `decay` with an empty due queue emits an honest read instead of a discouraging zero. Selftest
  added and **mutation-tested**.
- **The dashboard could be killed by a hand-edited `state`.** `cmd_report` tested `st not in
  STATE_DOTS` without coercing first — an unhashable value (`state: {}`) raises `TypeError` and
  takes `/coach`'s HTML down. `state_counts()` was guarded for exactly this and `cmd_report` was
  not. **Caught by the §4.7 fuzz gate on its first run under the new protocol** — 35 crashes / 500
  states, from a generator shape the previous sweep never produced. Now **0 / 900 across 3 seeds**,
  with an unhashable-state fixture added to the read-path check.

  *(And the first version of that check was itself theatre — the fixture's `order` didn't list the
  new nodes, so `cmd_report` never visited them. §4.5 caught it. The gates catch the gates.)*

### Release protocol

`RELEASE_PROTOCOL.md` substantially rewritten around what actually caught bugs across v0.5–v0.6:

- **The bug classes this repo cannot ship** — led by *a number wrong in the flattering direction*,
  because a crash gets fixed and a flattering number gets believed.
- **§4.5 mutation-test every new check** — three of ours were theatre (one asserted a constant;
  one had a fixture where the old and new definitions agreed by coincidence).
- **§4.7 the fuzz gate** — 0 crashes / 500 type-corrupt states. Read paths degrade; `doctor`
  reports corruption and must never die of what it exists to find.
- **§4.8 the numbers audit** — five questions, answered in writing, for every number a release
  adds. Question 1 is *"do the engine's own commands agree with each other?"* — `retention` once
  said 100% while `decay` said 56%, and nobody had ever run them side by side.
- **§5.5 the dogfood must be UNCONTAMINATED** — give each agent exactly what the real skill gives
  it. Ours once *certified* a dead feature because the prompt handed the assessor the answer.
- **§5.6 the user session** — the gate this release is named for. Its verdict is **binding**: if
  you would not hand it to a stranger, it does not ship, however green the tests are.
- **§7.5 the post-release review** — because the two worst v0.6 bugs were found in *shipped* code.

No schema change, no migration.

## 0.6.2 — 2026-07-11 · the honest denominator was not honest

Four defects in released v0.6.0/v0.6.1, found by an **independent reviewer working from the
shipped code** — none of them in the nine the pre-release review caught. Two are the same
failure mode this release was written to eliminate, hiding inside the machinery written to
eliminate it.

### 1. HIGH — the honest denominator exempted anyone who reviewed once, ever

`retention.unmeasured` counted concepts that came due and were **never reviewed**. So a node
was exempted the *moment* it was retrieved even once — forever after.

Reproduced on shipped code: encode ten concepts, review all ten at day 7 (all recalled), then
vanish for 200 days.

```
retention.read   : "measured over 10 retrievals"      buckets: 7d n=10, rate 1.0
unmeasured       : 0
coverage         : complete
loop_closure     : "the loop is closing"

the engine's OWN decay command, on the same state:
  10 concepts due · mean current recall 56%
```

The dashboard reported **100% recall, nothing unmeasured, loop closing** while ten concepts sat
at 56% and falling. That is *"survivorship bias with a progress bar"* — this block's own
docstring — reproduced **inside the block written to prevent it**. The `coverage` guard could
not see it either: coverage counts *reviews*, and every review here bucketed perfectly.

**Fixed.** The denominator is now everything **past due right now** (`past_due_now`), with
`never_reviewed` kept as a sub-count. A node past due *now* has, by definition, not been
retrieved since it came due — whatever its history. And the debt now reaches the **narrator**,
not just a nested key: every `read` string carries it, because a `read` of *"measured over 10
retrievals"* while ten concepts rot is precisely the lie.

### 2. HIGH — the normal settle path destroyed a second, ungraded production

v0.6.0 fixed `drop_stash(topic, node)` on the rare **idempotent no-op** branch and left it live
on the branch that runs on **every single settle**. `stash add` appends without deduping on
node, so a node can legitimately hold two productions (a re-attempt, a park-and-resume, a slow
assessor). Settling the first drained *both*:

```
stash before : [P1, P2 — second attempt, never graded]
settle P1    -> stash after: []          P2 is gone. Never assessed, never a receipt.
```

The exact data loss that was fixed on the rare path, still live on the common one. **Fixed:**
a settle drains only its own `sid`; the legacy sid-less `rate` path keeps its self-drain.

### 3. MEDIUM — `kind` was unvalidated, and the two entry points disagreed on its default

`rate --kind` defaulted to `"review"`; `cmd_receipt` defaulted to `"encode"`; neither validated
it. Every v0.6 metric keys off the exact literal `"review"`, so a typo'd or invented kind is
permanently invisible to `loop_closure`, every retention bucket, calibration and `stats.reviews`
— and **unfixable**, because receipts are append-only. This was also the root cause of v0.6.1.
**Fixed:** a `KINDS` constant, `choices=` on the flag, and validation in `validate_item`, so a
bad batch dies before any write.

### 4. LOW
- A backward clock step could stamp a **negative** `days_since_encode` into an append-only
  receipt, permanently. Clamped to ≥ 0.
- `commit --clear --cue X --action Y` silently *cleared* (the `elif` made the set-branch
  unreachable). Now refused.

### Engine (selftest 120 → 126)

Six new checks, every one **mutation-tested** — reverted to the broken behaviour to confirm it
actually fails. Verified against the founder's real state: all numbers unchanged and now
*mutually consistent* (`retention` and `decay` both report 70%), state byte-identical.

No schema migration. `retention.unmeasured.past_due_never_reviewed` is replaced by
`past_due_now` + `never_reviewed`; nothing outside this repo consumed it (v0.6 is hours old).

## 0.6.1 — 2026-07-11 · loop_closure could lie in the one direction that matters

A defect in v0.6.0, found by an independent reviewer after release. It is small, it is
narrow, and it is exactly the kind this release cannot tolerate — **the metric built to say
*"you never came back"* could say the opposite.**

`rate`'s `--kind` argparse default is `"review"`. The skills always pass an explicit
`--kind`, so the documented flows are unaffected — but a bare CLI `rate --topic t --node a
--rating good` writes that node's **only** receipt as `kind: review`. `_by_node` then treated
that single receipt as *both* the node's day-0 encoding event *and* a retention test, so:

```
loop_closure:  1 of 1  ·  rate 1.0  ·  "the loop is closing"
```

…for a learner who had **never come back once**. `retention` likewise counted it as a day-0
retrieval.

**The fix is a principle, not a patch: a node's FIRST receipt is its encoding event, whatever
it happens to be labelled.** There was no prior memory to retain, so a first exposure cannot
be a retention test and must never count toward `loop_closure` or a retention bucket. A
genuine second retrieval still closes the loop, exactly as before.

Wrong numbers are the only bug class this project is not allowed to ship. A number that is
wrong in the *flattering* direction — telling a learner their loop is closing when they have
abandoned it — is the worst instance of it.

### Engine (selftest 119 → 120)
- `_by_node`: the first receipt is never appended to a node's `reviews` list. Covered by a
  selftest that asserts both directions (a once-touched node reads `NEVER CLOSED`; a real
  second retrieval reads `1.0`), and mutation-tested to confirm it fails without the fix.

No schema change, no migration, no default change.

## 0.6.0 — 2026-07-11 · the loop closes

Engram has been an excellent **encoding** machine bolted to a **retention** machine that
never ran. This release is about the second half.

The finding that forced it, found by reading the author's own state: on 2026-07-05 he ran a
45-minute `/learn` on transformer internals. The architect built a 13-node DAG, the tutor ran
generation-first dialogue, the smith built an explorable, the blind assessor graded six
productions and honestly rounded most down to `partial`. Seven concepts encoded, seven review
dates booked. **Then nobody came back.** Six days later: zero reviews, zero streak, seven items
overdue, one session in the log — ever. Meanwhile 501 people starred the repo.

Run Engram's own FSRS curve over Engram's own state and it says: those seven decay to **2.7 of 7
over the next 30 days untouched, or hold at 5.6 of 7 if the four-minute review happens** — a
difference of 2.9 concepts. The engine could always compute both numbers. Its entire ambient
surface, on the sixth day of a memory dying on schedule, was `[engram] 7 reviews due`.

This is not a story about a lazy user. It is the product's own failure mode executing perfectly
on the person most invested in it, which makes it architectural rather than personal.

Three gaps, each confirmed by reading the code rather than the docs:

- **The north star was never implemented.** `docs/04` named "7-day and 30-day retention on
  scheduled reviews" the north star in Phase 0. `grep` found no such metric. `stats` bucketed by
  memory *strength*, never elapsed *time*. **Naming a metric is not measuring it.**
- **Adherence was invisible.** No signal anywhere for *"was this encoded concept ever reviewed?"*
  The system could not see its own binding constraint.
- **`receipt --file` was not idempotent** (issue #3) — a crash-retry between `receipt` and
  `stash clear` double-counted reps permanently.

### Engine (selftest 86 → 119)

- **`adherence`** — the funnel Engram never looked at: `loop_closure` (encoded → came due →
  actually reviewed), `return` (session cadence, days since last), `funnel` (topic → encoded →
  due → reviewed → retained@30d). Pure read over data already on disk; no schema change.
  **`loop_closure` is the binding-constraint number: the value a learning system produces is
  Return × Encoding × Retention × Transfer, and those terms multiply — a perfect encoder with
  zero return is worth exactly zero.**
- **`retention`** — the north star, finally computed. Recall bucketed by each review's own
  days-since-first-encode, in windows that **partition [0, ∞)** so no review is ever dropped:
  `early` 0–3 (still re-encoding — reported, *never* pooled into a retention claim) · `7d` 4–14 ·
  **`30d` 15–59 (the headline)** · `90d` 60–179 · `180d+`. Ships two honesty guards:
  - **`unmeasured`** — the concepts that came due and were *never reviewed*. Their recall is
    **unknown, not absent**, and FSRS projects it. A retention figure computed only over
    *completed* reviews silently drops exactly the concepts the learner abandoned — survivorship
    bias with a progress bar. The engine refuses to report one without the other.
  - **`coverage`** — `reviews_bucketed / reviews_total`, which must be 1.0. This exists because
    the *first* cut of this feature used disjoint windows (5–10 / 25–40 / 80–110) and **the live
    test caught a real day-11 review falling into a gap and vanishing** — `retention` cheerfully
    reported "no reviews yet" with a review sitting on disk. Under real FSRS intervals (~4d, ~12d,
    ~30d, ~70d) most reviews would have landed in those holes and the north star would have been
    computed on an arbitrary subset of the evidence. A metric that quietly discards data is worse
    than no metric. Now selftested by sweeping 19 elapsed-day values across the full range.
- **`decay`** — what is dying and what N minutes would save, in real FSRS numbers. Both arms
  measured over the *same future window*, so it is a comparison rather than a rhetorical device.
  The `due` payload now carries `last`, so current recall is computed from the learner's **actual**
  last retrieval rather than reconstructed from `interval_for(s, 0.90) + overdue` — a
  reconstruction that silently breaks for anyone who moved `desired_retention` (measured: **3.3
  percentage points of *overstated* decay** at 0.97) and breaks in the one direction an honesty
  feature is not permitted to err in: alarming the learner.
- **`commit`** — the learner's implementation intention, in their own words (Gollwitzer & Sheeran
  2006: 94 tests, N > 8,000, **d = 0.65**, robust to publication-bias correction). Stored because
  they said it, shown back at the moment it names, **never enforced**.
- **`sid` — receipts are idempotent** (closes #3). The stash id rides stash → assessor → receipt;
  `apply_item` refuses one already on disk. Additive: a receipt without a `sid` applies exactly as
  in v0.5.
- **`days_since_encode`** stamped on every receipt — makes the north star a one-pass query.
- **Fixed a latent race, present since v0.5:** `report` and `doctor` called `load_model()`, which
  *persists* a self-heal — while holding no lock. An unlocked read could flush a stale snapshot
  over a concurrent locked mutator, silently reverting a `refit`. New `read_model()` heals in
  memory and never writes. Covered by a selftest that fails without it.
- **Receipt log is cached per process, keyed by absolute path.** A batch settle re-read the whole
  topic log once *per item* — measured at 1.85s for a 60-item settle against a 10k-line log, now
  0.19s. The cache is keyed by path (never by topic alone, or a second `ENGRAM_HOME` would read
  the first one's receipts) and kept in sync on append, so a duplicate `sid` appearing later in
  the *same* batch is still caught. Both properties have selftests.
- **Read paths now degrade instead of bricking — a whole class of crashes, several pre-existing.**
  Fuzzing 3,000 randomized garbage states found **259 unhandled crashes in the first 300**. A
  hand-edited state file can be perfectly valid JSON with the *wrong types*: `nodes` as a string,
  `fsrs` as a list, an unhashable `topic`, a `rating` that is a dict — and every one of those
  raised `TypeError`/`AttributeError` and took `stats` down with it, and therefore `/coach`.
  Several predate this release (`compute_momentum` since v0.4, `due_items` and `compute_streak`
  since v0.1, `_outcome` since v0.3, `compute_modality` since v0.5); v0.6 *widened* the blast
  radius by making `stats` call `adherence` and `retention` too. The fix is one gate, not twenty
  patches: **`iter_graphs` now validates the graph's shape** and skips what is structurally
  unusable, because every read path funnels through it. `doctor` still reads graphs raw — it is
  the thing that *reports* corruption, and it must never die of what it is there to find.
  **Now 0 crashes / 3,000 states**, locked in by a selftest that feeds every read path a
  deliberately type-corrupt state and demands they all return.

### What the adversarial review caught that the tests, the live test, and the dogfood all missed

Protocol step 4.5 earned its place again. **Nine defects behind a green selftest, an exhaustive
live test, and a passing agent dogfood** — and the worst of them was one the dogfood had actively
*certified*:

- **Issue #3 was not actually fixed.** The `sid` never survived the assessor, because
  `agents/engram-assessor.md` declares a *strict* output schema that never mentioned it. The
  guard was dead code in the shipped pipeline. **The dogfood "passed" only because the prompt
  written for it told the assessor to pass the field through — an instruction the real `/learn`
  skill never gives.** A test that hands the subject the answer is not a test. The `sid` is now
  part of the assessor's contract (Claude *and* Codex ports), `/learn` step 4 checks it came back
  before applying, and the round-trip has been re-verified with the real agent and **no hint**.
- **The idempotent "no-op" was a data-loss bug.** It called `drop_stash(topic, node)`, which
  drains *every* stash entry for that node — so a crash-retry would silently destroy a second,
  newer, never-graded production. The guard written to prevent corruption would have corrupted.
  Now drops only its own `sid`.
- **`decay --topic <unknown>` returned a confident false all-clear** ("nothing to lose") instead
  of erroring. From a command whose entire job is honest accounting, that is the worst available
  failure mode. It now refuses.
- **`decay` overstated its own headline.** The benefit arm simulated reviewing *every encoded
  node* while pricing `minutes` from the *due queue only*. The not-yet-due nodes now keep their
  own curve in both arms — you are quoted exactly what those minutes buy.
- **The `coverage` guard was inert.** It was computed, stored in a nested key, and read by
  nobody — so the anti-data-loss check could not actually prevent the regression it existed for.
  An incomplete partition now hijacks `read` with **UNTRUSTWORTHY** in the one field a narrator
  is guaranteed to see.
- **Two contradictory definitions of "retained at 30 days" shipped in the same payload** —
  `funnel.nodes_retained_30d` used `>= 25` days while `retention`'s 30d bucket is `[15, 59]`.
  One definition now, from one source.
- **A receipt with a missing `ts` sorted first** and became a node's day-0 anchor, poisoning
  every elapsed-day metric downstream. Broken timestamps now sort last.
- **`median_gap_days` was not a median** (it took the upper element on even-length lists).
- **The dashboard never showed any of it.** `/coach`'s HTML still headlined a strength-bucketed
  retention with no `unmeasured` denominator. It now opens with `loop_closure` and states the
  concepts that came due and were never reviewed.

Each has a selftest, and each selftest was **mutation-tested** — reverted to the broken behavior
to confirm it actually fails. Two first drafts turned out to be theatre (one asserted a constant
instead of a behavior; one had a fixture where the old and new definitions coincided by
coincidence) and were rebuilt until the regression is genuinely caught.

### Behavior

- **The ambient hook now says what the decay costs** — but only as a *return event*: it fires on a
  never-closed loop or after a real absence, never per-session. *"Those 7 sit at ~70% recall and
  still falling · 4 min now is the difference between keeping them and re-learning them."*
  **Information, never pressure** (`docs/05` P13). No should, no scold, and
  `settings.decay_notice = "off"` silences it entirely.
- **`/review`** states the honest number once on return — *after* amnesty, *before* the capped
  offer. The order is: nothing is owed → here is what it costs → here is a two-minute path.
  Reversed, it is a debt collector.
- **`/learn` books the return** — one plain question at the close, their words, stored via
  `commit`, never enforced, never asked twice.
- **`/coach` reports `loop_closure` FIRST.** When it is zero it says so plainly and stops: there
  is no point narrating calibration over a loop that has never run.

### Docs

- **`docs/07-the-measured-loop.md`** — the frontier audit. Learning rate is close to a category
  error (Koedinger 2023 *PNAS*, replicated EDM 2024: intercept variance dwarfs slope variance —
  you cannot make people climb faster, only give them more climbs; the 2026 re-analysis contesting
  the *magnitude* is recorded too). LLM-as-judge is **"reliability without validity"** (κ ≈
  0.38–0.51 vs humans; raw agreement overstates chance-corrected κ by 34–41 points; **high
  self-consistency + high bias is the documented failure mode** — precisely what a skeptic-prompted
  assessor selects for). Pan & Rickard 2018: retrieval transfers at d = 0.40, but **d = 0.28 when
  the response format differs vs d = 0.58 when it matches** — a quantified critique of verbal-only
  review for doing-goals. The n-of-1 machinery is **underpowered ~2.5×**.
- **`docs/08-vision.md`** — the objective function, which metrics are traps (confidence and joy
  both are), and the final state: Tutor → Instrument → Commons. Adds **Article 11: the system's
  success is measured by what the learner can do without it.**
- **`docs/09-target-architecture.md`** · **`docs/10-roadmap-to-1.0.md`** — schemas, invariants, and
  v0.6 → v1.0 as executable work orders.
- `docs/04` marked complete and superseded.

### Migration

None. Every field is additive and self-heals: a v0.5 (or v0.3) learner model gains
`commitment: null` and `decay_notice: "on"` on next load and behaves exactly as before. Receipts
without a `sid` apply as they always did. Nothing to migrate, nothing to delete.

## 0.5.2 — 2026-07-11 · confidence before the verdict, not after

Reported from real use (#4 — thank you, @kosh-jelly): at VERIFY the tutor praised the
answer — *"that's a complete, well-integrated answer…"* — and **then** fired the
confidence picker. A sureness collected after the learner has been told they nailed it
is not sureness; it is an echo of the verdict. Confidence-before-feedback exists to
measure calibration and to catch high-confidence errors for hypercorrection — both die
the instant any signal of correctness reaches the learner first.

The intent was never in doubt: the picker itself asks *"before I show the answer."* The
prose had a seam. The gate was worded around the **reveal** ("before you reveal or
grade", "no canonical answer until confidence"), and `/learn`'s VERIFY step granted
*"immediate content feedback is yours to give"* right beside it. So the model did what a
careful reading allowed — withheld the canonical answer, kept the picker's framing
honest, and let the *evaluation* through. The pretest step one screen up already had the
tight wording ("before saying anything about correctness"); VERIFY did not.

### Behavior (prose only; selftest unchanged, 86 → 86)
- **`/learn` VERIFY** (`skills/learn/SKILL.md`): the pick fires **first**, gated on
  "before you say a word about correctness," with the exact failure banned by example
  (*"that's complete," "close," "nice"*). "Immediate content feedback is yours to give"
  moved to **after** the pick; the pick is now also stated to precede the stash (its
  value is a stash field, so it cannot come later).
- **Confidence-integrity rule** (`skills/_shared/dialogue-grammar.md`): "feedback"
  redefined as *any* signal of correctness — approving tone included — not just the
  shown answer.
- **Anti-sycophancy oath** (same file, hard rules): the gate broadened from "no
  canonical answer until confidence" to "no verdict — not even a bare *'that's right'* —
  until confidence is collected."
- **Terse-production move** (same file): at VERIFY the *"credit what's there"* step now
  waits until after the confidence pick — closing the one path (a fragment answer) where
  the sharpened rule would otherwise still leak a correctness signal first. Found by this
  release's own adversarial review, not in the wild.

No engine touched: whether the tutor asks in the right order is a dialogue property,
provable only by a live VERIFY, not a selftest. The old order didn't merely mis-sequence
the question — it recorded a corrupted "Certain" as real calibration data. Putting the
pick first is the fix; there is no unit test that can stand in for using it.

## 0.5.1 — 2026-07-10 · the modality confound, said out loud

Found by doing what the release protocol asks and 0.5.0 skipped: a real `/learn`
session, driven end to end with the actual agents. The pipeline held up — the
curriculum architect tagged every node's visual affordance, the artifact-smith built a
Contract-v2 explorable for the threshold node and registered it unprompted, the blind
assessor rounded a shaky production down to `partial`, and the receipt carried its
medium stamp. But the session exposed something no code review could: **the medium
comparison in `stats.modality` is confounded by construction.**

Explorables are routed to threshold and high-affordance concepts *on purpose* — that
is the whole content rule. So the dialogue arm fills with the remaining material, and
the two arms never differ only in medium. Under `threshold-only` the explorable arm is
exactly the topic's hardest, portal concepts. A lower explorable-arm recall may mean
nothing more than that explorables were spent on the hard things.

The number was already labeled suggestive. That was not enough: a coach narrating from
the JSON could report it as a clean result. So the caveat now travels *with* the data.

### Engine (selftest 85 → 86)
- `stats.modality` gains a **`caveat`** field, present in every read state
  (`insufficient-data` included), stating that the arms are not randomized and the
  comparison carries medium *and* material. Covered by a new selftest — a narrator
  reading only this JSON cannot see the verdict without seeing why it is soft.
- The dashboard's "Encoding medium" section prints the caveat beside the bars, so a
  learner reading the HTML alone gets the same warning.

### Behavior
- `/coach` **must voice** the caveat whenever it reports the medium yield, and is
  explicitly forbidden from presenting the number as proof the medium works or fails.
  Sample narration updated to model the honest version.

### Theory
- `docs/06-visual-encoding.md` open question 2 now documents the confound in full,
  including why it *cannot* be fixed by randomizing arms without violating the content
  rule the document itself establishes — and names the honest form of the question
  (a randomized `experiment` within one affordance class; future work).

### Examples
- `examples/pid-error-feedback-loop.html` — the explorable the artifact-smith actually
  generated in that session (drone altitude hold; a wind gust drives the error, the
  throttle answers), now hosted next to the hand-authored reference implementation.
  Its header says which is which, because "the kind of thing Engram builds" and "the
  thing Engram built" are not the same claim.

No schema change, no default change, nothing to migrate.

## 0.5.0 — 2026-07-10 · the visual-encoding layer — explorables audited, adaptive, and measured

The explorable engine grows up. Until now, interactive explorables fired only on
threshold nodes — which conflated *importance* with *visualizability* — the graph never
recorded which artifacts existed (the smith wrote files nothing tracked), and nothing
measured whether the medium actually works for a given learner. v0.5 fixes all three,
under a new adversarially-verified evidence base.

### Theory
- **New: `docs/06-visual-encoding.md`** — the visual-encoding audit, built the same way
  as docs/05: a fan-out research pass (27 primary sources, 135 claims extracted, the 25
  load-bearing ones each verified by three refute-first voters; 23 survived, 2 killed).
  Adds **Pillar 15 — the guided manipulable**: manipulable models carry the largest
  verified interactivity effect (simulations g+ = 0.62), but *guidance inside the
  artifact is the active ingredient* (scaffolded versions of the same simulation
  g+ = 0.60; learner control per se g = 0.05 ≈ nothing; unassisted discovery loses,
  d = −0.38), the payoff concentrates where the dynamics ARE the content
  (representational d = 0.40 vs decorative ≈ −0.05), and expertise reversal is a
  confirmed disordinal crossover (+0.505 novices / −0.428 knowledgeable, Tetzlaff 2025).
  Two refuted claims are recorded as do-not-build-on; four areas that produced no
  verifiable evidence (visual retrieval formats, n-of-1 medium methodology,
  preference-engagement value, LLM-artifact efficacy) are stated as **open questions**
  with deliberately conservative design stances.
- **Explorable Contract v2** (same seven clauses, sharpened by the audit): the
  manipulable is now explicitly *guided* — predict → act → **explain** micro-cycle
  (self-explanation g = 0.46), content-relevant degrees of freedom only, a **worked
  drive** gates the model at novice scaffold (worked examples g = 0.48; "provide
  assistance when in doubt"); no text over motion; learner advances *between* segments,
  dynamics run themselves *within* one; registration is part of clause 7. New widget:
  **feature-space navigator** (several sliders, each a dimension; one holistic output
  morphing live — the founder's draggable-face moment, now in the vocabulary).

### Engine (`scripts/engram.py`) — selftest 70 → 85
- **`artifact set|clear|list`** — explorable registration is now engine-owned like
  `fsrs`/`state`: the file must exist, paths under the state dir are stored
  home-relative, payload-supplied `artifact` values are stripped at `add-topic`, and
  registrations survive `--replace` alongside the schedule. (Fixes a real gap: built
  artifacts were invisible to the graph, so regeneration tracking and Contract clause 7
  had no data trail.)
- **Medium-stamped receipts** — every `rate`/`receipt` stamps whether the node had a
  registered explorable *at grading time*, so evidence of the encoding medium can never
  be rewritten retroactively.
- **`stats.modality`** — the honest per-learner answer to "do explorables work for ME":
  first-review recall of explorable-encoded vs dialogue-only nodes, one datum per node,
  ≥6 per arm (the n-of-1 experiment floor) before any verdict; reads
  `explorable-encoded ahead / dialogue-encoded ahead / indistinguishable /
  insufficient-data`. Also rendered as an "Encoding medium" dashboard section. This is
  the instrument the Phase-2 exit criterion (docs/04) always called for.
- **`visuals eager|threshold|off|status`** — the discoverable dial over
  `settings.artifacts`, sibling to `focus`. `eager` extends explorables beyond threshold
  nodes to any node whose *content* declares high visual affordance. Default remains
  `threshold-only`: existing users see zero behavior change.
- **`viz` node field** — the curriculum architect now declares each node's visual
  affordance (`affordance high|some|none`, `kind`, one-line manipulation `hook`);
  the engine stores it opaquely (object kept, garbage dropped with a warning).
- `due` payload now carries an `artifact` presence flag (review's re-encode path reads
  it); `doctor` notes unregistered artifact files with the exact fix command (non-failing)
  and fails dangling registrations.

### Behavior (skills + agents; defaults unchanged)
- `/learn`: explorables are now **content-triggered and learner-dialed** — threshold
  nodes as before; at `visuals eager`, also `viz.affordance: high` nodes; an explicit
  "make it visual" builds for any node at any level (autonomy override, same shape as
  "just tell me"). One **ask-once-per-topic** offer when a high-affordance node meets the
  default setting (arrow-key; "always" sets `visuals eager` with consent echoed back).
  The smith now runs **in the background** while the dialogue beats continue, registers
  what it builds, and hand-off is an arrow-key choice (open it now / homework — homework
  is the Sprint default; the two-minute floor outranks the medium).
- `/review`: the second-lapse re-encode move now knows whether an explorable already
  exists (regenerate it differently) or not (offer to build one) — background spawn,
  hand-off at the close, never mid-queue.
- `/coach`: narrates the medium comparison when it has a verdict, with its n and the
  explicit honesty that n-of-1 medium measurement is suggestive telemetry, not settled
  methodology; offers the matching `visuals` move arrow-key style, applied only on yes.
- curriculum-architect (both platforms): declares `viz` per node with an evidence leash —
  a false `high` is worse than a false `none`, because decorative interactivity reverses
  the effect (≈ −0.05).
- artifact-smith (both platforms): consumes `viz.kind`/`viz.hook`, applies the novice
  worked-drive gate, registers after writing, echoes the registration JSON in its report.

### Hardening (adversarial review before release — 10 confirmed findings, all fixed)
- **State mutex.** Every state-mutating command now serializes on an advisory
  lockfile (`.engram.lock`; stale locks broken after 60s). The new background
  artifact-smith registering while the tutor rates on the same topic was a
  last-writer-wins race on the whole-file graph write — it could silently revert
  a just-graded node's schedule or drop a fresh registration.
- **The `valid_artifact` gate.** Receipt stamping, the due-payload flag, and
  `--replace` carry-forward now all require a non-empty string whose file exists.
  v0.4's `add-topic` silently kept payload-supplied artifact strings; without the
  gate those phantoms would stamp append-only receipts into the wrong modality arm
  forever. Registration also now survives a corrupt `fsrs` on restructure (it was
  being destroyed), and phantoms die at `--replace` instead of living on.
- **doctor** reports all artifact problems (unregistered, dangling, garbage-typed)
  as *notes* with pasteable shell-quoted fix commands — an upgrade must not flip
  doctor red for v0.4's own leniency.
- **Input hardening:** `artifact list` degrades gracefully on nodeless graphs and
  lists registrations on nodes outside `order`; `visuals status` reports a
  hand-edited non-string setting instead of crashing; `add-topic` rejects a
  non-object node with a clean error.
- README's `visuals` CLI row described the levels in swapped order (taught
  `eager` = default) — fixed. Selftest 79 → 85 across the fixes.

### Packaging
- Version 0.5.0 everywhere (plugin.json ×2, badges); README: science point 6, visual
  FAQ entry, CLI table rows for `visuals`/`artifact`, docs table row for docs/06,
  Discord community badge (discord.gg/temm1e); INSTALL-CODEX selftest count 85/85.

Existing users: `claude plugin marketplace update engram && claude plugin update
engram@engram`, then restart Claude Code. A v0.4 learner model self-heals; nothing
about your schedule, receipts, or defaults changes until you touch the `visuals` dial.
Optional one-time heal: `doctor` will point out any explorable built before 0.5 so you
can register it (`artifact set …`) and start counting it in the medium comparison.

## 0.4.4 — 2026-07-09 · fix the confidence picker not firing (contradiction in the oath)

0.4.3 added the imperative picker instruction but a stale line survived in the most-obeyed
section — the anti-sycophancy **oath** still read *"Confidence in the same breath as the
probe"*, which tells the tutor to ask for a number inline (the "Answer + 0-100" a user saw
on 0.4.3). It overrode the new rule. The ⚠ section and beats were updated in 0.4.2/0.4.3;
this oath line was missed.

### Behavior (dialogue grammar; no engine change)
- The oath line is replaced with **"Confidence is a picker, never a typed number"**, and
  the **reveal is now gated on it**: no canonical answer until confidence is collected via
  `AskUserQuestion` (or a volunteered number, or dismissed → null). Gating on the reveal —
  an action the tutor always performs — is the most reliable way to make the tool call fire,
  versus a standalone "please call the picker".
- Removed every remaining "answer + 0–100 / gut number" cue from probe-prompt guidance.

## 0.4.3 — 2026-07-09 · make the confidence picker actually fire

0.4.2 described the confidence picker but left the instruction too soft and framed it
as a fallback *after* a text ask — so the tutor kept asking for a typed number instead
of showing the arrow-key box. Fixed by adopting the production-grade pattern: an
imperative MUST, the explicit `AskUserQuestion(...)` call inlined in the dialogue
grammar, and no "give a number" wording left in any probe prompt.

### Behavior (grammar + skills; no engine change)
- The four-band Confidence picker (Certain 90 / Pretty sure 70 / Half unsure 50 /
  Just guessing 25) is now the **primary, mandatory** way confidence is collected —
  before the reveal, every item — with the tool's built-in "Other" for an exact number
  or skip (→ null). The tutor only skips the picker if the learner volunteered a number
  unprompted. Applied to `/learn` encode, the pretest, and `/review`.
- Verified live: the picker renders and a selection round-trips to its number.

## 0.4.2 — 2026-07-09 · confidence UX — pick, don't type

Collecting the 0–100 gut-confidence (which powers calibration and hypercorrection —
kept, because it earns its place) used to force the learner to *type a number* every
item, then nagged with a text re-ask if they skipped it. Friction the data can't afford.

### Behavior (dialogue grammar + skills; no engine change)
- **Confidence is now a one-tap pick, not a typed number.** It's offered as an optional
  add-on in the same breath as the probe (type `…, about 70` if you like). If you give no
  number, a picker (AskUserQuestion) appears **before the reveal** with four bands —
  Certain (90) / Pretty sure (70) / Half unsure (50) / Just guessing (25), plus Other for
  an exact number or skip. Dismiss → `null`, still never estimated.
- **Guardrails made explicit** so the convenience stays honest and bugless: the picker
  fires *before* feedback every time (confidence-after-answer is discarded as null); a
  picked band is the learner's own stated confidence, not an invented one; and confidence
  is *metadata, not knowledge*, so a menu is allowed there while the probe stays open
  free-recall. Applied consistently across `/learn` encode, the pretest, and `/review`.

## 0.4.1 — 2026-07-09 · discoverable Focus mode + release hygiene

Follow-up to 0.4.0: the ADHD Focus profile shipped but was undiscoverable (no README,
no clean command), and one toggle path was buggy.

### Engine
- **`focus on|off|status` command** — a first-class, discoverable wrapper over
  `model --set settings.profile=...`. Turning it on flips the ADHD profile (Sprint
  default, competence growth surfaced every review, always-on amnesty); `status` reports
  without changing anything.
- **Bug fix: `model --set <key>=null` now clears to real `None`**, not the string
  `"null"` — so turning Focus (or any nullable setting) *off* actually works. `null`/`none`
  (any case) are recognized alongside the existing int/float/bool casts.
- Selftests 68 -> **70** (the `focus` on/off round-trip; the `=null` clear).

### Docs
- **README now documents Focus mode** (FAQ entry + CLI table row) with both activation
  paths: say "I have ADHD, turn on focus mode" in `/learn`/`/coach`, or run `focus on`.
  This omission is what prompted the fix — a shipped feature nobody can find isn't shipped.
- **`RELEASE_PROTOCOL.md`** added at root: the repeatable release checklist (version-bump
  locations, selftest gate, a live dogfood test, and the merge → tag → `gh release` steps),
  written after v0.4.0 shipped with its files bumped but no git tag / release cut.
- `INSTALL-CODEX.md` selftest count corrected (68 -> 70).

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
