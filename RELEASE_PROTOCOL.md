# Release Protocol

The repeatable checklist for shipping an Engram version. Follow every step, in order.

**Every gate in this document was added because it caught a real bug that the gate before it
could not see.** None of them is theoretical, and none of them is optional. The three that
people most want to skip — the fuzz, the user session, the post-release review — are the three
that found bugs in code that had already shipped.

**Rule of thumb for the number** (semver): user-visible feature → **minor** (`0.7.0`); bug fix,
doc, or polish → **patch** (`0.6.3`); a breaking change to state schema or the skill/CLI contract
→ **major**. When unsure, patch. A process-doc-only change (like this file) ships no version.

---

## The bug classes this repo cannot ship

Read this before you read anything else. Every gate below exists to catch one of these, and the
ordering of the list is the ordering of the harm.

| # | Class | Why it's fatal here | The one that taught us |
|---|---|---|---|
| **1** | **A wrong number — especially one that is wrong in the *flattering* direction** | Engram's entire value is that its numbers are true. A crash gets fixed because you see it. **A flattering number gets believed.** | `loop_closure` reported `1.0 · "the loop is closing"` for a learner who had never come back once (v0.6.1). `retention` reported *"100% recall, 0 unmeasured"* while the engine's own `decay` put the same concepts at **56% and falling** (v0.6.2). |
| **2** | **Silent data loss** | The learner's production is the only thing they actually made. Destroying it, silently, is unforgivable. | The normal settle path called `drop_stash(topic, node)` — draining **every** entry for that node — so settling one production destroyed a second, never-graded one (v0.6.2). **And v0.7: a new `die()` inside `apply_item` that the batch pre-flight didn't screen for wrote item 1's receipt and then aborted — an append-only log, torn in half.** |
| **3** | **Dead code shipped as a feature** | The CHANGELOG becomes a lie and the guard you're relying on isn't there. | Issue #3's `sid` idempotency guard never fired in production: the assessor's strict output schema didn't carry `sid`, so `apply_item` never saw one (v0.6.0 → fixed in the same release only because a review caught it). |
| **4** | **A guard nobody reads** | A tripwire that nothing consumes cannot trip. | `retention.coverage` was computed, stored in a nested key, and read by no runtime surface. **And v0.7: the grader-unvalidated stamp reached the JSON, the CLI and the skill — and was thrown away by the HTML dashboard, the one surface where a number is most believed.** |
| **5** | **A metric that silently drops evidence** | Survivorship bias with a progress bar. | Disjoint retention windows swallowed a real day-11 review while reporting *"no reviews yet"*. `unmeasured` exempted any node reviewed even once, ever. |
| **6** | **A read path that bricks** | `doctor` reports corruption; `stats` is not allowed to *die* of it. | 259 unhandled crashes in 300 fuzzed states. Several predated the release that surfaced them. **And 447 more, in SHIPPED code, the day someone finally fuzzed `next` — the command `/learn` calls every session.** |
| **7** | **A LABEL that lies** ⚠ NEW | The number is right and the reader is still deceived. This is bug class #1 wearing a disguise, and it is *harder* to see, because the arithmetic checks out. | v0.6.4: `retention` said 56% and `decay` said 66% — **both correct, ten points apart, and a user could not tell which to believe.** v0.7: `by_case_type` reported `n: 30` for a case type holding **ten items** (30 was judgments). v0.7: the audit stamped `gold_source: "bundled"` onto a run whose ground truth had been **locally re-adjudicated** — *"a provenance field that lies is worse than none, because it is believed."* |

> **The single sentence to keep:** *a number that is wrong in the direction that reassures the
> learner is worse than a crash.*
>
> **And its corollary, earned in v0.7:** *a number whose LABEL is wrong is a wrong number.* The
> arithmetic being right is not a defence — nobody reads the arithmetic.

---

## 0 · Preconditions

```bash
cd ~/Documents/Github/engram
git checkout -b release/vX.Y.Z          # never work on main directly
python3 scripts/engram.py selftest      # must already be green before you start
```

The default branch is what a fresh `claude plugin install` pulls, so it must never be
half-broken. Decide the version number now; it appears in several files (step 2).

## 1 · Land the work

Make the change. **If it touches `scripts/engram.py`, it MUST be covered by a new `selftest`
check** — no engine behavior ships untested. Update the affected docs and skill files in the
same branch.

**If it adds or changes a NUMBER, go read §4.8 before you write the code.** That section is the
spec, not the audit.

## 2 · Bump the version — EVERY location

The single most error-prone step. There is no central version constant; these must move together.

```bash
grep -rnE '"version"|version-[0-9]|selftest-[0-9]|[0-9]+ checks|[0-9]+/[0-9]+ checks' \
  .claude-plugin .codex-plugin README.md INSTALL-CODEX.md
```

| File | What to change |
|---|---|
| `.claude-plugin/plugin.json` | `"version"` |
| `.codex-plugin/plugin.json` | `"version"` (lockstep with the Claude one) |
| `scripts/engram.py` | `ENGRAM_VERSION` — **a selftest pins it to plugin.json**, so a missed bump goes RED (it caught v1.0.1) |
| `README.md` | version badge (`badge/version-X.Y.Z` **and** its `alt`) |
| `README.md` | selftest badge (`badge/selftest-N%2FN`) **if the count changed** |
| `README.md` | CLI table `selftest` row **if the count changed** |
| `INSTALL-CODEX.md` | selftest count comment **if the count changed** |

Re-run the grep after editing — **zero stale hits, or the badge lies.**

## 3 · Write the CHANGELOG

New section at the **top**:

```
## X.Y.Z — YYYY-MM-DD · <one-line theme>

<grouped: Theory / Engine / Behavior / Packaging. Trace each user-visible change to WHY.
 Note the selftest delta, e.g. "110 -> 119".>
```

**Write the bugs honestly, including the embarrassing ones.** The v0.6.2 entry says out loud
that survivorship bias was reproduced *inside the block written to prevent it*. That is the
entry a reader learns from. A CHANGELOG that only lists wins is marketing.

Release notes are generated from this section (step 6), so write it for a reader, not a git log.

---

# THE GATES

## 4 · The selftest gate

```bash
python3 scripts/engram.py selftest      # must end "N/N passed" — N == the badge
```

Red here stops the release. No exceptions.

**And then distrust it.** A green selftest means only that the checks you wrote pass. It says
nothing about the checks you didn't think to write, and — see next — nothing about whether the
checks you *did* write are real.

## 4.5 · Mutation-test every new check ⚠ NEW

**A check that still passes when you revert its fix is theatre.** Three of the checks written
during v0.6 were exactly that, and they looked identical to the real ones.

For each new check: revert the fix it guards, run the selftest, confirm **that specific check
fails**. Then restore.

```bash
cp scripts/engram.py /tmp/e.bak
# … revert ONE fix …
python3 scripts/engram.py selftest | grep "^FAIL"    # must name YOUR check
cp /tmp/e.bak scripts/engram.py
```

**The score so far: 3 fake checks in v0.6, 4 more in v0.7.** That rate is not going down, and
that is the actual lesson — *writing a check that proves nothing is the default outcome, and the
mutation test is the only thing that has ever caught one.*

The **four** ways a check turns out fake, all seen for real:

- **It asserts a constant, not a behavior.** `check(BUCKETS["30d"] == (15,59))` proves nothing;
  it just restates the source. Exercise the behavior — feed it a day-20 review and demand the
  funnel counts it.
- **The fixture makes old and new agree by coincidence.** One fixture had two nodes where the
  old (`>= 25`) and new (`[15,59]`) definitions *both* yielded 1. v0.7's coverage check used
  three **identical** runs — so the union and the intersection of graded sids were the same set,
  and swapping the honest denominator for the flattering one changed nothing. Build the fixture
  so the two definitions genuinely **diverge**, or the check cannot see the regression.
- **The assertion is weaker than the property.** ⚠ NEW. v0.7 asserted *"a 2-step grading error
  hurts more than a 1-step one"* to pin a **quadratic** weighting — which **linear** weights
  satisfy just as happily. Ask: *what else would also make this assertion true?* If anything
  would, you have tested nothing. (Pin an exact hand-computed value instead. And note that a
  *balanced* fixture would have been useless too: with equal marginals both schemes normalize to
  the same kappa.)
- **Another gate already covers it, so reverting the fix leaves it green.** ⚠ NEW. v0.7's
  raw-agreement check couldn't isolate the QWK floor, because its always-says-`recalled` grader
  also tripped the *bias* ceiling. Two of its dashboard checks passed with the fix reverted
  because a *different* element on the page happened to contain the string being grepped.
  **A check is only real if it fails when ITS OWN fix is reverted.** When several guards overlap,
  build a fixture where all the others are silent.

### ⚠ The special case: mutation-testing an ABSENCE check ⚠ NEW

Some checks assert something **is not there** — *"the engine has no network code"*, *"no
`subprocess`"*, *"no bare `n` key"*. **You cannot mutation-test those by breaking the detector.**
Setting `_net = []` makes the check vacuously true — which is *exactly what it already is* on a
clean codebase. It proves nothing at all.

> **For an absence check, the mutation must INTRODUCE THE THING.**

Add a real `import socket`. Add a real `os.system("curl …")`. Then demand the guard goes red.
v1.0's no-network guarantee is worth something only because four mutations do precisely that, on
every run of the suite, and the check catches all four.

**And a related trap, from the very same check:** the first draft **grepped its own source** for
the word `curl` — and found it, in its own comment and inside its own regex literal. **It failed on
itself.** The fix was to parse the **AST**, which cannot see a comment or a string and reports only
what the interpreter will actually execute.

> *If a structural guarantee can be defeated by a comment, it was never structural.*

## 4.6 · The adversarial review (never skip; green tests are not evidence)

```bash
/code-review high        # against `git diff main...release/vX.Y.Z`
```

Name the diff, the risk areas (concurrency, back-compat with older state, path handling, **and
every new number**), and say prose files matter only for cross-file consistency.

**Three rules learned the hard way:**

1. **A green selftest means nothing about the design.** This review found **10 confirmed defects
   behind 79 passing checks** (v0.5.0), and **9 behind 110** (v0.6.0) — including a concurrency
   race and a headline feature that was dead code.
2. **Never trust a review whose agents errored.** A run once died on a session limit (5 of 7
   agents failed) and cheerfully reported *"no findings survived verification."* **Check the
   failure list before you believe the verdict.**
3. **Feed the reviewer the shipped contract, not just the diff.** v0.6's `sid` guard was dead
   because the *assessor's agent spec* — a file not in the diff — didn't carry the field.
   A reviewer looking only at the diff cannot see that. Point it at the whole round-trip.

Every confirmed finding gets a fix **and** a check that fails without it (§4.5).

## 4.7 · The fuzz gate ⚠ NEW — read paths degrade, never brick

State files are **hand-editable JSON**, and a file can be perfectly valid JSON with the *wrong
types*: `nodes` as a string, `fsrs` as a list, an unhashable `topic`, a `rating` that is a dict.
Fuzzing found **259 unhandled crashes in the first 300 states** — and several predated the
release that surfaced them.

Throw randomized garbage at **every read command** and demand each one **returns**:

```python
# throwaway ENGRAM_HOME; randomize every field to every JSON type; 500+ states, 2+ seeds
for fn in (compute_stats, cmd_adherence, cmd_retention, cmd_decay, cmd_topics, cmd_due,
           cmd_next, cmd_topic_status,            # <- THE /learn SURFACE. v0.6 FORGOT IT.
           cmd_gold, cmd_grader_health,
           cmd_session_start, cmd_report, cmd_doctor):
    fn(...)          # SystemExit (a guarded die()) is fine. An exception is a defect.
```

> ### ⚠ ENUMERATE THE READ PATHS FROM THE CODE, NOT FROM MEMORY
>
> v0.6's list was written from the `/coach` surface — stats, adherence, retention, decay, report,
> doctor — and **simply forgot the `/learn` surface**. The first time anyone fuzzed `next` and
> `topic-status`, they found **447 crashes in 300 states, in already-shipped code**, and `next`
> is the command `/learn` calls at the **start of every session**. It had been broken since v0.1.
>
> **The list you write from memory is the list you already thought of.** Get it from the
> dispatch table:
>
> ```bash
> python3 - <<'PY'
> import re
> src = open("scripts/engram.py").read()
> block = re.search(r"handlers = \{(.+?)\n    \}", src, re.S).group(1)
> mutating = set(re.findall(r'"([\w-]+)"', re.search(r"mutating = \{(.+?)\}", src, re.S).group(1)))
> print(sorted(set(re.findall(r'"([\w-]+)":', block)) - mutating - {"selftest"}))
> PY
> ```
>
> Every name it prints is a read path. Every one of them goes in the fuzzer.
>
> **⚠ AND THEN THE AMENDMENT, because this rule had the same hole it was written to close.**
> The script above enumerates **commands**, and `experiment` is a *mutating* command — so its
> **read sub-actions** (`experiment status`, `experiment list`) never appeared in the list, and
> had never been fuzzed. The first time they were: **72 crashes in 600 states.**
>
> **A command with sub-actions has a read path PER SUB-ACTION.** Add every read-only sub-action
> by hand — the dispatch table cannot see them, and neither will you, unless you look:
>
> ```bash
> grep -nE 'args\.action ==|add_argument\("action"' scripts/engram.py
> ```

**The doctrine, and it is already written in `iter_graphs`' docstring:** aggregate/read-only
views must degrade gracefully — never brick. `doctor` is the thing that **reports** corruption
and must **never die of what it exists to find**.

Fix at the **gate**, not the call site. Twenty guards smeared across twenty functions is how
this bug class survives; one shape-check in `iter_graphs` is how it dies — **and then check that
the gate's TWIN has one too.** v0.6 hardened `iter_graphs` (every *aggregate* read) and left
`load_graph` (every *single-topic* read) with no shape check at all. **A gate is only a gate if
nothing routes around it.**

Target: **0 crashes / 500 states**. Lock it in with a selftest that feeds every read path a
deliberately type-corrupt state. And **re-fuzz after the release's last commit**, not before:
v0.7's own dashboard changes introduced 46 fresh crashes on garbage audit files, three gates
after the fuzz had already come back clean.

## 4.8 · The numbers audit ⚠ NEW — the most important gate in this file

**This is the gate that exists for bug class #1**, and it is the one this repo most needs,
because Engram's entire value proposition is that its numbers are true.

For **every number the release adds or changes**, answer all five in writing:

### 1. Is it cross-consistent with every other number the engine computes?

The engine has several ways to say related things. **They must agree.** In v0.6.2 they did not:

```
retention  →  "measured over 10 retrievals · 100% recall · unmeasured 0"
decay      →  "10 concepts due · mean current recall 56%"
```

Two commands, one state, contradictory stories, shipped. **Nobody had ever run them side by side.**

> **Do it now.** Build one state, run every command that touches the new number, and put their
> outputs next to each other. If any two disagree, one of them is lying and you do not yet know
> which.

### 2. Which direction does it fail in?

Enumerate the ways it can be wrong, and for each, ask: **does this reassure the learner?**

A number that can only fail *pessimistically* (says you're worse off than you are) is annoying.
A number that can fail *optimistically* — *"the loop is closing"*, *"100% recall"* — **gets
believed, and stops them reviewing.** Optimistic failure modes are release-blocking; pessimistic
ones are bugs. Treat them differently.

### 3. What is its denominator, and does it say so?

Every rate silently drops something. Name it, count it, and **publish it beside the rate.**

`retention` computed over completed reviews drops exactly the concepts the learner abandoned —
which are, definitionally, the ones that decayed. That is survivorship bias with a progress bar,
and Engram shipped it *twice* (once via disjoint buckets, once via an `unmeasured` scoped to
never-reviewed nodes).

### 4. Does anything actually READ it? — **and does EVERY SURFACE read it?**

A guard nobody consumes is not a guard. `coverage` was computed, stored, and read by nothing —
so the anti-data-loss tripwire could not trip.

**Rule: a number's failure state must reach the NARRATOR** — the `read` string, the skill prose,
the dashboard — not sit in a nested key that only a test ever opens.

> ### ⚠ AND THEN OPEN THE DASHBOARD. ACTUALLY OPEN IT. ⚠ NEW
>
> v0.7's `grader_unvalidated` stamp reached the JSON, the CLI, and the skill file. It was
> **thrown away by the HTML dashboard** — which rendered the retention `read` *only* in the
> branch that fires when there is **no retention data**. On the happy path it drew the bars and
> dropped the stamp. A grader that inflated every second item therefore produced a **full-width
> green bar reading 100%**, with **zero** mentions of the word *grader* anywhere on the page.
>
> **Every gate that release ran — selftest, mutation, fuzz, live test, numbers audit, user
> session — reads JSON.** The dashboard is the one surface a human actually *looks* at, and it
> was the only one that lied. It was found by an outside reviewer, after everything was green.
>
> So, for every number: **`grep` the rendered HTML for its failure state.** If the number can be
> wrong, the page that shows it must say so:
>
> ```bash
> python3 scripts/engram.py report --out /tmp/d.html
> grep -ci 'unvalidated\|unaudited\|grader\|<the failure word>' /tmp/d.html   # must be > 0
> ```

> ### ⚠ A FIELD IS NOT A NARRATOR — and the HAPPY PATH is where caveats die ⚠ NEW
>
> v0.7.0's audit computed a caveat (*"these runs are identical, so test-retest measures nothing"*),
> wrote it to `reasons` on disk, and **the `pass` branch threw it away** — then printed
> **"test-retest 1.00"** as a validated figure. The most reassuring number in the payload, quoted as
> evidence, by the branch that had just discarded the note saying it was evidence of nothing.
> `grader-health` did not even return the key, though the skill file says *"read `reasons` aloud."*
>
> **Two rules, both cheap, both learned by shipping the bug:**
>
> 1. **`pass` is the ONE verdict where the teeth are off — so it is the one place a caveat MUST
>    survive.** Every failing branch joins its reasons because failure is loud. The happy path
>    builds its own cheerful string and drops them. **Read the success branch hardest.**
> 2. **A check that asserts a FIELD CONTAINS the caveat proves nothing about whether anything READS
>    it.** v0.7's selftest did exactly that and stayed green while no runtime surface consumed the
>    key. **Follow the caveat all the way to a string a human sees** — the `read`, the skill's
>    output, the HTML — and assert it *there*.
>
> **And while you are in there: DERIVE, never BELIEVE.** `grader_unvalidated` was read *from the
> audit file* instead of computed from the (already-validated) `verdict`, so a file saying
> `{"verdict": "fail", "grader_unvalidated": false}` switched the teeth off completely. A flag that
> is a **function** of a validated field must be written as one.

### 5. Can it be reached from the CLI in a way the skills never take?

The skills always pass explicit flags. **The CLI has defaults, and they bite.** `rate --kind`
defaults to `"review"`, so a bare `rate` wrote a node's only receipt as a review — and
`loop_closure` reported a perfect score for a learner who never returned.

Every metric keys off exact literals. **Validate them** (`choices=`, a `KINDS` constant, a check
in `validate_item`) so a typo dies before any write — receipts are append-only, so a bad one can
never be corrected.

### 5.5 · IF THE NUMBER IS AN INSTRUMENT, TEST THE INSTRUMENT ⚠ NEW — and it is the sharpest gate here

**v0.7.0 built a gold set to catch a lenient grader — and the gold set was rewarding leniency.**
Nobody caught it, through eight gates, because every one of them tested the *grader*. **Not one
tested the ruler.**

The test that found it takes four lines, and it is now mandatory for any metric that *ranks* or
*certifies* anything:

> **Build a deliberately WRONG subject. Run it through your instrument. Assert it scores WORSE
> than a correct one.**

```
grader that is CORRECT on the trap item  ->  QWK 0.990
grader that is FOOLED by the trap item   ->  QWK 1.000   ← THE INSTRUMENT IS INVERTED
```

A ruler that ranks a fooled grader above a correct one is not a lenient ruler — it is a **negative**
one, and every number downstream of it has its sign flipped. This is a **monotonicity check**, and
it costs nothing:

- **Grader/judge?** Feed it a subject that fails the exact trap the set exists to set. It must score lower.
- **Retention metric?** Feed it a learner who forgot everything. It must read worse than one who didn't.
- **Adherence funnel?** Feed it someone who never came back. It must read worse than someone who did.

> ### ⚠⚠ AND VARY THE **POPULATION**, NOT JUST THE **BAR**. ⚠⚠ — the gate's own blind spot
>
> **v0.8 built this gate, ran it, passed it, and shipped an inverted ruler anyway.**
>
> The v0.8 instrument check varied the **bar**: one node, one receipt, graded `recalled` /
> `partial` / `lapsed`, asserting the metric ordered them correctly. It did. And the metric still
> ranked **a learner who had lost every capability 2× above one who had mastered every one** —
> because it pooled the whole lifetime log and was **order-blind**, and a single-receipt fixture
> can never see order.
>
> **Varying the bar tests the SUBJECT. Varying the population tests the RULER.** They are not the
> same test, and only the second one is this gate.
>
> So build **whole learners**, not single data points, and make them differ in *shape*:
>
> | vary | the fixture |
> |---|---|
> | **order** | improving (fail, fail, **pass**) vs declining (pass, pass, **fail**) — same events, opposite meaning |
> | **volume** | one probe vs twenty. Does a rate exist at n=1? *(Every sibling metric had a floor. This one had none, and read "100%" off a single datum.)* |
> | **recency** | a capability from June vs one from yesterday |
> | **composition** | 5 nodes × 1 probe vs 1 node × 5 probes — same `n`, different truth |
>
> If two learners with **opposite** real-world standing produce the **same** number — or worse, the
> **wrong** ordering — the ruler is broken, and no amount of testing the subject will ever show it.

**And the reason the gate is needed at all:** the author of an instrument is the last person able to
see it fail, because the instrument encodes their own judgment. Five of the six lenient
adjudications were the *same mistake* — crediting an **adjacent fact** as partial credit — and one
of them was on a `fluent-but-empty` item, which means **the author was fooled by fluency in the
category built to catch being fooled by fluency.**

**Then the corollary, and it is uncomfortable:** when the instrument disagrees with the subject and
you *correct the instrument*, you have made it **circular**. The agreement that follows measures your
willingness to concede, not the subject's validity. So:

- **Say so, in the payload.** Engram's audit now carries `gold_adjudication: "authored"` and refuses
  to let a QWK from an authored set certify a grader from the same model family.
- **Keep the disagreements you cannot resolve.** One item (`g_054`) was left contested on purpose,
  because an independent reviewer judged the original defensible. **An instrument with no
  disagreement left in it measures nothing.**
- **Find the claim that does NOT depend on the instrument being perfectly calibrated.** Here it was
  `graded_up == 0` — a *direction* count. Every authoring error was lenient, so correcting them moved
  the bar **down**, and the grader still never exceeded it. That claim got *stronger* under
  correction. **That is the one that goes on the badge.**

> ### ⚠ A WHITELIST THAT ADMITS A FREE-TEXT FIELD STRIPS NOTHING ⚠ NEW
>
> v1.0 shipped an `export` "whitelist" and a selftest that *proved it leaked nothing* — and it
> leaked every node's `claim` **verbatim**, because two of the whitelisted keys (`arm`, `stratum`)
> were **free-text strings a human authored**. A whitelist of field NAMES does not constrain field
> VALUES. The promise (*"no code path by which a production could arrive"*) was true of the keys
> and false of the payload.
>
> **Every string on a privacy whitelist must be one of two things: a closed ENUM the engine
> validates, or a HASH.** Anything a human typed — an arm label, a stratum, a topic, a grader id —
> gets hashed. `kind`/`grade`/`rating` may leave as themselves *only because* they are enums the
> ingest path refuses to let anything else into.
>
> **And the leak-test that missed it did so the classic way:** it asserted the whitelist keys were
> clean **by never populating them** — it never started an experiment, so `arm`/`stratum` were
> always `None`. A privacy test must stuff a canary into **every authored surface** and assert not
> one character survives. *A test that proves a field is clean by leaving it empty proves nothing.*

### 6. Does its LABEL survive contact with a reader? ⚠ NEW — bug class #7

The arithmetic being right is not a defence. **Nobody reads the arithmetic.** Three shipped
examples, all of them numerically correct and all of them deceiving:

- `retention` said **56%** and `decay` said **66%** — both true, over different populations,
  ten points apart, and a user could not tell which to believe (v0.6.4).
- `by_case_type` reported **`n: 30`** for a case type holding **ten items**. The 30 was
  *judgments* (10 items × 3 runs). Nothing said so, and the skill instructed the narrator to
  quote it as a sample size (v0.7).
- The audit wrote **`gold_source: "bundled"`** onto a run whose ground truth had been locally
  re-adjudicated. Not merely silent — **actively false, in the flattering direction** (v0.7).

**Three rules, and they cost one line each:**

1. **Two different denominators may never share a key name.** `items` and `judgments`, not `n`.
2. **A provenance field must be computed, never asserted.** If it can be wrong, it will be
   believed anyway — *a provenance field that lies is worse than no provenance field.*
3. **A mean hides its own direction.** `leniency_bias: +0.00` is produced by a *perfect* grader
   and by one that inflates a third of the set and deflates another third. Same number, opposite
   safety. **Publish the direction counts, not just the mean** (`graded_up` / `graded_down`), and
   put them in the `read`.

---

## 5 · The live test (drive the engine — never skip)

Selftest proves the units; this proves a learner's *experience*. Drive the real engine end to
end in a throwaway state dir, exercising everything the release touched.

```bash
export ENGRAM_HOME=$(mktemp -d); export ENGRAM_TODAY=2026-01-01
```

Exercise: `init` → `add-topic` → `topic-status` → `artifact set` → `rate` (encode) →
time-travel → `rate` (review) → `stats` → `adherence` → `retention` → `decay` → `commit` →
`focus`/`visuals` round-trip → `artifact list` → `report` → `doctor`.

**Confirm with your own eyes** that `s_after > s_before`, the receipt carries its medium stamp,
`momentum` is populated, `modality` carries its caveat, `retention` carries its `unmeasured`,
the dashboard writes, and `doctor` is `ok=true`.

**This step earned its place:** it caught disjoint retention windows silently eating a real
day-11 review — a bug no selftest could see, because the selftest fixture used day 7 and day 30
and never landed in the gap.

Then **read-only against the real state** (`~/.claude/learning`) and hash the directory before
and after. A read command that writes is a defect (three of them were).

## 5.5 · The agent dogfood — **UNCONTAMINATED** (required when skills, agents, or the Contract change)

The engine can be green while the *prose* regresses — and prose is where most of this plugin's
behavior lives. Steps 4–4.8 cannot see it.

```bash
export ENGRAM_HOME=$(mktemp -d)     # NEVER ~/.claude/learning — a dogfood receipt would
                                    # poison the learner's real schedule and telemetry
```

### ⚠ The rule that makes this test real, learned the expensive way

> **Give each agent EXACTLY what the real skill gives it. Not one word more.**

v0.6 shipped issue #3's fix as dead code. The dogfood *certified* it — because the prompt
written for the dogfood **told the assessor to pass the `sid` through**, an instruction the real
`/learn` skill never gives. The real assessor, following its own strict output schema, dropped
the field every time.

**A test that hands the subject the answer is not a test.** If you catch yourself adding a hint,
an explanation, or a "remember to…" to a dogfood prompt, **stop** — you have just discovered a
gap in the *real* contract. Fix the contract; don't patch the prompt.

Concretely: paste the literal output of `stash list`. Nothing else.

### The loop

1. **curriculum-architect** on a small real topic (5 nodes). Did it honor the current spec?
2. `add-topic` → `next`. Does the frontier node arrive with what the skills expect?
3. **artifact-smith** on the frontier node, given only what `/learn` would give it. Did it read
   the Contract, obey each clause, and **register itself**?
4. **Audit the artifact independently — never trust the agent's own QA report.** Grep it: no
   external refs, both themes, `prefers-reduced-motion`, the prediction gate hides content, the
   worked drive precedes free manipulation, both retrieval prompts, the blank-page ending, the
   header comment. Open it and click through.
5. `stash add` a plausible production → **assessor** (blind; stash contents only, verbatim) →
   `receipt` → `stash clear`. Did it round **down** on a gapped production and cite the rubric?
   **Did every field of the contract survive the round-trip?**
6. **Settle the same file twice.** The second must be a true no-op — and the stash must still
   contain any *other* ungraded production for that node.
7. Read the resulting telemetry (`stats`, `adherence`, `retention`, `doctor`, `report`) as a
   learner would.

Write down what surprised you. **A surprise here is not a reason to skip the release. It is the
release.**

## 5.6 · THE USER SESSION ⚠ NEW — the "user ready" gate

Everything above proves the system is *correct*. **Nothing above proves it is usable.** This
step is the only one that asks the question the 500 people who installed it actually care about:
*would a stranger get through this?*

**Be a learner. Not a tester. Actually try to learn something you don't know.**

```bash
export ENGRAM_HOME=$(mktemp -d)     # throwaway, always
```

Rules, and they are what make it worth doing:

- **Pick a topic you genuinely do not understand.** Not a demo topic. Not something you can fake.
  If you already know it, you cannot feel where the tutor is confusing.
- **Answer honestly.** Do not perform competence. Give the terse, half-right answer you would
  actually give at 11pm. That is the production the assessor has to handle, and the one that
  found the *terse-production* rule in the first place.
- **Do not fix anything while you are inside the session.** Write it down and keep going. The
  moment you start debugging, you have stopped being a user.
- **Then time-travel the sandbox and run `/review`.** The retention half is the half that has
  never run — you do not get to ship a release that touches it without running it.

### The report (paste it into the PR / release notes — it is required output)

```
## User session report — vX.Y.Z
topic: <what you tried to learn>      mode: <sprint|standard|deep>
real minutes: <n>                     nodes encoded: <n>      reviews cleared: <n>

WHAT WORKED
- …

WHAT CONFUSED ME
- …

WHAT ANNOYED ME — and what I would have quit over
- …

WHAT IT TOLD ME vs WHAT WAS TRUE
- <every number it showed me. was each one right? did any of them flatter me?>
- <run the other commands on the same state. do they agree?>       ← §4.8.1, by hand

WOULD A STRANGER GET THROUGH THIS?   yes / no — and why

VERDICT:   ship / do not ship
```

**The verdict is binding.** If you would not hand this to a stranger, it does not ship, no matter
how green the tests are. The whole point of the project is a tool a human keeps using; a release
that is correct and unusable has failed at the only thing that matters.

**And the honest note:** the *feel* of returning after three days cannot be faked with
`ENGRAM_TODAY`. When a release changes the retention loop, the amnesty protocol, or the ambient
surface, **use it for real, across real days, before the next release.** The founder's own
account — 7 encoded, 0 reviewed — is what this entire release existed to fix, and no sandbox
would ever have shown it.

---

## 6 · Merge, tag, release (the step that was once missed)

```bash
V=X.Y.Z
git add -A && git commit    # "release: vX.Y.Z — <theme>" (+ Co-Authored-By trailer)
git checkout main && git pull origin main
git merge --no-ff release/v$V -m "Merge: vX.Y.Z — <theme>"
git push origin main

python3 - "$V" > /tmp/relnotes.md <<'PY'
import sys; V=sys.argv[1]; on=False; out=[]
for ln in open("CHANGELOG.md").read().splitlines():
    if ln.startswith("## "+V): on=True; continue
    if on and ln.startswith("## ") and not ln.startswith("## "+V): break
    if on: out.append(ln)
open("/dev/stdout","w").write("\n".join(out).strip()+"\n")
PY

git tag -a "v$V" -m "v$V — <theme>" && git push origin "v$V"
gh release create "v$V" --title "v$V — <theme>" --notes-file /tmp/relnotes.md --latest
```

`--latest` is what flips the badge off the previous version. **Without the tag + release, `main`
has the new version and the world still sees the old one.**

## 7 · Verify the release is real

```bash
gh release list -L 3                       # the new vX.Y.Z must show "Latest"
git describe --tags --abbrev=0 origin/main # == vX.Y.Z
```

## 7.5 · The post-release review ⚠ NEW — because two HIGH bugs were found *after* shipping

Every gate above is run by the person who wrote the code, on the code they believe is right.
**They confirm what you already believe. That is their structural limit.**

The two worst bugs in v0.6 were found by an **independent reviewer reading the shipped code**,
after release:

- the "honest denominator" exempted anyone who reviewed once, ever — so the dashboard reported
  *100% recall, nothing unmeasured, loop closing* while the engine's own `decay` said 56%;
- the **normal** settle path (not the rare one already fixed) destroyed a learner's second,
  ungraded production, on every single settle.

So, **after every release that touches the engine**, spawn a reviewer against `main` with:

- the shipped code, **not** the diff (the diff hides what a contract file elsewhere fails to do);
- the list of what the pre-release review already found, so it does not re-report;
- a standing instruction: **"find a number that is wrong, especially one that is wrong in the
  direction that reassures the learner."**

If it finds something, **ship the patch immediately** and say so plainly in the CHANGELOG. Three
releases in an hour is not a failure; a wrong number left standing is.

## 8 · Tell existing users how to update

New installs pull `main` and are fine. Existing users must run:

```
claude plugin marketplace update engram && claude plugin update engram@engram
```

then restart (or `/reload-plugins`). Mention this in the release notes — a plain `plugin update`
before the marketplace refresh reports "already current" against the stale cache.

Then, per the repo's habit: **close the issues this release fixes, with a real reply** — what
shipped, what the wrinkle was, and how to get it.

---

### One-glance checklist

- [ ] on a `release/` branch; selftest green to start
- [ ] work landed; **every engine change has a selftest**
- [ ] version bumped in **all** grep locations (re-grep: zero stale)
- [ ] CHANGELOG written — including the embarrassing parts
- [ ] **§4** selftest → N/N, N == the badge
- [ ] **§4.5** every new check **mutation-tested** (revert the fix → that check fails)
- [ ] **§4.6** `/code-review high`; **no agent errored**; every finding fixed + checked
- [ ] **§4.7** fuzz: **0 crashes / 500 garbage states**; read-path list taken **from the dispatch
      table, not from memory**; re-fuzz **after the last commit**
- [ ] **§4.8** numbers audit — all **six** questions answered **in writing** for every new number
- [ ] **§4.8 Q4** the rendered **HTML dashboard** grepped for every failure state
- [ ] **§4.8 Q4** every caveat followed to a **string a human sees** — not just to a field
- [ ] **§4.8 §5.5** if the number is an **instrument**, a deliberately WRONG subject scores WORSE
- [ ] every guard added to N call sites — **grep for the N+1th** (`cmd_artifact` was the one missed)
- [ ] **§5** live test driven; real state read-only and **hash-identical** after
- [ ] **§5.5** agent dogfood — **uncontaminated** (agents got exactly what the skill gives them)
- [ ] **§5.6** **USER SESSION run; report written; verdict = ship**
- [ ] **§6** merged `--no-ff`; annotated tag; `gh release create … --latest`
- [ ] **§7** `gh release list` shows it as Latest
- [ ] **§7.5** post-release independent review scheduled/run
- [ ] **§8** update line published; fixed issues closed with a real reply

---

### Why each gate exists — the actual bug, in one line each

| Gate | The bug it caught |
|---|---|
| **4** selftest | the ordinary stuff — and nothing else |
| **4.5** mutation test | **3 fake checks in v0.6, 4 more in v0.7.** The rate is not dropping. One asserted a constant; one had a fixture where old and new agreed by coincidence; one asserted a property *weaker* than the one it was pinning; two were satisfied by a different element on the same page |
| **4.6** adversarial review | 10 defects behind 79 green checks (v0.5); 9 behind 110 (v0.6); **8 behind 155 (v0.7) — including the teeth never reaching the dashboard, in the release that was ABOUT the teeth** |
| **4.7** fuzz | 259 crashes in 300 states (v0.6) — and **447 more in v0.7, in already-shipped code**, the first time anyone fuzzed the command `/learn` calls every session |
| **4.8** numbers audit | `retention` said **100%** while `decay` said **56%** — two commands, one state, contradictory stories, shipped. And v0.7: three defects, **two of them the same unlabelled-denominator bug, found inside the release built to catch unlabelled denominators** |
| **5** live test | disjoint buckets **silently ate a real day-11 review** while reporting "no reviews yet" |
| **5.5** dogfood | the pipeline held — and the *first* dogfood **certified a dead feature**, because the prompt handed the assessor the answer |
| **5.6** user session | the founder encoded 7 concepts and reviewed **0**. Every test was green. The product had already failed. And in v0.7 it killed a line that put a caveat on a number **that did not exist** |
| **7.5** post-release review | **2 HIGH bugs in shipped code** (v0.6) — the honest denominator wasn't honest; the normal settle path destroyed the learner's work. Then v0.7: **the gold set built to catch a lenient grader was REWARDING leniency** — a fooled grader outscored a correct one, and eight gates had walked past it because every one of them tested the grader and **not one tested the ruler** |

**The pattern, stated once:** *every test you write confirms what you already believe. The things
that found real bugs were the ones you did not control — a fuzzer, a reviewer, and a real session
with a real human who did not come back.*

**The v0.7 corollary, and it is the sharpest one yet:** *the gate you build to catch a bug class
will not catch that bug class in itself.* v0.6's fuzz gate missed `next`. v0.7's numbers audit —
the gate that exists for unlabelled denominators — **shipped two unlabelled denominators**; the
release built to make the grader's failures visible **hid them from the dashboard**; and the gold
set built to catch a grader fooled by fluency **was itself adjudicated by an author fooled by
fluency, on a fluent-but-empty item.** Run every gate against the release that adds it, and then
have someone else run it again.

**And the deepest version of it, which is the reason §7.5 exists and is not optional:**

> **You cannot audit your own instrument.** Not because you are careless — because the instrument
> *is* your judgment, rendered in data. Every gate in this file is run by the person who wrote the
> code, and they will confirm what that person already believes. The only things that have ever
> found a real bug here are the ones that do not share the author's mind: **a fuzzer** (which has
> no beliefs), **a reviewer** (whose beliefs are different), and **a real learner who did not come
> back** (whose behaviour is not a belief at all).
>
> Budget for all three, every release. They are not overhead. They are the only measurement in the
> building that is not looking in a mirror.
