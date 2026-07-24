#!/usr/bin/env python3
"""
Engram state engine — the deterministic core of the Engram learning plugin.

All scheduling math, state transitions, and evidence (receipts) live here.
The LLM never computes dates or stability values; it calls this CLI (Article 10:
receipts or it didn't happen; the oracle is never a vibe).

Scheduler: FSRS-4.5 (open-spaced-repetition), with an optional per-user
interval multiplier fitted by `refit` once enough review evidence exists.

Stdlib only. State lives in ~/.claude/learning (override: ENGRAM_HOME).
Test hooks: ENGRAM_TODAY=YYYY-MM-DD freezes "today"; `selftest` runs in a tempdir.
"""

import argparse
import hashlib
import itertools
import json
import math
import os
import random          # v0.9: SEEDED randomization only — every draw is recomputable from the seed
import re
import shlex
import sys
import tempfile
import time
from datetime import date, timedelta
from html import escape

SCHEMA = 1
# The one place the engine knows its own version. Read by `export`, so a shared receipt states
# which engine produced it — a corpus of receipts from unknown engine versions is not a corpus.
# Pinned against .claude-plugin/plugin.json by a selftest, so it cannot drift.
ENGRAM_VERSION = "1.4.0"
RETENTION_DEFAULT = 0.90
INTERVAL_MAX = 365
RETENTION_MIN, RETENTION_MAX = 0.70, 0.97   # sane desired-retention bounds
MULTIPLIER_MIN, MULTIPLIER_MAX = 0.5, 1.5   # matches refit clamp
CAL_MIN_N = 10          # calibration verdict floor: below this, "insufficient-data"
PRODUCTION_MAX = 800    # receipt production cap (chars)

# FSRS-4.5 default parameters (open-spaced-repetition). w[0..3] are initial
# stabilities for Again/Hard/Good/Easy; the rest shape difficulty and growth.
W = [0.4872, 1.4003, 3.7145, 13.8206, 5.1618, 1.2298, 0.8975, 0.031,
     1.6474, 0.1367, 1.0461, 2.1072, 0.0793, 0.3246, 1.587, 0.2272, 2.8755]
DECAY = -0.5
FACTOR = 19.0 / 81.0  # chosen so R(t=S) = 0.9

RATINGS = {"again": 1, "hard": 2, "good": 3, "easy": 4}
GRADES = ("recalled", "partial", "lapsed")
# Ordinal positions for the four ratings — 0-based and contiguous, which is what a
# weighted kappa needs (RATINGS above is 1-based and is a different thing: the FSRS
# grade value). Two maps, two jobs, deliberately not merged.
RATING_SCORE = {"again": 0, "hard": 1, "good": 2, "easy": 3}
# Receipt kinds. Every v0.6 metric keys off the exact literal "review", so an
# invented kind would be permanently invisible — and receipts are append-only, so
# it could never be corrected. Validated at ingest; a bad batch dies before any write.
KINDS = ("encode", "review", "pretest", "transfer", "audit")
# Node KNOWLEDGE kinds (v1.1, docs/11 — KLI's three-kind taxonomy made data). Distinct name
# from a receipt's `kind` (the EVENT above) on purpose: two meanings never share a key
# (RELEASE_PROTOCOL §4.8 Q6). Surfaced everywhere as `node_kind`; the node's own JSON carries
# the architect's `kind` field, in node namespace, like `viz`. Engram stays fully general —
# the kind is declared per node by the CONTENT (a `procedure` is a git workflow as readily as
# an integral); there is no domain routing anywhere in this engine.
NODE_KINDS = ("concept", "procedure", "fact")
# Error classes on a graded production (v1.1, docs/11 P17): `conceptual` = the method/model
# was wrong; `slip` = method right, execution slipped. Different facts with different
# schedule meanings (slip-only caps the DAMAGE at partial/hard — a transcription error is
# not a memory lapse). Closed enum, validated at ingest, so export may carry it un-hashed.
ERROR_CLASSES = ("conceptual", "slip")
NODE_STATES = ("new", "learning", "review")
# grade <-> rating are a bijection (dialogue-grammar rating map); used for the
# calibration outcome fallback and grade/rating mismatch warnings.
GRADE_OF_RATING = {"again": "lapsed", "hard": "partial", "good": "recalled", "easy": "recalled"}
OUTCOME_OF_GRADE = {"recalled": 1.0, "partial": 0.5, "lapsed": 0.0}

_SEQ = itertools.count()

# ------------------------------------------------------ untrusted-input guards

_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

def slug_ok(s):
    """A safe filename component: no separators, no traversal, no absolute/hidden."""
    return (isinstance(s, str) and bool(_SLUG_RE.match(s))
            and s not in (".", "..") and not s.startswith(".")
            and "/" not in s and "\\" not in s and "\x00" not in s)

def require_slug(s, what="topic"):
    if not slug_ok(s):
        die("invalid %s %r (allowed: letters, digits, . _ - ; no slashes or '..')"
            % (what, s if isinstance(s, str) else type(s).__name__))
    return s

def safe_date(s):
    """Parse an ISO date, tolerating missing/garbled values (returns None)."""
    if not s or not isinstance(s, str):
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None

def as_number(x, default=None):
    """Coerce a JSON scalar to float for math; the default if not number-like.

    **NON-FINITE IS NOT A NUMBER.** `Infinity` and `NaN` are not valid JSON, but Python's `json`
    module PARSES them by default — so a hand-edited state file can hand this engine an `inf`
    that sails through every `isinstance(x, float)` check and then blows up the moment anything
    calls `int()` on it (`OverflowError: cannot convert float infinity to integer`), or silently
    poisons every comparison it touches (`NaN` compares False to everything, including itself).
    Found by fuzzing: 3 crashes in `decay` and `experiment status`, in code with no other flaw.

    This is THE numeric gate for the whole engine — every scheduler leaf, every metric, every
    threshold funnels through it. Fixing it here is one line; fixing it at the call sites is
    forty, and forty-first is the one that ships."""
    if isinstance(x, bool) or x is None:
        return default
    if isinstance(x, (int, float)):
        v = float(x)
        if v != v or v in (float("inf"), float("-inf")):   # NaN, +inf, -inf
            return default
        return v
    return default

def days_between(a_ts, b_ts):
    """Elapsed days between two ISO dates; None if either is missing/garbled."""
    a, b = safe_date(a_ts), safe_date(b_ts)
    if a is None or b is None:
        return None
    return (b - a).days

def _median(xs):
    """True median (mean of the two middle values on an even-length list)."""
    if not xs:
        return None
    ys = sorted(xs)
    n = len(ys)
    mid = n // 2
    return ys[mid] if n % 2 else round((ys[mid - 1] + ys[mid]) / 2, 1)

def _fsrs_of(node):
    """A node's FSRS block — ALWAYS a dict, whatever the graph actually contains.

    `node.get("fsrs") or {}` is not enough. A hand-edited graph can carry `fsrs: "garbage"`
    or `fsrs: ["x"]` — truthy non-dicts — and every downstream `.get()` then raises
    AttributeError. Found by fuzzing 300 randomized garbage states: this crashed
    `compute_momentum` (shipped since v0.4) and `due_items` (shipped since v0.1), and would
    have crashed `adherence` and `retention` too. Because `stats` calls all of them, a single
    bad hand-edit could brick `/coach` outright.

    Read paths must DEGRADE, never brick — the same doctrine `iter_graphs` already states
    for unreadable graph files. `doctor` is the thing that reports corruption; `stats` is not
    allowed to die of it."""
    f = node.get("fsrs") if isinstance(node, dict) else None
    return f if isinstance(f, dict) else {}

def _sort_key(r):
    """Stable ordering for receipts whose `ts`/`id` may be any JSON type after a hand-edit.

    Mixed types in a sort key (an int ts beside a str ts) raise TypeError in Python 3, so
    everything is coerced to str. A receipt with a MISSING or unparseable ts sorts LAST, not
    first: every real receipt carries a date, and a broken one must never win the race to
    become a node's day-0 anchor and poison every elapsed-day metric downstream.
    (Found by adversarial review.)"""
    ts = r.get("ts")
    ok = isinstance(ts, str) and safe_date(ts) is not None
    return (0 if ok else 1, str(ts or ""), str(r.get("id") or ""))

# ---------------------------------------------------------------- fsrs core

def clamp(x, lo, hi):
    return max(lo, min(hi, x))

def retrievability(elapsed_days, stability):
    if stability <= 0:
        return 0.0
    return (1.0 + FACTOR * elapsed_days / stability) ** DECAY

def interval_for(stability, retention, multiplier=1.0):
    # defensive clamps: a corrupt/edited model must never divide-by-zero or
    # explode the schedule (retention==0 -> 0**-power; negative multiplier -> <0).
    retention = clamp(retention, RETENTION_MIN, RETENTION_MAX)
    multiplier = clamp(multiplier, MULTIPLIER_MIN, MULTIPLIER_MAX)
    days = stability / FACTOR * (retention ** (1.0 / DECAY) - 1.0) * multiplier
    return int(clamp(round(days), 1, INTERVAL_MAX))

def init_stability(g):
    return clamp(W[g - 1], 0.1, 100.0)

def init_difficulty(g):
    return clamp(W[4] - (g - 3) * W[5], 1.0, 10.0)

def next_difficulty(d, g):
    nd = d - W[6] * (g - 3)
    # FSRS-4.5 mean-reverts toward D0(3) (Good), not D0(4); D0(4) is the FSRS-5
    # rule and would inflate stability growth ~20% under this 4.5 weight vector.
    nd = W[7] * init_difficulty(3) + (1.0 - W[7]) * nd
    return clamp(nd, 1.0, 10.0)

def next_stability_recall(d, s, r, g):
    hard_penalty = W[15] if g == 2 else 1.0
    easy_bonus = W[16] if g == 4 else 1.0
    grow = (math.exp(W[8]) * (11.0 - d) * (s ** -W[9])
            * (math.exp(W[10] * (1.0 - r)) - 1.0) * hard_penalty * easy_bonus)
    return clamp(s * (1.0 + grow), 0.1, 36500.0)

def next_stability_forget(d, s, r):
    sf = W[11] * (d ** -W[12]) * (((s + 1.0) ** W[13]) - 1.0) * math.exp(W[14] * (1.0 - r))
    return clamp(min(sf, s), 0.1, 36500.0)  # a lapse never increases stability

def apply_rating(fsrs, rating_name, on_date):
    """Pure transition: fsrs dict + rating -> new fsrs dict (+ receipt fields)."""
    g = RATINGS[rating_name]
    s0, d0 = as_number(fsrs.get("s")), as_number(fsrs.get("d"))
    if s0 is not None:
        s0 = clamp(s0, 0.1, 36500.0)   # corrupt s=0 would make s**-w blow up
    last = fsrs.get("last")
    if s0 is None:  # first exposure (or unrecoverable s -> treat as first)
        s, d, r = init_stability(g), init_difficulty(g), None
    else:
        if d0 is None:
            d0 = init_difficulty(3)     # corrupt difficulty -> re-anchor
        last_d = safe_date(last)
        elapsed = max(0, (on_date - last_d).days) if last_d else 0
        r = retrievability(elapsed, s0)
        d = next_difficulty(d0, g)
        s = next_stability_forget(d0, s0, r) if g == 1 else next_stability_recall(d0, s0, r, g)
    ivl = interval_for(s, as_number(fsrs.get("retention"), RETENTION_DEFAULT),
                       as_number(fsrs.get("im"), 1.0))
    out = dict(fsrs)
    # `reps` and `lapses` were the last two raw arithmetic leaves in the scheduler: every
    # other one (s, d, retention, im) already went through as_number, and these two did
    # `fsrs.get("reps", 0) + 1` straight. A hand-edited `"reps": "many"` raised TypeError —
    # and this runs on the MUTATOR path too, so it took `rate` down, not just `decay`.
    # Counters are non-negative integers or they are not counters.
    reps = as_number(fsrs.get("reps"), 0) or 0
    lapses = as_number(fsrs.get("lapses"), 0) or 0
    out.update({
        "s": round(s, 4), "d": round(d, 4),
        "last": on_date.isoformat(),
        "due": (on_date + timedelta(days=ivl)).isoformat(),
        "reps": max(0, int(reps)) + 1,
        "lapses": max(0, int(lapses)) + (1 if (g == 1 and s0 is not None) else 0),
    })
    return out, {"s_before": s0, "s_after": out["s"], "interval_days": ivl,
                 "retrievability": (round(r, 4) if r is not None else None)}

# ---------------------------------------------------------------- state io

def today():
    env = os.environ.get("ENGRAM_TODAY")
    return date.fromisoformat(env) if env else date.today()

def home():
    return os.environ.get("ENGRAM_HOME") or os.path.join(
        os.path.expanduser("~"), ".claude", "learning")

def p(*parts):
    return os.path.join(home(), *parts)

def _quarantine(path):
    """Preserve a corrupt state file instead of letting a writer clobber it."""
    try:
        os.replace(path, "%s.corrupt.%s" % (path, today().isoformat()))
    except OSError:
        pass

def read_json(path, default=None, quarantine=True):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except (json.JSONDecodeError, UnicodeDecodeError):
        if quarantine:
            _quarantine(path)   # never silently discard corrupt state
        return default

def _require_within_home(path):
    """Refuse to write outside the state dir (defence in depth vs slug traversal)."""
    base = os.path.realpath(home())
    rp = os.path.realpath(path)
    if rp != base and not rp.startswith(base + os.sep):
        die("refused write outside state dir: %s" % path)
    return rp

def write_json(path, obj):
    _require_within_home(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=2, ensure_ascii=False, sort_keys=False)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)   # don't leak a .tmp on failure
        except OSError:
            pass
        raise

def append_jsonl(path, obj):
    _require_within_home(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # O_NOFOLLOW: refuse to append through a pre-planted symlink at the final component.
    flags = os.O_CREAT | os.O_WRONLY | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o644)
    with os.fdopen(fd, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")

def read_jsonl(path):
    """Read a JSONL state file, keeping only OBJECT lines.

    Every consumer of every .jsonl in this store (receipts, stash, sessions, gold)
    treats entries as dicts. A line holding `5` or `true` is valid JSON and pure
    corruption — and until v1.1.0 it walked straight into `r.get(...)` and bricked
    every aggregate read (`stats`, `due`, `report`, `session-start`), a crash that
    had been reachable since v0.1 and was found by the v1.1.0 fuzz gate. Non-object
    lines now get exactly the treatment non-JSON lines always got here: skipped at
    the gate (RELEASE_PROTOCOL §4.7 — fix at the gate, not at twenty call sites)."""
    out = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(obj, dict):
                        out.append(obj)
    except FileNotFoundError:
        pass
    return out

# --------------------------------------------------------------- state mutex
# The skills legitimately run two engine processes at once (the artifact-smith
# registers in the background while the tutor rates on the same topic), and
# graph writes are whole-file read-modify-write — last-writer-wins would let a
# stale snapshot silently revert a schedule advance or drop a registration.
# So every state-MUTATING command serializes on an advisory lockfile (portable:
# O_CREAT|O_EXCL, no fcntl). Commands are millisecond-long; a lock older than
# LOCK_STALE_S is a crashed holder and is broken.

LOCK_TIMEOUT_S = 10.0
LOCK_STALE_S = 60.0

def _lock_path():
    return p(".engram.lock")

def acquire_lock(timeout_s=LOCK_TIMEOUT_S, stale_s=LOCK_STALE_S):
    path = _lock_path()
    os.makedirs(home(), exist_ok=True)
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return path
        except FileExistsError:
            try:
                if time.time() - os.stat(path).st_mtime > stale_s:
                    os.unlink(path)   # crashed holder; both breakers racing is fine
                    continue
            except OSError:
                continue              # holder released between our checks
            if time.monotonic() >= deadline:
                die("state is locked by another engram process (%s); "
                    "if none is running, delete the file" % path)
            time.sleep(0.05)

def release_lock():
    try:
        os.unlink(_lock_path())
    except OSError:
        pass

DEFAULT_MODEL = {
    "schema": SCHEMA,
    "created": None,
    "memory": {"fsrs_params": None, "desired_retention": RETENTION_DEFAULT,
               "interval_multiplier": 1.0, "last_refit": None},
    "challenge_band": {"target_success": 0.85, "hint_budget": 2},
    "interests": [],
    "goals": [],
    "strategy_weights": {"derivation_first": 0.6, "example_first": 0.4},
    # `commitment` is the learner's implementation intention (if-then plan), in their own
    # words — Gollwitzer & Sheeran 2006: 94 tests, N>8,000, d=0.65, robust to publication-bias
    # correction. Stored because they said it, shown back at the moment it names, NEVER
    # enforced (docs/07 §4). `decay_notice` gates the honest loss report on return: it is
    # INFORMATION, never pressure (docs/05 P13), and it is off-switchable like `momentum`.
    "settings": {"default_mode": "standard", "artifacts": "threshold-only", "ambient": "quiet",
                 "momentum": "on", "profile": None,
                 "commitment": None, "decay_notice": "on"},
    "rhythms": {},
    "accessibility": [],
}

def _deep_heal(m, default):
    """Restore missing keys and repair type-mismatched subtrees from DEFAULT_MODEL.

    Makes the learner model self-healing: a hand-edit that deletes `interests`,
    or a bad `--set memory=5` that replaced a dict with a scalar, is restored to
    a working shape on next load instead of crashing every command."""
    if not isinstance(m, dict):
        return json.loads(json.dumps(default))
    for k, dv in default.items():
        if isinstance(dv, dict):
            if isinstance(m.get(k), dict):
                _deep_heal(m[k], dv)
            else:
                m[k] = json.loads(json.dumps(dv))
        else:
            m.setdefault(k, dv)
    return m

def load_model():
    """Load the learner model, persisting a self-heal. Callers MUST hold the state lock."""
    raw = read_json(p("learner-model.json"))
    if raw is None:
        m = json.loads(json.dumps(DEFAULT_MODEL))
        m["created"] = today().isoformat()
        write_json(p("learner-model.json"), m)
        return m
    before = json.dumps(raw, sort_keys=True)
    m = _deep_heal(raw, DEFAULT_MODEL)
    if json.dumps(m, sort_keys=True) != before:
        write_json(p("learner-model.json"), m)   # persist the repair once
    return m

def read_model():
    """Load the learner model WITHOUT persisting the self-heal — for read-only commands.

    `decay`, `doctor` and `report` do not take the state lock (they are reads). But
    `load_model` *writes* when it heals, so calling it from an unlocked path is a
    last-writer-wins race against a concurrent locked mutator — a stale snapshot healed
    and flushed by `report` could silently revert a `refit` or a `commit`. This is the
    same class of bug the v0.5 review caught between the background artifact-smith and
    the tutor's `rate`, and it has been latent in `report`/`doctor` since then.

    The heal still happens in memory, so the caller sees a complete model; it is simply
    not persisted. The next *mutating* command — which does hold the lock — persists it."""
    raw = read_json(p("learner-model.json"))
    if raw is None:
        m = json.loads(json.dumps(DEFAULT_MODEL))
        m["created"] = today().isoformat()
        return m
    return _deep_heal(raw, DEFAULT_MODEL)

def load_graph(topic):
    """THE GATE for every single-topic command. `iter_graphs` is its multi-topic twin.

    v0.6 put a shape check in `iter_graphs` — which every AGGREGATE read funnels through —
    and stopped there. `load_graph` had none, so every SINGLE-TOPIC command (`next`,
    `topic-status`, `rate`, `receipt`, `artifact`, `focus`) read raw, unvalidated JSON. A
    v0.7 fuzz run found **447 crashes in 300 garbage states on shipped main**, every one of
    them here: `nodes` as a string, `order` holding a dict (an unhashable key), a node that
    is a list. `next` is the command /learn calls at the start of EVERY session — the
    hottest path in the product — and a hand-edited graph could take it down mid-lesson.

    The v0.6 fuzz gate never saw it because its read-path list was written from the /coach
    surface (stats, adherence, retention, decay, report, doctor) and simply forgot the
    /learn surface. Every test confirms what you already believe; the list you write is the
    list you already thought of.

    A structurally unusable graph DIES here — a guarded refusal with a fix path, never an
    AttributeError, and never a silent half-read. It does NOT drop or rewrite anything:
    mutators save what they read, so a lossy "repair" here would be a data-loss bug wearing
    a hard hat. Reads that must tolerate partial garbage use `graph_nodes`/`graph_order`."""
    require_slug(topic)
    path = p("graphs", topic + ".json")
    existed = os.path.exists(path)
    g = read_json(path)   # quarantines corrupt JSON (renames it) and returns None
    if g is None:
        if existed:
            die("topic %s is corrupt — quarantined to a .corrupt file; run `doctor`" % topic)
        die("unknown topic: %s (run `topics` to list)" % topic)
    if not isinstance(g, dict) or not isinstance(g.get("nodes"), dict):
        die("topic %s has an unusable shape (`nodes` must be an object, got %s) — "
            "run `doctor`, then fix or delete graphs/%s.json"
            % (topic, type(g.get("nodes")).__name__ if isinstance(g, dict) else type(g).__name__,
               topic))
    return g

def graph_nodes(g):
    """The READ view of a graph's nodes: only the entries that are actually nodes.

    A hand-edited graph can hold `"b": ["not", "a", "node"]` or a non-string key. Reads skip
    those; `doctor` reports them. Never used by a mutator — dropping a node from a view a
    mutator then SAVED would delete the learner's work to keep a loop tidy."""
    return {nid: n for nid, n in g["nodes"].items()
            if isinstance(nid, str) and isinstance(n, dict)}

def graph_order(g, nodes=None):
    """A safe iteration order: valid ids from `order` first, then any node it forgot.

    `order` is where the curriculum's pedagogy lives, so it leads. But it can contain a dict
    (unhashable -> `nid in nodes` raises), an int, or a ghost id — and a node missing from
    `order` entirely must still be reachable, or it would be invisible to `next` forever."""
    nodes = graph_nodes(g) if nodes is None else nodes
    raw = g.get("order") if isinstance(g.get("order"), list) else []
    seen, out = set(), []
    for nid in raw:
        if isinstance(nid, str) and nid in nodes and nid not in seen:
            seen.add(nid)
            out.append(nid)
    out.extend(nid for nid in sorted(nodes) if nid not in seen)
    return out

def save_graph(g):
    require_slug(g.get("topic"))
    write_json(p("graphs", g["topic"] + ".json"), g)

def all_topics():
    d = p("graphs")
    if not os.path.isdir(d):
        return []
    return sorted(f[:-5] for f in os.listdir(d)
                  if f.endswith(".json") and slug_ok(f[:-5]))

def iter_graphs(topic_filter=None):
    """Yield (topic, graph) for STRUCTURALLY USABLE graphs; skip the rest without dying.

    Aggregate/read-only views (topics, stats, adherence, retention, decay, report, due,
    session-start) must degrade gracefully when one graph file is broken — never brick on it.

    "Parses as JSON" is not enough. A hand-edited graph can be perfectly valid JSON whose
    `nodes` is a string, or whose `order` is a number — and every downstream `.items()` /
    `.get()` then raises, taking `stats` (and therefore /coach) down with it. Fuzzing 500
    randomized garbage states showed the majority of crashes funnel through exactly here, so
    the shape check belongs at this ONE gate rather than smeared across twenty call sites.
    `doctor` deliberately reads graphs raw, so it can still REPORT the corruption this skips."""
    for t in all_topics():
        if topic_filter and t != topic_filter:
            continue
        g = read_json(p("graphs", t + ".json"))
        if not isinstance(g, dict) or not isinstance(g.get("nodes"), dict):
            continue                                   # unusable shape: doctor reports it
        if not isinstance(g.get("order"), list):
            g = dict(g, order=sorted(g["nodes"]))      # salvageable: stable fallback order
        yield t, g

def die(msg, code=2):
    print("engram: error: " + msg, file=sys.stderr)
    sys.exit(code)

def emit(obj):
    print(json.dumps(obj, indent=2, ensure_ascii=False))

STASH_FILE = "pending-verify.jsonl"

# ---------------------------------------------------------------- commands

def cmd_init(_args):
    load_model()
    # `audits` holds the grader audits (v0.7); `gold` is where a learner drops their own
    # local-gold.jsonl additions. The bundled gold set is NOT copied here on purpose — a
    # copy would shadow the plugin's set forever, so a v0.8 gold item would never reach a
    # v0.7 learner. The plugin's file is the source of truth; local is additive.
    for sub in ("graphs", "receipts", "artifacts", "audits", "gold", "exports"):
        os.makedirs(p(sub), exist_ok=True)
    for f, default in (("misconceptions.json", []), ("experiments.json", [])):
        if read_json(p(f)) is None:
            write_json(p(f), default)
    emit({"ok": True, "home": home()})

def _read_text(src):
    """Read text from a file path, or stdin when src == '-'."""
    if src == "-":
        return sys.stdin.read()
    with open(src, "r", encoding="utf-8") as f:
        return f.read()

def load_payload(args):
    # --file/--json may be '-' to read from stdin — the safe channel for learner
    # text, so tutors never interpolate free-text into a shell command line.
    if getattr(args, "file", None):
        try:
            raw = _read_text(args.file)
        except OSError:
            die("cannot read file: %s" % args.file)
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            die("bad JSON in %s: %s" % (args.file, e))
    if getattr(args, "json", None) is not None:
        raw = _read_text("-") if args.json == "-" else args.json
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            die("bad --json: %s" % e)
    die("provide --json or --file")

def _fresh_fsrs():
    return {"s": None, "d": None, "due": None, "last": None, "reps": 0, "lapses": 0}

def _requires_cycle(g):
    """Return a node-id cycle over `requires` edges, or None. Report-only."""
    color = {}  # 0=unseen 1=on-stack 2=done
    def visit(nid, stack):
        color[nid] = 1
        for req in g["nodes"].get(nid, {}).get("edges", {}).get("requires", []) or []:
            if req not in g["nodes"]:
                continue
            if color.get(req) == 1:
                return stack[stack.index(req):] + [req]
            if color.get(req, 0) == 0:
                r = visit(req, stack + [req])
                if r:
                    return r
        color[nid] = 2
        return None
    for nid in g["nodes"]:
        if color.get(nid, 0) == 0:
            r = visit(nid, [nid])
            if r:
                return r
    return None

def cmd_add_topic(args):
    g = load_payload(args)
    for key in ("topic", "title", "nodes", "order"):
        if key not in g:
            die("topic JSON missing key: %s" % key)
    require_slug(g["topic"])
    if not isinstance(g["nodes"], dict) or not g["nodes"]:
        die("topic has no nodes")
    if not isinstance(g["order"], list):
        die("order must be a list")
    for nid in g["nodes"]:
        require_slug(nid, "node id")
    missing = [n for n in g["order"] if n not in g["nodes"]]
    if missing:
        die("order references unknown nodes: %s" % ", ".join(missing))

    path = p("graphs", g["topic"] + ".json")
    old = read_json(path) if os.path.exists(path) else None
    if old is not None and not args.replace:
        die("topic exists: %s (use --replace to overwrite)" % g["topic"])
    old_nodes = old.get("nodes", {}) if isinstance(old, dict) else {}

    warnings = []
    # dedupe order (keep first occurrence), then append any node missing from it
    seen, order = set(), []
    for nid in g["order"]:
        if nid in seen:
            warnings.append("duplicate id in order dropped: %s" % nid)
            continue
        seen.add(nid); order.append(nid)
    for nid in g["nodes"]:
        if nid not in seen:
            warnings.append("node not in order, appended: %s" % nid)
            seen.add(nid); order.append(nid)
    g["order"] = order

    for nid, node in g["nodes"].items():
        if not isinstance(node, dict):
            die("node %s must be an object, got %s" % (nid, type(node).__name__))
        for key in ("claim", "probe"):
            if not node.get(key):
                die("node %s missing %s" % (nid, key))
        node.setdefault("edges", {})
        node.setdefault("why_chain", [])
        node.setdefault("arbitrary", False)
        node.setdefault("threshold", False)
        node.setdefault("rubric", [])
        node.setdefault("transfer_probe", None)
        # `transfer` is ENGINE-OWNED and derived from receipts (invariant #4: state advances
        # only through receipts). A payload that supplied it would be claiming a capability
        # nobody measured — which is precisely the unearned claim this release exists to end.
        node.pop("transfer", None)
        node.pop("capstone", None)     # only `capstone`/`add-topic` may mint one
        # `viz` is the architect's content-modality hint (affordance/kind/hook) —
        # Willingham's rule made data: the CONTENT declares whether it rewards a
        # manipulable model; the learner's settings decide whether to act on it.
        # The engine stores it opaquely; skills own its semantics.
        if node.get("viz") is not None and not isinstance(node.get("viz"), dict):
            warnings.append("%s: viz hint is not an object — dropped" % nid)
            node["viz"] = None
        node.setdefault("viz", None)
        # `kind` is the architect's knowledge-kind declaration (v1.1, docs/11) — same
        # covenant as `viz`: content declares, engine stores opaquely, skills own semantics.
        # An unknown literal is DROPPED with a warning, never fatal: an older or newer
        # architect must not brick an add, and absence is byte-compatible v1.0.8 behavior
        # (node_kind_of treats a kindless node as `concept`, or `fact` when arbitrary).
        # A --replace payload that drops `kind` silently demoted a procedure to a concept:
        # /review stopped serving fresh instances, and a tutor still passing --error-class
        # produced receipts stamped `concept` carrying a slip. Warn, as every other
        # reclassification here does (v1.1.1, §7.5 post-release review).
        _prev = old_nodes.get(nid)
        if isinstance(_prev, dict):
            _was, _now = node_kind_of(_prev), node_kind_of(node)
            if _was != _now:
                warnings.append("%s: knowledge kind changed %s -> %s by this payload; new "
                                "receipts will be stamped %s" % (nid, _was, _now, _now))
        if node.get("kind") is not None and node.get("kind") not in NODE_KINDS:
            warnings.append("%s: unknown kind %r dropped (use %s)"
                            % (nid, node.get("kind"), "|".join(NODE_KINDS)))
            node.pop("kind", None)
        # `practice` (procedure nodes): problem_frame / discriminates_from / verify /
        # error_bank. Object-or-dropped, exactly like `viz`.
        if node.get("practice") is not None and not isinstance(node.get("practice"), dict):
            warnings.append("%s: practice block is not an object — dropped" % nid)
            node["practice"] = None
        if node.get("kind") == "procedure" and not (
                isinstance(node.get("practice"), dict)
                and node["practice"].get("problem_frame")):
            warnings.append("%s: kind=procedure without practice.problem_frame — reviews "
                            "will fall back to the stored probe (concept-style)" % nid)
        # The engine OWNS scheduling state — never trust payload-supplied state/fsrs
        # (mastery advances only through receipts; Article 10). On --replace, carry
        # the existing schedule forward for surviving node ids so restructuring a
        # topic is not silent data loss. `artifact` is engine-owned the same way:
        # only `artifact set` (which validates the file exists) may record one. A
        # registration survives restructuring independently of the schedule (a
        # corrupt fsrs must not cost the registration), and carry-forward is
        # existence-checked so v0.4-era phantom strings die here instead of living
        # on as fake registrations.
        node.pop("artifact", None)
        prev = old_nodes.get(nid)
        if isinstance(prev, dict) and isinstance(prev.get("fsrs"), dict):
            node["fsrs"] = prev["fsrs"]
            node["state"] = prev.get("state", "new")
        else:
            node["fsrs"] = _fresh_fsrs()
            node["state"] = "new"
        node["artifact"] = valid_artifact(prev)
        if node["state"] not in NODE_STATES:
            node["state"] = "new"
        for etype, targets in node.get("edges", {}).items():
            if not isinstance(targets, list):
                continue
            for t in targets:
                if t not in g["nodes"]:
                    warnings.append("%s.%s -> unknown node '%s'" % (nid, etype, t))
    cyc = _requires_cycle(g)
    if cyc:
        warnings.append("requires cycle (topic can stall): %s" % " -> ".join(cyc))
    g.setdefault("schema", SCHEMA)
    g.setdefault("created", today().isoformat())
    g.setdefault("goal", None)
    preserved = sum(1 for nid in g["nodes"]
                    if isinstance(old_nodes.get(nid), dict)
                    and isinstance(old_nodes[nid].get("fsrs"), dict)
                    and old_nodes[nid]["fsrs"].get("s") is not None)
    if old is not None:
        try:
            write_json(path + ".bak", old)   # snapshot before overwrite
        except SystemExit:
            pass
    # THE CAPSTONE IS A NODE, NOT A HOPE (v0.8). It requires every other node, so it unlocks
    # exactly when the frontier empties and then arrives in `next` like anything else. For four
    # releases the capstone was a paragraph in a skill file that said "do not let this silently
    # not happen" — and it silently did not happen, every single time, because a tutor running
    # low on context drops a suggestion and never drops a DAG.
    #
    # v0.8.1 — THREE BUGS LIVED IN THESE FOUR LINES, all found by the post-release reviewer:
    #
    #  1. `--replace` DESTROYED a completed capstone's schedule. The architect's payload never
    #     contains a capstone (it is popped at ingest), so `_has_capstone` was ALWAYS false on a
    #     replace and the capstone was ALWAYS re-minted with `state: new, fsrs: fresh` — after
    #     the carry-forward loop, so it was the one surviving node never carried forward. And it
    #     flattered: the reset removed the rotting capstone from `retention.unmeasured`, so
    #     "1 concept past due and unretrieved" became "30-day recall 100%". Survivorship bias,
    #     through a new door.
    #  2. `--replace` wiped `node.transfer` and never rebuilt it (unlike `artifact`, which is
    #     recomputed from evidence). Graph said `None`; `stats` still said `applied: 1`.
    #  3. A payload node legitimately named `capstone` was SILENTLY overwritten — and the minted
    #     capstone then listed ITSELF in `requires`, so it could never be served, while `next`
    #     cheerfully reported "this topic is finished".
    real = {nid: n for nid, n in g["nodes"].items() if not n.get("capstone")}
    if CAPSTONE_ID in real:
        die("node id `%s` is reserved for the engine's capstone — rename it in the payload "
            "(a node called `capstone` would be silently replaced by the build, and the build "
            "would then require itself)" % CAPSTONE_ID)
    old_cap = next((n for n in old_nodes.values()
                    if isinstance(n, dict) and n.get("capstone") is True), None)
    if real:
        cap = _capstone_node(g, real)          # requires = every REAL node; never itself
        if isinstance(old_cap, dict):
            # carry the schedule forward, exactly like every other surviving node
            if isinstance(old_cap.get("fsrs"), dict):
                cap["fsrs"] = old_cap["fsrs"]
                cap["state"] = old_cap.get("state", "new")
                if cap["state"] not in NODE_STATES:
                    cap["state"] = "new"
                preserved += 1
            cap["artifact"] = valid_artifact(old_cap)
            warnings.append("capstone re-minted with the new requires; schedule carried forward")
        g["nodes"][CAPSTONE_ID] = cap
        g["order"] = [n for n in g["order"] if n != CAPSTONE_ID] + [CAPSTONE_ID]
    # `transfer` is engine-owned and derived from the receipt log — so REBUILD it from evidence
    # rather than leaving the hole a `--replace` punched in it (the same discipline `artifact`
    # already had, and the same one `fsrs` gets via carry-forward).
    by = _by_node(_receipts_for(g["topic"]))
    for nid, node in g["nodes"].items():
        st = node_transfer_state(by.get((g["topic"], nid)))
        if st["receipts"]:
            node["transfer"] = st
    save_graph(g)
    emit({"ok": True, "topic": g["topic"], "nodes": len(g["nodes"]),
          "capstone": CAPSTONE_ID in g["nodes"],
          "schedule_preserved": preserved, "warnings": warnings})

def state_counts(g):
    counts = {"review": 0, "learning": 0, "new": 0}
    nodes = g.get("nodes")
    if not isinstance(nodes, dict):
        return counts           # `nodes` as a string is TRUTHY, so `or {}` never fired here
    for node in nodes.values():
        st = node.get("state", "new") if isinstance(node, dict) else "new"
        if not isinstance(st, str):
            st = "new"          # hand-edited garbage: count it, never crash on it
        counts[st] = counts.get(st, 0) + 1
    return counts

def retired_count(g):
    """Retired nodes in this graph — reported BESIDE `states`, never inside it (v1.3).

    Retirement is not a state (docs/15 §2.2), and a `retired` key sitting among three
    mutually-exclusive states that sum to the node count is bug class #7: the arithmetic is
    right and the reader is deceived. Two different populations never share a container."""
    nodes = g.get("nodes")
    if not isinstance(nodes, dict):
        return 0
    return sum(1 for n in nodes.values() if is_retired(n))

def cmd_topics(_args):
    out = []
    for t, g in iter_graphs():
        states = state_counts(g)
        due_count = 0
        for node in (g.get("nodes") or {}).values():
            if not isinstance(node, dict) or is_retired(node):
                continue                    # retired: off the queue, counted in `states`
            dd = safe_date(_fsrs_of(node).get("due"))
            if node.get("state") != "new" and dd and dd <= today():
                due_count += 1
        out.append({"topic": t, "title": g.get("title"), "goal": g.get("goal"),
                    "nodes": len(g["nodes"]), "states": states, "due": due_count,
                    "retired": retired_count(g)})
    emit(out)

def pending_nodes(topic):
    """Node ids for this topic with a production stashed but not yet graded.

    A stash line can be any JSON after a hand-edit, and an unhashable `node` (a list) would
    poison the set itself — so the shape is checked before the id is admitted, not after."""
    return {e["node"] for e in read_jsonl(p(STASH_FILE))
            if isinstance(e, dict) and e.get("topic") == topic
            and isinstance(e.get("node"), str)}

def valid_artifact(node):
    """The node's registered explorable (stored string) — or None.

    A registration counts only if it is a non-empty string whose file exists.
    File-existence is the discriminator that keeps v0.4-era phantom values out
    of everything downstream: pre-0.5 add-topic silently kept payload-supplied
    artifact strings the engine never validated, and those must never stamp a
    receipt, flag a due item, or survive a --replace. (A registration whose
    file was deleted is equally not evidence — doctor surfaces both cases.)"""
    a = node.get("artifact") if isinstance(node, dict) else None
    if not (isinstance(a, str) and a):
        return None
    return a if os.path.isfile(a if os.path.isabs(a) else p(a)) else None

def node_kind_of(node):
    """The node's knowledge kind, derived defensively (v1.1, docs/11).

    Explicit valid `kind` wins; else `arbitrary: true` means `fact` (the pre-v1.1 marker,
    honored forever); else `concept` — which is also the answer for garbage input, because
    this runs inside read paths that degrade and never brick (RELEASE_PROTOCOL §4.7)."""
    if not isinstance(node, dict):
        return "concept"
    k = node.get("kind")
    if k in NODE_KINDS:
        return k
    if node.get("arbitrary") is True:
        return "fact"
    return "concept"

# Review-session caps, mirroring skills/review §1 — the engine needs them to size the ambient
# offer, and two copies of a number is how they drift.
RETURN_ABSENCE_DAYS = 7   # what counts as "coming back" — ONE constant, shared by
                          # the hook's amnesty, the decay line, and the skills
QUICK_CAP = 5             # `/review quick`, and the Sprint/Focus default
STANDARD_CAP = 12         # the Standard-mode review cap

DUE_ORDERS = ("overdue", "savings")
DUE_HORIZON = 30          # the savings horizon, in days — matches DECAY_HORIZON_DEFAULT
# Expected minutes per item, by current retrievability. A near-forgotten item is not just
# low-value to review, it is SLOW: the learner re-derives it from nothing. Failures cost
# time, and the budget being spent is time, not items (Eglington & Pavlik 2020 — practicing
# at high predicted success beat both hardest-first and easiest-first on retention per unit
# time). These three constants are ENGINEERING, not measurement, and the payload says so.
DUE_MINUTES_BY_R = ((0.70, 0.6), (0.30, 1.0), (0.0, 2.0))
DUE_RELEARN_R = 0.10      # below this, the item is functionally a re-learn, not a review

def _expected_minutes(r_now):
    for floor, minutes in DUE_MINUTES_BY_R:
        if r_now >= floor:
            return minutes
    return DUE_MINUTES_BY_R[-1][1]

def _node_savings(fsrs, t, horizon, retention, im):
    """What reviewing THIS node today buys over `horizon` days, per expected minute.

    Uses exactly the primitives `decay` uses, in the same order, on the same inputs — so the
    two commands can never disagree about the same node (RELEASE_PROTOCOL §4.8 Q1: the
    engine's own commands must agree with each other, and a selftest pins it).

    MODEL-DERIVED, and every payload carrying it says so: one strong human RCT backs the
    POLICY FAMILY (model-predicted-recall-driven selection under an equal budget — Lindsey
    et al. 2014, +16.5% at 28 days, d = 1.42), and simulations back descending-retrievability
    for backlogs, but no human RCT has ever ranked backlog orders. Returns None when the node
    has never been encoded — nothing to save yet.

    ⚠ THE SHAPE OF THIS CURVE, measured rather than assumed (and it is the reason the
    `effectively_relearn` floor exists rather than being decoration). Sweeping stability at a
    fixed horizon, savings/min is an INVERTED U that peaks around R ≈ 0.34:

        R=0.073 -> 0.413   R=0.338 -> 0.659   R=0.753 -> 0.556   R=0.918 -> 0.230

    That peak independently reproduces the θ ≈ 0.33 threshold policy the Lindsey classroom
    deployment actually used — an FSRS knapsack and a human RCT arriving at the same target
    from different directions, which is the strongest thing that can be said for any of this.
    **But the left tail lies:** a near-dead concept scores high because reviewing it
    *resurrects* it, and a one-shot 30-day knapsack cannot see that a resurrection buys
    several more reviews of future budget. Every budgeted analysis in the record says do not
    serve the hopeless first. So items below `DUE_RELEARN_R` are PARKED (sorted last, flagged)
    rather than allowed to win the cap — the ranking keeps the peak and drops the tail."""
    s, last = as_number(fsrs.get("s")), safe_date(fsrs.get("last"))
    if s is None or last is None:
        return None
    elapsed = max(0, (t - last).days)
    r_now = retrievability(elapsed, s)
    r_no_review = retrievability(elapsed + horizon, s)
    after, _ = apply_rating(dict(fsrs, retention=retention, im=im), "good", t)
    r_if_reviewed = retrievability(horizon, as_number(after.get("s"), s))
    minutes = _expected_minutes(r_now)
    return {
        "r_now": round(r_now, 3),
        "savings": round(r_if_reviewed - r_no_review, 4),
        "expected_minutes": minutes,
        "savings_per_min": round((r_if_reviewed - r_no_review) / minutes, 4),
        "effectively_relearn": r_now < DUE_RELEARN_R,
    }

def is_retired(node):
    """Has the learner retired this node? (v1.3, docs/15 §2.2 — ONE predicate, every reader.)

    Retirement is a LEARNER DECISION, not a mastery event, so it deliberately does NOT use
    the `state` enum: a fourth state value would ripple through every state reader, and — the
    reason that mattered most — the capstone `requires` every node, so a retired node would
    block the capstone forever. Instead the decision lives in its own engine-owned block and
    every population asks this one function (docs/09 §2's rule about predicates: one
    implementation, or three of the four call sites are wrong).

    Value-directed remembering (Castel): learners are already strategic droppers, and honoring
    that is autonomy. What it must NEVER become is a flattering denominator — so every
    population that drops a retired node COUNTS it and says so (adherence.loop_closure's
    `retired_excluded`, retention.unmeasured's `retired`).

    Shape-defensive: a hand-edited `retired: "yes"` is not a retirement (reads degrade)."""
    if not isinstance(node, dict):
        return False
    r = node.get("retired")
    return isinstance(r, dict) and r.get("restored") is None

def retired_keys():
    """(topic, node) for every currently-retired node — the set the receipt-keyed metrics
    need, since receipts know nothing about a decision recorded on the graph."""
    out = set()
    for t, g in iter_graphs():
        for nid, node in (g.get("nodes") or {}).items():
            if isinstance(nid, str) and is_retired(node):
                out.add((t, nid))
    return out

def _requires_of(node):
    """The node's `requires` edges — string ids only. `edges` can be a string after a
    hand-edit, and `requires` can hold a dict, which is unhashable and crashes an `in`."""
    edges = node.get("edges")
    reqs = edges.get("requires") if isinstance(edges, dict) else None
    return [r for r in reqs if isinstance(r, str)] if isinstance(reqs, list) else []

def requires_met(g, node, provisional=frozenset(), nodes=None):
    nodes = graph_nodes(g) if nodes is None else nodes
    # A stashed-but-ungraded prerequisite counts as PROVISIONALLY met for an ordinary node, so
    # the batch-graded /learn flow can keep teaching while the assessor works. **The capstone
    # gets no such credit.** It is the claim that the learner can now USE the topic, and serving
    # it on prerequisites the assessor has not yet confirmed would build the culmination of the
    # course on unverified mastery — "no mastery without a receipt" is the constitution, and the
    # capstone is where that rule matters most. Provisional advancement is a UX affordance; the
    # capstone's requires are a claim about readiness.
    prov = frozenset() if node.get("capstone") is True else provisional
    for req in _requires_of(node):
        other = nodes.get(req)
        # A RETIRED prerequisite counts as satisfied (v1.3). The learner declared it
        # not-needed; gating every dependent on it forever would make `retire` a trap rather
        # than an autonomy verb — you would silently lose the rest of the topic by exercising
        # it. The tutor may still brief the gap in prose; the DAG does not hold the learner
        # hostage to a decision they were invited to make.
        if other is not None and is_retired(other):
            continue
        if other is not None and other.get("state") == "new" and req not in prov:
            return False
    return True

def cmd_next(args):
    g = load_graph(args.topic)
    nodes = graph_nodes(g)
    stashed = pending_nodes(args.topic)  # already-produced, awaiting the assessor
    for nid in graph_order(g, nodes):
        node = nodes[nid]
        if node.get("state") != "new" or nid in stashed:
            continue  # skip a node whose production is already stashed
        if is_retired(node):
            continue  # the learner took it off the list (v1.3); `requires_met` treats it as
                      # satisfied, so retiring a prerequisite opens the frontier, never seals it
        # A stashed-but-ungraded prerequisite counts as provisionally met, so the
        # batch-graded /learn flow can keep advancing instead of dead-ending.
        if requires_met(g, node, stashed, nodes):
            reqs = [r for r in _requires_of(node) if r in nodes]
            emit({"topic": args.topic, "id": nid, "node": node,
                  "requires_claims": {r: nodes[r].get("claim") for r in reqs},
                  "provisional_requires": [r for r in reqs
                                           if r in stashed and nodes[r].get("state") == "new"],
                  "pending_verify": len(stashed),
                  "remaining_new": sum(1 for n in nodes.values() if n.get("state") == "new")})
            return
    # The frontier is empty. On a v0.8 graph the capstone IS a node and would have been served
    # above; a pre-v0.8 graph has none, so say so — and say the command, because "propose the
    # build" as a line of skill prose is exactly what has been silently not happening.
    has_cap = _has_capstone(nodes)
    emit({"topic": args.topic, "id": None, "pending_verify": len(stashed),
          "capstone": {"exists": has_cap,
                       "materialize": (None if has_cap else
                                       "python3 engram.py capstone --topic %s" % args.topic)},
          "note": ("frontier nodes remain but are awaiting assessor grading — "
                   "grade the stash to advance" if stashed else
                   ("every concept is encoded and the capstone is done or pending — "
                    "this topic is finished" if has_cap else
                    "every concept is encoded, and this topic has NO CAPSTONE. The build is "
                    "the point of the whole topic; materialize it so it cannot be skipped."))})

def due_items(topic_filter=None, limit=None, horizon_days=0, order="overdue"):
    """The due queue. `order` decides WHICH items a capped session gets (v1.3).

    `overdue` is the order Engram has always served (most-overdue first, interleaved across
    topics) and remains the default for an UNCAPPED queue, where order is cosmetic.

    `savings` exists because a CAPPED session is a triage decision, and most-overdue-first is
    the one policy every budgeted analysis ranks last: a deeply overdue item sits on the flat
    tail of its forgetting curve and loses almost nothing more by waiting, while the
    near-threshold item is the one still cheap to save. It ranks by expected retention saved
    per expected minute (`_node_savings`). MODEL-DERIVED — the caller must carry
    `order_basis` into the payload, because no human RCT has ever ranked backlog orders."""
    per_topic = {}
    cutoff = today() + timedelta(days=horizon_days)
    model = read_model()
    _ret = as_number(model["memory"].get("desired_retention"), RETENTION_DEFAULT)
    _im = as_number(model["memory"].get("interval_multiplier"), 1.0)
    # v0.8: a due node that is MATURE enough for the harder question is flagged here, so
    # /review can serve the architect's `transfer_probe` instead of the ordinary probe without
    # a second engine call. The flag is computed, never guessed — and a node with a null
    # transfer_probe can never carry it.
    _tnodes = _by_node(collect_receipts())
    _t = today()
    for t, g in iter_graphs(topic_filter):
        items = []
        for nid in (g.get("order") or []):
            if not isinstance(nid, str):
                continue  # unhashable/typed junk in `order` would raise on dict.get()
            node = (g.get("nodes") or {}).get(nid)
            if not isinstance(node, dict):
                continue  # ghost id in order, or a hand-edited non-object node
            if is_retired(node):
                continue  # the learner took it off their list — it is COUNTED in
                          # adherence.loop_closure.retired_excluded and
                          # retention.unmeasured.retired, never silently dropped (v1.3)
            fsrs = _fsrs_of(node)
            due_d = safe_date(fsrs.get("due"))
            if node.get("state") == "new" or not due_d:
                continue
            if due_d <= cutoff:
                items.append({
                    "topic": t, "id": nid, "probe": node.get("probe"),
                    "claim": node.get("claim"), "rubric": node.get("rubric", []),
                    "threshold": node.get("threshold", False),
                    "arbitrary": node.get("arbitrary", False),
                    # lets /review's re-encode path know an explorable already exists
                    # (regenerate, don't duplicate) without loading the graph —
                    # validated, so hand-edited garbage can't fake one
                    "artifact": valid_artifact(node) is not None,
                    "due": fsrs.get("due"),
                    "overdue_days": (today() - due_d).days,
                    # `last` (the last successful retrieval) is carried so current
                    # retrievability can be computed EXACTLY. Reconstructing elapsed from
                    # `interval_for(s, RETENTION_DEFAULT) + overdue` is wrong the moment a
                    # learner changes `desired_retention` or carries an `interval_multiplier`
                    # — and it errs toward overstating the decay, which is the one direction
                    # an honesty feature is not allowed to err in.
                    "last": fsrs.get("last"),
                    "s": fsrs.get("s"), "reps": fsrs.get("reps", 0),
                    "lapses": fsrs.get("lapses", 0),
                    # v0.8: mature enough for the harder question? /review serves the
                    # transfer_probe instead of the probe, and the receipt gets kind=transfer.
                    # v0.8.1: the SLOT goes with it — maturity counts RETRIEVALS from the receipt
                    # log, not `fsrs.reps` (which includes the encode). Omitting it read 0
                    # retrievals for every node and silently flagged nothing, ever.
                    "transfer_ready": _transfer_ready(
                        node, node_transfer_state(_tnodes.get((t, nid))), _t,
                        _tnodes.get((t, nid))),
                    "transfer_probe": node.get("transfer_probe"),
                    "capstone": node.get("capstone") is True,
                    # v1.1 (docs/11 P17): the knowledge kind + practice block ride the due
                    # payload so /review can serve a procedure node a FRESH problem instance
                    # (never the stored numbers) without a second engine call. `node_kind`,
                    # not `kind` — a receipt's `kind` is the event, and the two must never
                    # share a name. Absent/garbage practice degrades to None (probe fallback).
                    "node_kind": node_kind_of(node),
                    "practice": (node.get("practice")
                                 if isinstance(node.get("practice"), dict) else None),
                })
                if order == "savings":
                    sv = _node_savings(fsrs, today(), DUE_HORIZON, _ret, _im)
                    # A due node always has an `s` and a `last`, so sv is None only for
                    # hand-edited state — in which case it sorts last rather than crashing.
                    items[-1].update(sv or {"savings_per_min": 0.0, "expected_minutes": None,
                                            "effectively_relearn": False})
        items.sort(key=lambda x: -x["overdue_days"])
        if items:
            per_topic[t] = items
    # interleave topics round-robin (P3: interleaving is the default)
    merged = []
    while any(per_topic.values()):
        for t in list(per_topic):
            if per_topic[t]:
                merged.append(per_topic[t].pop(0))
    if order == "savings":
        # Effectively-lost items sort LAST whatever their raw savings (see `_node_savings`:
        # the left tail of the curve rewards resurrection, and every budgeted analysis says
        # do not spend a capped session there). Stable within each group, so the interleaved,
        # most-overdue-first arrangement survives the re-rank rather than collapsing to one
        # topic (P3: interleaving is the default).
        merged.sort(key=lambda x: (bool(x.get("effectively_relearn")),
                                   -(x.get("savings_per_min") or 0.0)))
    if limit is not None:
        merged = merged[:limit]
    return merged

DUE_ORDER_BASIS = ("model-derived (FSRS projection: expected 30-day retention saved per "
                   "expected minute); the POLICY FAMILY has one strong human RCT behind it "
                   "(Lindsey et al. 2014) but no human RCT has ever ranked backlog orders — "
                   "docs/13 §2.2. NOTE `expected_minutes` is a RANKING WEIGHT (it prices a "
                   "cold item as slower), never a session estimate: `decay` and the session "
                   "hook size a session at ~0.6 min/item, and that is the only figure to "
                   "quote to a learner.")

def cmd_due(args):
    """Legacy `--limit` emits the bare list, byte-identically, in the order it always did.

    `--cap` is the v1.3 path: it defaults to `savings` ordering and therefore MUST emit the
    honesty label with it, which means an object rather than a list. Keeping the two shapes
    apart is deliberate — an older skill file calling `--limit` against a newer engine must
    not receive a shape it cannot parse, and a model-derived ranking must never travel
    without its basis (docs/14 §0.5)."""
    # getattr, not attribute access: internal callers (selftest, the fuzzer) build namespaces
    # from the v1.2.2 signature, and a read path must never raise on a missing optional flag.
    req_order, req_cap = getattr(args, "order", None), getattr(args, "cap", None)
    order = req_order or ("savings" if req_cap is not None else "overdue")
    if order not in DUE_ORDERS:
        die("unknown order '%s' (choose: %s)" % (order, ", ".join(DUE_ORDERS)))
    cap = req_cap if req_cap is not None else getattr(args, "limit", None)
    items = due_items(args.topic, cap, order=order)
    if req_cap is None and req_order is None:
        emit(items)                      # the v1.2.2 contract, untouched
        return
    emit({"order": order,
          "order_basis": DUE_ORDER_BASIS if order == "savings" else
                         "the order Engram has always served: most overdue first, interleaved",
          "cap": cap, "n": len(items), "items": items})

def gen_id(prefix):
    # pid + monotonic seq: unique within and across processes, even same-ms.
    return "%s_%d_%d_%03d" % (prefix, int(time.time() * 1000), os.getpid(), next(_SEQ))

def clean_confidence(conf):
    """0-100 int, or None. Never crashes on a bad type; never invents a number."""
    v = as_number(conf)
    if v is None:
        return None
    return int(round(clamp(v, 0.0, 100.0)))

def make_receipt(item, extra, kind):
    prod = item.get("production") or ""
    truncated = len(prod) > PRODUCTION_MAX
    receipt = {
        "id": gen_id("r"),
        "ts": today().isoformat(),
        "topic": item["topic"], "node": item["node"],
        "kind": kind,
        "probe": item.get("probe"),
        "production": (prod[:PRODUCTION_MAX] or None),
        "confidence": clean_confidence(item.get("confidence")),
        "grade": item.get("grade"),
        "rating": item["rating"],
        "misconceptions": item.get("misconceptions", []),
        "rubric_notes": item.get("rubric_notes"),
        "source": item.get("source", "self"),
        **extra,
    }
    # The stash id, threaded stash -> assessor -> receipt, is what makes `receipt --file`
    # idempotent: apply_item refuses a sid already on disk (issue #3). Absent on hand-rolled
    # `rate` calls, which is fine — they were never the double-apply risk.
    sid = item.get("sid")
    if isinstance(sid, str) and sid:
        receipt["sid"] = sid
    # The controlling error on a graded production (v1.1): `slip` (method right, execution
    # slipped) vs `conceptual` (the model was wrong). Validated upstream (validate_item);
    # absent on every pre-v1.1 receipt and on any grading that didn't classify — absence
    # stays honestly absent, it is never inferred.
    ec = item.get("error_class")
    if ec in ERROR_CLASSES:
        receipt["error_class"] = ec
    # Which grader produced this verdict (v0.7, docs/09 §3.3). Recorded when the assessor
    # states it, NEVER invented: a model guessing its own model-id is exactly the fabricated
    # data this repo bans, and v1.0's export must be able to carry each receipt's grader so
    # a shared finding can be weighted by that grader's MEASURED QWK. No v0.7 number keys
    # off it, so an assessor that omits it costs nothing today — it just stays honestly null.
    grader = item.get("grader")
    if isinstance(grader, str) and grader:
        receipt["grader"] = grader[:64]
    if truncated:
        receipt["production_truncated"] = True
    return receipt

# Receipt log cache, keyed by ABSOLUTE PATH (never by topic alone — selftest and any
# ENGRAM_HOME switch would otherwise read one home's receipts while writing another's).
# `cmd_receipt` applies a batch, and each item needs both the sid set and the node's
# first-receipt ts; re-reading the whole log per item is O(items x receipts) — measured at
# 1.85s for a 60-item settle against a 10k-line log. The cache is kept in sync on every
# append, so a sid written *earlier in the same batch* is still caught, which it must be:
# a batch can legitimately carry the same sid twice.
_RECEIPTS_CACHE = {}

def _receipts_for(topic):
    path = p("receipts", topic + ".jsonl")
    if path not in _RECEIPTS_CACHE:
        _RECEIPTS_CACHE[path] = read_jsonl(path)
    return _RECEIPTS_CACHE[path]

def _cache_receipt(topic, receipt):
    """Keep the cache honest after an append (populate-from-disk first, then append)."""
    _receipts_for(topic).append(receipt)

def _seen_sids(topic):
    """Stash ids already applied for this topic — the idempotency guard (issue #3)."""
    return {r.get("sid") for r in _receipts_for(topic) if isinstance(r.get("sid"), str)}

def _first_receipt_ts(topic, node):
    """Day 0 for a node: the ts of its earliest receipt. Receipts are append-only, so the
    first matching line IS the earliest — no sort needed. Returns None on first exposure."""
    for r in _receipts_for(topic):
        if r.get("node") == node:
            return r.get("ts")
    return None

def validate_item(item):
    """Raise (die) if an item can't be applied. Lets a batch fail before any write."""
    for key in ("topic", "node", "rating"):
        if key not in item:
            die("receipt item missing %s: %s" % (key, json.dumps(item)[:120]))
    require_slug(item["topic"])
    if not isinstance(item["rating"], str) or item["rating"] not in RATINGS:
        die("bad rating %r (use again|hard|good|easy)" % item["rating"])
    if item.get("grade") is not None and item["grade"] not in GRADES:
        die("bad grade %r (use recalled|partial|lapsed)" % item["grade"])
    k = item.get("kind")
    if k is not None and k not in KINDS:
        die("bad kind %r (use %s) — an invented kind is invisible to every metric and "
            "receipts are append-only, so it could never be corrected"
            % (k, "|".join(KINDS)))
    ec = item.get("error_class")
    if ec is not None and ec not in ERROR_CLASSES:
        die("bad error_class %r (use %s) — a typo'd class would ride an append-only "
            "receipt forever and silently vanish from the slip/conceptual split"
            % (ec, "|".join(ERROR_CLASSES)))

def drop_stash(topic, node):
    """Remove applied (topic, node) entries so the stash self-drains as receipts land."""
    path = p(STASH_FILE)
    entries = read_jsonl(path)
    keep = [e for e in entries if not (e.get("topic") == topic and e.get("node") == node)]
    if len(keep) != len(entries):
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        for e in keep:
            append_jsonl(path, e)

def drop_stash_sid(topic, sid):
    """Remove exactly the stash entry with this sid — the surgical sibling of drop_stash.

    drop_stash() drains every entry for a (topic, node), which is right when a receipt has
    just been APPLIED to that node. It is wrong on the idempotent no-op path: a second,
    never-graded production for the same node would be destroyed along with the already-
    settled one."""
    path = p(STASH_FILE)
    entries = read_jsonl(path)
    keep = [e for e in entries if not (e.get("topic") == topic and e.get("sid") == sid)]
    if len(keep) != len(entries):
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        for e in keep:
            append_jsonl(path, e)

def apply_item(item, kind):
    validate_item(item)
    g = load_graph(item["topic"])
    node = g["nodes"].get(item["node"])
    if node is None:
        die("unknown node %s in topic %s" % (item["node"], item["topic"]))
    if not isinstance(node, dict):
        # REFUSE, never crash and never coerce: advancing a schedule into a corrupt node
        # would write FSRS state on top of garbage, and receipts are append-only — the bad
        # evidence could never be taken back. `doctor` reports it; this declines to make it worse.
        die("node %s in topic %s is corrupt (an object was expected, found %s) — run `doctor`, "
            "then fix graphs/%s.json before rating it"
            % (item["node"], item["topic"], type(node).__name__, item["topic"]))
    # Idempotency (issue #3): a settle that already landed must be a no-op, not a second
    # application. `receipt --file` re-run after a crash between `receipt` and `stash clear`
    # used to double-count reps, append an indistinguishable duplicate receipt, and skew
    # stats/calibration/refit permanently. The stash id is the transaction id.
    sid = item.get("sid")
    if isinstance(sid, str) and sid and sid in _seen_sids(item["topic"]):
        # Drop ONLY the stash entry carrying THIS sid — never every entry for (topic, node).
        # A node can legitimately hold two stashed productions (a re-attempt after a park, a
        # second pass in one session). Draining by (topic, node) on the no-op path would
        # silently destroy a NEWER, differently-sid'd, never-graded production: the
        # idempotency guard would itself have become a data-loss bug. Found by adversarial
        # review; my own dogfood missed it.
        drop_stash_sid(item["topic"], sid)
        return {"node": item["node"], "topic": item["topic"], "applied": False,
                "idempotent": True, "sid": sid,
                "note": "receipt already applied — no-op (idempotency guard, issue #3)"}
    # ⚠ THE MATURITY BAR AT *INGEST*, not just at selection (v0.8.1).
    #
    # `_transfer_ready` guarded the SELECTION path and nothing guarded the WRITE path — so a bare
    # CLI `rate --kind transfer` on a node encoded yesterday certified `transfer.state: applied`
    # and `owned` on 24 hours of memory, while `transfer` itself returned zero candidates: the
    # engine refused to probe the very node it had just certified. That is §4.8 Q5 exactly — the
    # skills always pass what the engine expects, and the CLI is the door nobody guards.
    #
    # The capstone is exempt: it has no maturity, because it has no encoding phase. The build IS
    # the event.
    if kind == "transfer" and node.get("capstone") is not True:
        slot = _by_node(_receipts_for(item["topic"])).get((item["topic"], item["node"]))
        f = _fsrs_of(node)
        s, rr = as_number(f.get("s")), _retrievals(slot)
        if s is None or s <= TRANSFER_MATURE_S or rr < TRANSFER_MATURE_REPS:
            die("refusing a TRANSFER receipt on an immature node (%s/%s: stability %s, %d "
                "retrieval%s). Transfer asks whether a memory FIRES in new clothes — asking it "
                "of a memory that has not survived %dd across %d retrievals measures working "
                "memory, and failing it would be a fabricated setback. Review it first."
                % (item["topic"], item["node"],
                   ("%.1fd" % s) if s is not None else "none",
                   rr, "" if rr == 1 else "s",
                   int(TRANSFER_MATURE_S), TRANSFER_MATURE_REPS))
    # ⚠ AN AUDIT RECEIPT INFORMS; IT NEVER RESCHEDULES (v1.4, docs/15 §2.3).
    #
    # `/review` has spawned the blind assessor to spot-audit the tutor's own grades since
    # v0.2 — and the result was narrated once and then evaporated. `KINDS` has carried an
    # `audit` slot the whole time with nothing writing it. That is the transfer_probe defect
    # on the ONE grader `/coach audit` can never measure: the tutor writes every `/review`
    # receipt and every `error_class` behind `procedure_slip_share`, in-context, with the
    # dialogue in front of it, and nothing has ever checked it.
    #
    # So the verdict is now evidence on disk — and it touches NOTHING. No FSRS state, no node
    # state, no schedule, no `reps`. `/review`'s rule has always been "audits inform, they
    # don't reschedule" (re-rating an already-committed item would let a second opinion
    # silently rewrite a schedule the learner already acted on); this makes that structural
    # rather than a sentence in a skill file.
    if kind == "audit":
        extra = {"audited_rating": item.get("audited_rating"),
                 "agree": (bool(item["agree"]) if isinstance(item.get("agree"), bool)
                           else None),
                 "node_kind": node_kind_of(node)}
        receipt = make_receipt(item, extra, kind)
        append_jsonl(p("receipts", "%s.jsonl" % item["topic"]), receipt)
        _cache_receipt(item["topic"], receipt)
        if isinstance(sid, str) and sid:
            drop_stash_sid(item["topic"], sid)
        else:
            drop_stash(item["topic"], item["node"])
        return {"node": item["node"], "topic": item["topic"], "kind": "audit",
                "applied": True, "scheduled": False,
                "audited_rating": receipt.get("audited_rating"),
                "assessor_rating": receipt.get("rating"),
                "agree": receipt.get("agree"),
                "note": ("audit recorded — the schedule is untouched. It measures the TUTOR "
                         "against the blind assessor; see stats.self_grading.")}
    rating = item["rating"]
    model = load_model()
    node.setdefault("fsrs", _fresh_fsrs())
    node["fsrs"]["retention"] = as_number(model["memory"].get("desired_retention"), RETENTION_DEFAULT)
    node["fsrs"]["im"] = as_number(model["memory"].get("interval_multiplier"), 1.0)
    was_new = as_number(node["fsrs"].get("s")) is None

    # ⚠ A FAILED TRANSFER PROBE MUST NOT PUNISH THE MEMORY SCHEDULE (v0.8.1).
    #
    # v0.8 separated the three populations in the METRICS and pooled them in the SCHEDULER. On a
    # mature node — the only kind the system ever probes — one failed transfer probe did this:
    #
    #     s: 443.5 -> 12.3      (97% of the memory's durability, deleted)
    #     state: review -> learning     lapses: 0 -> 1     due: 2027-03-01 -> 2026-03-17
    #
    # …and dropped the node below the transfer bar, so it could never be re-probed. **Answering a
    # HARDER question wrong demolished the schedule for the ORIGINAL concept.** It contradicted
    # three separate sentences this very release shipped:
    #
    #   skills/review  — "A lapse here is NOT a memory failure and must never be framed as one."
    #   skills/coach   — "A transfer lapse is not a memory failure. Do not frame it as a setback."
    #   _transfer_ready — "failing it would be a lapse the schedule then punishes — A FABRICATED
    #                      SETBACK." (The maturity gate was built to prevent exactly this, and
    #                      only ever guarded IMMATURE nodes.)
    #
    # The learner remembers the concept. The capability just did not fire. Those are different
    # facts about different things, and the schedule is only allowed to hear about the first.
    # So a transfer LAPSE leaves `fsrs` untouched — and the receipt records `s_before == s_after`,
    # so the evidence stays honest about the fact that nothing moved. A transfer SUCCESS still
    # strengthens the memory, because applying an idea IS a retrieval, and a strong one.
    transfer_lapse = (kind == "transfer" and GRADE_OF_RATING.get(rating) == "lapsed")
    if transfer_lapse:
        f = node["fsrs"]
        s_now = as_number(f.get("s"))
        extra = {"s_before": s_now, "s_after": s_now, "interval_days": None,
                 "retrievability": None,
                 "schedule_unchanged": "a failed TRANSFER probe does not lapse the memory — "
                                       "the concept is remembered; the capability did not fire"}
        f.pop("retention", None)
        f.pop("im", None)
    else:
        node["fsrs"], extra = apply_rating(node["fsrs"], rating, today())
        node["fsrs"].pop("retention", None)
        node["fsrs"].pop("im", None)
    if transfer_lapse:
        pass                                  # state is untouched: the memory did not lapse
    elif rating == "again":
        node["state"] = "learning"
    elif was_new and rating == "hard":
        node["state"] = "learning"
    else:
        node["state"] = "review"
    # Evidence before state (Article 10): write the receipt first, so a crash can
    # only ever cost a harmless re-review — never advance mastery without a receipt.
    # Stamp the medium at grading time (had this node an explorable *now*?) so the
    # modality comparison in `stats` reads the receipt, never the current graph —
    # an artifact added later must not rewrite which arm old evidence belonged to.
    # Validated (file must exist): a v0.4 phantom string or a deleted explorable
    # is not evidence of the medium, and a wrong stamp is append-only forever.
    if valid_artifact(node):
        extra = {**extra, "artifact": True}
    # The knowledge-kind stamp (v1.1), recorded at grading time like the `artifact` medium
    # stamp — `stats.by_kind` reads the receipt, never the current graph, so a later graph
    # edit (or a topic rebuild that reclassifies a node) can never rewrite which kind old
    # evidence belonged to. Closed enum by construction (node_kind_of).
    extra = {**extra, "node_kind": node_kind_of(node)}
    # Day 0 is the node's FIRST receipt. Stamping elapsed-days here is what makes the north
    # star (retention at 7/30/90 days — docs/04 named it in Phase 0 and never built it) a
    # one-pass query over the receipt log instead of a join against the graph. On first
    # exposure there is no prior receipt, so this is 0 by construction.
    enc_ts = _first_receipt_ts(item["topic"], item["node"])
    dse = days_between(enc_ts, today().isoformat()) if enc_ts else 0
    # clamp: a backward clock step (or a hand-edited ts) would otherwise stamp a
    # negative elapsed-day count into an append-only receipt, permanently.
    extra = {**extra, "days_since_encode": max(0, dse or 0)}
    # The capstone stamp, recorded at grading time like the `artifact` medium stamp — so `_by_node`
    # can tell a capstone's FIRST receipt (which is its build, a transfer) from an ordinary node's
    # first receipt (which is its encoding), while staying a pure function of the receipt log.
    if node.get("capstone") is True:
        extra = {**extra, "capstone": True}
    receipt = make_receipt(item, {**extra, "due_next": node["fsrs"].get("due")}, kind)
    append_jsonl(p("receipts", item["topic"] + ".jsonl"), receipt)
    _cache_receipt(item["topic"], receipt)   # a duplicate sid later in THIS batch must still be caught
    # THE CAPABILITY CLAIM (v0.8). `node.transfer` is engine-owned and written ONLY here, only
    # by a transfer-kind receipt — the same discipline as `fsrs`. Derived from the receipt log
    # (which is append-only and therefore the truth), never accumulated in place, so it can
    # never drift from the evidence that produced it.
    if kind == "transfer":
        slot = _by_node(_receipts_for(item["topic"])).get((item["topic"], item["node"]))
        node["transfer"] = node_transfer_state(slot)
    save_graph(g)
    # Drain ONLY the stash entry this receipt settles. v0.6.0 fixed this on the rare
    # idempotent-no-op branch and left it broken on the branch that runs EVERY time: a node
    # can legitimately hold two stashed productions (a re-attempt, a second pass, a session
    # resumed after a park — `stash add` appends without deduping on node), and draining by
    # (topic, node) silently destroyed the newer, never-graded one. A learner's real work,
    # gone, with no trace. Sid-less receipts (the legacy bare-`rate` path, which never had a
    # stash entry to lose) keep the old self-drain.
    if isinstance(sid, str) and sid:
        drop_stash_sid(item["topic"], sid)
    else:
        drop_stash(item["topic"], item["node"])
    result = {"node": item["node"], "rating": rating, "state": node["state"],
              "due": node["fsrs"]["due"], "applied": True, **extra}
    if item.get("grade") and GRADE_OF_RATING.get(rating) != item["grade"]:
        result["grade_rating_mismatch"] = "grade=%s but rating=%s" % (item["grade"], rating)
    return result

def cmd_rate(args):
    production = args.production
    if getattr(args, "production_file", None):
        try:
            production = _read_text(args.production_file)
        except OSError:
            die("cannot read --production-file: %s" % args.production_file)
    item = {"topic": args.topic, "node": args.node, "rating": args.rating,
            "confidence": args.confidence, "production": production,
            "grade": args.grade, "probe": args.probe, "source": args.source,
            "error_class": getattr(args, "error_class", None)}
    ar = getattr(args, "audited_rating", None)
    if ar is not None:
        if args.kind != "audit":
            die("--audited-rating is only meaningful on `--kind audit` (it records what the "
                "TUTOR graded, so the blind assessor's verdict can be compared to it). A "
                "rating-bearing audit of the wrong kind would reschedule the node.")
        item["audited_rating"] = ar
    emit(apply_item(item, args.kind))

def cmd_receipt(args):
    payload = load_payload(args)
    items = payload if isinstance(payload, list) else [payload]
    # Validate every item AND confirm every node exists AND IS USABLE before applying ANY, so a
    # bad item (a hallucinated node id, a corrupt node) can't half-apply the batch.
    #
    # The pre-flight used to check EXISTENCE only. v0.7 then added a `die()` inside `apply_item`
    # for a corrupt (non-dict) node — a new abort path the pre-flight did not screen for — so a
    # 3-item batch whose middle node was corrupt wrote item 1's receipt and then died. Receipts
    # are APPEND-ONLY: a half-applied batch cannot be taken back, and a sid-less batch would
    # double-apply item 1 on the retry. A new refusal must be hoisted into the pre-flight, or it
    # is not a refusal — it is a tear. (Found by the independent reviewer.)
    for item in items:
        validate_item(item)
        g = load_graph(item["topic"])
        node = g.get("nodes", {}).get(item["node"])
        if node is None:
            die("unknown node %s in topic %s" % (item["node"], item["topic"]))
        if not isinstance(node, dict):
            die("node %s in topic %s is corrupt (an object was expected, found %s) — run "
                "`doctor`; NOTHING in this batch was applied"
                % (item["node"], item["topic"], type(node).__name__))
    results = [apply_item(item, item.get("kind", "encode")) for item in items]
    emit(results)

def cmd_stash(args):
    path = p(STASH_FILE)
    if args.action == "add":
        payload = load_payload(args)
        items = payload if isinstance(payload, list) else [payload]
        for item in items:
            for key in ("topic", "node", "probe", "production"):
                if key not in item:
                    die("stash item missing %s" % key)
            require_slug(item["topic"])
            item.setdefault("ts", today().isoformat())
            # The stash id is the settle transaction id: it rides stash -> assessor ->
            # receipt, and apply_item refuses one already on disk. This is what makes
            # `receipt --file` idempotent and closes the crash-retry window (issue #3).
            item.setdefault("sid", gen_id("s"))
            prod = item.get("production") or ""
            if len(prod) > PRODUCTION_MAX:   # bound stash growth (matches receipt cap)
                item["production"] = prod[:PRODUCTION_MAX]
                item["production_truncated"] = True
            append_jsonl(path, item)
        emit({"ok": True, "pending": len(read_jsonl(path))})
    elif args.action == "list":
        emit(read_jsonl(path))
    elif args.action == "count":
        emit({"pending": len(read_jsonl(path))})
    elif args.action == "clear":
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        emit({"ok": True, "pending": 0})

# known numeric leaf keys -> (lo, hi) clamp, so a typo can't wreck the scheduler
MODEL_NUMERIC_BOUNDS = {
    "memory.desired_retention": (RETENTION_MIN, RETENTION_MAX),
    "memory.interval_multiplier": (MULTIPLIER_MIN, MULTIPLIER_MAX),
    "challenge_band.target_success": (0.0, 1.0),
    "challenge_band.hint_budget": (0, 8),
}

def cmd_model(args):
    m = load_model()
    changed = False
    if args.set:
        for assignment in args.set:
            if "=" not in assignment:
                die("--set expects key=value, got %r" % assignment)
            key, _, raw = assignment.partition("=")
            val = raw
            for cast in (int, float):
                try:
                    val = cast(raw)
                    break
                except ValueError:
                    continue
            if raw in ("true", "false"):
                val = (raw == "true")
            if raw.lower() in ("null", "none"):
                val = None   # clear a nullable setting (e.g. settings.profile=null)
            parts = key.split(".")
            if parts[0] not in m:
                die("unknown model key: %s" % parts[0])
            # walk to the parent, refusing to traverse or clobber a container
            ref = m
            for part in parts[:-1]:
                nxt = ref.get(part) if isinstance(ref, dict) else None
                if nxt is None:
                    nxt = ref[part] = {}
                elif not isinstance(nxt, dict):
                    die("cannot set %s: %r is not an object" % (key, part))
                ref = nxt
            leaf = parts[-1]
            if isinstance(ref.get(leaf), (dict, list)) and not isinstance(val, (dict, list)):
                die("refusing to overwrite object/list key %r with a scalar — "
                    "set a leaf field instead (e.g. %s.<field>=value)" % (leaf, key))
            bounds = MODEL_NUMERIC_BOUNDS.get(key)
            if bounds is not None:
                if not isinstance(val, (int, float)) or isinstance(val, bool):
                    die("%s expects a number in [%s, %s]" % (key, bounds[0], bounds[1]))
                val = clamp(val, bounds[0], bounds[1])
            ref[leaf] = val
            changed = True
    for interest in (args.add_interest or []):
        if interest not in m["interests"]:
            m["interests"].append(interest)
            changed = True
    for goal in (getattr(args, "add_goal", None) or []):
        if goal not in m["goals"]:
            m["goals"].append(goal)
            changed = True
    if changed:
        write_json(p("learner-model.json"), m)
    emit(m)

def cmd_focus(args):
    """Toggle the ADHD Focus profile (`settings.profile`) — a discoverable wrapper
    over `model --set settings.profile=...`. The skills read the flag and turn UP
    dials they already honor (Sprint default, competence growth surfaced every
    review, always-on amnesty). No new pedagogy, no gamification; a declared need,
    honored. See docs/05-affective-layers.md, "The ADHD question"."""
    m = load_model()
    if args.action in ("on", "off"):
        m["settings"]["profile"] = "adhd" if args.action == "on" else None
        write_json(p("learner-model.json"), m)
    prof = m["settings"].get("profile")
    emit({"profile": prof, "focus_active": prof == "adhd",
          "note": ("Focus on: Sprint default, growth surfaced every review, always-on amnesty."
                   if prof == "adhd" else "Focus off: standard defaults.")})

VISUALS_LEVELS = {"eager": "eager", "threshold": "threshold-only", "off": "off"}
VISUALS_NOTES = {
    "eager": ("Eager: explorables for threshold nodes AND any node whose content has real "
              "visual affordance (the architect's viz hint). The medium's yield for you is "
              "measured (stats.modality) — evidence can talk you back down."),
    "threshold-only": ("Threshold-only (default): explorables for the few portal concepts "
                       "per topic. You can always ask for one on any node."),
    "off": "Off: no explorables are built. Dialogue still dual-codes (ASCII sketches, tables).",
}

def cmd_visuals(args):
    """Toggle the visual-encoding dial (`settings.artifacts`) — a discoverable wrapper
    over `model --set settings.artifacts=...`, sibling to `focus`. The levels gate when
    the artifact-smith fires; content-appropriateness stays with the node's viz hint
    (Willingham: match the content, not the learner) and the learner can request an
    explorable on any node regardless of level. docs/06-visual-encoding.md."""
    m = load_model()
    if args.action in VISUALS_LEVELS:
        m["settings"]["artifacts"] = VISUALS_LEVELS[args.action]
        write_json(p("learner-model.json"), m)
    cur = m["settings"].get("artifacts", "threshold-only")
    # hand-edited to garbage (any type): report the raw value, describe the default
    if not isinstance(cur, str) or cur not in VISUALS_NOTES:
        cur = "threshold-only"
    emit({"artifacts": m["settings"].get("artifacts"), "note": VISUALS_NOTES[cur]})

def cmd_artifact(args):
    """Register/inspect explorables on graph nodes. The graph's `artifact` field is
    engine-owned (like fsrs/state): only this command records one, after checking the
    file actually exists — Contract clause 7 (versioned + regenerable) and the modality
    telemetry both depend on registrations being true. Paths under the state dir are
    stored home-relative so a moved home doesn't dangle every registration."""
    if args.action == "list":
        out = []
        for t, g in iter_graphs(args.topic):
            nodes = g.get("nodes")
            if not isinstance(nodes, dict):
                continue   # hand-edited graph: degrade like every aggregate view
            # audit surface: every registration in the graph, `order` first (stable,
            # human order), then any hand-added nodes outside it — never invisible.
            # Through graph_order, the ONE safe way to walk `order` — the hand-rolled
            # walk here was the N+1th call site the v1.0.6 fuzz caught (an unhashable
            # entry in `order` raised at `n in nodes`; mixed-type ids broke the sort).
            order = graph_order(g, graph_nodes(g))
            for nid in order:
                node = nodes.get(nid)
                a = (node or {}).get("artifact") if isinstance(node, dict) else None
                if isinstance(a, str) and a:
                    ap = a if os.path.isabs(a) else p(a)
                    out.append({"topic": t, "node": nid, "artifact": a,
                                "exists": os.path.isfile(ap)})
        emit(out)
        return
    for req, what in ((args.topic, "--topic"), (args.node, "--node")):
        if not req:
            die("artifact %s needs %s" % (args.action, what))
    g = load_graph(args.topic)
    node = g["nodes"].get(args.node)
    if node is None:
        die("unknown node %s in topic %s" % (args.node, args.topic))
    if not isinstance(node, dict):
        # The LAST mutator still reading a raw node value. `load_graph` guarantees `nodes` is a
        # dict; it guarantees nothing about the values, and this one assigned straight into them
        # (`node["artifact"] = ...` on a list -> TypeError). Worse than an ordinary crash: `doctor`
        # RECOMMENDS `artifact clear` as the fix for a corrupt artifact field, so the repair the
        # tool tells you to run was the thing that blew up. (Found by the post-release reviewer —
        # `apply_item` and `cmd_receipt` both got this guard in v0.7 and `cmd_artifact` was missed,
        # which is the whole reason §4.7 says to enumerate the surface from the dispatch table.)
        die("node %s in topic %s is corrupt (an object was expected, found %s) — run `doctor`, "
            "then fix graphs/%s.json by hand"
            % (args.node, args.topic, type(node).__name__, args.topic))
    if args.action == "set":
        if not args.path:
            die("artifact set needs --path")
        rp = os.path.realpath(os.path.expanduser(args.path))
        if not os.path.isfile(rp):
            die("artifact file not found: %s (write the file first, then register it)"
                % args.path)
        base = os.path.realpath(home())
        node["artifact"] = os.path.relpath(rp, base) if rp.startswith(base + os.sep) else rp
    else:  # clear — superseded/regenerating (the old file is not deleted, just unlinked)
        node["artifact"] = None
    save_graph(g)
    emit({"ok": True, "topic": args.topic, "node": args.node,
          "artifact": node["artifact"]})

def cmd_misconception(args):
    path = p("misconceptions.json")
    items = read_json(path, [])
    if not isinstance(items, list):
        # Mutators DIE on an unusable file (a lossy "repair" they then saved would be
        # data loss); the read view degrades and `doctor` reports it (v1.0.6 fuzz).
        if args.action in ("add", "resolve"):
            die("misconceptions.json has an unusable shape (expected a list, got %s) — "
                "run `doctor`, then fix or delete it" % type(items).__name__)
        items = []
    if args.action == "add":
        items.append({"id": gen_id("m"),
                      "ts": today().isoformat(), "topic": args.topic,
                      "node": args.node, "description": args.description,
                      "status": "open"})
        write_json(path, items)
    elif args.action == "resolve":
        found = False
        for it in items:
            if isinstance(it, dict) and it.get("id") == args.id:
                it["status"] = "resolved"
                it["resolved_ts"] = today().isoformat()
                found = True
        if not found:
            die("no misconception with id %s" % args.id)
        write_json(path, items)
    emit([it for it in items
          if isinstance(it, dict) and args.topic in (None, it.get("topic"))])

# ============================================================= THE METHOD (v0.9)
# Article 7 ("adapt on evidence, never taxonomy") is the article that replaces learning styles
# with real n-of-1 measurement — and the machinery implementing it was not sound enough to
# support the claims it exists to make. Four defects, all of them in the shipped code:
#
#   1. `arm = arms[len(assignments) % len(arms)]`  -> ROUND-ROBIN, not randomized. Perfectly
#      predictable, and therefore assignable by anything that knows the order things happen in.
#   2. Unstratified -> `docs/06` open-Q2 already documented the consequence: explorables are
#      routed to the hardest concepts ON PURPOSE, so the medium comparison carries the MATERIAL
#      as well as the medium. The document disclosed the confound honestly. It did not fix it.
#   3. `min_per_arm: 6` -> the SCED alternating-treatments literature puts sufficient power at
#      ~28-30 observations. Six per arm is underpowered by roughly 2.5x (`docs/07` §9).
#   4. `exp["verdict"] = args.verdict` -> **THE MODEL COMPUTED THE VERDICT.** A payload said
#      "derivation-first won" and the engine wrote it down. That is a direct violation of
#      invariant #2 — *the engine owns every number* — in the one command whose entire purpose
#      is to produce a number nobody is allowed to make up.
#
# A confounded, unpowered, round-robin trial settled by narration is not evidence. It is a
# vibe with a JSON file.

EXPERIMENT_MIN_PER_ARM = 15      # ~30 total: SCED alternating-treatments power (docs/07 §9)
EXPERIMENT_PERMUTATIONS = 10000  # exact randomization test — no scipy, no distributional prayer
EXPERIMENT_BOOTSTRAP = 2000
EXPERIMENT_METRICS = ("first_review_recall",)

def _stratum_of(node, keys):
    """The stratum a node belongs to, from the pre-registered `stratify_by` keys.

    This is what kills the confound that broke `stats.modality`: randomize the medium WITHIN one
    affordance class and the material stops riding along with the medium."""
    parts = []
    for k in keys:
        cur = node
        for seg in k.split("."):
            cur = cur.get(seg) if isinstance(cur, dict) else None
        parts.append("%s=%s" % (k, cur if isinstance(cur, (str, int, bool, float)) else "none"))
    return "|".join(parts) or "all"

def _arm_sequence(arms, seed, stratum, n):
    """Deterministic, reproducible, BALANCED randomization: shuffled blocks, one arm each.

    Not `random.choice` — that would randomize and never balance, so a 20-node run could land
    14/6 and the effect would be measured over an arm that barely exists. Not round-robin either
    — that balances and never randomizes, which is what shipped. Blocks give both: within each
    block of len(arms), the ORDER is random (seeded) and every arm appears exactly once.

    Keyed on (seed, stratum) so the whole sequence is recomputable by anyone holding the seed.
    An assignment nobody can reproduce is not an assignment; it is an anecdote."""
    rng = random.Random("%s|%s" % (seed, stratum))
    out = []
    while len(out) < n + len(arms):
        block = list(arms)
        rng.shuffle(block)
        out.extend(block)
    return out[:n + len(arms)]

def _exp_arms(exp):
    """The experiment's arms — string-only, deduped. THE GATE for every experiment read.

    `experiments.json` is hand-editable JSON like everything else, and `exp["arms"]` was read
    RAW: an `arms` that is an int raised TypeError, a missing one raised KeyError, and an `arms`
    holding a dict blew up on `arm not in out` (unhashable). **72 crashes in 600 fuzzed states**
    — found the moment `experiment status`/`list` were finally fuzzed.

    They had never been fuzzed because §4.7 says to enumerate the read paths from the DISPATCH
    TABLE, and `experiment` lives in `mutating` (start/assign/settle write) — so its READ
    sub-actions were invisible to the enumeration. **A command with sub-actions has a read path
    per sub-action.** The rule that found this is the rule that had the hole; both are now fixed."""
    arms = exp.get("arms") if isinstance(exp, dict) else None
    if not isinstance(arms, list):
        return []
    out = []
    for a in arms:
        if isinstance(a, str) and a and a not in out:
            out.append(a)
    return out

def _exp_min_per_arm(exp):
    n = as_number((exp or {}).get("min_per_arm"), EXPERIMENT_MIN_PER_ARM)
    return max(1, int(n if n is not None else EXPERIMENT_MIN_PER_ARM))

def _experiment_outcomes(exp):
    """{arm: [outcome…]} — engine-computed, from RECEIPTS. Never from a payload.

    `first_review_recall`: the node's FIRST genuine review (not its encoding — v0.6.1), scored
    recalled=1.0 / partial=0.5 / lapsed=0.0 (`_outcome`, the shared predicate)."""
    by = _by_node(collect_receipts())
    out = {arm: [] for arm in _exp_arms(exp)}
    detail = []
    assignments = exp.get("assignments") if isinstance(exp, dict) else None
    for a in (assignments if isinstance(assignments, list) else []):
        if not isinstance(a, dict):
            continue
        arm, tp, nid = a.get("arm"), a.get("topic"), a.get("node")
        if not isinstance(arm, str) or arm not in out:
            continue                       # an unhashable/absent arm is not an assignment
        if not isinstance(tp, str) or not isinstance(nid, str):
            continue
        slot = by.get((tp, nid))
        if not slot or not slot["reviews"]:
            continue                       # assigned, not yet reviewed: no datum, not a zero
        r = slot["reviews"][0]
        out[arm].append(_outcome(r))
        detail.append({"topic": tp, "node": nid, "arm": arm,
                       "outcome": _outcome(r), "ts": r.get("ts"),
                       "days_since_encode": r.get("days_since_encode")})
    return out, detail

def _spread(groups):
    """The test statistic: max(arm mean) - min(arm mean). Reduces to the plain difference for
    two arms, and generalizes to more without inventing an F distribution we cannot justify."""
    means = [sum(v) / len(v) for v in groups.values() if v]
    return (max(means) - min(means)) if len(means) >= 2 else 0.0

def _randomization_test(groups, seed):
    """Exact-ish randomization test: shuffle the ARM LABELS, recompute the spread, count how
    often chance beats what we saw. Pre-declared in the design, computed here, narrated nowhere.

    This is the honest test for an n-of-1: it assumes nothing about the distribution, only that
    under the null the labels were exchangeable — which is TRUE BY CONSTRUCTION, because the
    engine randomized them itself."""
    pool = [v for vs in groups.values() for v in vs]
    sizes = [(arm, len(vs)) for arm, vs in groups.items()]
    if len([1 for _, n in sizes if n]) < 2 or len(pool) < 2:
        return None
    observed = _spread(groups)
    rng = random.Random("perm|%s" % seed)
    hits = 0
    for _ in range(EXPERIMENT_PERMUTATIONS):
        rng.shuffle(pool)
        i, perm = 0, {}
        for arm, n in sizes:
            perm[arm] = pool[i:i + n]
            i += n
        if _spread(perm) >= observed - 1e-12:
            hits += 1
    return round((hits + 1) / float(EXPERIMENT_PERMUTATIONS + 1), 4)   # add-one: never claims p=0

def _bootstrap_ci(groups, seed):
    """Percentile bootstrap CI — on the SIGNED two-arm difference, and ONLY for two arms.

    v1.0.1 (the v0.9 review's finding #2): the old version bootstrapped `_spread` = max(mean) −
    min(mean), which is a non-negative EXTREME-ORDER statistic. Its bootstrap distribution is
    bounded below by 0 and biased strictly upward as the arm count grows — so for 3+ arms the
    "95% CI" provably EXCLUDED its own point estimate (three identical arms, observed spread 0.000,
    reported CI [0.033, 0.367]). A CI that excludes its point estimate is definitionally broken, and
    it manufactured a strategy separation that was not there — the flattering direction.

    The signed difference of two arms has no such floor, so its bootstrap CI is honest. For k > 2
    there is no single signed effect to bound, so we return None rather than a broken interval, and
    the settle read says the effect size is a spread with no CI. Refusing to draw a bad CI is more
    honest than drawing one."""
    named = [(arm, vs) for arm, vs in groups.items() if vs]
    if len(named) != 2:
        return None                       # k != 2: no single signed effect to bound. Say so.
    (a_arm, a_vs), (b_arm, b_vs) = sorted(named)   # deterministic sign: sorted arm order
    rng = random.Random("boot|%s" % seed)
    diffs = []
    for _ in range(EXPERIMENT_BOOTSTRAP):
        ra = sum(a_vs[rng.randrange(len(a_vs))] for _ in a_vs) / len(a_vs)
        rb = sum(b_vs[rng.randrange(len(b_vs))] for _ in b_vs) / len(b_vs)
        diffs.append(ra - rb)
    diffs.sort()
    lo = diffs[int(0.025 * len(diffs))]
    hi = diffs[min(len(diffs) - 1, int(0.975 * len(diffs)))]
    return {"of": "%s − %s" % (a_arm, b_arm), "ci95": [round(lo, 3), round(hi, 3)]}

def cmd_experiment(args):
    path = p("experiments.json")
    items = _as_list(read_json(path, []))
    if args.action == "start":
        exp = load_payload(args)
        if not isinstance(exp, dict):
            die("experiment design must be an object")
        for key in ("question", "arms", "metric"):
            if key not in exp:
                die("experiment missing %s" % key)
        if not isinstance(exp["arms"], list) or len(exp["arms"]) < 2 \
                or not all(isinstance(a, str) and a for a in exp["arms"]) \
                or len(set(exp["arms"])) != len(exp["arms"]):
            die("experiment needs >=2 distinct string arms")
        if exp["metric"] not in EXPERIMENT_METRICS:
            die("unknown metric %r — the engine will not silently compute a different one "
                "(supported: %s)" % (exp["metric"], ", ".join(EXPERIMENT_METRICS)))
        if any(e.get("status") == "active" for e in items if isinstance(e, dict)):
            die("an experiment is already active — settle it before starting another "
                "(one active experiment at a time; see /coach)")
        strat = exp.get("stratify_by")
        if strat is not None and not (isinstance(strat, list)
                                      and all(isinstance(s, str) for s in strat)):
            die("stratify_by must be a list of node-field paths (e.g. [\"threshold\"])")
        mpa = as_number(exp.get("min_per_arm"), EXPERIMENT_MIN_PER_ARM)
        # THE DESIGN IS THE PRE-REGISTRATION. Written before a single datum exists, and the
        # engine will not let it be edited afterwards (see `assign`/`settle`). Under-powering
        # is a CHOICE the design has to make in writing, and it is recorded as one.
        exp.update({
            "id": gen_id("x"),
            "seed": (exp["seed"] if isinstance(exp.get("seed"), (int, str)) and exp.get("seed")
                     else gen_id("s")),        # RECORDED, so every assignment is recomputable
            "stratify_by": strat or [],
            "min_per_arm": max(1, int(mpa)),
            "analysis": "randomization-test (exact); percentile-bootstrap CI on the spread",
            "randomized": True,
            "started": today().isoformat(), "status": "active",
            "assignments": [], "verdict": None,
        })
        if exp["min_per_arm"] < EXPERIMENT_MIN_PER_ARM:
            exp["power_note"] = (
                "min_per_arm=%d is BELOW the %d this engine considers powered (~%d observations "
                "total; the SCED alternating-treatments literature puts sufficient power at "
                "~28-30 — docs/07 §9). The settle will read `underpowered` and it will be right."
                % (exp["min_per_arm"], EXPERIMENT_MIN_PER_ARM, EXPERIMENT_MIN_PER_ARM * 2))
        items.append(exp)
        write_json(path, items)
        emit(exp)
    elif args.action == "assign":
        active = [e for e in items if isinstance(e, dict) and e.get("status") == "active"]
        if not active or not _exp_arms(active[0]):
            emit({"arm": None, "note": "no active experiment"})
            return
        exp = active[0]
        if not isinstance(exp.get("assignments"), list):
            exp["assignments"] = []        # a hand-edited log must not take the assigner down
        if not (isinstance(args.topic, str) and isinstance(args.node, str)):
            die("experiment assign needs --topic and --node")
        # already assigned? RETURN THE SAME ARM. An assignment that changes on a re-run is not
        # an assignment — and /learn can legitimately call this twice for one node.
        for a in exp["assignments"]:
            if isinstance(a, dict) and a.get("topic") == args.topic and a.get("node") == args.node:
                emit({"id": exp["id"], "arm": a.get("arm"), "stratum": a.get("stratum"),
                      "note": "already assigned — arms never move under a node"})
                return
        node = {}
        try:
            node = graph_nodes(load_graph(args.topic)).get(args.node) or {}
        except SystemExit:
            pass                              # an unknown topic still gets a (default) stratum
        strat = exp.get("stratify_by")
        stratum = _stratum_of(node, [s for s in strat if isinstance(s, str)]
                              if isinstance(strat, list) else [])
        seen = sum(1 for a in exp["assignments"]
                   if isinstance(a, dict) and a.get("stratum") == stratum)
        arm = _arm_sequence(_exp_arms(exp), exp.get("seed"), stratum, seen + 1)[seen]
        exp["assignments"].append({"ts": today().isoformat(), "arm": arm, "stratum": stratum,
                                   "topic": args.topic, "node": args.node})
        write_json(path, items)
        emit({"id": exp["id"], "arm": arm, "stratum": stratum,
              "seed": exp["seed"], "reproducible": True})
    elif args.action == "settle":
        # ⚠ THE ENGINE COMPUTES THE VERDICT. The model narrates it. It does not make it up.
        exp = next((e for e in items
                    if isinstance(e, dict) and e.get("id") == args.id), None)
        if exp is None:
            die("no experiment with id %s" % args.id)
        if getattr(args, "verdict", None):
            die("`--verdict` is refused: the engine computes the verdict (invariant #2 — the "
                "engine owns every number). Until v0.9 this field wrote whatever the model "
                "said into the experiment log, which is how a vibe becomes a finding.")
        # ⚠ OPTIONAL-STOPPING GUARD (v1.0.1, the v0.9 post-release review's finding #3). Settle had
        # no status check: re-settling as data trickled in kept only the last verdict and roughly
        # TRIPLED the false-positive rate (0.04 -> 0.117 at nominal 0.05). Peek-and-re-settle until
        # the coin lands is the exact optional-stopping fallacy a pre-registered design exists to
        # forbid. One analysis. `start` already refuses a second active experiment; `settle` now
        # refuses a second analysis of the same one.
        if exp.get("status") == "settled":
            die("experiment %s is already settled — a pre-registered trial is analysed ONCE. "
                "Re-settling as data arrives is optional stopping: it roughly triples the "
                "false-positive rate, and it is the exact fallacy pre-registration forbids. "
                "Start a fresh experiment for a new question." % args.id)
        groups, detail = _experiment_outcomes(exp)
        # A hand-edited receipt with a truthy non-rating and no grade yields a None outcome, and
        # `sum([1.0, None])` is a TypeError that bricked settle (finding #5). Reads DEGRADE, they
        # do not brick — drop the un-scoreable data points, exactly as every other read path drops
        # type-corrupt input rather than dying on it.
        groups = {arm: [v for v in vs if isinstance(v, (int, float))] for arm, vs in groups.items()}
        # ⚠ THE POWER FLOOR IS THE ENGINE'S, NOT THE PAYLOAD'S (v1.0.1, finding #1 — SEVERE).
        # `powered` was gated on the experiment's OWN `min_per_arm`, so a design that declared
        # `min_per_arm: 6` (the underpowered v0.8 default this release exists to kill) certified
        # as `powered: true` and read "suggestive" — on 6 data points per arm. A power gate you can
        # buy down with one payload field is not a power gate, and the shipped skill actively
        # promised the opposite ("the settle will read underpowered, and it will be right"). The
        # design may set a HIGHER bar than the engine; it may never set a lower one.
        mpa = max(_exp_min_per_arm(exp), EXPERIMENT_MIN_PER_ARM)
        ns = {arm: len(v) for arm, v in groups.items()}
        means = {arm: (round(sum(v) / len(v), 3) if v else None) for arm, v in groups.items()}
        powered = all(n >= mpa for n in ns.values()) and len(ns) >= 2
        p_value = _randomization_test(groups, exp.get("seed"))
        ci = _bootstrap_ci(groups, exp.get("seed"))
        effect = round(_spread(groups), 3) if any(ns.values()) else None
        best = max((a for a in means if means[a] is not None),
                   key=lambda a: means[a], default=None)
        # per-stratum balance: the whole reason to stratify is to be able to SHOW it worked
        balance = {}
        assigns = exp.get("assignments")
        for a in (assigns if isinstance(assigns, list) else []):
            if not isinstance(a, dict):
                continue
            st, arm = a.get("stratum"), a.get("arm")
            if not isinstance(st, str) or not isinstance(arm, str):
                continue                  # an unhashable stratum/arm would poison the dict itself
            balance.setdefault(st, {}).setdefault(arm, 0)
            balance[st][arm] += 1
        ci_str = ("95%% CI on %s %s" % (ci["of"], ci["ci95"])) if isinstance(ci, dict) \
            else "no CI (3+ arms: the spread has no honest interval — see ci95)"
        if not powered:
            read = ("UNDERPOWERED — %s. This is not a null result; it is an ABSENCE of a result, "
                    "and the difference matters: a coin flipped twice does not disprove the coin. "
                    "Need >=%d per arm (the engine's floor; a design cannot buy it down)."
                    % (", ".join("%s n=%d" % (a, n) for a, n in sorted(ns.items())), mpa))
        elif p_value is not None and p_value < 0.05:
            read = ("%s leads by %.2f (p=%.3f, randomization test; %s). Suggestive, and it is "
                    "n-of-1 — it is true about YOU, on THIS material, and it is not a law."
                    % (best, effect, p_value, ci_str))
        else:
            read = ("no arm separated from the others (spread %.2f, p=%.3f). At this n that means "
                    "'we cannot tell', not 'they are the same'." % (effect or 0.0, p_value or 1.0))
        exp.update({
            "status": "settled", "settled": today().isoformat(),
            "verdict": {                       # ENGINE-COMPUTED. Every field of it.
                "n_per_arm": ns, "mean_per_arm": means,
                "effect_spread": effect, "leader": best,
                "p_value": p_value, "ci95": ci,
                "powered": powered, "min_per_arm": mpa,
                "analysis": exp.get("analysis"),
                "seed": exp.get("seed"), "balance_by_stratum": balance,
                "n_observations": sum(ns.values()),
                "read": read,
            },
            "outcomes": detail,
        })
        write_json(path, items)
        emit(exp["verdict"])
    elif args.action == "status":
        exp = next((e for e in items if isinstance(e, dict)
                    and (e.get("id") == args.id or (args.id is None
                                                    and e.get("status") == "active"))), None)
        if exp is None:
            emit({"active": None, "note": "no active experiment"})
            return
        groups, _ = _experiment_outcomes(exp)
        mpa = max(_exp_min_per_arm(exp), EXPERIMENT_MIN_PER_ARM)   # the ENGINE's floor, not the payload's
        ns = {arm: len(v) for arm, v in groups.items()}
        assigns = exp.get("assignments")
        ready = bool(ns) and len(ns) >= 2 and all(n >= mpa for n in ns.values())
        emit({"id": exp.get("id"), "question": exp.get("question"),
              "status": exp.get("status"),
              "n_per_arm": ns, "min_per_arm": mpa,
              "assigned": len(assigns) if isinstance(assigns, list) else 0,
              "ready_to_settle": ready,
              "read": ("%d/%d per arm — %s"
                       % (min(ns.values()) if ns else 0, mpa,
                          "ready to settle" if ready
                          else "still collecting; settling now would read `underpowered`"))})
    else:
        emit(items)

def cmd_log_session(args):
    entry = {"ts": today().isoformat(), "kind": args.kind, "mode": args.mode,
             "minutes": args.minutes, "items": args.items, "notes": args.notes}
    append_jsonl(p("sessions.jsonl"), entry)
    emit({"ok": True})

def collect_receipts():
    out = []
    for t in all_topics():
        out.extend(read_jsonl(p("receipts", t + ".jsonl")))
    return out

def compute_streak(receipts):
    dayset = {r.get("ts") for r in receipts if isinstance(r.get("ts"), str)}
    cursor = today()
    if cursor.isoformat() not in dayset:
        cursor -= timedelta(days=1)  # grace: today isn't over yet
    streak = 0
    while cursor.isoformat() in dayset:
        streak += 1
        cursor -= timedelta(days=1)
    return streak

def _outcome(r):
    """The correctness signal for calibration: prefer the assessor grade (what the
    learner actually got right), falling back to the scheduler rating. A `partial`
    (grade) / `hard` (rating) is real partial credit, not a total miss.

    Both fields are coerced to str first: a hand-edited receipt can carry a dict or list
    here, and `x in OUTCOME_OF_GRADE` on an unhashable raises TypeError, taking `stats`
    (and therefore /coach) down with it. Read paths degrade; they do not brick."""
    g = r.get("grade")
    if isinstance(g, str) and g in OUTCOME_OF_GRADE:
        return OUTCOME_OF_GRADE[g]
    rating = r.get("rating")
    if not isinstance(rating, str):
        return None
    grade = GRADE_OF_RATING.get(rating)
    return OUTCOME_OF_GRADE.get(grade) if grade else None

def _calibration(rs):
    pairs = []
    for r in rs:
        c = clean_confidence(r.get("confidence"))
        o = _outcome(r)
        if c is not None and o is not None:
            pairs.append((c / 100.0, o))
    if not pairs:
        return {"brier": None, "bias": None, "n": 0, "read": None}
    brier = round(sum((c - o) ** 2 for c, o in pairs) / len(pairs), 4)
    bias = round(sum(c - o for c, o in pairs) / len(pairs), 4)
    read = ("insufficient-data" if len(pairs) < CAL_MIN_N else
            "overconfident" if bias > 0.05 else
            "underconfident" if bias < -0.05 else "well-calibrated")
    return {"brier": brier, "bias": bias, "n": len(pairs), "read": read}

MOMENTUM_WINDOW_DAYS = 7

def compute_momentum(receipts):
    """Real competence-growth signal over the last week, computed here (never by the
    model — Article 10). Foundations P13: surfacing true progress sustains adult
    motivation; every field below is an already-earned number, not an invented score.

    - reviews_7d / recalled_7d: retrievals cleared, and genuine wins among them
    - stability_gained_7d: total DAYS of durability added by successful reviews
      (sum of max(0, s_after - s_before)); the honest 'your memory got stronger' figure
    - most_durable: the single most durable memory right now (node id + its stability)
    - retained_total: nodes currently in the review (retained) state
    Window is a calendar cutoff; a receipt with an unparseable ts simply doesn't count."""
    cutoff = today() - timedelta(days=MOMENTUM_WINDOW_DAYS)
    reviews_7d = recalled_7d = 0
    gained = 0.0
    # v0.8: RETRIEVALS, not just reviews. A transfer probe advances the FSRS schedule exactly
    # like any other rating, so counting only `kind == "review"` here would report LESS
    # durability than the learner actually built — and undercounting real progress is its own
    # dishonesty, in the direction that quietly tells someone their work did not land.
    # (`retention` still counts reviews ONLY; see `_review_receipts` for why the populations
    # differ and which question each one answers.)
    genuine = {id(r) for r in _retrieval_receipts(receipts)}
    for r in receipts:
        d = safe_date(r.get("ts"))
        if d is None or d < cutoff:
            continue
        if id(r) in genuine:
            reviews_7d += 1
            sb, sa = as_number(r.get("s_before")), as_number(r.get("s_after"))
            if sb is not None and sa is not None and sa > sb:
                gained += (sa - sb)
        # wins ⊆ retrievals (the docstring's contract). Encode and pretest receipts carry
        # grade:"recalled" too, and counting them here reported retrieval wins to a learner
        # who had not retrieved once — the flattering direction. (v1.0.7, found by the
        # §7.5 post-release review; the guarding check's fixture couldn't see it.)
        if id(r) in genuine and r.get("grade") == "recalled":
            recalled_7d += 1
    most_durable = None
    retained_total = 0
    for _t, g in iter_graphs():
        for nid, node in (g.get("nodes") or {}).items():
            if not isinstance(node, dict):
                continue
            if node.get("state") == "review":
                retained_total += 1
            s = as_number(_fsrs_of(node).get("s"))
            if s is not None and (most_durable is None or s > most_durable["stability_days"]):
                most_durable = {"node": nid, "stability_days": round(s, 1)}
    return {
        "window_days": MOMENTUM_WINDOW_DAYS,
        "reviews_7d": reviews_7d,
        "recalled_7d": recalled_7d,
        "stability_gained_7d": round(gained, 1),
        "most_durable": most_durable,
        "retained_total": retained_total,
    }

# The modality floor inherited the experiment's underpowered `min_per_arm: 6` and, as `docs/10`
# predicted, it MOVES WITH IT. Six per arm is ~2.5x under the SCED alternating-treatments power
# requirement (~28-30 observations; docs/07 §9), and a medium comparison that reads a verdict off
# six data points is not "suggestive" — it is noise with a caveat stapled to it.
#
# Raising this SUPPRESSES a number some existing learners can currently see. That is correct: the
# number was never earned. Suppressing an unearned number is not a regression, it is the product.
MODALITY_MIN_N = EXPERIMENT_MIN_PER_ARM   # 15 — powered, and it moves with the experiment floor
SLIP_SHARE_MIN_N = 5   # below this, narrators quote counts, never a percentage (v1.1)

# Shipped inside the stats block so the narrator cannot forget it (the coach reads
# this JSON, not the docs). Surfaced live in a dogfood session: explorables are
# routed to threshold / high-viz-affordance nodes by design, so the two arms never
# differ *only* in medium — they differ in the material too. See docs/06 §Open.
MODALITY_CAVEAT = ("arms are not randomized: explorables go to threshold and "
                   "high-affordance concepts, so this compares medium AND material. "
                   "Suggestive personal telemetry, never proof — say so when reporting it.")

def compute_modality(receipts):
    """Per-learner medium yield (Article 7: adapt on evidence, never taxonomy).
    Compares first-review recall between nodes that HAD a registered explorable at
    review time (the receipt's own `artifact` stamp) and dialogue-only nodes. This is
    the honest per-learner answer to "do explorables work for ME" — a preference is
    honored as a preference, but retention data arbitrates (docs/01 §Rejections;
    docs/06-visual-encoding.md). One datum per node (its FIRST review), because later
    reviews confound medium with maturity. Deliberately suggestive, never 'proven':
    the read is guarded by the same per-arm floor as n-of-1 experiments, and it ships
    its own confound caveat (MODALITY_CAVEAT) — the assignment is not randomized."""
    first = {}
    for r in _review_receipts(receipts):      # §4.8 Q1: a node's FIRST receipt is not a review
        d = safe_date(r.get("ts"))
        if d is None:
            continue
        topic, node = r.get("topic"), r.get("node")
        if not isinstance(topic, str) or not isinstance(node, str):
            continue                       # hand-edited: an unhashable key would crash
        key = (topic, node)
        if key not in first or d < first[key][0]:   # ties: keep the earlier-appended
            first[key] = (d, r)
    # v1.0.1 (the v0.9 review's finding #4): `first_review_recall` must mean ONE thing. This used
    # `rating != "again"`, scoring a `partial` as a FULL 1.0 — while the experiment engine, on the
    # identically-named metric, scores `partial` as 0.5 (`_outcome`). Same name, same engine, same
    # data, two answers, and modality's was the lenient one. §4.8 Q1: the engine's commands must
    # agree. Both now use `_outcome`, the shared predicate.
    arms = {"explorable": [0.0, 0], "dialogue": [0.0, 0]}
    for _d, r in first.values():
        # `_outcome` returns None for a hand-edited receipt with a truthy non-rating and no grade —
        # and `0.0 += None` is a TypeError that bricked `stats`, and therefore /coach. v1.0.1 added
        # the switch to `_outcome` (finding #4) AND the drop-guard in `settle` (finding #5) — but
        # not HERE, one function over. Same bug class, same release, same fix: drop the un-scoreable
        # datum. Reads degrade, they never brick. (Found by the v1.0.1 verification review.)
        o = _outcome(r)
        if o is None:
            continue
        arm = "explorable" if r.get("artifact") else "dialogue"
        arms[arm][1] += 1
        arms[arm][0] += o
    out = {a: {"first_review_recall": (round(ok / n, 3) if n else None), "n": n}
           for a, (ok, n) in arms.items()}
    ex, dg = out["explorable"], out["dialogue"]
    if ex["n"] >= MODALITY_MIN_N and dg["n"] >= MODALITY_MIN_N:
        diff = ex["first_review_recall"] - dg["first_review_recall"]
        out["read"] = ("explorable-encoded ahead" if diff > 0.10 else
                       "dialogue-encoded ahead" if diff < -0.10 else
                       "indistinguishable")
    else:
        out["read"] = "insufficient-data"
    out["min_n"] = MODALITY_MIN_N
    out["caveat"] = MODALITY_CAVEAT
    return out

BY_KIND_CAVEAT = ("kinds are different material by construction — a procedure node and a "
                  "concept node differ in content, difficulty, and grading format, so this "
                  "comparison carries the material along with the kind and is never a causal "
                  "claim. It exists as the instrument for an open question (docs/11 §7.3: "
                  "does the forgetting model fit skills as well as declarative memory?), "
                  "and pre-v1.1 receipts carry no kind stamp — they count as concept, which "
                  "is what every pre-v1.1 grading event actually was.")

SELF_GRADING_MIN_N = 20   # below this: counts, never a rate (the house floor rule)

def compute_self_grading(receipts):
    """Does the TUTOR agree with the blind assessor? (v1.4 — the grader nothing measured.)

    `/coach audit` measures the assessor. It has never measured the tutor, and the tutor
    writes **every `/review` receipt** and every `error_class` behind `procedure_slip_share`
    — in-context, with the dialogue it just ran in front of it, which is the exact condition
    the separation of powers exists to distrust.

    ⚠ WHAT THIS IS NOT. It is not validity. The tutor cannot be spawned blind — dialogue
    context is a permanent confound — so no blindness property is ever claimed for it. This
    is educational measurement's *read-behind*: agreement with a second rater whose OWN
    validity is what the gold-set audit measures. Tutor validity is bounded by that chain and
    can never exceed it, and the `read` says so in those words rather than in a footnote.

    `signed_bias` > 0 means the tutor rates ABOVE the blind grader — the flattering
    direction, and the only one that can stop a learner reviewing. Reported with direction
    counts beside it, because a mean near zero is also what "inflates half, deflates half"
    looks like (§4.8 Q6, rule 3).

    Banded on `partial`, deliberately: the 2026 short-answer literature finds LLM graders
    near-human at the extremes and materially off in the mid-range, which is exactly where
    a tutor's sympathy for a learner it just taught would land."""
    audits = [r for r in receipts if r.get("kind") == "audit"
              and r.get("rating") in RATINGS and r.get("audited_rating") in RATINGS]
    n = len(audits)
    out = {"n": n, "min_n": SELF_GRADING_MIN_N,
           "definition": ("of the tutor's own /review grades that the blind assessor "
                          "re-graded, how often the two agree — and in which direction they "
                          "differ. Agreement with the assessor, NOT validity.")}
    if not n:
        out.update(qwk_vs_assessor=None, signed_bias=None, agree=0, tutor_higher=0,
                   tutor_lower=0, by_band={}, insufficient_data=True,
                   read=("no /review grade has ever been spot-audited. The tutor writes every "
                         "review receipt and nothing has ever checked it — /review escalates "
                         "to the assessor on a large, disputed, or partial-heavy session."))
        return out
    pairs = [(r["audited_rating"], r["rating"]) for r in audits]   # (tutor, assessor)
    higher = sum(1 for t, a in pairs if RATING_SCORE[t] > RATING_SCORE[a])
    lower = sum(1 for t, a in pairs if RATING_SCORE[t] < RATING_SCORE[a])
    agree = sum(1 for t, a in pairs if t == a)
    bias = sum(RATING_SCORE[t] - RATING_SCORE[a] for t, a in pairs) / float(n)
    band = {}
    for r, (t, a) in zip(audits, pairs):
        # Band by what the ASSESSOR said — the closest thing to ground truth on the item.
        key = {"again": "lapsed", "hard": "partial"}.get(a, "recalled")
        s = band.setdefault(key, {"n": 0, "agree": 0, "bias_sum": 0.0})
        s["n"] += 1
        s["agree"] += 1 if t == a else 0
        s["bias_sum"] += RATING_SCORE[t] - RATING_SCORE[a]
    by_band = {k: {"n": v["n"], "agreement": round(v["agree"] / float(v["n"]), 3),
                   "signed_bias": round(v["bias_sum"] / float(v["n"]), 3)}
               for k, v in sorted(band.items())}
    enough = n >= SELF_GRADING_MIN_N
    q = _qwk([(a, t) for t, a in pairs], scores=RATING_SCORE) if enough else None
    out.update(qwk_vs_assessor=(round(q, 3) if q is not None else None),
               signed_bias=(round(bias, 3) if enough else None),
               agree=agree, tutor_higher=higher, tutor_lower=lower,
               by_band=by_band, insufficient_data=not enough)
    limit = ("Agreement with the blind assessor, whose own validity is what `/coach audit` "
             "measures — tutor validity is bounded by that chain, never better.")
    if not enough:
        out["read"] = ("%d spot-audit%s so far: the tutor agreed %d time%s, graded HIGHER %d, "
                       "lower %d. Counts only — %d audits before any rate. %s"
                       % (n, "" if n == 1 else "s", agree, "" if agree == 1 else "s",
                          higher, lower, SELF_GRADING_MIN_N, limit))
    else:
        out["read"] = ("tutor vs blind assessor over %d spot-audits: QWK %s, signed bias %s "
                       "(+ = the tutor grades higher, the flattering direction); it graded "
                       "UP %d and down %d. %s"
                       % (n, _fmt(out["qwk_vs_assessor"]),
                          _fmt(out["signed_bias"], sign=True), higher, lower, limit))
    return out

def compute_by_kind(receipts):
    """Retention telemetry split by knowledge kind (v1.1, docs/11 P17; the compute_modality
    mold, deliberately: same population (_review_receipts), same one-datum-per-node
    first-review rule, same _outcome predicate, same floor — so the engine's numbers agree
    with each other by construction (RELEASE_PROTOCOL §4.8 Q1).

    The `read` compares PROCEDURE vs CONCEPT only: `fact` is reported but never versus'd
    (three-way reads invite invented metrics), and the caveat ships inside the payload.

    `procedure_slip_share` rides along: of procedure-node gradings that carried an
    error_class, what fraction were slips? Its denominator is N_CLASSIFIED — receipts the
    grader actually classified — never all procedure receipts, and it says so by name."""
    first = {}
    for r in _review_receipts(receipts):
        d = safe_date(r.get("ts"))
        if d is None:
            continue
        topic, node = r.get("topic"), r.get("node")
        if not isinstance(topic, str) or not isinstance(node, str):
            continue
        key = (topic, node)
        if key not in first or d < first[key][0]:
            first[key] = (d, r)
    arms = {k: [0.0, 0] for k in NODE_KINDS}
    for _d, r in first.values():
        o = _outcome(r)
        if o is None:
            continue
        nk = r.get("node_kind")
        if nk not in NODE_KINDS:
            # Pre-v1.1 receipts carry no stamp. Every pre-v1.1 grading WAS a concept-style
            # free-recall event (procedure nodes did not exist), so `concept` is the truthful
            # label of the EVENT — not a guess about the content. The caveat says so.
            nk = "concept"
        arms[nk][1] += 1
        arms[nk][0] += o
    out = {k: {"first_review_recall": (round(ok / n, 3) if n else None), "n": n}
           for k, (ok, n) in arms.items()}
    pr, co = out["procedure"], out["concept"]
    if pr["n"] >= MODALITY_MIN_N and co["n"] >= MODALITY_MIN_N:
        diff = pr["first_review_recall"] - co["first_review_recall"]
        out["read"] = ("procedure-encoded ahead" if diff > 0.10 else
                       "procedure-encoded behind" if diff < -0.10 else
                       "indistinguishable")
    else:
        out["read"] = "insufficient-data"
    out["min_n"] = MODALITY_MIN_N
    # The slip split is REVIEW telemetry (docs/12 WO-3: "among procedure-node review
    # receipts that carry error_class") — encode-stage misses, where the method is still
    # forming, would bias the share toward "slip", which is precisely this number's
    # flattering direction. The first cut iterated every receipt kind; caught by the
    # pre-release adversarial review, fixture made to diverge (§4.5).
    # ⚠ THE FLOOR COUNTS NODES, NOT JUDGMENTS (v1.1.1). The recall arms above take one
    # datum per node on purpose; the slip split did not, so ONE node the learner had failed
    # five times running supplied the entire denominator and the page read "100% were
    # execution slips" — the single most flattering thing it could say about a node that
    # keeps dying. `n_nodes` is published beside `n_classified` and the narrators gate on
    # it. (Found by the §7.5 post-release review.)
    slips = classified = 0
    nodes = set()
    for r in _review_receipts(receipts):
        if r.get("node_kind") != "procedure":
            continue
        ec = r.get("error_class")
        if ec in ERROR_CLASSES:
            classified += 1
            slips += 1 if ec == "slip" else 0
            t, n = r.get("topic"), r.get("node")
            if isinstance(t, str) and isinstance(n, str):
                nodes.add((t, n))
    out["procedure_slip_share"] = {
        "share": (round(slips / classified, 3) if classified else None),
        "n_classified": classified,
        "n_nodes": len(nodes),
        "min_nodes": SLIP_SHARE_MIN_N,
    }
    out["caveat"] = BY_KIND_CAVEAT
    return out

# ------------------------------------------------- adherence & retention (v0.6)
# The two numbers Engram never had. Everything here is a pure read over data the engine
# has been writing since v0.1 and has never once looked at: no new state, no migration.
#
# Why they matter more than anything else in this file: the value a learning system
# produces is Return x Encoding x Retention x Transfer, and those terms MULTIPLY. A
# perfect encoder with zero return is worth exactly zero — which was the founder's own
# account for six days (7 encoded, 0 reviewed) while the engine reported a cheerful
# `[engram] 7 reviews due`. See docs/08 §The exhibit.

def _by_node(receipts):
    """(topic, node) -> {"first": earliest receipt, "reviews": [review receipts, ascending]}.

    The FIRST receipt for a node is its encoding event: its `ts` is day 0, and its
    `due_next` is the first review Engram ever booked for it."""
    order = sorted(receipts, key=_sort_key)
    out = {}
    for r in order:
        topic, node = r.get("topic"), r.get("node")
        # a hand-edited receipt can carry any JSON type here; a dict/list would be an
        # unhashable key and take the whole command down with it
        if not isinstance(topic, str) or not isinstance(node, str) or not topic or not node:
            continue
        # An AUDIT receipt is a measurement OF A GRADER, not a retrieval by the learner
        # (v1.4). It may never become a node's `first` — that slot defines day 0 for every
        # retention bucket and `days_since_encode` — and it counts toward no population here.
        # A bare CLI `rate --kind audit` on a never-encoded node is therefore invisible to the
        # learner's metrics, which is exactly right: nobody retrieved anything.
        if r.get("kind") == "audit":
            continue
        key = (topic, node)
        first = key not in out
        slot = out.setdefault(key, {"first": r, "reviews": [], "transfers": []})
        # A node's FIRST receipt is its ENCODING EVENT — whatever it happens to be labelled.
        # There was no prior memory to retain, so a first exposure cannot be a retention test,
        # and it must never count toward `loop_closure` or a retention bucket.
        #
        # This matters because `rate`'s `--kind` argparse default is "review": a bare
        # `rate --topic t --node a --rating good` (the CLI path; the skills always pass an
        # explicit --kind) writes a node's only receipt as kind=review. Before this guard,
        # such a node reported loop_closure = 1.0 — "the loop is closing" — for a learner who
        # had never come back once. The metric built to say "you never returned" said the
        # opposite, which is the single worst direction for it to be wrong in.
        if first:
            # …**EXCEPT A CAPSTONE, WHICH HAS NO ENCODING PHASE AT ALL** (v0.8.1). It is built
            # once, and the build IS the event — a `kind: transfer`. So v0.8.0 shipped a
            # capability metric that could not see the capstone: the learner built the thing,
            # passed it, and `stats.transfer` read **"NO CAPABILITY HAS EVER BEEN MEASURED"**
            # while the receipt sat on disk. The release's own thesis — *"transfer_probe was
            # authored since v0.1 and read by NOTHING"* — reproduced one level up, on the most
            # important node in the graph.
            #
            # The receipt carries its own `capstone` stamp (written at grading time by
            # `apply_item`, exactly like the `artifact` medium stamp), so this stays a pure
            # function of the receipt log — and the v0.6.1 guard is untouched for every ordinary
            # node: a bare CLI `rate --kind transfer` on a never-encoded concept is still
            # swallowed as that concept's encoding event, because it is one.
            if r.get("capstone") is True and r.get("kind") == "transfer" and r.get("rating"):
                slot["transfers"].append(r)
            continue
        if r.get("kind") == "review" and r.get("rating"):
            slot["reviews"].append(r)
        elif r.get("kind") == "transfer" and r.get("rating"):
            # A TRANSFER receipt is a retrieval, but it is NOT a retention review, and the two
            # must never be pooled. Retention asks "does the memory survive N days?"; transfer
            # asks "does the capability fire when the problem wears different clothes?" Pooling
            # them would drag the north star down with a harder question and answer neither.
            slot["transfers"].append(r)
    return out

def _review_receipts(receipts):
    """Every receipt that is a genuine RETENTION review.

    A `kind: review` receipt that is NOT its node's first — because a node's first receipt is
    its ENCODING event whatever it is labelled, and a first exposure cannot be a retention test.

    v0.6.1 established that principle in `_by_node` (which feeds `adherence` and `retention`)
    and left `stats.reviews`, `compute_momentum`, `compute_modality` and the calibration split
    filtering on `kind == "review"` **directly** — four implementations of one rule, three of
    them wrong. A bare CLI `rate` (argparse default `kind="review"`) on a never-encoded node
    therefore inflated `stats.reviews`, and — worse — handed `compute_modality` an *encoding*
    receipt as that node's "first review", corrupting the medium telemetry `docs/06` exists to
    produce. `adherence` said 0 reviews while `stats` said 1, on the same state.

    One predicate. Used everywhere. (RELEASE_PROTOCOL §4.8 Q1: the engine's own commands must
    agree with each other.)

    ── THE THREE POPULATIONS (v0.8), because there are now genuinely three questions ──

    v0.6.4's bug was FOUR implementations of ONE rule, three of them wrong. The fix was one
    shared predicate. v0.8 adds a second KIND of retrieval, and the temptation is to bolt it
    onto the same predicate — which would be the same bug from the other end: ONE definition
    covering THREE questions, and therefore answering none of them.

    | population              | the question it answers                    | who reads it |
    |-------------------------|--------------------------------------------|--------------|
    | `_review_receipts`      | does the memory survive N days?             | retention (THE north star), recall_by_stability, calibration, modality, adherence |
    | `_transfer_receipts`    | does the capability fire in new clothes?    | stats.transfer, node.transfer |
    | `_retrieval_receipts`   | how much durability was actually grown?     | momentum |

    They are NOT interchangeable, and pooling any two of them silently answers a question
    nobody asked. Retention pooled with transfer would drag the north star down with a harder
    question. Momentum WITHOUT transfer would understate real growth, because a transfer probe
    grows stability exactly like any other successful retrieval — and understating a learner's
    real progress is its own kind of dishonesty."""
    out = []
    for slot in _by_node(receipts).values():
        out.extend(slot["reviews"])
    return out

def _transfer_receipts(receipts):
    """Every receipt that is a genuine TRANSFER probe — the capability measurement.

    Never pooled into retention. A node is *retained* when recall survives a month; it is
    *owned* when it fires on a probe wearing different clothes (docs/09 §3.2)."""
    out = []
    for slot in _by_node(receipts).values():
        out.extend(slot["transfers"])
    return out

def _retrieval_receipts(receipts):
    """Reviews AND transfers: every retrieval that actually grew (or shrank) a memory.

    This is the population `momentum` wants. A transfer probe advances the FSRS schedule like
    any other rating, so excluding it would report less durability than the learner really
    built — pessimistic, but wrong, and a system that undercounts real progress is lying in the
    other direction."""
    out = []
    for slot in _by_node(receipts).values():
        out.extend(slot["reviews"])
        out.extend(slot["transfers"])
    return sorted(out, key=_sort_key)

def _grade_of(r):
    """The receipt's grade, falling back to its rating. One definition, shared."""
    g = r.get("grade")
    if isinstance(g, str) and g in GRADES:
        return g
    rt = r.get("rating")
    return GRADE_OF_RATING.get(rt) if isinstance(rt, str) else None

def node_transfer_state(slot):
    """The node's transfer block, derived from its receipts. ENGINE-OWNED, never payload-set.

    `untested` — never probed. `probed` — probed, and it did not fire. `applied` — the most
    recent transfer probe was *recalled*: the capability fired.

    Computed from the LATEST transfer receipt, not from "ever". A capability that fired in June
    and failed in September is not currently owned, and pretending otherwise would be a wrong
    number in the flattering direction — which is bug class #1.

    v0.8.1: "latest" means the latest **DATED** one. `_sort_key` deliberately sorts a receipt with
    an unparseable `ts` LAST (so it can never win day-0), and taking `ts[-1]` therefore handed the
    crown to exactly that garbage receipt — a hand-edited undated `recalled` could flip a node to
    `applied` over a real, dated `lapsed`. The v0.6 fix and the v0.8 rule collided, and they
    collided in the flattering direction."""
    ts = slot["transfers"] if slot else []
    if not ts:
        return {"state": "untested", "last": None, "receipts": 0}
    dated = [r for r in ts if safe_date(r.get("ts"))]
    last = dated[-1] if dated else None
    if last is None:
        # every transfer receipt is undated: we know it was PROBED and we cannot know the outcome
        return {"state": "probed", "last": None, "receipts": len(ts),
                "note": "no transfer receipt carries a parseable date — outcome unknown"}
    return {"state": "applied" if _grade_of(last) == "recalled" else "probed",
            "last": last.get("ts"), "receipts": len(ts)}

# ============================================================== THE ORACLE (v0.7)
# The blind assessor's grade drives mastery, retention, calibration, and the schedule
# itself — and until now its agreement with any ground truth was UNMEASURED. If it is
# lenient, every number Engram has ever printed is inflated and nothing in the system
# could discover it. The constitution says "the oracle is never a vibe"; it has been one.
#
# Three numbers from the literature shape every threshold below (docs/07 §3):
#   - LLM judges hit kappa 0.376-0.511 vs human ground truth. Moderate. Well under 0.70.
#   - Raw agreement OVERSTATES chance-corrected agreement by 33.8-41.2 points. So raw
#     agreement is a liar and is never allowed to be the headline. QWK is the headline.
#   - THE PARADOX: one measured judge scored test-retest 0.992 with position bias 0.192 —
#     perfectly reproducible and systematically wrong. High self-consistency is NOT
#     evidence of correctness, and Engram's assessor prompt (skeptic, round down, cite the
#     rubric) selects for exactly that profile. So consistency alone can never certify.

# ============================================================== THE CLAIM (v0.8)
# `transfer_probe` has been authored by the curriculum architect since v0.1, stored by the
# engine, and READ BY NOTHING. On the founder's own graph, 12 of 13 nodes carry one and
# `grep transfer_probe scripts/engram.py` found exactly one line: a `setdefault`. Zero
# transfer receipts exist anywhere, ever. Engram has been a very good memory system wearing
# a capability system's marketing, and `skills/learn` §5 says of the transfer step: "this is
# the point of the whole topic — do not let it silently not happen." It silently did not happen.
#
# A node is RETAINED when recall survives a month. It is OWNED when it fires on a probe that
# wears different clothes. Those are two different claims, backed by two different pieces of
# evidence, and the graph has been conflating them.
TRANSFER_MATURE_S = 21.0      # stability, in days: the memory has survived a real interval
TRANSFER_MATURE_REPS = 3      # …across at least three RETRIEVALS (from the receipt log — the
                              # encode is not a retrieval, and counting `fsrs.reps` made this an
                              # advertised 3 that delivered 2).
TRANSFER_COOLDOWN_DAYS = 30   # don't re-probe the same node every session; it is not a quiz
TRANSFER_STATES = ("untested", "probed", "applied")
# Every sibling metric has a floor (calibration 10, modality 15, the grader audit 30). Transfer
# had NONE — so a single probe read "FIRED on 100%" and chipped it on the dashboard while
# `calibration` and `modality` correctly said `insufficient-data` on the same state. A rate over
# fewer than five probes moves more than 20 points on one item, and a number a single datum can
# swing by 20 points is not a rate. Counts are facts and are always shown; the RATE waits.
TRANSFER_MIN_N = 5

GOLD_SCORE = {"lapsed": 0, "partial": 1, "recalled": 2}   # ordinal; QWK needs the order

# ── THE CANARY (v1.4) ────────────────────────────────────────────────────────────────────
# A badge is only valid for the grader that earned it. When the model changes underneath a
# learner (a platform upgrade), the honest options are "re-run the whole 86x3 ceremony" or
# "carry a badge nobody re-earned" — and the second is how a stale pass gets believed. The
# canary is the cheap third option: a fixed, seed-stable subset that can only ever RE-LICENSE
# the prior verdict or DEMAND a full re-audit. It can never mint a `pass` (invariant 12).
#
# Composition is deliberate, not random: the mid-band (`partial`) is where the 2026 measured
# literature puts LLM-grader divergence, and these case types are where THIS grader's real
# inflations were caught (v1.1.0's audit) or where it still disagrees with the gold on purpose.
CANARY_N = 15
CANARY_CASE_TYPES = ("right-answer-wrong-reason", "right-answer-wrong-method",
                     "partial-credit-boundary", "procedure-partial-boundary",
                     "slip-vs-conceptual", "fluent-but-empty")
AUDIT_STALE_DAYS = 90     # when the grader context is unknowable, time is the only signal
QWK_FLOOR = 0.60        # below this the grader is not trustworthy at all -> teeth
QWK_TARGET = 0.70       # the conventional threshold for automated scoring -> pass
BIAS_MAX = 0.15         # signed leniency ceiling: mean(grader - gold), + = inflating
MIN_AUDIT_N = 30        # below this, the audit says "insufficient-data", never a verdict
MIN_AUDIT_RUNS = 3      # test-retest needs >=3 runs; with fewer, the paradox check is blind
PARADOX_RETEST = 0.95   # above this consistency, leniency must be strictly under BIAS_MAX

# What the assessor is allowed to see of a gold item. A WHITELIST, never a blacklist:
# the assessor never sees `gold_grade`, `case_type`, or `rationale`, and a field added to
# the gold schema later cannot leak by being forgotten in a delete-list. This is invariant
# #5 (the assessor is blind) applied to the audit itself — and RELEASE_PROTOCOL §5.5's
# hardest lesson: a test that hands the subject the answer is not a test.
GOLD_ASSESSOR_KEYS = ("topic", "node", "sid", "claim", "rubric", "probe",
                      "production", "confidence", "kind", "node_kind")
# Everything the assessor must never see. The whitelist above already makes that structural;
# this list is what the BLINDNESS selftest asserts is absent.
GOLD_SECRET_KEYS = ("gold_grade", "case_type", "rationale")
# …but only these two are DIAGNOSTIC OF A LEAK, and only these kill an audit. `rationale` is a
# key any grader might invent on its own, and accusing an innocent grader of cheating — fatally,
# so the audit cannot run — is a false positive that costs more than it saves.
GOLD_ANSWER_KEYS = ("gold_grade", "case_type")

# ⚠ THE INSTRUMENT'S OWN LIMIT — v0.7's most important finding, and it is not a number.
#
# v0.7.0 shipped this gold set and published QWK 0.93. Then a post-release reviewer measured the
# thing nobody had thought to measure: it ran a CORRECT grader and a deliberately FOOLED one
# against the set — and **the fooled grader scored higher** (1.000 vs 0.990). The gold set was
# REWARDING leniency. The instrument was inverted.
#
# The cause was five lenient adjudications by the set's own author, all of the same kind:
# crediting an ADJACENT FACT as partial credit. Majority is not intersection. Consonance is not
# pitch-set arithmetic. The history of a theory is not its mechanism. The grader had caught every
# one of them, 3 runs out of 3 — including on a `fluent-but-empty` item, which means **the author
# was fooled by fluency in the very category built to catch being fooled by fluency.**
#
# Correcting them lifts agreement 0.889 -> 0.965. **That rise is not evidence the grader got
# better. It is evidence the instrument had been measuring the AUTHOR'S inconsistency.** And
# because the corrections were prompted by the grader's own disagreements, the QWK that follows
# is CIRCULAR: an authored gold set cannot validate a grader from the same model family, because
# when the two disagree and the author concedes, the agreement that follows measures only the
# author's willingness to concede. (One real disagreement, g_054, is deliberately KEPT — an
# independent reviewer judged the gold defensible there. An instrument with no disagreement left
# in it measures nothing.)
#
# So the engine says this on every audit, until someone who is not the author has adjudicated the
# set. §4.8 Q4, turned on the instrument itself: a limit only the docs know is a limit nobody reads.
#
# **What survives — and is STRONGER for the correction:** `direction.graded_up`. Every authoring
# error was LENIENT, so fixing them moved the bar DOWN, giving the grader more room to be caught
# inflating. Across 258 blind judgments it still graded UP exactly zero times. That is a safety
# property, it does not depend on the gold being perfectly calibrated, and it is the only claim
# here that was ever worth a badge.
GOLD_ADJUDICATION = "authored"      # -> "human" only when someone who is NOT the author has done it
# ⚠ The corrected-item count is DERIVED, never hardcoded (v1.1.1). It shipped as a literal
# "5" and the set reached 6 `disputed` records in the same release that added the sixth —
# so the string that exists to disclose the instrument's contamination was UNDERSTATING it,
# on the dashboard, in the flattering direction. A provenance field that lies is worse than
# none (§4.8 Q6). Found by the §7.5 post-release review.
# The clean anchors — everything else in the set is a deliberate trap. Derived so the
# published percentage can never go stale against the file (v1.1.1).
GOLD_CLEAN_CASE_TYPES = ("clear-recalled", "clear-lapsed", "procedure-clean", "procedure-lapsed")

def _adversarial_pct(items):
    items = [it for it in items if isinstance(it, dict)]
    if not items:
        return 0
    clean = sum(1 for it in items if it.get("case_type") in GOLD_CLEAN_CASE_TYPES)
    return int(round((len(items) - clean) / len(items) * 100))

def _gold_circularity(n_corrected):
    return ("GOLD SET IS AUTHORED, NOT INDEPENDENTLY HUMAN-ADJUDICATED, and %d items were "
            "corrected after the grader disagreed with them. A QWK measured against it CANNOT "
            "certify a grader from the same model family: when the author concedes to the "
            "grader, the agreement that follows measures the author. The figure that survives "
            "this is `direction.graded_up` — a safety property that does not depend on the "
            "gold being perfectly calibrated." % n_corrected)

def _plugin_root():
    """The plugin/repo root — the dir holding scripts/ and gold/. realpath, so a
    symlinked install still finds the bundled gold set."""
    return os.path.dirname(os.path.dirname(os.path.realpath(__file__)))

def _valid_gold_item(it):
    if not isinstance(it, dict):
        return False
    if not isinstance(it.get("sid"), str) or not it["sid"]:
        return False
    if it.get("gold_grade") not in GRADES:
        return False
    for k in ("claim", "probe", "production"):
        if not isinstance(it.get(k), str) or not it[k]:
            return False
    if not isinstance(it.get("rubric"), list) or not it["rubric"]:
        return False
    return True

def load_gold(override=None):
    """(items, meta) — the bundled gold set, plus the learner's own additions, WITH PROVENANCE.

    The bundled file is the source of truth and ships with the plugin, so a plugin update
    delivers new gold items. `gold/local-gold.jsonl` in the state dir is ADDITIVE (a
    learner's own disputed grades are gold candidates — docs/10 parallel track) and wins
    on a sid collision, because a human who disputed an adjudication outranks mine.

    **AND THAT IS A LOADED GUN, so the audit must record exactly where its ground truth came
    from.** A `local-gold.jsonl` that re-adjudicates the bundled sids to agree with the grader
    turns a `fail` (qwk 0.55, leniency +0.64) into a `pass` (qwk 1.00) — on the DEFAULT path,
    no flag required — and the first cut of `gold_source` would still have written
    `"bundled:gold/assessor-gold.jsonl"` into the audit file. Not merely silent: **actively
    false**, and false in the flattering direction. (Found by the independent reviewer, in the
    fix written to answer §4.8 Q5. A provenance field that lies is worse than no provenance
    field, because it is believed.)

    So: count the overrides, count the additions, and let the caller put both in the read.

    `skipped` is likewise returned and never swallowed: a malformed gold item that silently
    vanished would shrink the denominator invisibly."""
    if override:
        raw = read_jsonl(override)
        bundled_sids, local_sids = set(), set()
        source, modified = os.path.abspath(override), True    # not the shipped ground truth
    else:
        bundled = read_jsonl(os.path.join(_plugin_root(), "gold", "assessor-gold.jsonl"))
        local = read_jsonl(p("gold", "local-gold.jsonl"))
        bundled_sids = {it["sid"] for it in bundled if _valid_gold_item(it)}
        local_sids = {it["sid"] for it in local if _valid_gold_item(it)}
        raw = bundled + local
        source, modified = "bundled:gold/assessor-gold.jsonl", bool(local_sids)
        if modified:
            source = ("bundled + gold/local-gold.jsonl (%d re-adjudicated, %d added)"
                      % (len(local_sids & bundled_sids), len(local_sids - bundled_sids)))
    items, skipped = {}, 0
    for it in raw:
        if _valid_gold_item(it):
            items[it["sid"]] = it        # later (local) wins on a sid collision
        else:
            skipped += 1
    return list(items.values()), {
        "source": source,
        "skipped": skipped,
        "local_overrides": len(local_sids & bundled_sids),   # bundled adjudications REPLACED
        "local_added": len(local_sids - bundled_sids),       # brand-new items
        "modified": modified,          # ← the flag that must reach the narrator
    }

def canary_items(items):
    """The re-licensing subset: ~15 items, chosen the same way every time (v1.4).

    Seed-stable by sha256 of the sid — NOT by `random`, which the engine may not use at all
    (a shuffled canary is a different instrument each run, and two runs that disagree would
    be indistinguishable from a grader that changed). Weak/contested case types come first
    and the `partial` band is oversampled, because that is where the measured literature puts
    LLM-grader divergence and where this grader's own real inflations were caught."""
    if not items:
        return []
    # STRATIFIED BY BAND, not just sorted by difficulty. The first cut ranked weak-case-type
    # and mid-band first and drew 15 — and every one came back `partial`, so the canary was
    # structurally blind to a grader that had started failing the CLEAR cases. A tripwire that
    # can only see one band is not a tripwire; it is a narrower badge. Quotas oversample the
    # middle (where the measured divergence lives) while keeping real anchors at both ends.
    quotas = {"partial": 7, "lapsed": 4, "recalled": 4}
    def rank(it):
        return (0 if (it.get("case_type") or "") in CANARY_CASE_TYPES else 1,
                hashlib.sha256((it.get("sid") or "").encode("utf-8")).hexdigest())
    picked = []
    for band, want in sorted(quotas.items()):
        pool = sorted((i for i in items if i.get("gold_grade") == band), key=rank)
        picked.extend(pool[:want])
    if len(picked) < CANARY_N:      # a thin gold set: top up deterministically, never pad
        seen = {i.get("sid") for i in picked}
        rest = sorted((i for i in items if i.get("sid") not in seen), key=rank)
        picked.extend(rest[:CANARY_N - len(picked)])
    return sorted(picked, key=rank)[:CANARY_N]

def cmd_gold(_args):
    """Emit the gold set SHAPED EXACTLY LIKE `stash list` — a bare array, answer stripped.

    This is what /coach audit feeds the real assessor, and the shape is the point: `gold >
    f.json` must be a drop-in for `stash list > f.json`, because an audit that hands the
    grader anything the real skill would not hand it measures a grader that does not exist.
    v0.6 shipped a dead feature that a dogfood CERTIFIED, purely because the dogfood prompt
    told the assessor something /learn never tells it (RELEASE_PROTOCOL §5.5).

    So: no envelope, no counts, no instructions — stdout is exactly the payload. The skipped
    count goes to STDERR (a human sees it; the JSON pipe stays clean) and is re-reported in
    the audit's own coverage block, so it never goes unsaid."""
    items, meta = load_gold()
    if getattr(_args, "canary", False):
        items = canary_items(items)
    if meta["skipped"]:
        sys.stderr.write("engram: %d malformed gold item(s) skipped\n" % meta["skipped"])
    if meta["modified"]:
        sys.stderr.write("engram: ground truth is %s\n" % meta["source"])
    # `node_kind` (v1.1) rides only where it exists — a real stash carries the key on
    # procedure entries and OMITS it on concept ones, and the audit payload must be
    # indistinguishable from a real settle. `confidence` stays even when null (null
    # confidence is legitimate data the assessor must pass through untouched).
    emit([{k: it.get(k) for k in GOLD_ASSESSOR_KEYS
           if k != "node_kind" or it.get(k) is not None} for it in items])

def _qwk(pairs, scores=None):
    """Quadratic weighted kappa over (gold, grader) grade pairs. None if undefined.

    `scores` is the ORDINAL MAP — which categories exist and in what order. It defaults to
    the three grades; v1.4 passes the four ratings so the tutor-vs-assessor agreement is
    computed by this same function rather than a second implementation that could drift
    (the v0.6.4 lesson: one predicate, or three of the four call sites are wrong).

    THE headline. Raw agreement overstates chance-corrected agreement by 34-41 points in
    the measured literature, so it is reported but never quoted alone. Returns None when
    the expected-disagreement mass is zero (both raters degenerate onto one category) —
    None, not 1.0: an undefined agreement must never read as a perfect one, because that
    is a wrong number in the flattering direction, which is bug class #1 in this repo."""
    scores = GOLD_SCORE if scores is None else scores
    k = len(scores)
    n = len(pairs)
    if not n:
        return None
    obs = [[0] * k for _ in range(k)]
    for gold, grader in pairs:
        obs[scores[gold]][scores[grader]] += 1
    row = [sum(obs[i]) for i in range(k)]
    col = [sum(obs[i][j] for i in range(k)) for j in range(k)]
    num = den = 0.0
    for i in range(k):
        for j in range(k):
            w = ((i - j) ** 2) / float((k - 1) ** 2)
            num += w * obs[i][j]
            den += w * (row[i] * col[j] / float(n))
    if den == 0:
        return None
    return 1.0 - num / den

def _fmt(x, sign=False):
    """A number for a human, or the honest word for its absence. Never crashes on None —
    an audit read is the one string a learner is guaranteed to see."""
    if not isinstance(x, (int, float)) or isinstance(x, bool):
        return "not measured"
    return ("%+.2f" if sign else "%.2f") % x

def _audit_runs(payload):
    """Normalize the audit payload into a list of runs (each a list of graded items)."""
    if isinstance(payload, list):
        if payload and all(isinstance(x, list) for x in payload):
            return payload               # [[...], [...], [...]]
        return [payload]                 # a single run, as the assessor emits it
    if isinstance(payload, dict):
        runs = payload.get("runs")
        if isinstance(runs, list) and all(isinstance(x, list) for x in runs):
            return runs
        one = payload.get("run")
        if isinstance(one, list):
            return [one]
    die("audit payload must be the assessor's output array, a list of >=%d such arrays, "
        "or {\"grader\": \"...\", \"runs\": [[...], ...]}" % MIN_AUDIT_RUNS)

def _run_grades(run):
    """({sid: grade}, duplicate_sids) for one assessor run.

    **FIRST grade wins on a duplicate sid, and the duplicate is REPORTED.** The first cut did
    `out[sid] = grade` — last-wins — so a grader that got 12 items badly wrong and then
    re-emitted those same 12 sids with corrected grades later in the array turned a `fail`
    (qwk 0.00, leniency +0.67) into a `pass` (qwk 1.00), silently. `n` stayed 33 and nothing
    said a word.

    That is the mirror image of the dropped-sid bug the coverage guard already catches: same
    class, opposite mechanism, and an LLM assessor self-correcting mid-array produces it for
    free. A grader does not get to mark its own homework twice and keep the better score.

    Items without a usable sid+grade are dropped here and counted by the caller — a dropped
    item is a coverage failure, not a silence."""
    out, dupes = {}, set()
    for it in run:
        if not isinstance(it, dict):
            continue
        sid, grade = it.get("sid"), it.get("grade")
        if isinstance(sid, str) and sid and grade in GRADES:
            if sid in out:
                dupes.add(sid)      # keep the FIRST verdict; the re-do is evidence, not a fix
                continue
            out[sid] = grade
    return out, dupes

def cmd_assessor_audit(args):
    """Measure the grader that writes every receipt. Writes audits/<date>-NN.json.

    ONE denominator for every number in this payload: the set of gold items graded in
    EVERY run. Per-run denominators would let a grader that dropped half the set report a
    beautiful QWK over the half it kept — survivorship bias, wearing a lab coat."""
    payload = load_payload(args)
    runs = _audit_runs(payload)
    grader = "engram-assessor"
    if isinstance(payload, dict) and isinstance(payload.get("grader"), str) and payload["grader"]:
        grader = payload["grader"][:64]

    # CONTAMINATION GUARD. If the grader's output carries the gold answer, the grader was
    # shown the gold answer, and the audit is theatre. Die loudly rather than certify.
    #
    # NARROWED to the two keys that could ONLY have come from the gold schema. The first cut
    # also died on `rationale` — which is an extremely natural key for a grader to invent
    # unprompted, and killing the audit to accuse an innocent grader of cheating is a
    # false-positive that makes the feature unrunnable. `gold_grade` IS the answer;
    # `case_type` all but is (terse-but-correct -> recalled 10/10, confident-and-wrong ->
    # lapsed 10/10). Neither has any business in a grader's output, ever.
    for run in runs:
        for it in run:
            if isinstance(it, dict) and any(k in it for k in GOLD_ANSWER_KEYS):
                die("audit payload carries %s — the grader was shown the answer, so this "
                    "audit would be theatre. Feed the assessor `engram.py gold` output "
                    "verbatim and nothing else (RELEASE_PROTOCOL §5.5)."
                    % "/".join(k for k in GOLD_ANSWER_KEYS if k in it))

    gold, gold_meta = load_gold(getattr(args, "gold", None))
    # THE SCOPE (v1.4). A canary run grades a ~15-item subset, so it is measured against that
    # subset and — critically — can never mint a `pass` (invariant 12). Detected from the
    # payload rather than trusted from a flag: the sids the grader actually returned are the
    # only honest evidence of which set it was given.
    canary = canary_items(gold)
    canary_sids = {g["sid"] for g in canary}
    scope = "full"
    graded_sids_probe = {sid for r in runs for it in r
                         if isinstance(it, dict) and isinstance(it.get("sid"), str)
                         for sid in [it["sid"]]}
    if (getattr(args, "canary", False)
            or (graded_sids_probe and graded_sids_probe <= canary_sids
                and len(graded_sids_probe) < len(gold))):
        scope, gold = "canary", canary
    grader_context = getattr(args, "grader_context", None)
    grader_context = (grader_context[:120] if isinstance(grader_context, str) and grader_context
                      else "unknown")
    skipped = gold_meta["skipped"]
    by_sid = {g["sid"]: g for g in gold}
    parsed = [_run_grades(r) for r in runs]
    graded = [g for g, _ in parsed]
    dupes = sorted({sid for _, d in parsed for sid in d})

    # THE HONEST DENOMINATOR: graded in every run, and known to the gold set.
    matched = sorted(sid for sid in by_sid if all(sid in g for g in graded)) if graded else []
    ungraded = sorted(sid for sid in by_sid if sid not in matched)
    unknown = sorted({sid for g in graded for sid in g if sid not in by_sid})

    # Are the runs literally the same object three times? The engine cannot prove independence
    # — nothing can, from the outside — but it can refuse to ASSERT a reproducibility figure it
    # may not have measured. Three copy-pasted runs give test_retest 1.00 and satisfy both
    # MIN_AUDIT_RUNS and the paradox gate, which exist precisely to prevent certification
    # without a reproducibility measurement. (A genuinely deterministic grader also produces
    # identical runs, which is why this is a caveat and not a refusal — the ambiguity is real,
    # so the ambiguity is what gets published.)
    identical_runs = len(graded) > 1 and all(g == graded[0] for g in graded[1:])

    per_run, confusion, by_case, by_gold_band = [], {}, {}, {}
    up = down = exact_n = 0            # THE DIRECTION OF ERROR — see `direction` below
    for g in graded:
        pairs = [(by_sid[sid]["gold_grade"], g[sid]) for sid in matched]
        if not pairs:
            per_run.append({"n": 0, "qwk": None, "exact_agreement": None,
                            "leniency_bias": None})
            continue
        exact = sum(1 for a, b in pairs if a == b) / float(len(pairs))
        bias = sum(GOLD_SCORE[b] - GOLD_SCORE[a] for a, b in pairs) / float(len(pairs))
        q = _qwk(pairs)
        per_run.append({"n": len(pairs), "qwk": (round(q, 3) if q is not None else None),
                        "exact_agreement": round(exact, 3), "leniency_bias": round(bias, 3)})
        for sid in matched:
            a, b = by_sid[sid]["gold_grade"], g[sid]
            confusion["%s->%s" % (a, b)] = confusion.get("%s->%s" % (a, b), 0) + 1
            if GOLD_SCORE[b] > GOLD_SCORE[a]:
                up += 1                # graded UP = inflated. THE dangerous direction.
            elif GOLD_SCORE[b] < GOLD_SCORE[a]:
                down += 1              # graded DOWN = harsh. Costly, but never flattering.
            else:
                exact_n += 1
            bd = by_gold_band.setdefault(a, {"items": set(), "judgments": 0, "agree": 0,
                                              "bias_sum": 0.0, "up": 0})
            bd["items"].add(sid)
            bd["judgments"] += 1
            bd["agree"] += 1 if a == b else 0
            bd["bias_sum"] += GOLD_SCORE[b] - GOLD_SCORE[a]
            bd["up"] += 1 if GOLD_SCORE[b] > GOLD_SCORE[a] else 0
            ct = by_sid[sid].get("case_type") or "unclassified"
            slot = by_case.setdefault(ct, {"items": set(), "judgments": 0, "agree": 0,
                                           "bias_sum": 0.0})
            slot["items"].add(sid)
            slot["judgments"] += 1
            slot["agree"] += 1 if a == b else 0
            slot["bias_sum"] += GOLD_SCORE[b] - GOLD_SCORE[a]

    def _mean(key):
        vals = [r[key] for r in per_run if r.get(key) is not None]
        return round(sum(vals) / len(vals), 3) if vals else None

    qwk, exact_agreement, leniency_bias = _mean("qwk"), _mean("exact_agreement"), _mean("leniency_bias")
    qwks = [r["qwk"] for r in per_run if r.get("qwk") is not None]
    qwk_min = min(qwks) if qwks else None

    # TEST-RETEST: consistency across runs. Reported, and DELIBERATELY never sufficient.
    retest = None
    if len(graded) >= 2 and matched:
        agrees = [sum(1 for sid in matched if a[sid] == b[sid]) / float(len(matched))
                  for i, a in enumerate(graded) for b in graded[i + 1:]]
        retest = round(sum(agrees) / len(agrees), 3) if agrees else None

    # ITEMS and JUDGMENTS are different denominators and must never share a key called `n`.
    # The first cut emitted `n: 30` for a case type that has TEN items — 30 was judgments
    # (10 items x 3 runs), and nothing said so. That is the v0.6.4 unlabelled-denominator bug
    # reproduced inside the release built to catch unlabelled denominators (§4.8 Q3). Name it,
    # count it, publish it beside the rate.
    # THE MID-BAND IS WHERE GRADERS ACTUALLY FAIL (v1.4). The 2026 short-answer literature
    # finds rubric-anchored LLM graders near-human at the extremes and materially off in the
    # middle — while the headline QWK, pooled across bands, looks fine. `partial` is Engram's
    # middle, so the audit now reports each band's own agreement, signed bias and inflation
    # count. A number that is right in aggregate and wrong where it matters is bug class #7.
    band_report = {b: {"items": len(s["items"]), "judgments": s["judgments"],
                       "agreement": round(s["agree"] / float(s["judgments"]), 3),
                       "leniency_bias": round(s["bias_sum"] / float(s["judgments"]), 3),
                       "graded_up": s["up"]}
                   for b, s in sorted(by_gold_band.items()) if s["judgments"]}
    by_case_type = {ct: {"items": len(s["items"]), "judgments": s["judgments"],
                         "agreement": round(s["agree"] / float(s["judgments"]), 3),
                         "leniency_bias": round(s["bias_sum"] / float(s["judgments"]), 3)}
                    for ct, s in sorted(by_case.items()) if s["judgments"]}

    # THE DIRECTION OF ERROR — the single most decision-relevant fact in the whole payload,
    # and the first cut left it derivable-but-unstated inside `confusion`, which nothing reads.
    # `leniency_bias` is a MEAN: +0.00 is equally consistent with a perfect grader and with one
    # that inflates half the set and deflates the other half. Only the direction counts
    # distinguish them, and the difference is the entire safety argument:
    #   graded UP   -> the learner is told they know something they do not. They stop reviewing.
    #   graded DOWN -> the learner re-drills something they had earned. Costly, never flattering.
    direction = {"graded_up": up, "graded_down": down, "exact": exact_n,
                 "judgments": up + down + exact_n,
                 "note": ("`graded_up` is the only direction that can flatter a learner into "
                          "not reviewing. A mean bias near zero does NOT imply zero inflation — "
                          "it can also mean the grader inflates as often as it deflates.")}

    n = len(matched)
    # A canary is 15 items BY DESIGN, so it cannot be held to the full audit's floor — that
    # would make every canary read `insufficient-data` and the re-licensing path would be
    # dead code shipped as a feature (bug class #3).
    min_n = min(CANARY_N, len(gold)) if scope == "canary" else MIN_AUDIT_N
    # A run that graded the same sid twice did not cover the gold set — it covered part of it
    # and then had a second go. Same class as a dropped sid, so it lands in the same guard.
    coverage_complete = bool(gold) and not ungraded and not unknown and not dupes
    reasons = []
    # The instrument's own limit, on every audit, first. It is not a caveat about this run — it is
    # a caveat about what a QWK from THIS gold set can mean at all, and it must outlive any
    # particular verdict. When someone who is not the author adjudicates the set, this goes away.
    if GOLD_ADJUDICATION != "human" and not getattr(args, "gold", None):
        reasons.append(_gold_circularity(
            sum(1 for it in gold if isinstance(it, dict) and it.get("disputed"))))
    if gold_meta["modified"]:
        reasons.append(
            "GROUND TRUTH IS NOT THE SHIPPED GOLD SET: %s. This verdict is not comparable to "
            "the published QWK, and a gold set re-adjudicated to agree with the grader would "
            "certify anything." % gold_meta["source"])
    if dupes:
        reasons.append(
            "%d sid(s) were graded MORE THAN ONCE in a single run (%s) — the first verdict was "
            "kept and the re-do discarded. A grader does not get to mark its own homework twice "
            "and keep the better score."
            % (len(dupes), ", ".join(dupes[:4])))
    if identical_runs:
        reasons.append(
            "all %d runs returned IDENTICAL grades — so test-retest measures nothing here. "
            "Either the grader is perfectly deterministic, or the runs were not independent, "
            "and this figure cannot tell those apart." % len(runs))
    if ungraded:
        reasons.append("coverage: %d of %d gold items were not graded in every run (the "
                       "assessor dropped their sid, or graded them inconsistently across "
                       "runs) — every number here is computed over the %d that survived"
                       % (len(ungraded), len(gold), n))
    if unknown:
        reasons.append("coverage: %d graded sid(s) are not in the gold set (%s)"
                       % (len(unknown), ", ".join(unknown[:4])))
    if skipped:
        reasons.append("gold set: %d malformed item(s) skipped" % skipped)
    if qwk is None:
        reasons.append("QWK undefined — the grader (or the gold set) has no variance to "
                       "measure agreement against")
    elif qwk < QWK_FLOOR:
        reasons.append("QWK %.2f is below the %.2f floor — the grader does not agree with "
                       "human adjudication well enough to trust any number downstream"
                       % (qwk, QWK_FLOOR))
    if leniency_bias is not None and leniency_bias > BIAS_MAX:
        reasons.append("leniency_bias +%.2f exceeds the +%.2f ceiling — the grader INFLATES, "
                       "so every retention figure it feeds is too high" % (leniency_bias, BIAS_MAX))
    # THE PARADOX GATE. High self-consistency is what a reliably-LENIENT grader also looks
    # like, and Engram's prompt selects for consistency. So consistency may never certify
    # on its own: above PARADOX_RETEST, leniency must be STRICTLY under the ceiling.
    paradox = (retest is not None and retest > PARADOX_RETEST
               and leniency_bias is not None and leniency_bias >= BIAS_MAX)
    if paradox:
        reasons.append("THE CONSISTENCY-BIAS PARADOX: test-retest %.2f with leniency +%.2f. "
                       "A grader this reproducible and this lenient is not a good grader — "
                       "it is a reliably wrong one (docs/07 §3). Consistency is not validity."
                       % (retest, leniency_bias))

    teeth = (qwk is None or qwk < QWK_FLOOR
             or (leniency_bias is not None and leniency_bias > BIAS_MAX) or paradox)
    if n < min_n:
        verdict = "insufficient-data"
        reasons.insert(0, "n=%d < %d — not enough adjudicated items to say anything about "
                          "this grader" % (n, min_n))
    elif not coverage_complete:
        verdict = "incomplete"          # the QWK is over a subset the GRADER chose. Untrustworthy.
    elif teeth:
        verdict = "fail"
    elif len(runs) < MIN_AUDIT_RUNS:
        verdict = "insufficient-runs"   # the paradox check never ran, so nothing may be certified
        reasons.append("only %d run(s) — the consistency-bias paradox cannot be checked "
                       "below %d, and an unchecked paradox may not be certified as a pass"
                       % (len(runs), MIN_AUDIT_RUNS))
    elif qwk < QWK_TARGET:
        verdict = "warn"
        reasons.append("QWK %.2f clears the %.2f floor but is under the %.2f conventional "
                       "target for automated scoring" % (qwk, QWK_FLOOR, QWK_TARGET))
    else:
        verdict = "pass"
    # ⚠ A CANARY MAY NEVER MINT A PASS (invariant 12). It grades ~15 items chosen for
    # difficulty, so it is a TRIPWIRE, not a certification: it can re-license the verdict a
    # full audit already earned, or demand a fresh full audit. Anything else and the cheap
    # path would quietly replace the expensive one, which is how a 15-item badge ends up
    # standing in for an 86-item claim.
    if scope == "canary" and verdict not in ("insufficient-data",):
        clean = (up == 0 and not teeth)
        verdict = "canary-pass" if clean else "canary-fail"
        reasons.append(
            "CANARY SCOPE: %d of %d gold items, chosen for difficulty (mid-band and the case "
            "types this grader has historically failed). A canary can RE-LICENSE the last "
            "full audit or demand a new one — it can never certify a grader on its own."
            % (n, len(canary)))
        if not clean:
            reasons.append("the canary caught %d inflation%s — the badge is void until a FULL "
                           "audit is re-run" % (up, "" if up == 1 else "s"))

    if verdict == "pass":
        # `pass` structurally implies runs >= MIN_AUDIT_RUNS and matched non-empty, so retest
        # and leniency are real numbers here. Formatted defensively anyway: a %.2f against a
        # None raises TypeError, and the ONLY thing standing between this line and that crash
        # is a branch three ifs up the ladder. The §4.5 mutation run found this by bypassing
        # that branch — a latent landmine for whoever next edits the verdict order.
        read = ("grader validated: QWK %s over %d adjudicated items, %d runs; leniency %s; "
                "test-retest %s"
                % (_fmt(qwk), n, len(runs), _fmt(leniency_bias, sign=True), _fmt(retest)))
        # …AND THE CAVEATS COME WITH IT. `pass` was the ONLY verdict that built a fresh read and
        # threw `reasons` away — and `pass` is the only verdict where the teeth are off, so it is
        # the one place a caveat has to survive. Three copy-pasted runs produced
        # `identical_runs: true`, the engine wrote "test-retest measures nothing here" into
        # `reasons`, and then the read it printed said **"test-retest 1.00"** as a validated
        # figure. The most reassuring number in the payload, quoted as evidence, by the branch
        # that had just discarded the note explaining it was evidence of nothing.
        #
        # Bug class #4 — a guard nobody reads — reproduced INSIDE the release built to catch it.
        # And the selftest for it green-checked `reasons`, a key no runtime surface consumed:
        # a check can assert a field exists and still prove nothing about whether anyone reads it.
        # (Found by the independent post-release reviewer. §4.8 Q4, again, the hard way.)
        if reasons:
            read += " — BUT: " + "; ".join(reasons)
    elif qwk is not None:
        read = "QWK %.2f (n=%d, %d runs) — %s" % (qwk, n, len(runs), "; ".join(reasons))
    else:
        read = "; ".join(reasons) or "no measurement could be made"
    # The direction of error reaches the NARRATOR, not just a nested key (§4.8 Q4). "It never
    # once graded up" and "it inflates 1 in 12" are the same mean bias and opposite products.
    if direction["judgments"]:
        read += (" · of %d judgments it graded UP %d time%s (the only direction that can flatter) "
                 "and DOWN %d"
                 % (direction["judgments"], up, "" if up == 1 else "s", down))
    # Name the weakest case type ONLY when it is genuinely weak — i.e. worse than the
    # grader's own average. On a clean audit, "weakest: clear-lapsed (100% agreement)" is
    # noise that reads like a defect. The whole value of this clause is that it points at
    # the case type the grader actually fails (docs/09 §4.4: "inflates fluent-but-empty
    # productions — the exact failure the separation of powers exists to prevent").
    worst = min(by_case_type.items(), key=lambda kv: kv[1]["agreement"], default=None)
    if (worst and worst[1]["judgments"] >= 3 and exact_agreement is not None
            and worst[1]["agreement"] < exact_agreement):
        read += (" · weakest case type: %s (%.0f%% agreement over %d items, leniency %+.2f)"
                 % (worst[0], 100 * worst[1]["agreement"], worst[1]["items"],
                    worst[1]["leniency_bias"]))

    audit = {
        "ts": today().isoformat(), "grader": grader,
        "n": n, "gold_n": len(gold), "runs": len(runs),
        "qwk": qwk,                        # THE headline
        "qwk_min_run": qwk_min,
        "exact_agreement": exact_agreement,  # reported, NEVER quoted alone (34-41pt inflation)
        "leniency_bias": leniency_bias,      # signed; + = inflating
        "test_retest": retest,               # consistency, NOT correctness
        "direction": direction,            # ← the safety argument, in three integers
        "confusion": confusion,            # counts are JUDGMENTS (items x runs), not items
        "by_case_type": by_case_type,
        "by_gold_band": band_report,       # v1.4: where in the range the grader actually fails
        "scope": scope,                    # "full" | "canary" — a canary never certifies
        # WHICH GRADER earned this verdict (v1.4). Supplied by the skill from what its
        # platform actually knows; the engine stores it verbatim and NEVER invents one — a
        # model naming its own weights is fabricated data. "unknown" is honest and falls back
        # to time-based staleness.
        "grader_context": grader_context,
        "by_run": per_run,
        # WHICH ground truth produced this verdict (§4.8 Q5) — reported HONESTLY, which the
        # first cut did not: it hard-coded "bundled" even when gold/local-gold.jsonl had
        # silently re-adjudicated every item. A provenance field that lies is worse than none,
        # because it is believed. `load_gold` now counts the overrides and this reports them.
        "gold_source": gold_meta["source"],
        "gold_adjudication": GOLD_ADJUDICATION,   # "authored" | "human" — the instrument's limit
        "gold_modified": gold_meta["modified"],
        "gold_local_overrides": gold_meta["local_overrides"],
        "gold_local_added": gold_meta["local_added"],
        "identical_runs": identical_runs,
        "duplicate_sids": dupes,
        # The gold set is ADVERSARIAL BY DESIGN (share derived, never hardcoded — it shipped as
        # a stale "88%" from the 66-item era), so this bias is measured on the cases where
        # graders fail — not on the mix of productions a learner actually writes. It is the right
        # number for "can this grader be fooled"; it is an upper bound on "how wrong are my
        # receipts". Saying so is cheaper than being quietly misread.
        "bias_note": ("leniency_bias is measured over a deliberately adversarial gold set "
                      "(%d%% trap cases). It bounds how far the grader CAN be pushed; it is not "
                      "an unbiased estimate of its bias on ordinary productions."
                      % _adversarial_pct(gold)),
        "coverage": {"gold_n": len(gold), "measured": n,
                     "ungraded": ungraded, "unknown_sids": unknown, "duplicate_sids": dupes,
                     "gold_skipped_malformed": skipped, "complete": coverage_complete},
        "thresholds": {"qwk_floor": QWK_FLOOR, "qwk_target": QWK_TARGET,
                       "bias_max": BIAS_MAX, "min_n": MIN_AUDIT_N,
                       "min_runs": MIN_AUDIT_RUNS, "paradox_retest": PARADOX_RETEST},
        "paradox_triggered": paradox,
        "grader_unvalidated": verdict not in ("pass", "warn"),
        "verdict": verdict,
        "reasons": reasons,
        "read": read,
    }
    # Audits are EVIDENCE, so they are append-only like receipts: a same-day re-audit gets
    # its own file and never overwrites the earlier one. (docs/09 §3.4 said <date>.json;
    # a second audit that day would have destroyed the first, and destroying evidence to
    # keep a filename tidy is not a trade this project makes.)
    os.makedirs(p("audits"), exist_ok=True)
    seq = 1
    while os.path.exists(p("audits", "%s-%02d.json" % (audit["ts"], seq))):
        seq += 1
    path = p("audits", "%s-%02d.json" % (audit["ts"], seq))
    write_json(path, audit)
    emit({**audit, "path": path})

def _audit_sort_key(name):
    """("2026-07-11", 2) from "2026-07-11-02.json". NUMERIC on the sequence, never lexicographic.

    A plain string sort puts `...-100.json` BEFORE `...-99.json`, so the 100th audit of a day —
    a `fail` — would be shadowed by the 99th, a `pass`. Improbable and flattering, which is the
    worst combination: the function's own docstring swears it never serves a stale pass."""
    stem = name[:-5] if name.endswith(".json") else name
    head, _, tail = stem.rpartition("-")
    try:
        return (head, int(tail))
    except ValueError:
        return (stem, -1)          # an unrecognised name sorts before any real audit

def _latest_audit():
    """The newest audit file, or None. Never falls back to an older one on corruption:
    a stale `pass` shown because today's audit is unreadable is a flattering lie."""
    d = p("audits")
    try:
        names = sorted((f for f in os.listdir(d) if f.endswith(".json")), key=_audit_sort_key)
    except OSError:
        return None
    if not names:
        return None
    # ⚠ THE LATEST *FULL* AUDIT — a canary is not a candidate (v1.4). A canary can only
    # re-license or revoke; if it were allowed to BE the latest audit, running one would
    # replace an 86-item verdict with a 15-item one, and `canary-pass` (not a valid full
    # verdict) would read as `unreadable` and silently void a badge that was fine. The cheap
    # path must never overwrite the expensive one — it may only vouch for it.
    for latest in reversed(names):
        a = read_json(os.path.join(d, latest), quarantine=False)
        if isinstance(a, dict) and a.get("scope") == "canary":
            continue
        if not isinstance(a, dict) or a.get("verdict") not in (
                "pass", "warn", "fail", "incomplete", "insufficient-runs", "insufficient-data"):
            return {"__unreadable__": latest}
        return a
    return None

def _latest_canary_relicense(full_audit):
    """Has a CLEAN canary been run since this full audit? (v1.4)

    Scans the audit directory for canary-scoped results newer than the full audit's own
    timestamp. A `canary-pass` re-licenses a badge whose grader context changed; a
    `canary-fail` never does (and its own teeth are already engaged through the verdict)."""
    d = p("audits")
    if not os.path.isdir(d):
        return None
    base = safe_date(full_audit.get("ts") if isinstance(full_audit, dict) else None)
    best = None
    for name in sorted(os.listdir(d)):
        if not name.endswith(".json"):
            continue
        rec = read_json(os.path.join(d, name), default=None, quarantine=False)
        if not isinstance(rec, dict) or rec.get("scope") != "canary":
            continue
        if rec.get("verdict") != "canary-pass":
            continue
        ts = safe_date(rec.get("ts"))
        if ts and (base is None or ts >= base):
            best = rec
    return best

def compute_grader_health(current_grader_context=None):
    """The teeth. An unaudited oracle makes every number downstream unearned.

    `grader_unvalidated` is TRUE until an audit says otherwise — including when no audit
    has ever run. That is not pessimism, it is the constitution: no unearned claims. It
    fails toward "we don't know", never toward "it's fine"."""
    a = _latest_audit()
    if a is None:
        return {"audited": False, "verdict": "unaudited", "grader_unvalidated": True,
                "stamp": "grader unaudited — QWK unknown; run /coach audit",
                "read": ("the grader that writes every receipt has never itself been "
                         "graded. Its agreement with human adjudication is unknown, so "
                         "every number it feeds is unearned. `/coach audit` measures it "
                         "in about four minutes.")}
    if "__unreadable__" in a:
        return {"audited": False, "verdict": "unreadable", "grader_unvalidated": True,
                "stamp": "latest audit file is corrupt — grader unvalidated",
                "read": ("audits/%s is unreadable. Refusing to fall back to an older "
                         "audit: a stale pass is worse than no pass. Re-run /coach audit."
                         % a["__unreadable__"])}
    # An audit file whose `verdict` is a valid literal can still hold garbage in every OTHER
    # field after a hand-edit — and every one of them is now interpolated into the dashboard's
    # HTML. `escape()` on a list raises AttributeError and takes `report` (and `stats`, and
    # therefore /coach) down with it. Sanitize at THIS gate, not at the twelve call sites.
    _num = lambda k: (a.get(k) if isinstance(a.get(k), (int, float))
                      and not isinstance(a.get(k), bool) else None)
    _str = lambda k: (a[k] if isinstance(a.get(k), str) else None)
    # DERIVE `grader_unvalidated` FROM THE VERDICT — never trust it from the file.
    # `_latest_audit` already whitelists `verdict`; it never checked that the two agreed. An
    # audit file carrying `"verdict": "fail"` with `"grader_unvalidated": false` (a hand-edit, a
    # torn write) silenced the teeth completely: no stamp, no red on the dashboard, retention
    # reading a clean "30-day recall 100%". This function's own docstring swears it "fails toward
    # 'we don't know', never toward 'it's fine'" — and it was believing a boolean a corrupt file
    # handed it. The verdict is the validated field; the flag is a FUNCTION of it, not an input.
    unval = a.get("verdict") not in ("pass", "warn")
    qwk = _num("qwk")

    # ── STALENESS (v1.4): A BADGE BELONGS TO THE GRADER THAT EARNED IT ──────────────────
    #
    # A silent model swap under a learner runs UNIFORMLY MORE LENIENT in the one published
    # measurement of it (2026: injected judge-version drift, detected 60/60, lenient in
    # direction) — which is precisely Engram's dangerous direction. A platform upgrade would
    # otherwise inherit an audit it never sat, and the export gate would keep opening.
    #
    # Two triggers, in order of evidence: a CONTEXT MISMATCH (both known and different) is
    # decisive; when either side is unknown, TIME is the only signal left and is used
    # conservatively. Naive rolling drift detectors are deliberately NOT used — the measured
    # false-alarm rate on drift-free streams is 75%, and a gate that cries wolf is a gate
    # nobody reads.
    stale = None
    audited_ctx = _str("grader_context")
    current_ctx = current_grader_context if isinstance(current_grader_context, str) else None
    if not unval:
        if (audited_ctx and current_ctx and audited_ctx not in ("unknown",)
                and current_ctx not in ("unknown",) and audited_ctx != current_ctx):
            stale = ("stale-model", "the model that earned this badge (%s) is not the one "
                                    "grading you now (%s)" % (audited_ctx, current_ctx))
        else:
            ts = safe_date(_str("ts"))
            age = (today() - ts).days if ts else None
            if age is not None and age > AUDIT_STALE_DAYS:
                stale = ("stale-age", "the last full audit is %d days old and the grader it "
                                      "measured cannot be identified (%s)"
                                      % (age, audited_ctx or "no context recorded"))
    if stale:
        # A canary can lift this without a full re-run — that is what it is for — and the
        # relicensing is recorded rather than assumed.
        relicensed = _latest_canary_relicense(a)
        if relicensed:
            stale = None
    if stale:
        code, why = stale
        return {"audited": True, "ts": _str("ts"), "grader": _str("grader"),
                "n": _num("n"), "runs": _num("runs"), "qwk": qwk,
                "exact_agreement": _num("exact_agreement"),
                "leniency_bias": _num("leniency_bias"), "test_retest": _num("test_retest"),
                "direction": (a.get("direction") if isinstance(a.get("direction"), dict) else None),
                "by_case_type": (a["by_case_type"] if isinstance(a.get("by_case_type"), dict) else {}),
                "by_gold_band": (a["by_gold_band"] if isinstance(a.get("by_gold_band"), dict) else {}),
                "grader_context": audited_ctx, "current_grader_context": current_ctx,
                "gold_source": _str("gold_source"),
                "gold_adjudication": _str("gold_adjudication") or GOLD_ADJUDICATION,
                "gold_modified": bool(a.get("gold_modified")),
                "identical_runs": bool(a.get("identical_runs")),
                "reasons": [why], "verdict": code, "grader_unvalidated": True,
                "stamp": "GRADER BADGE EXPIRED (%s) — %s" % (code, why),
                "read": ("%s. The QWK below was real when it was measured and it is not a "
                         "claim about today's grader. `/coach audit` re-runs the canary "
                         "(~15 items) first; a clean canary re-licenses the badge, a dirty "
                         "one demands the full set." % why.capitalize())}
    if unval:
        stamp = "GRADER UNVALIDATED (%s) — these grades are not trustworthy" % a.get("verdict")
    elif a.get("gold_modified"):
        # A `pass` measured against a locally re-adjudicated gold set is not the shipped
        # measurement, and it must never look like one. A gold set edited to agree with the
        # grader would certify anything — so the fact rides on the stamp, not in a nested key.
        stamp = ("grader passed against a MODIFIED gold set (%s) — not the published measurement"
                 % (_str("gold_source") or "unknown source"))
    elif a.get("verdict") == "warn":
        stamp = "grader QWK %s — clears the floor, under the %.2f target" % (_fmt(qwk), QWK_TARGET)
    else:
        stamp = None
    d = a.get("direction")
    # `reasons` was computed, written to disk, asserted by a selftest — and returned by NOTHING.
    # `skills/coach/SKILL.md` says "Read `reasons` aloud"; the key did not exist on this payload.
    rs = [r for r in (a.get("reasons") or []) if isinstance(r, str)] \
        if isinstance(a.get("reasons"), list) else []
    return {"audited": True, "ts": _str("ts"), "grader": _str("grader"),
            "n": _num("n"), "runs": _num("runs"), "qwk": qwk,
            "exact_agreement": _num("exact_agreement"),
            "leniency_bias": _num("leniency_bias"), "test_retest": _num("test_retest"),
            "direction": d if isinstance(d, dict) else None,   # /coach must be able to say "never inflated"
            "by_case_type": (a["by_case_type"] if isinstance(a.get("by_case_type"), dict) else {}),
            "gold_source": _str("gold_source"),   # a verdict is only as good as its ground truth
            "gold_adjudication": _str("gold_adjudication") or GOLD_ADJUDICATION,
            "gold_modified": bool(a.get("gold_modified")),
            "identical_runs": bool(a.get("identical_runs")),
            "reasons": rs,                        # ← the caveats reach a narrator at last
            "verdict": a.get("verdict"), "grader_unvalidated": unval,
            "stamp": stamp, "read": _str("read") or "audit present but unreadable"}

ADJ_ANCHOR_PASS = 0.80        # calibration gate before an external rater may adjudicate
ADJ_ALPHA_GOOD, ADJ_ALPHA_TENTATIVE = 0.80, 0.667   # Krippendorff's canonical thresholds

def _krippendorff_ordinal(pairs):
    """Krippendorff's alpha for TWO raters on an ordinal 3-point scale. None if undefined.

    Computed here rather than approximated by a kappa because the adjudication kit's whole
    point is a statistic an outside reader recognises, with its own disagreement model:
    alpha = 1 - Do/De, where the ordinal metric weights a lapsed-vs-recalled disagreement
    more than an adjacent one. With two raters and no missing data this reduces to the
    standard coincidence-matrix form."""
    n = len(pairs)
    if n < 2:
        return None
    k = len(GOLD_SCORE)
    # values, by ordinal rank
    counts = [0] * k
    for a, b in pairs:
        counts[GOLD_SCORE[a]] += 1
        counts[GOLD_SCORE[b]] += 1
    total = 2 * n
    # ordinal difference metric (Krippendorff): squared sum of interval masses
    def delta(i, j):
        if i == j:
            return 0.0
        lo, hi = (i, j) if i < j else (j, i)
        s = sum(counts[g] for g in range(lo, hi + 1)) - (counts[lo] + counts[hi]) / 2.0
        return s * s
    do = sum(delta(GOLD_SCORE[a], GOLD_SCORE[b]) for a, b in pairs) / float(n)
    de = 0.0
    for i in range(k):
        for j in range(k):
            if i != j:
                de += counts[i] * counts[j] * delta(i, j)
    de = de / float(total * (total - 1)) if total > 1 else 0.0
    if de == 0:
        return None            # no disagreement possible: undefined, never a flattering 1.0
    return 1.0 - do / de

def _bootstrap_alpha_ci(pairs, seed=20260724, iters=1000):
    """Percentile CI for alpha. n=86 gives a WIDE interval — publish it anyway; a point
    estimate from 86 items quoted without its spread is the label lying about its own
    precision (§4.8 Q6)."""
    if len(pairs) < 4:
        return None
    rng = random.Random(seed)
    vals = []
    for _ in range(iters):
        s = [pairs[rng.randrange(len(pairs))] for _ in range(len(pairs))]
        a = _krippendorff_ordinal(s)
        if a is not None:
            vals.append(a)
    if len(vals) < iters // 2:
        return None
    vals.sort()
    return [round(vals[int(0.025 * len(vals))], 3), round(vals[int(0.975 * len(vals)) - 1], 3)]

def cmd_adjudication_stats(args):
    """Score an EXTERNAL human's adjudication of the gold set (v1.4, docs/ADJUDICATION.md).

    The repo has asked for one non-author human since v0.7 — *"the highest-value contribution
    anyone could make to this repository"* — and never shipped the procedure that would make
    their work countable. This is that procedure, in code: the calibration gate, the
    chance-corrected statistics an outside reader expects, and thresholds fixed BEFORE any
    file is read so the bar cannot move to fit the result.

    Read-only. It never edits the gold set: an adjudication that silently rewrote the ground
    truth would be the circularity this whole apparatus exists to disclose."""
    rows = load_payload(args)
    if isinstance(rows, dict):
        rows = rows.get("items") or rows.get("rows") or []
    if not isinstance(rows, list) or not rows:
        die("adjudication file must be a JSON array (or {items:[…]}) of "
            '{"sid": …, "grade": recalled|partial|lapsed, "anchor": true|false}')
    gold, gold_meta = load_gold(getattr(args, "gold", None))
    by_sid = {g["sid"]: g for g in gold}
    clean, bad = {}, []
    for r in rows:
        # `isinstance(..., str)` BEFORE the membership test: a hand-written adjudication file
        # can hold any JSON type, and `{"a": 1} in GOLD_SCORE` raises `unhashable type` rather
        # than returning False. Found by the fuzz — 35 crashes in 300 states, in a read path
        # whose entire job is to survive a human's hand-authored file.
        if not isinstance(r, dict) or not isinstance(r.get("sid"), str) \
                or not isinstance(r.get("grade"), str) or r["grade"] not in GOLD_SCORE:
            bad.append(r if isinstance(r, (str, int)) else "malformed")
            continue
        if r["sid"] not in by_sid:
            bad.append(r["sid"])
            continue
        clean[r["sid"]] = (r["grade"], bool(r.get("anchor")))
    anchors = {s: v for s, v in clean.items() if v[1]}
    scored = {s: v for s, v in clean.items() if not v[1]}
    # THE CALIBRATION GATE, FIRST. An untrained rater's disagreement is noise, and noise
    # published as "the gold set is contested" would be worse than no adjudication at all.
    a_pairs = [(by_sid[s]["gold_grade"], g) for s, (g, _) in anchors.items()]
    a_exact = (sum(1 for x, y in a_pairs if x == y) / float(len(a_pairs))) if a_pairs else None
    gate = {"n": len(a_pairs), "exact": (round(a_exact, 3) if a_exact is not None else None),
            "required": ADJ_ANCHOR_PASS,
            "passed": bool(a_pairs) and a_exact is not None and a_exact >= ADJ_ANCHOR_PASS}
    pairs = [(by_sid[s]["gold_grade"], g) for s, (g, _) in sorted(scored.items())]
    n = len(pairs)
    exact = (round(sum(1 for x, y in pairs if x == y) / float(n), 3)) if n else None
    qwk = _qwk(pairs) if n else None
    alpha = _krippendorff_ordinal(pairs) if n else None
    ci = _bootstrap_alpha_ci(pairs) if n else None
    stricter = sum(1 for x, y in pairs if GOLD_SCORE[y] < GOLD_SCORE[x])
    lenient = sum(1 for x, y in pairs if GOLD_SCORE[y] > GOLD_SCORE[x])
    confusion = {}
    for x, y in pairs:
        confusion["%s->%s" % (x, y)] = confusion.get("%s->%s" % (x, y), 0) + 1
    if not gate["passed"]:
        verdict, note = "calibration-failed", (
            "the rater did not clear the anchor gate (%s of %d anchors exact; %.0f%% required), "
            "so their adjudication is not scored. Retrain on the anchors, do not lower the bar."
            % (("%.0f%%" % (100 * a_exact)) if a_exact is not None else "no",
               len(a_pairs), 100 * ADJ_ANCHOR_PASS))
    elif alpha is None or n < MIN_AUDIT_N:
        verdict, note = "insufficient-data", (
            "n=%d scored items — too few to say anything about the gold set" % n)
    elif alpha >= ADJ_ALPHA_GOOD:
        verdict, note = "corroborated", (
            "alpha %.3f clears %.2f: an outside rater independently agrees with the authored "
            "gold. ONE external rater CORROBORATES; it does not replace the author — that "
            "would take two independent externals agreeing with each other." % (alpha, ADJ_ALPHA_GOOD))
    elif alpha >= ADJ_ALPHA_TENTATIVE:
        verdict, note = "tentatively-corroborated", (
            "alpha %.3f is in the tentative band [%.3f, %.2f) — usable for drawing tentative "
            "conclusions only, and every disagreement should be adjudicated before any badge "
            "language changes" % (alpha, ADJ_ALPHA_TENTATIVE, ADJ_ALPHA_GOOD))
    else:
        verdict, note = "contested", (
            "alpha %.3f is below %.3f: the external rater and the author do not agree, so the "
            "gold set is CONTESTED and the circularity caveat stays at full strength. That is "
            "a real finding about the instrument, not a failure of the rater." % (alpha, ADJ_ALPHA_TENTATIVE))
    emit({"rater": (getattr(args, "rater", None) or "external"),
          "gold_source": gold_meta["source"], "gold_n": len(gold),
          "anchor_gate": gate,
          "n": n, "exact": exact, "qwk": (round(qwk, 3) if qwk is not None else None),
          "alpha": (round(alpha, 3) if alpha is not None else None), "alpha_ci": ci,
          "direction": {"rater_stricter": stricter, "rater_more_lenient": lenient,
                        "agree": n - stricter - lenient},
          "confusion": confusion,
          "unknown_or_malformed": len(bad),
          "verdict": verdict,
          "read": ("%s · exact %s, QWK %s, alpha %s %s over %d items (pre-adjudication — the "
                   "only numbers that count as independent). %s"
                   % (verdict.upper(), _fmt(exact), _fmt(qwk), _fmt(alpha),
                      ("CI %s" % ci) if ci else "", n, note))})

def cmd_grader_health(args):
    emit(compute_grader_health(getattr(args, "grader_context", None)))

def has_transfer_question(node):
    """Is there a harder question to ask of this node at all?

    A `transfer_probe` the architect wrote — **or a capstone**, which carries none because the
    capstone IS the transfer probe. v0.8.0's census required a non-empty `transfer_probe`, so the
    capstone could never be counted `applied` however many times it was graded."""
    if not isinstance(node, dict):
        return False
    if node.get("capstone") is True:
        return True
    tp = node.get("transfer_probe")
    return isinstance(tp, str) and bool(tp.strip())

def _retrievals(slot):
    """Actual retrievals from the RECEIPT LOG — reviews + transfers, never `fsrs.reps`.

    `reps` counts every rating INCLUDING the encode, so `reps >= 3` delivered 2 retrievals while
    advertising 3 ("across 3+ retrievals", said the read). Off by one, in the direction that
    certifies transfer on less evidence than claimed. The engine's own doctrine (`_by_node`) is
    that the first receipt is the ENCODING EVENT, not a retrieval — so count the retrievals."""
    return (len(slot["reviews"]) + len(slot["transfers"])) if slot else 0

def _transfer_ready(node, tstate, t, slot=None):
    """Is this node mature enough to be asked the harder question?

    Mature = the memory has survived real intervals (s > 21d) across real RETRIEVALS (>= 3, counted
    from the receipt log — not `fsrs.reps`, which includes the encode). Probing transfer on a node
    the learner encoded yesterday measures nothing but their working memory, and failing it would
    be a lapse the schedule then punishes — a fabricated setback."""
    if node.get("capstone") is True:
        return False       # the capstone is served by `next` as a NODE, never re-probed by `transfer`
    tp = node.get("transfer_probe")
    if not (isinstance(tp, str) and tp.strip()):
        return False                       # a null transfer_probe is NEVER selected
    f = _fsrs_of(node)
    s = as_number(f.get("s"))
    if s is None or s <= TRANSFER_MATURE_S:
        return False
    if _retrievals(slot) < TRANSFER_MATURE_REPS:
        return False                       # 3 REAL retrievals, as advertised — the encode is not one
    last = safe_date(tstate.get("last"))
    if last and (t - last).days < TRANSFER_COOLDOWN_DAYS:
        return False                       # probed recently: this is a tool, not a quiz show
    return True

def transfer_candidates(topic_filter=None, limit=None):
    """Mature nodes whose capability has not been measured — untested first, then coldest.

    Pure read over graphs + receipts. Serves the probe the architect wrote and nothing has ever
    asked (docs/09 §1: "transfer_probe is dead data")."""
    nodes = _by_node(collect_receipts())
    t = today()
    out = []
    for tp, g in iter_graphs(topic_filter):
        for nid, node in graph_nodes(g).items():
            if is_retired(node):
                continue                      # off the learner's list (v1.3)
            slot = nodes.get((tp, nid))
            st = node_transfer_state(slot)
            if not _transfer_ready(node, st, t, slot):
                continue
            f = _fsrs_of(node)
            out.append({
                "topic": tp, "id": nid,
                "claim": node.get("claim"),
                "transfer_probe": node.get("transfer_probe"),
                "rubric": node.get("rubric", []),
                "transfer": st,
                "s": f.get("s"), "reps": f.get("reps", 0),
                "due": f.get("due"),
            })
    # untested first (never measured at all), then the coldest — a capability nobody has ever
    # checked outranks one that was checked in the spring.
    out.sort(key=lambda x: (x["transfer"]["state"] != "untested", x["transfer"]["last"] or ""))
    return out[:limit] if limit else out

CAPSTONE_ID = "capstone"

def _capstone_node(g, nodes):
    """The build, as a NODE — requiring every other node, so it unlocks exactly when the
    frontier empties and appears in `next` like anything else.

    `skills/learn` §5 has always said of the capstone: "this is the point of the whole topic —
    do not let it silently not happen." It silently did not happen, every time, because it was
    a suggestion in a prompt rather than a node in a graph. **A hope is not a schedule.** Put it
    in the DAG and it cannot be skipped by a tutor that ran out of context."""
    title = g.get("title") if isinstance(g.get("title"), str) else g.get("topic")
    goal = g.get("goal") if isinstance(g.get("goal"), str) and g.get("goal") else None
    return {
        "claim": ("You can USE %s in your own work, not just explain it." % (title or "this")),
        "probe": ("Build the thing. In your real repo, your real notes, your real argument — "
                  "produce something that only works if you actually understand %s.%s "
                  "Ship it, then explain which concept made which decision."
                  % (title or "this topic", (" Your stated goal: %s." % goal) if goal else "")),
        "rubric": ["the artifact exists and works (or the argument stands on its own)",
                   "names at least two concepts from this topic that DECIDED something in it",
                   "identifies where the model broke down or needed more than the topic gave"],
        "transfer_probe": None,          # the capstone IS the transfer probe
        "why_chain": [], "arbitrary": False, "threshold": False, "viz": None,
        "capstone": True,                 # the marker that makes materialization idempotent
        "edges": {"requires": sorted(nodes)},   # unlocks exactly when nothing is `new`
        "state": "new", "fsrs": _fresh_fsrs(), "artifact": None,
    }

def _has_capstone(nodes):
    return any(n.get("capstone") is True for n in nodes.values())

def cmd_capstone(args):
    """Materialize the capstone into an EXISTING graph. Idempotent: runs twice -> one node.

    New topics get theirs from `add-topic` structurally. This is the path for the graphs that
    already exist — including the founder's, which has been sitting one node short of the point
    of the whole exercise since day one."""
    g = load_graph(args.topic)
    nodes = graph_nodes(g)
    if _has_capstone(nodes):
        cid = next(nid for nid, n in nodes.items() if n.get("capstone") is True)
        emit({"ok": True, "topic": args.topic, "id": cid, "created": False,
              "note": "capstone already exists — no-op"})
        return
    if CAPSTONE_ID in g["nodes"]:
        die("topic %s already has a node called `%s` that is not a capstone — rename it first"
            % (args.topic, CAPSTONE_ID))
    g["nodes"][CAPSTONE_ID] = _capstone_node(g, nodes)
    if not isinstance(g.get("order"), list):
        g["order"] = sorted(nodes)
    g["order"] = [n for n in g["order"] if n != CAPSTONE_ID] + [CAPSTONE_ID]
    save_graph(g)
    emit({"ok": True, "topic": args.topic, "id": CAPSTONE_ID, "created": True,
          "requires": len(nodes),
          "read": ("the capstone is now a node in the graph. It unlocks when every concept is "
                   "encoded, and it shows up in `next` like anything else — so it cannot "
                   "silently not happen.")})

def cmd_retire(args):
    """The learner takes something off their list — the autonomy verb Engram never had (v1.3).

    Why this is exempt from "state advances only through receipts" (docs/09 §2.4), said
    rather than assumed: receipts guard MASTERY claims. Retirement advances no claim — it
    records a decision, on the node it governs, reversibly. It deliberately does not touch
    `state` (docs/15 §2.2): a fourth state value would ripple through every state reader, and
    the capstone requires every node, so it would block the build forever.

    Evidence: value-directed remembering (Castel) — learners are already strategic droppers,
    and a system that only lets them abandon (silently, guiltily) rather than retire
    (deliberately, visibly) is misreading a competence as a failure. The adherence LINK is
    untested and docs/13 §4.3 says so.

    THE RULE THAT KEEPS IT HONEST: the engine NEVER proposes retiring a specific node. That
    would be auto-retiring whatever the learner keeps failing — a flattering denominator
    dressed as help. The learner names it; the engine only records and counts."""
    require_slug(args.topic)
    g = load_graph(args.topic)
    nodes = graph_nodes(g)
    if args.node is not None:
        if args.node not in nodes:
            die("unknown node %s in topic %s (run `topic-status --topic %s`)"
                % (args.node, args.topic, args.topic))
        targets = [args.node]
    else:
        targets = sorted(nodes)
    changed, skipped = [], []
    for nid in targets:
        node = nodes[nid]
        if not isinstance(node, dict):
            skipped.append(nid)                     # corrupt node: doctor's business, not ours
            continue
        if args.restore:
            if not is_retired(node):
                skipped.append(nid)
                continue
            # The block STAYS, stamped — the decision's history is auditable rather than
            # erased. `is_retired` reads False the moment `restored` is set.
            node["retired"]["restored"] = today().isoformat()
            changed.append(nid)
        else:
            if is_retired(node):
                skipped.append(nid)
                continue
            node["retired"] = {"ts": today().isoformat(), "restored": None}
            changed.append(nid)
    if changed:
        save_graph(g)
    live = sum(1 for n in nodes.values() if isinstance(n, dict) and is_retired(n))
    verb = "restored" if args.restore else "retired"
    emit({"ok": True, "topic": args.topic, verb: changed, "unchanged": skipped,
          "retired_now": live,
          "read": ("%d node%s %s; %d retired in this topic. Retired nodes leave the review "
                   "queue and the frontier, and are COUNTED in every denominator they leave "
                   "(adherence, retention.unmeasured) — chosen, never quietly dropped."
                   % (len(changed), "" if len(changed) == 1 else "s", verb, live))})

def cmd_transfer(args):
    cands = transfer_candidates(args.topic, args.limit)
    total = len(transfer_candidates(args.topic))
    if not cands:
        emit({"items": [], "n": 0,
              "read": ("nothing is mature enough to test for transfer yet — a node needs "
                       "stability over %dd across %d+ retrievals, and a transfer_probe the "
                       "architect actually wrote" % (int(TRANSFER_MATURE_S), TRANSFER_MATURE_REPS))})
        return
    untested = sum(1 for c in cands if c["transfer"]["state"] == "untested")
    emit({"items": cands, "n": len(cands), "total_ready": total,
          "read": ("%d concept%s ready for the harder question (%d never tested). This is not "
                   "recall — it is whether the idea fires when it wears different clothes."
                   % (total, "s" if total != 1 else "", untested))})

def compute_transfer():
    """stats.transfer — capability recall, reported SEPARATELY and never pooled with retention.

    Engram has claimed to build capability and measured only memory. These two numbers answer
    different questions, and the one that matters is the one that has never had a value."""
    receipts = collect_receipts()
    ts = _transfer_receipts(receipts)
    nodes = _by_node(receipts)
    states = {"untested": 0, "probed": 0, "applied": 0}
    ready = len(transfer_candidates())
    for tp, g in iter_graphs():
        for nid, node in graph_nodes(g).items():
            if not has_transfer_question(node):     # …INCLUDING the capstone (v0.8.1)
                continue
            states[node_transfer_state(nodes.get((tp, nid)))["state"]] += 1
    # TWO BARS, TWO NAMES — and neither one gets to be called just `rate`.
    #
    # The first cut reported a single `rate` counting anything not-`lapsed`, so a node whose
    # only transfer receipt was `partial` read **rate: 1.0** while its own `state` read
    # **`probed`** — because `state: applied` requires `recalled`. Two numbers, one state, two
    # silently different definitions of success, and the looser one was the flattering one.
    # (§4.8 Q1, caught before the gate ran, which is the first time that has happened here.)
    #
    # `fired` is the headline because "is this capability mine?" is a yes/no question and a
    # half-application is not a yes. `any` is published beside it because it is the SAME bar
    # retention uses (recalled-or-partial), and the two numbers are only comparable if they are
    # measured the same way.
    # ── THE HEADLINE IS *CURRENT OWNERSHIP*, NOT A LIFETIME POOL ────────────────────────────
    #
    # v0.8.0's `rate_fired` pooled the **entire append-only lifetime log** and was **ORDER-BLIND**
    # — while `node.transfer.state` was deliberately latest-evidence, with a docstring saying
    # *"a capability that fired in June and failed in September is not currently owned, and
    # pretending otherwise would be a wrong number in the flattering direction."*
    #
    # They fixed it in `state` and shipped it in the number `/coach` leads with:
    #
    #   IMPROVING learner (failed 5 twice, then mastered all 5) -> owns 5 -> "FIRED on 33%"
    #   DECLINING learner (passed 5 twice, then LOST all 5)     -> owns 0 -> "FIRED on 67%"
    #
    # **The learner with ZERO current capability scored exactly DOUBLE the one who owned all five**
    # — and the dashboard rendered `fired 67%` and `owned 0` as adjacent chips. That is not a
    # lenient ruler; it is a NEGATIVE one, and every number downstream had its sign flipped.
    #
    # The shipped §5.5 instrument gate missed it because it varied the BAR (recalled/partial/
    # lapsed on one node, one receipt) and never varied the POPULATION. **It tested the subject,
    # not the ruler** — the exact v0.7 lesson, repeated one release later.
    #
    # So: two numbers, two names (§4.8 Q6), and the CURRENT one leads.
    #   `owned_rate`      — of the capabilities you have PROBED, how many do you own RIGHT NOW?
    #   `probe_fire_rate` — of every probe you have ever attempted, how many fired? (history)
    grades = [_grade_of(r) for r in ts]
    fired = sum(1 for gr in grades if gr == "recalled")
    partial = sum(1 for gr in grades if gr == "partial")
    lapsed = sum(1 for gr in grades if gr == "lapsed")
    tested = states["probed"] + states["applied"]        # nodes with a verdict, right now
    owned_rate = round(states["applied"] / tested, 3) if tested else None
    probe_fire_rate = round(fired / len(ts), 3) if ts else None
    probe_any_rate = round((fired + partial) / len(ts), 3) if ts else None
    thin = len(ts) < TRANSFER_MIN_N
    have = sum(states.values())
    if not ts:
        read = ("NO CAPABILITY HAS EVER BEEN MEASURED. %d concept%s %s a transfer question; "
                "%d %s mature enough to be asked it."
                % (have, "s" if have != 1 else "", "carry" if have != 1 else "carries",
                   ready, "is" if ready == 1 else "are"))
    elif thin:
        # every sibling metric has a floor (calibration 10, modality 15, the audit 30). Transfer
        # had none, so ONE probe read "FIRED on 100%" and chipped it on the dashboard. Counts are
        # facts and are always shown; a RATE over fewer than 5 probes moves >20 points on a single
        # item, and a number that a single datum can swing by 20 points is not a rate.
        read = ("insufficient-data for a transfer RATE (%d probe%s; need %d). You currently own "
                "%d of %d tested capabilit%s — that is a count, and counts are facts."
                % (len(ts), "s" if len(ts) != 1 else "", TRANSFER_MIN_N,
                   states["applied"], tested, "y" if tested == 1 else "ies"))
    else:
        read = ("you currently OWN %d%% of the %d capabilities you have tested (%d of %d). "
                "Across every probe ever attempted, %d%% fired. This is not recall — it is "
                "whether the idea works in different clothes — and it is never pooled into "
                "retention."
                % (round(owned_rate * 100), tested, states["applied"], tested,
                   round(probe_fire_rate * 100)))
    return {"n": len(ts),
            "fired": fired, "partial": partial, "lapsed": lapsed,
            # THE HEADLINE — current ownership. Order-aware, because `state` is.
            "owned": states["applied"], "tested": tested,
            "owned_rate": (owned_rate if not thin else None),
            # …and the lifetime probe-level history, named as history so it cannot be mistaken
            # for the headline the way v0.8.0's did.
            "probe_fire_rate": (probe_fire_rate if not thin else None),
            "probe_any_rate": (probe_any_rate if not thin else None),
            "min_n": TRANSFER_MIN_N, "insufficient_data": thin,
            "states": states, "ready_now": ready,
            "definition": ("`owned_rate` (THE HEADLINE) = of the capabilities you have probed, the "
                           "fraction whose MOST RECENT probe fired. It is order-aware, exactly as "
                           "`transfer.state` is: a capability that fired in June and failed in "
                           "September is not owned now. `probe_fire_rate` is the LIFETIME "
                           "probe-level history and is order-blind by construction — it answers a "
                           "different question and must never be read as the headline. NEVER "
                           "pooled with retention: retention asks whether the memory survived; "
                           "transfer asks whether the capability fires."),
            "read": read}

def compute_adherence():
    """The funnel: encoded -> came due -> was actually reviewed.

    `loop_closure` is THE binding-constraint metric. It answers the one question Engram
    could never ask itself: *of the concepts I taught and scheduled, how many did the
    learner ever come back for?* When it is 0, no other number on the dashboard is real,
    and /coach is required to say so before reporting any of them."""
    receipts = collect_receipts()
    nodes = _by_node(receipts)
    t = today()

    # RETIRED nodes leave this rate — and are counted on the way out (v1.3). A learner who
    # retires everything they never reviewed would otherwise drive loop_closure to a
    # flattering 1.0, which is bug class #1 with the learner's own hand on the lever. So the
    # count travels WITH the rate and reaches the `read` string whenever it is nonzero: the
    # number stays honest by being labeled, not by punishing the verb.
    retired = retired_keys()
    reached = done = retired_excluded = 0
    for key, slot in nodes.items():
        first_due = safe_date(slot["first"].get("due_next"))
        if first_due is None or first_due > t:
            continue                      # not yet due: the loop hasn't been asked to close
        if key in retired:
            retired_excluded += 1
            continue
        reached += 1
        if slot["reviews"]:
            done += 1
    rate = round(done / reached, 3) if reached else None

    sdates = sorted(d for d in (safe_date(s.get("ts"))
                                for s in read_jsonl(p("sessions.jsonl"))) if d)
    gaps = sorted((b - a).days for a, b in zip(sdates, sdates[1:]))
    last = sdates[-1] if sdates else None

    # "Retained at 30 days" must mean ONE thing across the whole payload. This used to say
    # `>= 25 days` while retention's 30d bucket says [15, 59] — two contradictory definitions
    # of the same phrase, shipping side by side in `stats`. Both now read from the single
    # source of truth. (Found by adversarial review.)
    lo30, hi30 = next((lo, hi) for name, lo, hi in RETENTION_BUCKETS if name == "30d")
    retained_30d = sum(
        1 for slot in nodes.values()
        if any(lo30 <= (days_between(slot["first"].get("ts"), r.get("ts")) or -1) <= hi30
               and r.get("rating") != "again" for r in slot["reviews"]))

    if not nodes:
        read = "no concepts encoded yet"
    elif reached == 0:
        read = "nothing has come due yet — the loop has not been tested"
    elif done == 0:
        read = ("THE LOOP HAS NEVER CLOSED: %d concept%s came due and none %s reviewed"
                % (reached, "s" if reached != 1 else "", "were" if reached != 1 else "was"))
    elif rate < 0.5:
        read = "the loop closes less than half the time — retention is mostly not happening"
    else:
        read = "the loop is closing"
    if retired_excluded:
        read += (" (%d past-due concept%s excluded because you retired %s — this rate is over "
                 "what you kept)" % (retired_excluded, "s" if retired_excluded != 1 else "",
                                     "them" if retired_excluded != 1 else "it"))

    return {
        "loop_closure": {"encoded_past_due": reached, "first_review_done": done,
                         "rate": rate, "retired_excluded": retired_excluded, "read": read},
        "return": {
            "sessions_7d": sum(1 for d in sdates if 0 <= (t - d).days < 7),
            "sessions_30d": sum(1 for d in sdates if 0 <= (t - d).days < 30),
            "days_since_last_session": ((t - last).days if last else None),
            "median_gap_days": _median(gaps),
            "reviews_due_now": len(due_items()),
        },
        "funnel": {
            "topics_started": len(all_topics()),
            "nodes_encoded": len(nodes),
            "nodes_reaching_first_due": reached,
            "nodes_first_reviewed": done,
            "nodes_retained_30d": retained_30d,
            "nodes_retired": len(retired),
        },
    }

# Elapsed-day windows for the north star. They must PARTITION [0, inf) — every review lands
# in exactly one bucket, and none is ever silently dropped.
#
# The first cut of this used disjoint windows (5-10 / 25-40 / 80-110) and a v0.6 live test
# caught it immediately: a real review at day 11 fell in a *gap* and vanished, so `retention`
# reported "no reviews yet" while a review sat on disk. Under real FSRS intervals (~4d, ~12d,
# ~30d, ~70d) most reviews would have landed in those holes, and the north star would have
# been computed on an arbitrary subset of the evidence — precisely the dishonesty this
# release exists to kill. A metric that quietly discards data is worse than no metric.
#
# `early` is kept separate and NEVER pooled into a retention claim: a sub-4-day retrieval is
# still encoding, not evidence that anything was retained.
RETENTION_BUCKETS = (
    ("early", 0, 3),          # sub-week: re-encoding, not retention. Reported, never pooled.
    ("7d", 4, 14),            # about a week
    ("30d", 15, 59),          # about a month   <- the headline
    ("90d", 60, 179),         # about a quarter
    ("180d+", 180, 10 ** 6),  # permastore territory
)

def compute_retention():
    """THE NORTH STAR. docs/04 named it in Phase 0 ("7-day and 30-day retention on
    scheduled reviews") and it was never implemented — `stats` has only ever bucketed by
    memory *strength*, not elapsed *time*.

    Every review is bucketed by ITS OWN days-since-encode, not just first reviews: under
    FSRS the first review lands ~4 days out, so a first-reviews-only metric would leave
    the 30d and 90d buckets containing nothing but *abandoned* nodes — the exact
    population whose recall we most want to stop pretending we measured.

    `unmeasured` is the honest denominator and is NOT optional. A retention figure computed
    only over completed reviews silently drops precisely the concepts the learner walked
    away from — which are, definitionally, the ones that decayed. That is survivorship bias
    with a progress bar, and shipping it would make Engram a liar in the one place it
    cannot afford to be."""
    receipts = collect_receipts()
    nodes = _by_node(receipts)
    t = today()

    buckets = {name: {"recalled": 0, "partial": 0, "lapsed": 0, "n": 0, "rate": None}
               for name, _, _ in RETENTION_BUCKETS}
    for slot in nodes.values():
        enc = slot["first"].get("ts")
        for r in slot["reviews"]:
            el = days_between(enc, r.get("ts"))
            if el is None:
                continue
            for name, lo, hi in RETENTION_BUCKETS:
                if lo <= el <= hi:
                    b = buckets[name]
                    grade = r.get("grade")
                    if not isinstance(grade, str) or grade not in GRADES:
                        rating = r.get("rating")
                        grade = (GRADE_OF_RATING.get(rating)
                                 if isinstance(rating, str) else None)
                    if grade in GRADES:
                        b[grade] += 1
                    b["n"] += 1
                    break
    for b in buckets.values():
        if b["n"]:
            b["rate"] = round((b["recalled"] + b["partial"]) / b["n"], 3)

    # THE HONEST DENOMINATOR: everything that is PAST DUE RIGHT NOW.
    #
    # v0.6.0 shipped this as "past due AND never reviewed", which exempted a node the moment
    # it was retrieved even once — so a learner who reviewed ten concepts at day 7 and then
    # vanished for 200 days saw: "measured over 10 retrievals · 100% recall · unmeasured 0 ·
    # coverage complete · the loop is closing", while the engine's own `decay` put those same
    # ten at 56% and falling. Survivorship bias with a progress bar, reproduced INSIDE the
    # block written to prevent it. (Found by adversarial review, after release.)
    #
    # A node that is past due NOW has, by definition, not been retrieved since it came due.
    # Its current recall is UNKNOWN — not absent — whatever its history. That, and only that,
    # is the population a retention figure silently drops.
    stale, never, proj, retired_n = 0, 0, [], 0
    for tp, g in iter_graphs():
        for nid, node in (g.get("nodes") or {}).items():
            if not isinstance(node, dict):
                continue
            # Retired nodes leave `past_due_now` and are counted in their own key (v1.3).
            # They are CHOSEN, not abandoned — different words for different facts, and the
            # honest denominator stays honest only if the exit is visible.
            if is_retired(node):
                retired_n += 1
                continue
            f = _fsrs_of(node)
            s, due, last = (as_number(f.get("s")), safe_date(f.get("due")),
                            safe_date(f.get("last")))
            if s is None or due is None or due > t:
                continue                       # never encoded, or not yet due: nothing owed
            stale += 1
            slot = nodes.get((tp, nid))
            if slot is None or not slot["reviews"]:
                never += 1                     # never retrieved at all — the worst case
            if last:
                proj.append(retrievability(max(0, (t - last).days), s))

    bucketed = sum(b["n"] for b in buckets.values())
    total_reviews = sum(len(s["reviews"]) for s in nodes.values())
    headline = buckets["30d"]

    if headline["n"]:
        read = "30-day recall %d%% (n=%d)" % (round(headline["rate"] * 100), headline["n"])
    elif bucketed:
        read = ("measured over %d retrieval%s — none yet at the 30-day mark"
                % (bucketed, "s" if bucketed != 1 else ""))
    else:
        read = "insufficient-data (no reviews yet)"
    # The unmeasured denominator must reach the NARRATOR, not just sit in a nested key. A
    # `read` of "measured over 10 retrievals" while ten concepts rot past due is the exact
    # lie this block exists to prevent — and v0.6.0 told it. Every read now carries the debt.
    if stale:
        read += (" — but %d concept%s %s past due and unretrieved (FSRS: ~%d%% recall now); "
                 "%s not in the number above"
                 % (stale, "s" if stale != 1 else "", "are" if stale != 1 else "is",
                    round((sum(proj) / len(proj) if proj else 0) * 100),
                    "they are" if stale != 1 else "it is"))
    # The coverage guard is worthless if nothing reads it. If the windows ever stop
    # partitioning [0, inf), the metric is silently discarding evidence — and it must SAY so
    # in the one field a narrator is guaranteed to read, not merely record it in a nested key
    # nobody consumes. (Found by adversarial review: the guard was inert.)
    if bucketed != total_reviews:
        read = ("UNTRUSTWORTHY — %d of %d reviews fell outside every bucket and were dropped; "
                "the windows no longer partition [0,inf). Fix RETENTION_BUCKETS before "
                "believing any number here. (%s)"
                % (total_reviews - bucketed, total_reviews, read))
    # THE TEETH (v0.7). Every figure in this block is a count of the ASSESSOR's verdicts, so
    # it is only as true as the assessor. Stamped HERE, in the one function every caller
    # funnels through (`stats`, `cmd_retention`, the dashboard), because v0.6.4's lesson was
    # that a rule implemented in four places is a rule wrong in three. And the stamp reaches
    # the `read` STRING, not just a nested key: a guard nobody reads cannot trip (§4.8 Q4).
    #
    # BUT ONLY WHEN THERE IS A FIGURE TO QUALIFY. The §5.6 user session, run against the
    # founder's real state, produced this:
    #
    #     "[grader unaudited — QWK unknown; run /coach audit] insufficient-data (no reviews yet)"
    #
    # A caveat on a number that does not exist. There are no grades to distrust, because there
    # are no retrievals — and it stacked a second reproach on top of "THE LOOP HAS NEVER
    # CLOSED", which is precisely the wall-of-debt the constitution forbids (docs/05 P13/P14:
    # information, never pressure). The flag stays TRUE in the payload — it is a true fact
    # about the grader, and /coach reads it — but a narrator is not handed a disclaimer for a
    # measurement nobody made. The moment one retrieval lands, the stamp lands with it.
    gh = compute_grader_health()
    if gh.get("stamp") and bucketed:
        read = "[%s] %s" % (gh["stamp"], read)
    return {
        "grader_unvalidated": gh["grader_unvalidated"],
        "grader_verdict": gh["verdict"],
        "buckets": buckets,
        "definition": ("of retrievals attempted N days after a concept was FIRST encoded, the "
                       "fraction graded recalled-or-partial. Windows partition [0, inf): "
                       "early 0-3 (re-encoding, never pooled) · 7d 4-14 · 30d 15-59 (headline) "
                       "· 90d 60-179 · 180d+ 180+."),
        # Every review must land in exactly one bucket. If this is ever < 1.0, the metric is
        # silently discarding evidence and must not be trusted (a v0.6 live test caught
        # exactly that, with disjoint windows that dropped a real day-11 review).
        "coverage": {
            "reviews_bucketed": bucketed, "reviews_total": total_reviews,
            "complete": bucketed == total_reviews,
        },
        "unmeasured": {
            "past_due_now": stale,             # ← the honest denominator
            "never_reviewed": never,           # of those, never retrieved even once
            "retired": retired_n,              # v1.3: chosen off the list, not abandoned
            "projected_recall_now": (round(sum(proj) / len(proj), 3) if proj else None),
            "note": ("UNKNOWN, not absent. These are past due RIGHT NOW — not retrieved since "
                     "they came due, whatever their history. Reporting retention without them "
                     "is survivorship bias: they are exactly the concepts that decayed. "
                     "`retired` is a separate, honest exit: the learner took those off their "
                     "list deliberately, so they are neither measured nor counted as debt."),
        },
        "read": read,
    }

def _as_list(x):
    """A JSON file that should hold a list, but may hold anything after a hand-edit."""
    return x if isinstance(x, list) else []

def _open_misconceptions():
    """Render-safe view: the fields the narrator surfaces are coerced to strings HERE, at
    the gate — `report` escapes them straight into HTML, and an int in a hand-edited file
    must degrade to text, never AttributeError the whole dashboard (v1.0.6 fuzz)."""
    out = []
    for m in _as_list(read_json(p("misconceptions.json"), [])):
        if isinstance(m, dict) and m.get("status") == "open":
            out.append(dict(m, topic="%s" % (m.get("topic") or ""),
                            node="%s" % (m.get("node") or ""),
                            description="%s" % (m.get("description") or "")))
    return out

def compute_stats():
    receipts = collect_receipts()
    reviews = _review_receipts(receipts)          # §4.8 Q1: one definition, shared
    review_ids = {id(r) for r in reviews}
    def bucket(r):
        s = as_number(r.get("s_before")) or 0
        return "early" if s < 7 else ("week" if s < 30 else "month+")
    buckets = {}
    for r in reviews:
        b = bucket(r)
        ok = 1 if r["rating"] != "again" else 0
        agg = buckets.setdefault(b, [0, 0])
        agg[0] += ok
        agg[1] += 1
    recall = {b: {"rate": round(v[0] / v[1], 3), "n": v[1]} for b, v in buckets.items() if v[1]}
    # Calibrate on review recall only; first-exposure (encode) guesses are a
    # separate, noisier signal — reported alongside, never pooled into the verdict.
    with_conf = [r for r in receipts if r.get("confidence") is not None]
    calibration = _calibration([r for r in with_conf if id(r) in review_ids])
    # …and `calibration_encode` was a RESIDUAL bucket (`not in review_ids`), so v0.8's transfer
    # receipts fell straight into it — a bucket whose own docstring calls it "first-exposure
    # (encode) guesses". Transfer is precisely where a learner is MOST overconfident (they know
    # the concept; the capability doesn't fire), so that overconfidence was being misattributed
    # to their encoding self-assessment, and /coach would diagnose the wrong faculty and
    # prescribe the wrong fix. A residual bucket silently absorbs every kind you add later.
    # Name the population, always. (§4.8 Q3, and the one real population leak in v0.8.)
    transfer_ids = {id(r) for r in _transfer_receipts(receipts)}
    calibration_encode = _calibration([r for r in with_conf
                                       if id(r) not in review_ids and id(r) not in transfer_ids])
    calibration_transfer = _calibration([r for r in with_conf if id(r) in transfer_ids])
    topics = []
    for t, g in iter_graphs():
        topics.append({"topic": t, "title": g.get("title"), "states": state_counts(g)})
    sessions = read_jsonl(p("sessions.jsonl"))
    last_coach = max((s.get("ts") for s in sessions if s.get("kind") == "coach" and s.get("ts")),
                     default=None)
    return {
        "receipts": len(receipts), "reviews": len(reviews),
        # The binding constraint and the north star lead the block on purpose: /coach is
        # required to report loop_closure BEFORE any other number, because when the loop
        # has never closed, nothing below it is real yet (docs/10 v0.6).
        "adherence": compute_adherence(),
        "retention": compute_retention(),
        # THE CAPABILITY CLAIM (v0.8) — reported beside retention and NEVER pooled into it.
        # Retention says the memory survived. Transfer says the idea is yours. Engram has
        # always claimed the second and only ever measured the first.
        "transfer": compute_transfer(),
        # The oracle behind every grade above. /coach reports its verdict BEFORE any
        # retention number, because an unaudited grader makes all of them unearned.
        "grader_health": compute_grader_health(),
        "recall_by_stability": recall,
        "calibration": calibration,
        "calibration_encode": calibration_encode,
        "calibration_transfer": calibration_transfer,   # v0.8.1: named, never a residual bucket
        "streak_days": compute_streak(receipts),
        "momentum": compute_momentum(receipts),
        "modality": compute_modality(receipts),
        # v1.1: retention split by knowledge kind (concept/procedure/fact), the instrument
        # for docs/11 §7.3. Same predicates as modality; caveat ships inside the payload.
        "by_kind": compute_by_kind(receipts),
        # v1.4: the OTHER grader. `grader_health` measures the blind assessor against the
        # gold set; this measures the tutor — which writes every /review receipt — against
        # the blind assessor. Agreement, never validity, and the read says so.
        "self_grading": compute_self_grading(receipts),
        "due_now": len(due_items()),
        "pending_verify": len(read_jsonl(p(STASH_FILE))),
        "topics": topics,
        "misconceptions_open": len(_open_misconceptions()),
        "active_experiment": next((e.get("question") for e in _as_list(read_json(p("experiments.json"), []))
                                   if isinstance(e, dict) and e.get("status") == "active"), None),
        "last_coach_checkin": last_coach,
    }

def cmd_stats(_args):
    emit(compute_stats())

def cmd_adherence(_args):
    emit(compute_adherence())

def cmd_retention(_args):
    emit(compute_retention())

DECAY_HORIZON_DEFAULT = 30

def cmd_decay(args):
    """What is dying right now, and what a review today would save — in real FSRS numbers.

    The engine has always been able to compute this and has never once said it. On the
    founder's own state (7 concepts encoded 2026-07-05, zero reviews) it says: 2.9 of 7
    survive to day 30 untouched; 5.6 of 7 survive if the four-minute review happens today.
    Four minutes is worth 2.7 concepts, and the ambient surface said `7 reviews due`.

    THE RULE THAT KEEPS THIS HONEST (docs/05 P13, and it is not negotiable): this is
    INFORMATION, NEVER PRESSURE. It reports a forgetting curve the way a lab notebook
    reports a result — flatly, because the result is what it is. The skills surface it ONCE
    on return, with amnesty and a two-minute path, never per-session, never as a should, and
    `settings.decay_notice = "off"` silences it entirely. A line that reads to a skeptic as
    "the tutor is trying to make me feel guilty" is a defect, not a feature."""
    t = today()
    horizon = clamp(int(args.horizon or DECAY_HORIZON_DEFAULT), 1, INTERVAL_MAX)
    model = read_model()
    retention = as_number(model["memory"].get("desired_retention"), RETENTION_DEFAULT)
    im = as_number(model["memory"].get("interval_multiplier"), 1.0)

    if args.topic:
        # An unknown topic must ERROR, not return "nothing to lose". A confident false
        # all-clear from a command whose entire job is honest accounting is the worst
        # possible failure mode. (Found by adversarial review.)
        require_slug(args.topic)
        if args.topic not in all_topics():
            die("unknown topic: %s (run `topics` to list)" % args.topic)

    rows, due_n = [], 0
    for tp, g in iter_graphs(args.topic):
        for nid in (g.get("order") or []):
            if not isinstance(nid, str):
                continue          # unhashable/typed junk in `order` raises on dict.get()
            node = (g.get("nodes") or {}).get(nid)
            if not isinstance(node, dict) or is_retired(node):
                continue                       # retired: not decaying on the learner's ledger
            f = _fsrs_of(node)
            s, last = as_number(f.get("s")), safe_date(f.get("last"))
            if s is None or last is None:
                continue                       # never encoded: nothing to lose yet
            elapsed = max(0, (t - last).days)
            due_d = safe_date(f.get("due"))
            is_due = bool(due_d and due_d <= t)
            due_n += 1 if is_due else 0
            # counterfactual: rate it `good` today, then look `horizon` days past that.
            sim = dict(f, retention=retention, im=im)
            after, _ = apply_rating(sim, "good", t)
            rows.append({
                "topic": tp, "node": nid, "due": is_due,
                "s": round(s, 1),
                "r_now": round(retrievability(elapsed, s), 3),
                "r_no_review": round(retrievability(elapsed + horizon, s), 3),
                "r_if_reviewed": round(retrievability(horizon, as_number(after["s"], s)), 3),
                "s_if_reviewed": round(as_number(after["s"], s), 1),
            })

    # The benefit arm must be priced over exactly the nodes the learner would actually
    # review — the DUE ones. Simulating a `good` rating on every encoded node while
    # charging only for the due queue overstates what N minutes buys, which is precisely
    # the dishonesty this command exists to avoid. A not-yet-due node keeps its own curve
    # in both arms. (Found by adversarial review.)
    for r in rows:
        if not r["due"]:
            r["r_if_reviewed"] = r["r_no_review"]
            r["s_if_reviewed"] = r["s"]

    n = len(rows)
    mean = lambda k: (round(sum(r[k] for r in rows) / n, 3) if n else None)
    alive = lambda k: (round(sum(r[k] for r in rows), 1) if n else 0.0)
    # THE DENOMINATOR MUST BE ON THE LABEL. `decay` averages over EVERY encoded node (that is
    # its job: what happens to this topic if you do nothing). `retention.unmeasured` and the
    # ambient hook average over the PAST-DUE population (that is theirs: what is rotting).
    # Both are correct, both were called "current recall", and they differed by ~10 points on
    # the same state — so a learner comparing them cannot tell which to believe. Neither is
    # lying; the *labels* were. Ship both figures, name their populations, and the three
    # surfaces reconcile exactly. (RELEASE_PROTOCOL §4.8 Q1.)
    due_rows = [r for r in rows if r["due"]]
    mean_due = (round(sum(r["r_now"] for r in due_rows) / len(due_rows), 3)
                if due_rows else None)
    out = {
        "topic": args.topic, "horizon_days": horizon,
        "encoded": n, "due_now": due_n,
        "now": {
            "mean_recall": mean("r_now"),          # over ALL encoded nodes
            "mean_recall_due": mean_due,           # over the DUE nodes — matches retention + hook
            "population": "mean_recall is over all %d encoded node%s; mean_recall_due is over "
                          "the %d past due (the same population retention.unmeasured and the "
                          "session hook report)" % (n, "s" if n != 1 else "", due_n),
            "expected_alive": alive("r_now"),
        },
        "at_horizon_no_review": {"mean_recall": mean("r_no_review"),
                                 "expected_alive": alive("r_no_review")},
        "at_horizon_if_reviewed_today": {"mean_recall": mean("r_if_reviewed"),
                                         "expected_alive": alive("r_if_reviewed"),
                                         "minutes": max(1, round(due_n * 0.6)) if due_n else 0},
        "nodes": rows,
        "notice": model["settings"].get("decay_notice", "on"),
    }
    if not n:
        out["read"] = "nothing encoded yet — nothing to lose"
    elif not due_n:
        # Nothing is due, so the benefit arm is (correctly) identical to the do-nothing arm —
        # and v0.6.2 dutifully reported "a difference of 0.0", which a learner reads as
        # "reviewing buys me nothing." Arithmetically true, rhetorically the opposite of the
        # truth. Same bug class this release is named for, pointing the other way.
        # (Found by the RELEASE_PROTOCOL §5.6 user session, not by any test.)
        out["saved_by_reviewing_today"] = 0.0
        out["read"] = ("%d concept%s encoded, none due yet — nothing to save today. The "
                       "schedule brings each one back just before it fades; %.1f of %d are "
                       "expected to survive the next %d days on that schedule."
                       % (n, "s" if n != 1 else "", alive("r_no_review"), n, horizon))
    else:
        saved = alive("r_if_reviewed") - alive("r_no_review")
        out["saved_by_reviewing_today"] = round(saved, 1)
        out["read"] = (
            "%d concept%s encoded; %.1f expected to survive %d days untouched, %.1f if "
            "reviewed today (%s minute%s) — a difference of %.1f"
            % (n, "s" if n != 1 else "", alive("r_no_review"), horizon,
               alive("r_if_reviewed"), out["at_horizon_if_reviewed_today"]["minutes"],
               "s" if out["at_horizon_if_reviewed_today"]["minutes"] != 1 else "",
               saved))
    emit(out)

def cmd_commit(args):
    """The learner's implementation intention — an if-then plan, in their own words.

    Gollwitzer & Sheeran (2006): 94 independent tests, N > 8,000, d = 0.65 on goal
    attainment — the broad figure; behavior-specific meta-analyses run d ≈ 0.14–0.31 and that
    is the honest number to expect here (docs/13 §2.1). Still the strongest licensed adherence
    move available that costs nothing and steers no one.

    Stored because they said it. Shown back at the moment it names (v1.3: the session hook and
    /review finally DO show it — for three releases it was written and displayed by nothing).
    NEVER enforced — this is not a reminder system, it is the learner's own sentence repeated
    to them (docs/07 §4).

    v1.3 adds `renewed`: re-prompting a stated plan is what the direct RCTs actually tested
    (Messmer 2022; Prestwich 2010), and the effect decays over weeks, so the skills offer a
    keep/rephrase/drop at a seam. `age_days` is emitted so that offer is engine-driven rather
    than a model's guess at how stale the plan is."""
    m = load_model()
    before = m["settings"].get("commitment")
    if args.clear and (args.cue or args.action):
        die("commit: --clear cannot be combined with --cue/--action (which did you mean?)")
    if args.clear:
        m["settings"]["commitment"] = None
    elif args.cue or args.action:
        if not (args.cue and args.action):
            die('commit needs both --cue and --action '
                '(e.g. --cue "when I open the terminal" --action "I clear one review")')
        prev = before if isinstance(before, dict) else {}
        hist = [d for d in (prev.get("renewed") or []) if isinstance(d, str)]
        # A RENEWAL is a re-commitment to the same plan; a REPHRASE is a new plan. Either way
        # the stamp records that the learner touched it today, which is what `age_days` (and
        # therefore the renewal offer's cadence) is actually asking about.
        if prev.get("set"):
            hist = (hist + [today().isoformat()])[-12:]      # bounded: a year of monthly seams
        m["settings"]["commitment"] = {"cue": args.cue, "action": args.action,
                                       "set": prev.get("set") or today().isoformat(),
                                       "renewed": hist}
    if m["settings"].get("commitment") != before:
        write_json(p("learner-model.json"), m)
    c = m["settings"].get("commitment")
    age = None
    if isinstance(c, dict):
        stamps = [d for d in ([c.get("set")] + list(c.get("renewed") or []))
                  if isinstance(d, str)]
        dates = [d for d in (safe_date(s) for s in stamps) if d]
        if dates:
            age = (today() - max(dates)).days
    emit({"commitment": c, "age_days": age,
          "note": ("%s, %s." % (c["cue"], c["action"]) if isinstance(c, dict) and c.get("cue")
                   else "no commitment set — /learn offers to book one at the close.")})

STATE_DOTS = {"review": "●", "learning": "◐", "new": "·"}

def cmd_topic_status(args):
    g = load_graph(args.topic)
    nodes = graph_nodes(g)
    counts = state_counts(g)
    total = max(1, len(nodes))
    width = 24
    filled = int(round(width * counts["review"] / total))
    half = int(round(width * counts["learning"] / total))
    bar = "█" * filled + "▒" * half + "░" * max(0, width - filled - half)
    title = g.get("title")
    lines = ["%s — %s" % (args.topic, title if isinstance(title, str) else ""),
             "%s  %d retained · %d learning · %d untouched" % (
                 bar, counts["review"], counts["learning"], counts["new"]), ""]
    for nid in graph_order(g, nodes):
        node = nodes[nid]
        fsrs = _fsrs_of(node)
        due = fsrs.get("due") or "—"
        s = as_number(fsrs.get("s"))
        flags = ("†" if node.get("threshold") else "") + ("*" if node.get("arbitrary") else "")
        st = node.get("state")
        lines.append("%s %-34s%-2s due %-10s S=%s" % (
            # an UNHASHABLE state (a dict/list after a hand-edit) raises TypeError on the
            # dict lookup itself — the same crash class state_counts was already guarded for
            STATE_DOTS.get(st, "?") if isinstance(st, str) else "?",
            nid, flags, due if isinstance(due, str) else "—",
            ("%.1fd" % s) if s else "—"))
    lines.append("")
    lines.append("● retained (review)   ◐ learning   · untouched   † threshold   * memorize-only")
    print("\n".join(lines))

def _mean_recall_now(due):
    """Mean current retrievability across a due queue, from each item's own FSRS curve.

    Elapsed days come from the item's `last` (its last successful retrieval), read straight
    off the graph — never reconstructed. An earlier cut derived elapsed as
    `interval_for(s, RETENTION_DEFAULT) + overdue_days`, which silently breaks for any learner
    who changed `desired_retention` or carries an `interval_multiplier`, and breaks in the
    direction of *overstating* the decay. This line's entire warrant is that it is honest;
    it does not get to estimate what it can read.

    Returns None when nothing in the queue carries usable state."""
    rs = []
    t = today()
    for d in due:
        s = as_number(d.get("s"))
        last = safe_date(d.get("last"))
        if s is None or s <= 0 or last is None:
            continue
        rs.append(retrievability(max(0, (t - last).days), s))
    return (sum(rs) / len(rs)) if rs else None

def cmd_session_start(_args):
    if not os.path.isdir(home()):
        return  # never installed/used: stay silent
    due = due_items()
    pending = len(read_jsonl(p(STASH_FILE)))
    if not due and not pending:
        return  # Article 8: ambient, never nagging
    if due:
        by_topic = {}
        for d in due:
            # Only ever echo validated slugs into hook output — this text is injected
            # into the agent's context; a free-form topic name would be a prompt-
            # injection vector. (Slugs are already enforced at ingest; belt-and-braces.)
            t = d.get("topic")
            if slug_ok(t):
                by_topic[t] = by_topic.get(t, 0) + 1
        summary = ", ".join("%s: %d" % kv for kv in sorted(by_topic.items(), key=lambda x: -x[1])[:3])
        minutes = max(1, round(len(due) * 0.6))
        # THE WALL OF DEBT, defused (v1.3). "28 reviews due · ~17 min" is the line the amnesty
        # protocol exists to prevent, printed to the exact learner it exists to protect —
        # ambient, cap-blind, profile-blind. Above the threshold the line LEADS with a path
        # that fits and still states the full count: information, never a smaller truth.
        # (docs/05 P14: a wall of debt is the churn trigger, not the cure.)
        try:
            _m = read_model()                      # read-only: the hook holds no lock
            _profile = _m["settings"].get("profile")
            _mode = _m["settings"].get("default_mode")
        except Exception:
            _profile = _mode = None
        cap = QUICK_CAP if (_profile == "adhd" or _mode == "sprint") else STANDARD_CAP
        # ⚠ AMNESTY FIRST, AND IT MUST BE THE FIRST WORDS ON THE SCREEN (v1.3).
        #
        # `/review`'s return protocol has always guaranteed an order — *nothing is owed →
        # here is what it costs → here is a two-minute path* — and states plainly that
        # REVERSED, IT IS A DEBT COLLECTOR. The hook is the surface that speaks FIRST, before
        # `/review` is even typed, and it had no amnesty at all: it opened with the count, then
        # the decay cost, and (for one afternoon during this release) closed on the learner's
        # own unkept promise. The v1.3 dogfood read that sequence cold and called it what it
        # was. The skill cannot repair an ordering violation that happens before it runs, so
        # the ordering guarantee has to live HERE.
        #
        # Fires only on a real absence — the same >=7d clause the decay line uses (`returning`
        # below), computed once and shared, so the two surfaces can never disagree about what
        # counts as coming back.
        gone_days, never_closed, returning = None, False, False
        try:
            _ad = compute_adherence()
            gone_days = _ad["return"]["days_since_last_session"]
            never_closed = (_ad["loop_closure"]["encoded_past_due"] > 0
                            and _ad["loop_closure"]["first_review_done"] == 0)
            returning = gone_days is not None and gone_days >= RETURN_ABSENCE_DAYS
        except Exception:
            pass                                  # ambient surface: never break a session
        # The amnesty fires on EVERY return event the cost line fires on — including a loop
        # that has never closed with no session history to date the gap, where the honest
        # phrasing simply drops the day count rather than inventing one. (Caught by the
        # ordering check: the first fix left exactly that path amnesty-less, which is the
        # path the founder's own state was in for six days.)
        if returning and gone_days is not None:
            amnesty = ("back after %d days — nothing's owed, a gap doesn't hurt the schedule. "
                       % gone_days)
        elif never_closed or returning:
            amnesty = "nothing's owed here — spacing is doing its job. "
        else:
            amnesty = ""
        if len(due) > 2 * cap:
            print("[engram] %s%d review%s due (%s) · /review quick clears the %d most urgent "
                  "(~%d min) · full queue ~%d min."
                  % (amnesty, len(due), "s" if len(due) != 1 else "", summary, cap,
                     max(1, round(cap * 0.6)), minutes))
        else:
            print("[engram] %s%d review%s due (%s) · ~%d min · /review to clear, /learn to continue."
                  % (amnesty, len(due), "s" if len(due) != 1 else "", summary, minutes))
        # The honest cost line (v0.6). Engram has always been able to compute what the
        # decay costs and has never said it — its whole ambient surface on the sixth day
        # of a memory dying on schedule was "7 reviews due" (docs/08 §The exhibit).
        #
        # It is a RETURN-EVENT line, not a per-session nag: it fires only when the loop
        # has genuinely never closed, or after a real absence. Information, never pressure
        # (docs/05 P13) — a forgetting curve reported the way a lab notebook reports a
        # result. No "should", no scold. `settings.decay_notice = "off"` silences it.
        try:
            model = read_model()                      # read-only: the hook holds no lock
            if model["settings"].get("decay_notice", "on") != "off":
                if never_closed or returning:
                    # THE PLAN COMES BEFORE THE COST, and that ordering is the whole finding.
                    # Printed after the cost, a learner's own sentence lands as the punchline
                    # to a decay warning — their unkept promise, quoted at them. Printed
                    # before it, between amnesty and the number, it is what it was written to
                    # be: the thing they decided, in their words, at the moment it names.
                    #
                    # `commit` has stored this since v0.6 and NOTHING displayed it until now
                    # — the transfer_probe defect, on the strongest licensed adherence lever
                    # in the repo. What the direct RCTs tested is the read-back (Messmer 2022;
                    # Prestwich 2010), not the storing.
                    #
                    # Rationed by the return-event rule alone: no daily fallback, because a
                    # sentence you wrote becomes nagging the moment it greets you every
                    # session. Steady-state re-anchoring is the renewal offer's job, in
                    # session, where it can be declined.
                    c = model["settings"].get("commitment")
                    if isinstance(c, dict) and c.get("cue") and c.get("action"):
                        # ensure_ascii=False so the learner's OWN SENTENCE reads like their
                        # sentence — a Vietnamese cue or an em dash must not come back as
                        # `—`. The escaping that matters for safety (quotes, newlines,
                        # control chars) is unaffected, so a commitment carrying a fake
                        # `[engram]` line still arrives as one inert quoted literal: hook
                        # output is injected into an agent's context.
                        print("[engram] your plan: %s"
                              % json.dumps("%s — %s" % (c["cue"], c["action"]),
                                           ensure_ascii=False)[:400])
                    mean_now = _mean_recall_now(due)
                    if mean_now is not None and mean_now < 0.90:
                        subject = ("that one sits" if len(due) == 1
                                   else "those %d sit" % len(due))
                        print("[engram] %s at ~%d%% recall and still falling · %d min now is "
                              "the difference between keeping %s and re-learning %s."
                              % (subject, round(mean_now * 100), minutes,
                                 "it" if len(due) == 1 else "them",
                                 "it" if len(due) == 1 else "them"))
        except Exception:
            pass                                       # ambient surface: never break a session
    if pending:
        print("[engram] %d production%s awaiting assessor grading — /learn or /review will finish verification."
              % (pending, "s" if pending != 1 else ""))
    sessions = read_jsonl(p("sessions.jsonl"))
    last_coach = max((s.get("ts") for s in sessions if s.get("kind") == "coach" and s.get("ts")),
                     default=None)
    lc = safe_date(last_coach)
    if lc and (today() - lc).days > 7:
        print("[engram] coach check-in overdue (last: %s) · /coach when convenient." % last_coach)

def cmd_path(_args):
    print(home())

# ---------------------------------------------------------------- refit

def cmd_refit(args):
    """Coarse per-user schedule fit (v1): a single interval multiplier.

    Uses review receipts where a predicted retrievability was recorded.
    If observed recall differs from predicted, rescale intervals along the
    FSRS power forgetting curve so predictions match behavior. Full FSRS
    parameter optimization is out of scope for v1 (documented in README)."""
    receipts = [r for r in collect_receipts()
                if r.get("kind") == "review" and r.get("rating")
                and r.get("retrievability") is not None]
    n = len(receipts)
    if n == 0:
        emit({"ok": False, "reason": "no review receipts with predictions yet",
              "hint": "keep reviewing; refit is meaningful only with real evidence"})
        return
    if n < 50 and not args.force:
        emit({"ok": False, "reason": "need >=50 review receipts with predictions, have %d" % n,
              "hint": "keep reviewing; refit is meaningful only with real evidence"})
        return
    observed = sum(1.0 for r in receipts if r["rating"] != "again") / n
    predicted = sum(r["retrievability"] for r in receipts) / n
    def inv(r):  # proportional to elapsed/S at recall probability r (power curve)
        return (clamp(r, 0.5, 0.999) ** (1.0 / DECAY)) - 1.0
    multiplier = clamp(inv(predicted) / inv(observed), 0.5, 1.5)
    m = load_model()
    prev = m["memory"].get("interval_multiplier", 1.0)
    m["memory"]["interval_multiplier"] = round(multiplier, 3)
    m["memory"]["last_refit"] = today().isoformat()
    write_json(p("learner-model.json"), m)
    emit({"ok": True, "n_reviews": n, "observed_recall": round(observed, 3),
          "predicted_recall": round(predicted, 3),
          "interval_multiplier": {"before": prev, "after": round(multiplier, 3)},
          "read": ("intervals shortened — memory decays faster than the default model"
                   if multiplier < 0.97 else
                   "intervals lengthened — memory holds better than the default model"
                   if multiplier > 1.03 else "no meaningful adjustment needed")})

# ---------------------------------------------------------------- doctor

# ============================================================ THE COMMONS (v1.0)
# The evidence base of learning science is built on undergraduates, word pairs, and 20-minute
# retention intervals. **Almost nothing tests self-directed adults, on hard conceptual material,
# at 30-90 day horizons, with blind-graded free recall.** Engram produces exactly that data as a
# byproduct of being useful — and, since v0.7, with a MEASURED oracle behind every grade.
#
# ── THE PROMISE, AND WHY IT IS STRUCTURAL RATHER THAN TRUSTED ──────────────────────────────
#
# 1. **The engine never grows a socket.** `export` writes a FILE and stops. The *agent* — which
#    already has Bash and is already trusted with the machine — does the posting, via `gh`, only
#    after an explicit human yes. The 100%-local badge stays true because the thing it is about
#    (`engram.py`) contains zero network code, and a permanent selftest proves it on every run.
#
# 2. **The payload is a WHITELIST.** Not "we remembered to delete the productions" — *there is no
#    code path by which a production could arrive.* Every field is constructed by name. A field
#    added to a receipt in v1.1 cannot leak by being forgotten in a delete-list, which is the
#    same lesson `gold` taught in v0.7 and the reason both are built the same way.
#
# 3. **`stripped` ships INSIDE the file.** The promise is verifiable by the person making it, not
#    merely asserted at them.
#
# 4. **It is ATTRIBUTED, and it says so.** `gh` posts from your account. A "salted anonymous hash"
#    riding inside a signed envelope would be a lie, so Engram does not tell it. Attribution is
#    also the *stronger* design: a retention study lives on LONGITUDINAL LINKAGE — following the
#    same learner across months IS the question — and attributed n=100 beats anonymous n=500.
#
# 5. **An unaudited oracle cannot contribute.** Every shared grade came from the assessor; if
#    nobody has measured it, the data is not evidence, it is noise with a schema. **v0.7 gates
#    v1.0, and the gate is a refusal, not a warning.**

EXPORT_STRIPPED = ("production", "probe", "claim", "rubric", "goal", "interests",
                   "misconceptions", "misconception_text", "rubric_notes", "feedback_line",
                   "topic_string", "node_id", "title", "why_chain", "transfer_probe",
                   "commitment", "notes", "question",
                   # v1.0.1: these three were STRINGS ON THE WHITELIST — and a whitelist that
                   # admits a free-text string strips nothing. `arm` and `stratum` are learner-
                   # and architect-authored: `stratify_by: ["claim"]` routed a node's CLAIM
                   # verbatim into the export, while the file's own `stripped` list swore `claim`
                   # was removed. `grader` was uncapped here. All three now leave as HASHES.
                   "arm_label", "stratum_label", "grader_id")
# The ONLY keys that may appear on an exported receipt. Constructed by name; nothing else can
# arrive — BUT a whitelist that admits a free-text field is a hole in the whitelist, and that hole
# was the v1.0.0 leak. Every STRING key here is now either a closed enum the engine validates, or
# a hash. Nothing a human typed leaves as itself.
EXPORT_RECEIPT_KEYS = ("topic_hash", "node_hash", "kind", "grade", "rating", "confidence",
                       "days_since_encode", "s_before", "s_after", "interval_days",
                       "retrievability", "artifact", "arm_hash", "stratum_hash",
                       "grader_hash", "grader_qwk", "node_kind", "error_class", "self_graded")
# `kind`/`grade`/`rating`/`node_kind`/`error_class` are the only strings that leave un-hashed,
# because each is a CLOSED ENUM the engine validates — not free text. Anything a human
# authored is hashed. (`node_kind` and `error_class` are stamped by the engine itself from
# validated enums — v1.1; they are exactly the fields a retention-of-skills finding needs.)
_EXPORT_ENUM = {"kind": KINDS, "grade": GRADES, "rating": tuple(RATINGS),
                "node_kind": NODE_KINDS, "error_class": ERROR_CLASSES}

def _hash12(s):
    """A stable 12-hex-char digest. Groups a learner's own receipts and lets the corpus compare
    WITHIN a topic — without the topic string leaving.

    **And the honest caveat, which ships in the file:** a hash of a COMMON topic string
    ("transformers", "bayes") is recoverable by dictionary attack in seconds. This hides the
    string from a casual reader; it does not hide it from someone who wants it, and the export is
    ATTRIBUTED anyway. If a topic's NAME is sensitive, do not contribute that topic — `export
    --topic T` exists so you can choose."""
    return hashlib.sha256(("engram/v1|" + str(s)).encode("utf-8")).hexdigest()[:12]

def cmd_export(args):
    """Write a text-stripped receipt bundle to a file. NO NETWORK. The agent posts, on consent."""
    # The staleness teeth reach the export gate too (v1.4): a badge earned by a grader that is
    # no longer the one grading you is not a badge, and a corpus assembled behind one would
    # carry a QWK nobody re-earned. Contributing is exactly where that matters most.
    gh = compute_grader_health(getattr(args, "grader_context", None))
    if gh["grader_unvalidated"] and not getattr(args, "allow_unvalidated", False):
        die("REFUSING TO EXPORT: the grader behind every one of these grades is %s (%s).\n"
            "  A finding aggregated from unaudited oracles is not a finding — it is noise with a\n"
            "  schema, and publishing it would put a number into the world that nobody can stand\n"
            "  behind. This is the gate v0.7 exists to be.\n"
            "  Run `/coach audit` (about four minutes), then export."
            % (gh["verdict"], gh.get("stamp") or gh.get("read", "")[:80]))

    qwk = gh.get("qwk")
    # arm/stratum, joined from the pre-registered experiment log — so a shared receipt carries the
    # condition it was collected under, which is the difference between data and an anecdote.
    arms = {}
    for e in _as_list(read_json(p("experiments.json"), [])):
        if not isinstance(e, dict):
            continue
        for a in (e.get("assignments") if isinstance(e.get("assignments"), list) else []):
            if isinstance(a, dict) and isinstance(a.get("topic"), str) \
                    and isinstance(a.get("node"), str):
                arms[(a["topic"], a["node"])] = (a.get("arm"), a.get("stratum"))

    topics = [args.topic] if getattr(args, "topic", None) else all_topics()
    out, skipped = [], 0
    for t in topics:
        for r in read_jsonl(p("receipts", t + ".jsonl")):
            if not isinstance(r, dict) or not isinstance(r.get("node"), str):
                skipped += 1
                continue
            arm, stratum = arms.get((t, r["node"]), (None, None))
            # CONSTRUCTED BY NAME — and every free-text field is HASHED, not carried. An `arm`
            # label and a `stratum` are learner/architect prose; the corpus only needs to know
            # that two receipts shared a condition, never what the condition was CALLED. Same for
            # the grader id. A closed enum (kind/grade/rating) leaves as itself because it is not
            # text a human wrote. This is the v1.0.0 leak, closed: `stratify_by: ["claim"]` can no
            # longer route a node's claim into the file, because the stratum leaves as a digest.
            rec = {
                "topic_hash": _hash12(t),
                "node_hash": _hash12("%s/%s" % (t, r["node"])),
                "kind": r.get("kind") if r.get("kind") in _EXPORT_ENUM["kind"] else None,
                "grade": r.get("grade") if r.get("grade") in _EXPORT_ENUM["grade"] else None,
                "rating": r.get("rating") if r.get("rating") in _EXPORT_ENUM["rating"] else None,
                "confidence": clean_confidence(r.get("confidence")),
                "days_since_encode": as_number(r.get("days_since_encode")),
                "s_before": as_number(r.get("s_before")),
                "s_after": as_number(r.get("s_after")),
                "interval_days": as_number(r.get("interval_days")),
                "retrievability": as_number(r.get("retrievability")),
                "artifact": bool(r.get("artifact")),
                "arm_hash": _hash12("arm|" + arm) if isinstance(arm, str) and arm else None,
                "stratum_hash": (_hash12("stratum|" + stratum)
                                 if isinstance(stratum, str) and stratum else None),
                "grader_hash": (_hash12("grader|" + r["grader"])
                                if isinstance(r.get("grader"), str) and r["grader"] else None),
                # ⚠ ONLY where an audited grader actually wrote the verdict (v1.1.1). This
                # stamped the assessor's QWK onto TUTOR-graded review receipts too — and v1.1
                # made that material by exporting `error_class`, which only the tutor writes.
                # A corpus consumer would have read one oracle's measured validity over two
                # populations, one of which nothing has ever audited. Null is honest.
                "grader_qwk": (qwk if isinstance(r.get("grader"), str) and r["grader"] else None),
                "self_graded": not (isinstance(r.get("grader"), str) and r["grader"]),
                "node_kind": (r.get("node_kind")
                              if r.get("node_kind") in _EXPORT_ENUM["node_kind"] else None),
                "error_class": (r.get("error_class")
                                if r.get("error_class") in _EXPORT_ENUM["error_class"] else None),
            }
            out.append({k: rec[k] for k in EXPORT_RECEIPT_KEYS})

    bundle = {
        "engram_version": ENGRAM_VERSION,
        "exported": today().isoformat(),
        # The engine NEVER guesses your identity. You type it, or it stays null and the `gh` post
        # carries it anyway — which is the whole reason the anonymity claim would have been a lie.
        "contributor": (args.contributor if isinstance(getattr(args, "contributor", None), str)
                        and args.contributor else None),
        "attributed": True,
        "grader": {"verdict": gh.get("verdict"), "qwk": qwk,
                   "leniency_bias": gh.get("leniency_bias"),
                   "gold_adjudication": gh.get("gold_adjudication"),
                   "direction": gh.get("direction"),
                   # HONEST about what `grader_qwk` on each receipt IS: the validity of the grader
                   # measured NOW, stamped on every receipt regardless of when it was graded. A
                   # receipt graded before any audit existed still carries today's number — which
                   # is the best available estimate, not a per-receipt measurement, and saying so
                   # is cheaper than being quietly misread (the reviewer's finding #2).
                   "qwk_note": ("grader_qwk on each receipt is the grader's validity measured at "
                                "EXPORT time, not at grading time — receipts graded before this "
                                "audit carry it too. It is the current best estimate of the "
                                "oracle behind them, not a timestamped per-receipt measurement.")},
        "n_receipts": len(out),
        "receipts": out,
        "stripped": list(EXPORT_STRIPPED),
        "topic_hash_note": ("topic/node strings are hashed, not carried. A hash of a COMMON topic "
                            "name is recoverable by dictionary attack — this hides the string from "
                            "a casual reader, not from someone who wants it. The export is "
                            "ATTRIBUTED regardless. If a topic's NAME is sensitive, do not "
                            "contribute it: `export --topic T` exports one topic at a time."),
        "consent_note": ("NOTHING HAS BEEN SENT. This is a file on your disk. `engram.py` contains "
                         "no network code and never will — read it. Only you, via /coach "
                         "contribute and an explicit yes, can post it, and it posts PUBLICLY under "
                         "your GitHub handle."),
    }
    os.makedirs(p("exports"), exist_ok=True)
    seq = 1
    while os.path.exists(p("exports", "%s-%02d.json" % (bundle["exported"], seq))):
        seq += 1
    path = p("exports", "%s-%02d.json" % (bundle["exported"], seq))
    write_json(path, bundle)
    emit({"ok": True, "path": path, "n_receipts": len(out),
          "skipped_malformed": skipped,
          "grader_qwk": qwk, "attributed": True,
          "read": ("wrote %d receipts to %s — text-stripped, %d field types removed, and NOTHING "
                   "has left this machine. Read the file. Then, if you want to: /coach contribute."
                   % (len(out), path, len(EXPORT_STRIPPED)))})

def cmd_doctor(_args):
    issues = []
    notes = []   # non-failing observations with a fix path (doctor stays ok)
    info = {"python": "%d.%d.%d" % sys.version_info[:3], "home": home()}
    os.makedirs(home(), exist_ok=True)
    info["writable"] = os.access(home(), os.W_OK)
    if not info["writable"]:
        issues.append("state dir is not writable")
    try:
        read_model()
        info["model_ok"] = True
    except SystemExit:
        info["model_ok"] = False
        issues.append("learner-model.json unreadable")
    topics = all_topics()
    info["topics"] = len(topics)
    node_count = 0
    for t in topics:
        g = read_json(p("graphs", t + ".json"), quarantine=False)
        if g is None:
            issues.append("graph unreadable/corrupt: %s (fix or delete graphs/%s.json)" % (t, t))
            continue
        if not isinstance(g, dict) or not isinstance(g.get("nodes"), dict):
            issues.append("graph %s has an unusable shape (nodes must be an object) — "
                          "reads skip it; fix or delete graphs/%s.json" % (t, t))
            continue
        node_count += len(g["nodes"])
        for nid in (g.get("order") if isinstance(g.get("order"), list) else []):
            if not isinstance(nid, str):
                issues.append("%s: order contains a non-string entry (%s)"
                              % (t, type(nid).__name__))
            elif nid not in g["nodes"]:
                issues.append("%s: order references missing node %s" % (t, nid))
        for nid, node in g["nodes"].items():
            if not isinstance(node, dict):
                issues.append("%s/%s: node is not an object (%s)"
                              % (t, nid, type(node).__name__))
                continue
            st = node.get("state")
            if st not in NODE_STATES:
                issues.append("%s/%s: invalid state %r" % (t, nid, st))
            due = _fsrs_of(node).get("due")
            if st != "new" and not due:
                issues.append("%s/%s: state=%s but no due date" % (t, nid, st))
            elif due and safe_date(due) is None:
                issues.append("%s/%s: unparseable due date %r" % (t, nid, due))
            a = node.get("artifact")
            if isinstance(a, str) and a:
                ap = a if os.path.isabs(a) else p(a)
                if not os.path.isfile(ap):
                    # note, not issue: v0.4 graphs can carry never-validated payload
                    # strings, and an upgrade must not flip doctor red for our own
                    # past leniency. The engine already ignores these everywhere
                    # (valid_artifact); this is fix-it advice, not corruption.
                    notes.append("%s/%s: registered artifact missing on disk: %s — "
                                 "regenerate it, or run: artifact clear --topic %s --node %s"
                                 % (t, nid, a, t, nid))
            elif a is not None and not (isinstance(a, str) and a):
                notes.append("%s/%s: artifact value is not a path (%s) — run: "
                             "artifact clear --topic %s --node %s"
                             % (t, nid, type(a).__name__, t, nid))
            elif slug_ok(nid) and os.path.isfile(p("artifacts", t, nid + ".html")):
                # an explorable exists at the conventional path but was never
                # registered (pre-0.5 builds) — registration enables regeneration
                # tracking and the modality telemetry, so surface the exact fix
                # (path shell-quoted: state dirs with spaces must stay pasteable)
                notes.append("%s/%s: unregistered artifact file — register with: "
                             "artifact set --topic %s --node %s --path %s"
                             % (t, nid, t, nid, shlex.quote(p("artifacts", t, nid + ".html"))))
    # surface quarantined corrupt files so the user knows state was preserved, not lost
    corrupt = []
    for sub in ("", "graphs"):
        d = p(sub) if sub else home()
        if os.path.isdir(d):
            corrupt += [os.path.join(sub, f) for f in os.listdir(d) if ".corrupt." in f]
    if corrupt:
        issues.append("quarantined corrupt files present: %s" % ", ".join(sorted(corrupt)))
    info["nodes"] = node_count
    info["receipts"] = len(collect_receipts())
    info["pending_verify"] = len(read_jsonl(p(STASH_FILE)))
    info["artifacts"] = sum(len(files) for _, _, files in os.walk(p("artifacts")))
    info["issues"] = issues
    info["notes"] = notes
    info["ok"] = not issues
    emit(info)

# ---------------------------------------------------------------- report

REPORT_CSS = """
:root{--bg:#faf9f6;--surface:#fff;--ink:#201c26;--muted:#6f697a;--line:#e3e0da;
--accent:#6d4aa8;--accent-soft:#efe9f8;--good:#3e7d5a;--warn:#9a6b0f;--bad:#ad4f44;
--good-soft:#e4f0e9;--warn-soft:#f7efdc;}
@media (prefers-color-scheme:dark){:root{--bg:#171420;--surface:#201c2b;--ink:#eae6f2;
--muted:#9a93a8;--line:#332e40;--accent:#b29be8;--accent-soft:#2b2440;--good:#7cc49b;
--warn:#e0b45c;--bad:#e08a82;--good-soft:#1e2f26;--warn-soft:#322a1c;}}
:root[data-theme=light]{--bg:#faf9f6;--surface:#fff;--ink:#201c26;--muted:#6f697a;
--line:#e3e0da;--accent:#6d4aa8;--accent-soft:#efe9f8;--good:#3e7d5a;--warn:#9a6b0f;
--bad:#ad4f44;--good-soft:#e4f0e9;--warn-soft:#f7efdc;}
:root[data-theme=dark]{--bg:#171420;--surface:#201c2b;--ink:#eae6f2;--muted:#9a93a8;
--line:#332e40;--accent:#b29be8;--accent-soft:#2b2440;--good:#7cc49b;--warn:#e0b45c;
--bad:#e08a82;--good-soft:#1e2f26;--warn-soft:#322a1c;}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.55 "Iowan Old Style",Palatino,Charter,Georgia,serif;padding:0 20px 64px}
main{max-width:880px;margin:0 auto}
h1{font-size:26px;margin:40px 0 4px}h2{font-size:18px;margin:36px 0 10px}
.sub{color:var(--muted);font-size:13px;margin:0 0 24px}
.mono,td,th,.chip{font-family:ui-monospace,"SF Mono",Menlo,monospace;
font-variant-numeric:tabular-nums}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin:16px 0}
.chip{font-size:12px;padding:6px 12px;border:1px solid var(--line);border-radius:20px;
background:var(--surface)}
.chip b{color:var(--accent)}
.card{background:var(--surface);border:1px solid var(--line);border-radius:8px;
padding:16px 18px;margin:12px 0}
.goal{color:var(--muted);font-size:13px;margin:2px 0 10px}
.bar{display:flex;height:10px;border-radius:5px;overflow:hidden;background:var(--line);margin:8px 0 4px}
.bar span{display:block;height:100%}
.legend{font-size:12px;color:var(--muted)}
table{border-collapse:collapse;width:100%;font-size:12.5px;margin-top:10px}
th{text-align:left;color:var(--muted);font-weight:500;font-size:11px;
text-transform:uppercase;letter-spacing:.08em;padding:6px 8px;border-bottom:1px solid var(--line)}
td{padding:5px 8px;border-bottom:1px solid var(--line)}
tr:last-child td{border-bottom:none}
.dot-review{color:var(--good)}.dot-learning{color:var(--warn)}.dot-new{color:var(--muted)}
.hbar{display:flex;align-items:center;gap:10px;margin:6px 0;font-size:13px}
.hbar .track{flex:1;height:12px;background:var(--line);border-radius:6px;overflow:hidden}
.hbar .fill{height:100%;background:var(--accent)}
.hbar .lab{width:70px}.hbar .val{width:110px;text-align:right;color:var(--muted);font-size:12px}
.note{color:var(--muted);font-size:13px}
.flag{color:var(--accent)}
footer{margin-top:48px;padding-top:16px;border-top:1px solid var(--line);
color:var(--muted);font-size:12px}
"""

def cmd_report(args):
    stats = compute_stats()
    model = read_model()
    d = today().isoformat()
    parts = ["<meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>",
             "<title>Engram — learning dashboard</title><style>%s</style><main>" % REPORT_CSS,
             "<h1>Engram</h1><p class='sub'>learning dashboard · generated %s · all data local</p>" % d]
    chips = [("streak", "%d day%s" % (stats["streak_days"], "s" if stats["streak_days"] != 1 else "")),
             ("due today", str(stats["due_now"])),
             ("pending grading", str(stats["pending_verify"])),
             ("receipts", str(stats["receipts"])),
             ("open misconceptions", str(stats["misconceptions_open"]))]
    parts.append("<div class='chips'>" + "".join(
        "<span class='chip'>%s <b>%s</b></span>" % (escape(k), escape(v)) for k, v in chips) + "</div>")

    for t, g in iter_graphs():
        counts = state_counts(g)
        total = max(1, len(g["nodes"]))
        seg = lambda n, color: ("<span style='width:%.1f%%;background:var(--%s)'></span>"
                                % (100.0 * n / total, color)) if n else ""
        parts.append("<div class='card'><h2 style='margin:0'>%s</h2>"
                     % escape(str(g.get("title") or t)))
        if g.get("goal"):
            parts.append("<p class='goal'>goal: %s</p>" % escape(str(g["goal"])))
        parts.append("<div class='bar'>%s%s</div>" % (seg(counts["review"], "good"),
                                                      seg(counts["learning"], "warn")))
        parts.append("<p class='legend'>%d retained · %d learning · %d untouched</p>"
                     % (counts["review"], counts["learning"], counts["new"]))
        rows = []
        for nid in g["order"]:
            node = g["nodes"].get(nid) if isinstance(nid, str) else None
            if not isinstance(node, dict):
                continue
            st = node.get("state", "new")
            # `st not in STATE_DOTS` raises TypeError on an unhashable value (a hand-edited
            # `state: {}` or `state: []`), taking the whole dashboard down. state_counts() was
            # guarded for this and cmd_report was not. Caught by the §4.7 fuzz gate.
            if not isinstance(st, str) or st not in STATE_DOTS:
                st = "new"
            fsrs = _fsrs_of(node)
            flags = ("<span class='flag'>†</span>" if node.get("threshold") else "") + \
                    ("<span class='flag'>*</span>" if node.get("arbitrary") else "")
            s = as_number(fsrs.get("s"))
            lapses = fsrs.get("lapses", 0)
            # every interpolated value is escape()d — node fsrs is attacker-settable
            rows.append("<tr><td class='dot-%s'>%s</td><td>%s %s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
                st, STATE_DOTS[st], escape(nid), flags,
                ("%.1fd" % s) if s else "—", escape(str(fsrs.get("due") or "—")),
                escape(str(lapses)) if lapses else ""))
        parts.append("<table><tr><th></th><th>concept</th><th>stability</th><th>due</th>"
                     "<th>lapses</th></tr>%s</table></div>" % "".join(rows))

    # v0.6: the binding constraint and the north star lead the dashboard, because a
    # dashboard that opens with calibration over a loop that never closed is decor.
    ad, ret = stats["adherence"], stats["retention"]
    gh = stats["grader_health"]          # v0.7: computed since v0.7, RENDERED since v0.7.1
    lc = ad["loop_closure"]
    parts.append("<h2>The loop</h2>")
    if lc["rate"] is None:
        parts.append("<p class='note'>%s</p>" % escape(lc["read"]))
    else:
        pct = int(round(lc["rate"] * 100))
        tone = "bad" if lc["rate"] == 0 else ("warn" if lc["rate"] < 0.5 else "good")
        parts.append("<div class='hbar'><span class='lab mono'>closed</span>"
                     "<span class='track'><span class='fill' style='width:%d%%;"
                     "background:var(--%s)'></span></span>"
                     "<span class='val'>%d of %d · %d%%</span></div>"
                     % (pct, tone, lc["first_review_done"], lc["encoded_past_due"], pct))
        parts.append("<p class='note'><b>%s</b> — of the concepts Engram taught and scheduled, "
                     "this is how many you came back for. Every other number on this page is "
                     "multiplied by it.</p>" % escape(lc["read"]))

    parts.append("<h2>Retention — recall by days since you first learned it</h2>")
    # THE TEETH, ON THE SCREEN. `ret["read"]` is the ONLY carrier of the grader stamp, and the
    # first cut rendered it exclusively in the `else` branch — i.e. only when there was NO
    # retention data to qualify. On the happy path it drew the bars and dropped the stamp, so a
    # grader that inflated every second item produced a full-width green bar reading 100% with
    # nothing anywhere to say the grade behind it had failed its own audit.
    #
    # That is bug class #1 (a flattering number) and #4 (a guard nobody reads), on the single
    # surface where a number is MOST believed — and `compute_retention`'s own comment claimed
    # the dashboard was covered. It funnelled through the function and then threw the result away.
    # Found by the independent adversarial reviewer; the live test, the fuzz, the numbers audit
    # and the user session had all walked straight past it, because every one of them reads JSON.
    if gh.get("stamp"):
        parts.append("<p class='note' style='color:var(--bad)'><b>%s</b></p>" % escape(gh["stamp"]))
    # THE OTHER GRADER (v1.4). `grader_health` above is the blind assessor, measured against
    # the gold set. The TUTOR writes every /review receipt and, until now, nothing measured it
    # — so its number reaches the page too, or it is a guard nobody reads (§4.8 Q4). Rendered
    # in the neutral register: it is agreement with the assessor, never validity, and the
    # direction is what matters, because a mean bias of zero is also what "inflates half,
    # deflates half" looks like.
    sg = stats.get("self_grading") or {}
    if sg.get("n"):
        parts.append("<p class='note'><b>tutor vs blind assessor:</b> %s</p>" % escape(sg["read"]))
        if sg.get("tutor_higher"):
            parts.append("<p class='note' style='color:var(--bad)'>the tutor graded ABOVE the "
                         "blind assessor %d time%s — the only direction that can flatter.</p>"
                         % (sg["tutor_higher"], "" if sg["tutor_higher"] == 1 else "s"))
    if any(b["n"] for b in ret["buckets"].values()):
        for key, label in (("early", "0–3d (still encoding)"), ("7d", "4–14d"),
                           ("30d", "15–59d"), ("90d", "60–179d"), ("180d+", "180d+")):
            b = ret["buckets"][key]
            if not b["n"]:
                continue
            parts.append("<div class='hbar'><span class='lab mono'>%s</span>"
                         "<span class='track'><span class='fill' style='width:%d%%'></span></span>"
                         "<span class='val'>%d%% · n=%d</span></div>"
                         % (escape(label), int(b["rate"] * 100), int(b["rate"] * 100), b["n"]))
    parts.append("<p class='note'>%s</p>" % escape(ret["read"]))   # unconditionally, always
    u = ret["unmeasured"]
    if u["past_due_now"]:
        parts.append("<p class='note' style='color:var(--bad)'><b>%d concept%s past due and "
                     "unretrieved right now</b> (%d never reviewed at all). They are <b>not</b> "
                     "in the numbers above — their recall is <i>unknown, not absent</i>, and "
                     "FSRS puts them near <b>%d%%</b>. A retention figure that quietly drops "
                     "them is survivorship bias with a progress bar.</p>"
                     % (u["past_due_now"], "s" if u["past_due_now"] != 1 else "",
                        u["never_reviewed"],
                        int(round((u["projected_recall_now"] or 0) * 100))))
    # v1.3: the retired exit reaches the PAGE, not just the JSON (§4.8 Q4 — the dashboard is
    # the one surface a human actually looks at, and it is the one that lied in v0.7). Stated
    # in the neutral register it deserves: this is a decision, not debt.
    if u.get("retired"):
        parts.append("<p class='note'>%d concept%s <b>retired by you</b> — off the queue on "
                     "purpose, neither measured above nor counted as debt.</p>"
                     % (u["retired"], "s" if u["retired"] != 1 else ""))
    if not ret["coverage"]["complete"]:
        parts.append("<p class='note' style='color:var(--bad)'><b>coverage incomplete — see above</b></p>")

    # THE CAPABILITY CLAIM (v0.8). Retention says the memory survived; transfer says the idea is
    # yours. Rendered HERE because §4.8 Q4 now requires it: a number whose failure state reaches
    # the JSON, the CLI and the skill — and not the page a human actually looks at — is the exact
    # bug v0.7 shipped. "NO CAPABILITY HAS EVER BEEN MEASURED" belongs on the screen, in red.
    tr = stats["transfer"]
    parts.append("<h2>Transfer — does the idea fire in different clothes?</h2>")
    if not tr["n"]:
        parts.append("<p class='note' style='color:var(--bad)'><b>%s</b></p>" % escape(tr["read"]))
    else:
        chips = [("OWNED NOW", "%d / %d" % (tr["owned"], tr["tested"]))]
        if not tr["insufficient_data"]:
            chips.append(("owned rate", "%d%%" % round((tr["owned_rate"] or 0) * 100)))
            chips.append(("lifetime probe fire rate", "%d%%"
                          % round((tr["probe_fire_rate"] or 0) * 100)))
        chips += [("probes", str(tr["n"])), ("untested", str(tr["states"]["untested"]))]
        parts.append("<div class='chips'>%s</div>" % "".join(
            "<span class='chip'>%s <b>%s</b></span>" % (escape(k), escape(v)) for k, v in chips))
        parts.append("<p class='note'>%s</p>" % escape(tr["read"]))
    parts.append("<p class='note'><b>Never pooled with retention above.</b> Retention asks "
                 "whether the memory survived; transfer asks whether the capability fires. "
                 "One of them is the one you actually paid for.</p>")

    # THE ORACLE (v0.7). Every number above is a count of the assessor's verdicts, so the
    # dashboard has to say who the assessor is and whether anyone has ever checked it.
    parts.append("<h2>The grader behind every number above</h2>")
    # every value here can be garbage from a hand-edited audit file, so str() then escape()
    if not gh.get("audited"):
        parts.append("<p class='note'>%s</p>" % escape(str(gh["read"])))
    else:
        d = gh.get("direction") or {}
        up, judged = d.get("graded_up"), d.get("judgments")
        chips = [("QWK", _fmt(gh.get("qwk"))), ("leniency", _fmt(gh.get("leniency_bias"), sign=True)),
                 ("test–retest", _fmt(gh.get("test_retest"))), ("items", str(gh.get("n"))),
                 ("runs", str(gh.get("runs"))), ("verdict", str(gh.get("verdict")))]
        if isinstance(up, int) and isinstance(judged, int) and judged:
            chips.insert(2, ("graded UP", "%d / %d" % (up, judged)))
        parts.append("<div class='chips'>%s</div>" % "".join(
            "<span class='chip'>%s <b>%s</b></span>" % (escape(str(k)), escape(str(v)))
            for k, v in chips))
        parts.append("<p class='note'>%s</p>" % escape(str(gh.get("read") or "")))
        parts.append("<p class='note'>Raw agreement is never quoted alone: it overstates "
                     "chance-corrected agreement by 34–41 points. <b>QWK is the headline.</b></p>")

    parts.append("<h2>Recall by memory strength <span class='note' style='font-size:13px;font-weight:400'>(the older view — grouped by how durable the memory is, not by how long ago you learned it)</span></h2>")
    if stats["recall_by_stability"]:
        for b, label in (("early", "early (S<7d)"), ("week", "week (7–30d)"), ("month+", "month+ (>30d)")):
            v = stats["recall_by_stability"].get(b)
            if not v:
                continue
            parts.append("<div class='hbar'><span class='lab mono'>%s</span>"
                         "<span class='track'><span class='fill' style='width:%d%%'></span></span>"
                         "<span class='val'>%d%% recall · n=%d</span></div>"
                         % (escape(label), int(v["rate"] * 100), int(v["rate"] * 100), v["n"]))
        parts.append("<p class='note'>target band ≈ 85%% — much higher means reviews are "
                     "too easy/late-scheduled matter is absent; much lower means encoding "
                     "or scheduling needs attention.</p>")
    else:
        parts.append("<p class='note'>No review outcomes yet — retention appears here after "
                     "your first scheduled /review sessions.</p>")

    parts.append("<h2>Calibration</h2>")
    cal = stats["calibration"]
    if cal["brier"] is not None:
        parts.append("<p class='note'>Brier %.3f · bias %+.3f → <b>%s</b> · n=%d "
                     "(only answers where you actually stated a confidence count)</p>"
                     % (cal["brier"], cal["bias"], escape(cal["read"]), cal["n"]))
    else:
        parts.append("<p class='note'>No honest confidence data yet — confidence is recorded "
                     "only when you actually say a number before feedback. It is never estimated "
                     "for you.</p>")

    parts.append("<h2>Encoding medium</h2>")
    mod = stats["modality"]
    if mod["read"] != "insufficient-data":
        for arm, label in (("explorable", "explorable"), ("dialogue", "dialogue-only")):
            v = mod[arm]
            parts.append("<div class='hbar'><span class='lab mono'>%s</span>"
                         "<span class='track'><span class='fill' style='width:%d%%'></span></span>"
                         "<span class='val'>%d%% first-review recall · n=%d</span></div>"
                         % (escape(label), int(v["first_review_recall"] * 100),
                            int(v["first_review_recall"] * 100), v["n"]))
        parts.append("<p class='note'>%s — your own receipts comparing how concepts "
                     "encoded with an interactive explorable hold up against dialogue-only "
                     "ones, at each node's first review. <b>Read it carefully:</b> %s "
                     "<span class='mono'>visuals eager|threshold|off</span> is the dial.</p>"
                     % (escape(mod["read"]), escape(mod["caveat"])))
    elif mod["explorable"]["n"] == 0:
        parts.append("<p class='note'>No explorable-encoded reviews yet — once explorables "
                     "enter the mix, their retention is compared against dialogue-only "
                     "encoding here, from your own receipts.</p>")
    else:
        parts.append("<p class='note'>Comparing media needs ≥%d first-reviews per arm "
                     "(explorable-encoded: %d, dialogue: %d so far) — the honest verdict "
                     "appears when both sides have history.</p>"
                     % (mod["min_n"], mod["explorable"]["n"], mod["dialogue"]["n"]))

    # v1.1 (docs/11): knowledge-kind split, rendered in the modality section's mold — which
    # means the FLOOR is the modality floor: percentage bars render only when the compared
    # arms both clear MODALITY_MIN_N (`read` != insufficient-data). The first cut rendered
    # a full-width 100% bar off a single first-review — an unearned optimistic rate on the
    # one surface a human actually looks at (§4.8 Q2, release-blocking direction; caught by
    # the pre-release adversarial review). Below the floor: honest counts, no rates. The
    # caveat must reach this page either way (§4.8 Q4).
    bk = stats["by_kind"]
    kind_arms = [(k, bk[k]) for k in NODE_KINDS
                 if isinstance(bk.get(k), dict) and bk[k].get("n")]
    if kind_arms:
        parts.append("<h2>Knowledge kinds</h2>")
        slip = bk.get("procedure_slip_share") or {}
        slip_line = ""
        # Quote the slip PERCENTAGE only at a real n; below the floor, counts are facts
        # and rates are noise ("100% were slips" off n=1 is the flattering read).
        if (slip.get("n_nodes") or 0) >= SLIP_SHARE_MIN_N:
            slip_line = (" Of the %d classified procedure-review errors across %d nodes, "
                         "%d%% were execution slips rather than wrong method — a slip is "
                         "priced gentler (partial/hard), because a transcription error is "
                         "not a memory lapse." % (slip["n_classified"], slip["n_nodes"],
                                                  int((slip.get("share") or 0) * 100)))
        elif slip.get("n_classified"):
            slip_line = (" %d procedure-review error(s) classified so far, across %d node(s) "
                         "— counts, not rates, until at least %d nodes have one."
                         % (slip["n_classified"], slip.get("n_nodes") or 0,
                            SLIP_SHARE_MIN_N))
        # ⚠ EVERY arm carries its OWN floor (v1.1.1). `read` is computed from procedure-vs-
        # concept only, so gating the bar loop on `read` alone let `fact` — which the read
        # never looks at — render a full-width 100% bar off a SINGLE first review. That is
        # the same unearned-optimistic-rate bug this section already fixed once, one line
        # further down, and the v1.1.0 selftest could not see it because its fixture built
        # no fact nodes. Found by the §7.5 post-release review. Sub-floor kinds are reported
        # as counts, which are facts; a rate off n=1 is not.
        if bk["read"] != "insufficient-data":
            shown = [(k, v) for k, v in kind_arms if v["n"] >= bk["min_n"]]
            thin = [(k, v) for k, v in kind_arms if v["n"] < bk["min_n"]]
            for k, v in shown:
                parts.append("<div class='hbar'><span class='lab mono'>%s</span>"
                             "<span class='track'><span class='fill' style='width:%d%%'></span></span>"
                             "<span class='val'>%d%% first-review recall · n=%d</span></div>"
                             % (escape(k), int(v["first_review_recall"] * 100),
                                int(v["first_review_recall"] * 100), v["n"]))
            if thin:
                parts.append("<p class='note'>Below the ≥%d floor, counts only: %s.</p>"
                             % (bk["min_n"],
                                escape(" · ".join("%s n=%d" % (k, v["n"]) for k, v in thin))))
            parts.append("<p class='note'>%s — recall split by what each node IS (concept / "
                         "procedure / fact), from your own receipts.%s <b>Read it carefully:"
                         "</b> %s</p>"
                         % (escape(bk["read"]), escape(slip_line), escape(bk["caveat"])))
        else:
            counts = " · ".join("%s: %d" % (k, v["n"]) for k, v in kind_arms)
            parts.append("<p class='note'>Splitting recall by knowledge kind needs ≥%d "
                         "first-reviews in both compared kinds (%s so far) — the honest "
                         "verdict appears when both sides have history.%s "
                         "<b>Read it carefully:</b> %s</p>"
                         % (bk["min_n"], escape(counts), escape(slip_line),
                            escape(bk["caveat"])))

    mis = _open_misconceptions()
    if mis:
        parts.append("<h2>Open misconceptions</h2>")
        for m in mis:
            parts.append("<div class='card'><span class='mono' style='font-size:12px'>%s / %s</span>"
                         "<p style='margin:6px 0 0'>%s</p></div>"
                         % (escape(m.get("topic") or ""), escape(m.get("node") or ""),
                            escape(m.get("description") or "")))

    horizon = due_items(horizon_days=7)
    parts.append("<h2>Next 7 days</h2>")
    if horizon:
        per_day = {}
        for item in horizon:
            per_day[item["due"]] = per_day.get(item["due"], 0) + 1
        peak = max(per_day.values())
        for day in sorted(per_day):
            n = per_day[day]
            parts.append("<div class='hbar'><span class='lab mono'>%s</span>"
                         "<span class='track'><span class='fill' style='width:%d%%'></span></span>"
                         "<span class='val'>%d node%s</span></div>"
                         % (escape(day), int(100 * n / peak), n, "s" if n != 1 else ""))
    else:
        parts.append("<p class='note'>Nothing scheduled in the next 7 days.</p>")

    parts.append("<footer>state: %s · regenerate: <span class='mono'>python3 engram.py report"
                 "</span> · Engram never sends data anywhere.</footer></main>" % escape(home()))

    out_path = args.out or p("artifacts", "dashboard.html")
    if args.out and not getattr(args, "allow_outside", False):
        # Confine to the state dir by default so a prompt-injected --out can't drop
        # an HTML file into an arbitrary location; --allow-outside is the opt-in.
        base = os.path.realpath(home())
        if not os.path.realpath(out_path).startswith(base + os.sep):
            die("refusing to write outside the state dir: %s (pass --allow-outside to override)"
                % out_path)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("<!doctype html>\n" + "\n".join(parts) + "\n")
    emit({"ok": True, "path": out_path})

# ---------------------------------------------------------------- selftest

def approx(a, b, tol=0.02):
    return abs(a - b) <= tol * max(1.0, abs(b))

def cmd_selftest(_args):
    total = [0]
    failures = []
    def check(name, cond):
        """`cond` may be a bool, or a zero-arg callable whose EXCEPTION is a failure.

        A check that raises must fail BY NAME, not take the whole suite down with it. Every
        §4.5 mutation of a crash-guard used to report "the selftest crashed" — true,
        unmissable, and useless for locating which guard you just reverted, because the
        traceback names the engine line, not the check. It also meant one broken check hid
        the verdict of every check after it."""
        total[0] += 1
        if callable(cond):
            try:
                cond = cond()
            except SystemExit as ex:
                print("FAIL %s  [engine exited: %s]" % (name, ex))
                failures.append(name)
                return
            except BaseException as ex:
                print("FAIL %s  [raised %s: %s]" % (name, type(ex).__name__, ex))
                failures.append(name)
                return
        print("%s %s" % ("PASS" if cond else "FAIL", name))
        if not cond:
            failures.append(name)

    check("R(t=S) == 0.9", approx(retrievability(10, 10), 0.9, 0.001))
    check("interval(S, 0.9) == S", interval_for(10, 0.9) == 10)
    check("interval multiplier scales", interval_for(10, 0.9, 0.5) == 5)
    check("initial stabilities ordered", W[0] < W[1] < W[2] < W[3])
    d, s, r = 5.0, 10.0, 0.9
    s_hard = next_stability_recall(d, s, r, 2)
    s_good = next_stability_recall(d, s, r, 3)
    s_easy = next_stability_recall(d, s, r, 4)
    s_forget = next_stability_forget(d, s, r)
    check("stability growth ordered hard<good<easy", s_hard < s_good < s_easy)
    check("all recall ratings grow stability", s < s_hard)
    check("lapse shrinks stability", s_forget < s)
    check("lapse capped at prior S", next_stability_forget(2.0, 0.5, 0.99) <= 0.5)
    check("again raises difficulty", next_difficulty(5.0, 1) > 5.0)
    check("easy lowers difficulty", next_difficulty(5.0, 4) < 5.0)
    check("difficulty clamped", next_difficulty(10.0, 1) <= 10.0 and next_difficulty(1.0, 4) >= 1.0)
    check("R monotonic in elapsed", retrievability(20, 10) < retrievability(5, 10))
    check("harder material grows slower",
          next_stability_recall(9.0, s, r, 3) < next_stability_recall(2.0, s, r, 3))

    with tempfile.TemporaryDirectory() as tmp:
        os.environ["ENGRAM_HOME"] = tmp
        os.environ["ENGRAM_TODAY"] = "2026-07-05"
        load_model()
        g = {"topic": "t", "title": "T", "order": ["a", "b"], "nodes": {
            "a": {"claim": "A holds", "probe": "Why does A hold?"},
            "b": {"claim": "B follows from A", "probe": "Derive B.",
                  "edges": {"requires": ["a"]}}}}
        write_json(os.path.join(tmp, "payload.json"), g)
        _capture(cmd_add_topic, _ns(file=os.path.join(tmp, "payload.json")))
        nxt = _capture_json(cmd_next, _ns(topic="t"))
        check("frontier respects requires", nxt["id"] == "a")
        _capture(cmd_rate, _ns(topic="t", node="a", rating="good", confidence=70,
                               production="because reasons", grade="recalled", kind="encode"))
        nxt2 = _capture_json(cmd_next, _ns(topic="t"))
        check("frontier advances after encode", nxt2["id"] == "b")
        check("nothing due immediately after good", len(due_items()) == 0)
        os.environ["ENGRAM_TODAY"] = "2026-08-05"
        due_later = due_items()
        check("item comes due later", len(due_later) == 1 and due_later[0]["id"] == "a")
        _capture(cmd_rate, _ns(topic="t", node="a", rating="again", confidence=90,
                               production=None, grade="lapsed", kind="review"))
        g2 = load_graph("t")
        check("lapse recorded", g2["nodes"]["a"]["fsrs"]["lapses"] == 1
              and g2["nodes"]["a"]["state"] == "learning")
        stats = _capture_json(cmd_stats, _ns())
        check("stats computes calibration", stats["calibration"]["brier"] is not None)
        # n=1 review -> verdict suppressed (min-n guard); the encode confidence is
        # split into its own pool, not pooled into the review verdict.
        check("calibration verdict suppressed below min-n",
              stats["calibration"]["read"] == "insufficient-data")
        check("encode confidence split from review calibration",
              stats["calibration"]["n"] == 1 and stats["calibration_encode"]["n"] == 1)

        # momentum (P13 competence salience) — the engine owns the growth math, not the model
        check("stats includes momentum block",
              isinstance(stats.get("momentum"), dict) and stats["momentum"]["window_days"] == 7)
        check("momentum reports a most-durable memory",
              stats["momentum"]["most_durable"] is not None
              and stats["momentum"]["most_durable"]["node"] in ("a", "b"))
        # unit-test the durability arithmetic in isolation (today == 2026-08-05 here):
        # only in-window successful reviews count; a shrink contributes 0; old ones excluded.
        # Each node needs its ENCODE receipt first — a node's first receipt is its encoding
        # event, never a review (v0.6.1), and every counter now shares that one predicate.
        mom = compute_momentum([
            {"id": "e1", "ts": "2026-05-01", "kind": "encode", "rating": "good",
             "topic": "t", "node": "n1"},
            {"id": "e2", "ts": "2026-05-01", "kind": "encode", "rating": "good",
             "topic": "t", "node": "n2"},
            {"id": "e3", "ts": "2026-05-01", "kind": "encode", "rating": "good",
             "topic": "t", "node": "n3"},
            {"id": "e4", "ts": "2026-05-01", "kind": "encode", "rating": "good",
             "topic": "t", "node": "n4"},
            {"id": "r1", "ts": "2026-08-05", "kind": "review", "rating": "good",
             "topic": "t", "node": "n1", "s_before": 2.0, "s_after": 9.0, "grade": "recalled"},
            {"id": "r2", "ts": "2026-08-04", "kind": "review", "rating": "hard",
             "topic": "t", "node": "n2", "s_before": 5.0, "s_after": 6.5},
            {"id": "r3", "ts": "2026-08-05", "kind": "review", "rating": "again",
             "topic": "t", "node": "n3", "s_before": 8.0, "s_after": 3.0},   # lapse: no negative growth
            {"id": "r4", "ts": "2026-06-01", "kind": "review", "rating": "good",
             "topic": "t", "node": "n4", "s_before": 1.0, "s_after": 40.0},  # outside window
            # IN-WINDOW first-exposure receipts carrying grade:"recalled" — the inflators
            # the v1.0.6 fixture couldn't see (its encodes were out-of-window AND gradeless,
            # so the recalled_7d check was theatre; §7.5 post-release review, v1.0.7).
            {"id": "e5", "ts": "2026-08-05", "kind": "encode", "rating": "good",
             "topic": "t", "node": "n5", "grade": "recalled"},
            {"id": "p1", "ts": "2026-08-05", "kind": "pretest", "rating": "easy",
             "topic": "t", "node": "n6", "grade": "recalled"},
        ])
        check("momentum sums only in-window durability gains",
              mom["reviews_7d"] == 3 and approx(mom["stability_gained_7d"], 8.5, 0.01))
        check("momentum recalled_7d = wins among RETRIEVALS only (in-window encode/pretest "
              "'recalled' grades do not count)", mom["recalled_7d"] == 1)

        # settings self-heal: a model missing the new keys is repaired, not broken
        healed = _deep_heal({"schema": SCHEMA, "settings": {"default_mode": "sprint"}},
                            DEFAULT_MODEL)
        check("settings self-heal adds momentum/profile defaults",
              healed["settings"]["momentum"] == "on"
              and healed["settings"]["profile"] is None
              and healed["settings"]["default_mode"] == "sprint")

        # `model --set ...=null` clears to real None, not the string "null"
        _capture(cmd_model, _ns(set=["settings.profile=null"]))
        check("model --set =null clears to None (not the string 'null')",
              read_json(os.path.join(tmp, "learner-model.json"))["settings"]["profile"] is None)

        # the `focus` command toggles the ADHD profile on and cleanly back off
        on = _capture_json(cmd_focus, _ns(action="on"))
        prof_on = read_json(os.path.join(tmp, "learner-model.json"))["settings"]["profile"]
        off = _capture_json(cmd_focus, _ns(action="off"))
        prof_off = read_json(os.path.join(tmp, "learner-model.json"))["settings"]["profile"]
        check("focus on/off toggles profile and reports state",
              prof_on == "adhd" and on["focus_active"] is True
              and prof_off is None and off["focus_active"] is False)

        # receipt ids unique within a fast batch
        batch = [{"topic": "t", "node": "a", "rating": "good"},
                 {"topic": "t", "node": "b", "rating": "good"}]
        write_json(os.path.join(tmp, "batch.json"), batch)
        _capture(cmd_receipt, _ns(file=os.path.join(tmp, "batch.json")))
        ids = [r["id"] for r in collect_receipts()]
        check("receipt ids unique", len(ids) == len(set(ids)))

        # add-interest keeps every value passed in one call
        _capture(cmd_model, _ns(add_interest=["AAA", "BBB"]))
        m = read_json(os.path.join(tmp, "learner-model.json"))
        check("add-interest appends all values", "AAA" in m["interests"] and "BBB" in m["interests"])

        # streak: activity yesterday only → streak 1 (grace day)
        os.environ["ENGRAM_TODAY"] = "2026-08-06"
        check("streak grace day", compute_streak(collect_receipts()) >= 1)
        os.environ["ENGRAM_TODAY"] = "2026-08-05"
        check("streak same day counts", compute_streak(collect_receipts()) >= 1)

        # stash roundtrip
        item = {"topic": "t", "node": "b", "probe": "p?", "production": "text"}
        write_json(os.path.join(tmp, "stash.json"), [item, item])
        _capture(cmd_stash, _ns(action="add", file=os.path.join(tmp, "stash.json")))
        check("stash add/count", _capture_json(cmd_stash, _ns(action="count"))["pending"] == 2)
        check("stash surfaces in stats", _capture_json(cmd_stats, _ns())["pending_verify"] == 2)
        _capture(cmd_stash, _ns(action="clear"))
        check("stash clear", _capture_json(cmd_stash, _ns(action="count"))["pending"] == 0)

        # refit: guarded without data; with forced synthetic bad recall → shorter intervals
        guard = _capture_json(cmd_refit, _ns(force=False))
        check("refit guarded on thin data", guard["ok"] is False)
        for i in range(30):
            append_jsonl(os.path.join(tmp, "receipts", "t.jsonl"),
                         {"id": "syn%d" % i, "ts": "2026-08-01", "topic": "t", "node": "a",
                          "kind": "review", "rating": ("again" if i < 12 else "good"),
                          "retrievability": 0.9})
        refit = _capture_json(cmd_refit, _ns(force=True))
        check("refit shortens intervals when recall worse than predicted",
              refit["ok"] and refit["interval_multiplier"]["after"] < 1.0)
        m2 = read_json(os.path.join(tmp, "learner-model.json"))
        check("refit persists multiplier", m2["memory"]["interval_multiplier"] < 1.0)

        # report generates a self-contained file
        rep = _capture_json(cmd_report, _ns(out=os.path.join(tmp, "dash.html")))
        html_text = open(rep["path"], encoding="utf-8").read()
        check("report written", rep["ok"] and "<title>" in html_text)
        check("report self-contained", "http://" not in html_text and "https://" not in html_text)

        # doctor runs clean on this state
        doc = _capture_json(cmd_doctor, _ns())
        check("doctor ok on healthy state", doc["ok"] is True)

        os.environ.pop("ENGRAM_HOME", None)
        os.environ.pop("ENGRAM_TODAY", None)

    # ============ 0.3.0 hardening regression checks (each in its own home) ======

    # -- FSRS-4.5 difficulty anchor: Good at D0(3) is a fixed point (issue #1.1) --
    check("difficulty reverts to D0(3) (FSRS-4.5 anchor)",
          approx(next_difficulty(init_difficulty(3), 3), init_difficulty(3), 0.001))
    check("difficulty anchor is NOT D0(4)",
          not approx(next_difficulty(init_difficulty(4), 3), init_difficulty(4), 0.001))

    # -- calibration outcome from grade, not rating (issue #2.1) --
    check("partial is half credit, not a total miss", _outcome({"grade": "partial"}) == 0.5)
    check("hard rating falls back to half credit",
          _outcome({"rating": "hard"}) == 0.5 and _outcome({"rating": "good"}) == 1.0)
    cal_partial = _calibration([{"confidence": 90, "grade": "partial", "rating": "hard"}])
    check("hard/partial @90 is not maxed to +0.9 bias",
          cal_partial["bias"] == 0.4 and cal_partial["brier"] < 0.2)
    # -- min-n verdict floor (issue #2.2) --
    check("calibration below min-n reads insufficient-data",
          _calibration([{"confidence": 80, "grade": "recalled"}])["read"] == "insufficient-data")
    over = _calibration([{"confidence": 90, "grade": "lapsed"}] * CAL_MIN_N)
    check("calibration at >=min-n yields a verdict",
          over["read"] == "overconfident" and over["n"] == CAL_MIN_N)

    # -- confidence coercion is safe and bounded (R8/N3) --
    check("confidence clamped and typed",
          clean_confidence(150) == 100 and clean_confidence(-20) == 0
          and clean_confidence("high") is None and clean_confidence(0.9) == 1)

    # -- NON-FINITE IS NOT A NUMBER (v0.9, found by fuzzing `decay` and `experiment status`) --
    # `Infinity`/`NaN` are not valid JSON — and Python's json module parses them anyway. An `inf`
    # sails through every `isinstance(x, float)` check, then dies on the first `int()`
    # (OverflowError), and a `NaN` poisons every comparison it touches (it compares False to
    # everything, including itself). One gate, not forty call sites.
    check("as_number rejects inf/-inf/NaN — non-finite is not a number",
          as_number(float("inf")) is None and as_number(float("-inf")) is None
          and as_number(float("nan")) is None
          and as_number(float("inf"), 7.0) == 7.0          # …and honours the default
          and as_number(float("nan"), 7.0) == 7.0
          and as_number(3.5) == 3.5 and as_number(0) == 0.0)   # real numbers still pass
    check("a NaN confidence never becomes a number",
          clean_confidence(float("nan")) is None and clean_confidence(float("inf")) is None)

    # -- slug guard (R5 traversal) --
    check("slug accepts real topics",
          slug_ok("transformers-attention") and slug_ok("t") and slug_ok("a.b_c"))
    check("slug rejects traversal/abs/hidden",
          not slug_ok("../pwned") and not slug_ok("/etc/x")
          and not slug_ok(".hidden") and not slug_ok("a/b") and not slug_ok(""))

    def raises(fn, *a, **k):
        import io, contextlib
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                fn(*a, **k)
            return False
        except SystemExit:
            return True

    def fresh(fn):
        """A throwaway ENGRAM_HOME, as a THUNK — so `check` can catch what `fn` raises and
        fail that check BY NAME instead of the exception killing the whole suite."""
        def run():
            with tempfile.TemporaryDirectory() as h:
                os.environ["ENGRAM_HOME"] = h
                os.environ["ENGRAM_TODAY"] = "2026-07-06"
                try:
                    _capture(cmd_init, _ns())
                    return fn(h)
                finally:
                    os.environ.pop("ENGRAM_HOME", None)
                    os.environ.pop("ENGRAM_TODAY", None)
        return run

    def _add_ab(replace=False):
        g = {"topic": "t", "title": "T", "order": ["a", "b"], "nodes": {
            "a": {"claim": "A", "probe": "pa"},
            "b": {"claim": "B", "probe": "pb", "edges": {"requires": ["a"]}}}}
        _capture(cmd_add_topic, _ns(json=json.dumps(g), replace=replace))

    # -- refit --force with zero receipts no longer divides by zero (issue #1.3) --
    check("refit --force on empty data is graceful",
          fresh(lambda h: _capture_json(cmd_refit, _ns(force=True))["ok"] is False))

    # -- add-topic rejects a traversal slug and writes nothing outside home (R5) --
    def _traversal(h):
        bad = {"topic": "../pwned", "title": "x", "order": ["a"],
               "nodes": {"a": {"claim": "c", "probe": "p"}}}
        rejected = raises(cmd_add_topic, _ns(json=json.dumps(bad)))
        outside = os.path.exists(os.path.join(os.path.dirname(h), "pwned.json"))
        return rejected and not outside
    check("add-topic rejects traversal slug, writes nothing outside home", fresh(_traversal))

    # -- add-topic ignores payload-supplied mastery (issue: mastery without receipt) --
    def _no_free_mastery(h):
        g = {"topic": "t", "title": "T", "order": ["a"], "nodes": {"a": {
            "claim": "c", "probe": "p", "state": "review",
            "fsrs": {"s": 99.0, "d": 5.0, "due": "2030-01-01", "last": "2029-01-01",
                     "reps": 7, "lapses": 0}}}}
        _capture(cmd_add_topic, _ns(json=json.dumps(g)))
        node = load_graph("t")["nodes"]["a"]
        return node["state"] == "new" and node["fsrs"]["s"] is None
    check("add-topic strips payload-supplied state/fsrs (no mastery without receipts)",
          fresh(_no_free_mastery))

    # -- add-topic --replace preserves surviving node schedule (H4 data loss) --
    def _replace_preserves(h):
        _add_ab()
        _capture(cmd_rate, _ns(topic="t", node="a", rating="good", grade="recalled", kind="encode"))
        s_before = load_graph("t")["nodes"]["a"]["fsrs"]["s"]
        g = {"topic": "t", "title": "T2", "order": ["a", "b", "c"], "nodes": {
            "a": {"claim": "A", "probe": "pa"}, "b": {"claim": "B", "probe": "pb"},
            "c": {"claim": "C", "probe": "pc"}}}
        _capture(cmd_add_topic, _ns(json=json.dumps(g), replace=True))
        s_after = load_graph("t")["nodes"]["a"]["fsrs"]["s"]
        return s_before is not None and s_after == s_before
    check("add-topic --replace preserves surviving node schedule", fresh(_replace_preserves))

    # -- next skips a stashed node AND advances past a stashed prereq (issue #2.4/R3b) --
    def _stash_aware_next(h):
        _add_ab()
        _capture(cmd_stash, _ns(action="add", json=json.dumps(
            {"topic": "t", "node": "a", "probe": "pa", "production": "ans a"})))
        nx = _capture_json(cmd_next, _ns(topic="t"))
        stash_b = _capture(cmd_stash, _ns(action="add", json=json.dumps(
            {"topic": "t", "node": "b", "probe": "pb", "production": "ans b"})))
        nx2 = _capture_json(cmd_next, _ns(topic="t"))
        return (nx["id"] == "b" and nx.get("provisional_requires") == ["a"]
                and nx2["id"] is None and nx2["pending_verify"] == 2)
    check("next skips stashed node and provisionally clears stashed prereq",
          fresh(_stash_aware_next))

    # ============ v0.6 — the loop closes: adherence, retention, decay, commit, sid ======

    # -- days_between is the spine of every elapsed-day metric --
    check("days_between computes elapsed days, tolerates garbage",
          days_between("2026-07-05", "2026-08-04") == 30
          and days_between(None, "2026-07-05") is None
          and days_between("not-a-date", "2026-07-05") is None)

    # -- ADHERENCE: the funnel must COUNT the abandoned node, never drop it --
    # This is the whole point. A funnel that silently omits "came due, never reviewed"
    # would report the founder's 0/7 as a clean sheet.
    def _adherence_counts_the_abandoned(h):
        _add_ab()
        # encode both on day 0; `good` books a review a few days out
        _capture(cmd_rate, _ns(topic="t", node="a", rating="good", grade="recalled",
                               kind="encode", production="x"))
        _capture(cmd_rate, _ns(topic="t", node="b", rating="good", grade="recalled",
                               kind="encode", production="x"))
        os.environ["ENGRAM_TODAY"] = "2026-08-06"      # both now long past due
        ad = _capture_json(cmd_adherence, _ns())
        lc = ad["loop_closure"]
        # nothing reviewed: 2 came due, 0 done, rate 0.0 — and it must SAY so
        never = (lc["encoded_past_due"] == 2 and lc["first_review_done"] == 0
                 and lc["rate"] == 0.0 and "NEVER CLOSED" in lc["read"])
        # now review one of them; the funnel must move to 1/2
        _capture(cmd_rate, _ns(topic="t", node="a", rating="good", grade="recalled",
                               kind="review", production="x"))
        lc2 = _capture_json(cmd_adherence, _ns())["loop_closure"]
        moved = (lc2["encoded_past_due"] == 2 and lc2["first_review_done"] == 1
                 and lc2["rate"] == 0.5)
        os.environ["ENGRAM_TODAY"] = "2026-07-06"
        return never and moved
    check("adherence: loop_closure counts came-due-and-abandoned (0/2 -> 1/2)",
          fresh(_adherence_counts_the_abandoned))

    # -- a node encoded but NOT yet due must not be counted as a missed close --
    def _adherence_ignores_not_yet_due(h):
        _add_ab()
        _capture(cmd_rate, _ns(topic="t", node="a", rating="easy", grade="recalled",
                               kind="encode", production="x"))   # easy -> far-out due date
        lc = _capture_json(cmd_adherence, _ns())["loop_closure"]
        return lc["encoded_past_due"] == 0 and lc["rate"] is None and "not been tested" in lc["read"]
    check("adherence: a not-yet-due node is not a missed close",
          fresh(_adherence_ignores_not_yet_due))

    # -- RETENTION: the north star, bucketed by elapsed days since ENCODE --
    def _retention_buckets(h):
        _add_ab()
        _capture(cmd_rate, _ns(topic="t", node="a", rating="good", grade="recalled",
                               kind="encode", production="x"))       # day 0 = 2026-07-06
        os.environ["ENGRAM_TODAY"] = "2026-07-13"                    # +7d -> "7d" bucket
        _capture(cmd_rate, _ns(topic="t", node="a", rating="good", grade="recalled",
                               kind="review", production="x"))
        os.environ["ENGRAM_TODAY"] = "2026-08-05"                    # +30d -> "30d" bucket
        _capture(cmd_rate, _ns(topic="t", node="a", rating="again", grade="lapsed",
                               kind="review", production="x"))
        r = _capture_json(cmd_retention, _ns())
        os.environ["ENGRAM_TODAY"] = "2026-07-06"
        b7, b30 = r["buckets"]["7d"], r["buckets"]["30d"]
        return (b7["n"] == 1 and b7["recalled"] == 1 and b7["rate"] == 1.0
                and b30["n"] == 1 and b30["lapsed"] == 1 and b30["rate"] == 0.0
                and "30-day recall 0%" in r["read"])
    check("retention: reviews bucket by days-since-encode (7d recalled, 30d lapsed)",
          fresh(_retention_buckets))

    # -- THE BUCKETS MUST PARTITION [0, inf): no review is EVER silently dropped --
    # The first cut of this used disjoint windows (5-10/25-40/80-110) and a live test caught a
    # real day-11 review vanishing into a gap — `retention` reported "no reviews yet" with a
    # review sitting on disk. A metric that quietly discards evidence is worse than no metric.
    # This check sweeps every elapsed day across the whole range and demands full coverage.
    def _retention_partitions(h):
        _add_ab()
        _capture(cmd_rate, _ns(topic="t", node="a", rating="good", grade="recalled",
                               kind="encode", production="x"))       # day 0
        base = date(2026, 7, 6)
        days = [0, 1, 3, 4, 5, 9, 11, 14, 15, 20, 30, 45, 59, 60, 75, 100, 179, 180, 400]
        for d in days:                                   # every one must land somewhere
            os.environ["ENGRAM_TODAY"] = (base + timedelta(days=d)).isoformat()
            _capture(cmd_rate, _ns(topic="t", node="a", rating="good", grade="recalled",
                                   kind="review", production="x"))
        r = _capture_json(cmd_retention, _ns())
        os.environ["ENGRAM_TODAY"] = "2026-07-06"
        cov = r["coverage"]
        return (cov["reviews_total"] == len(days)
                and cov["reviews_bucketed"] == len(days)     # ← the day-11 bug would fail here
                and cov["complete"] is True)
    check("retention buckets partition [0,inf): every review lands in exactly one (none dropped)",
          fresh(_retention_partitions))

    # -- `early` (0-3d) is reported but NEVER pooled into a retention claim --
    def _early_not_pooled(h):
        _add_ab()
        _capture(cmd_rate, _ns(topic="t", node="a", rating="good", grade="recalled",
                               kind="encode", production="x"))
        os.environ["ENGRAM_TODAY"] = "2026-07-08"            # +2d: still encoding, not retention
        _capture(cmd_rate, _ns(topic="t", node="a", rating="good", grade="recalled",
                               kind="review", production="x"))
        r = _capture_json(cmd_retention, _ns())
        os.environ["ENGRAM_TODAY"] = "2026-07-06"
        return (r["buckets"]["early"]["n"] == 1 and r["buckets"]["30d"]["n"] == 0
                and "none yet at the 30-day mark" in r["read"])
    check("retention: a sub-4-day retrieval counts as `early`, never as retention",
          fresh(_early_not_pooled))

    # -- RETENTION: the honest denominator. THE anti-survivorship-bias guard. --
    # A retention figure computed only over completed reviews drops exactly the concepts
    # the learner abandoned. This check exists so that can never silently ship.
    def _retention_unmeasured(h):
        _add_ab()
        _capture(cmd_rate, _ns(topic="t", node="a", rating="good", grade="recalled",
                               kind="encode", production="x"))
        os.environ["ENGRAM_TODAY"] = "2026-08-06"       # came due, never reviewed
        r = _capture_json(cmd_retention, _ns())
        os.environ["ENGRAM_TODAY"] = "2026-07-06"
        u = r["unmeasured"]
        return (u["past_due_now"] == 1 and u["never_reviewed"] == 1
                and 0.0 < u["projected_recall_now"] < 1.0     # real FSRS projection
                and "survivorship" in u["note"]
                and "past due and unretrieved" in r["read"])
    check("retention: unmeasured block counts past-due-never-reviewed (no survivorship bias)",
          fresh(_retention_unmeasured))

    # -- a reviewed node leaves the unmeasured pool (it is measured, not stale) --
    def _retention_unmeasured_clears(h):
        _add_ab()
        _capture(cmd_rate, _ns(topic="t", node="a", rating="good", grade="recalled",
                               kind="encode", production="x"))
        os.environ["ENGRAM_TODAY"] = "2026-08-06"
        _capture(cmd_rate, _ns(topic="t", node="a", rating="good", grade="recalled",
                               kind="review", production="x"))
        r = _capture_json(cmd_retention, _ns())
        os.environ["ENGRAM_TODAY"] = "2026-07-06"
        return r["unmeasured"]["past_due_now"] == 0
    check("retention: a reviewed node leaves the unmeasured pool",
          fresh(_retention_unmeasured_clears))

    # -- DECAY: reviewing today must beat not reviewing, in real FSRS numbers --
    # Time must pass first. A same-day review buys NOTHING (next check pins this): with
    # elapsed=0, retrievability is 1.0, so FSRS's prediction-error term exp(w*(1-r))-1
    # collapses to zero and stability does not grow. That is not a bug — it is the spacing
    # effect, in the arithmetic. The decay pitch is only ever honest once a memory has aged.
    def _decay(h):
        _add_ab()
        _capture(cmd_rate, _ns(topic="t", node="a", rating="good", grade="recalled",
                               kind="encode", production="x"))     # day 0, s ~ 3.71
        os.environ["ENGRAM_TODAY"] = "2026-07-12"                  # six days later, like the founder
        d = _capture_json(cmd_decay, _ns(topic="t", horizon=30))
        os.environ["ENGRAM_TODAY"] = "2026-07-06"
        no, yes = d["at_horizon_no_review"], d["at_horizon_if_reviewed_today"]
        return (d["encoded"] == 1
                and yes["expected_alive"] > no["expected_alive"]   # the whole point
                and d["saved_by_reviewing_today"] > 0
                and 0.0 < no["mean_recall"] < 1.0
                and d["nodes"][0]["s_if_reviewed"] > d["nodes"][0]["s"])
    check("decay: reviewing an aged memory today beats not reviewing (FSRS, not rhetoric)",
          fresh(_decay))

    # -- the spacing effect, asserted: a same-day review adds no stability --
    # (Pins the reason `decay` is honest only after time passes, and guards against anyone
    # "fixing" the zero-gain case by inventing growth FSRS does not license.)
    check("same-day review buys no stability (r=1 -> no prediction error -> no growth)",
          approx(next_stability_recall(5.0, 10.0, 1.0, 3), 10.0, 0.001))

    # -- decay is silent about nodes that were never encoded (nothing to lose) --
    def _decay_empty(h):
        _add_ab()
        d = _capture_json(cmd_decay, _ns(topic="t", horizon=30))
        return d["encoded"] == 0 and "nothing to lose" in d["read"]
    # -- decay with NOTHING DUE must not read as "reviewing is pointless" (v0.6.3) --
    # Nothing due -> the benefit arm is correctly identical to the do-nothing arm, and v0.6.2
    # reported "a difference of 0.0". Arithmetically true; a learner reads it as "reviewing
    # buys me nothing", which is the opposite of the truth. Found by the §5.6 USER SESSION —
    # no test caught it, because no test reads the sentence as a human.
    def _decay_nothing_due(h):
        _add_ab()
        _capture(cmd_rate, _ns(topic="t", node="a", rating="easy", grade="recalled",
                               kind="encode", production="x"))     # easy -> due far out
        d = _capture_json(cmd_decay, _ns(topic="t", horizon=30))
        return (d["due_now"] == 0
                and "nothing to save today" in d["read"]
                and "difference of 0.0" not in d["read"]
                and "brings each one back" in d["read"])   # says what the schedule IS for
    check("decay with nothing due says 'nothing to save today', not 'a difference of 0.0'",
          fresh(_decay_nothing_due))
    check("decay: an unencoded topic has nothing to lose", fresh(_decay_empty))

    # ================================================== THE METHOD (v0.9)
    # `experiment assign` was ROUND-ROBIN, unstratified, unpowered — and its verdict was written
    # by the MODEL. A confounded, unpowered trial settled by narration is not evidence; it is a
    # vibe with a JSON file.

    def _exp_topic(n=36, thresh=lambda i: i % 2 == 0):
        nodes = {"n%02d" % i: {"claim": "c", "probe": "p", "rubric": ["r"],
                               "threshold": thresh(i),
                               "viz": {"affordance": "manip" if thresh(i) else "none"}}
                 for i in range(n)}
        pth = p("payload.json")
        write_json(pth, {"topic": "m", "title": "M", "order": sorted(nodes), "nodes": nodes})
        _capture(cmd_add_topic, _ns(file=pth, replace=False))
        return sorted(nodes)

    def _exp_start(seed="S1", strat=("threshold",), mpa=None, arms=("A", "B")):
        d = {"question": "q", "arms": list(arms), "metric": "first_review_recall",
             "seed": seed, "stratify_by": list(strat)}
        if mpa is not None:
            d["min_per_arm"] = mpa
        return _capture_json(cmd_experiment, _ns(action="start", json=json.dumps(d), file=None))

    def _exp_assign_all(ids):
        return {nid: _capture_json(cmd_experiment,
                                   _ns(action="assign", topic="m", node=nid,
                                       json=None, file=None, id=None, verdict=None))
                for nid in ids}

    # -- assignment is RANDOMIZED (not round-robin) AND reproducible from the seed --
    def _assignment_is_randomized_and_reproducible(h):
        ids = _exp_topic(24)
        _exp_start(seed="S1")
        a1 = _exp_assign_all(ids)
        seq = [a1[n]["arm"] for n in ids]
        # ROUND-ROBIN would be strict alternation within the assignment ORDER. Randomized is not.
        strict_alternation = all(seq[i] != seq[i + 1] for i in range(len(seq) - 1))
        # …and the SAME seed must reproduce the SAME arms, exactly (an assignment nobody can
        # recompute is not an assignment; it is an anecdote)
        def again(_h):
            ids2 = _exp_topic(24)
            _exp_start(seed="S1")
            return [_exp_assign_all(ids2)[n]["arm"] for n in ids2]
        same_seed = fresh(again)()
        def other(_h):
            ids3 = _exp_topic(24)
            _exp_start(seed="DIFFERENT")
            return [_exp_assign_all(ids3)[n]["arm"] for n in ids3]
        diff_seed = fresh(other)()
        return (not strict_alternation            # NOT round-robin…
                and seq == same_seed              # …but fully reproducible from the seed…
                and seq != diff_seed              # …and a different seed gives a different draw
                and all(a["reproducible"] for a in a1.values()))
    check("experiment assignment is RANDOMIZED (not round-robin) and reproducible from the seed",
          fresh(_assignment_is_randomized_and_reproducible))

    # -- STRATIFIED: arms balance WITHIN each stratum, which is what kills the confound --
    # docs/06 open-Q2: explorables are routed to the hardest concepts ON PURPOSE, so an
    # unstratified comparison carries the MATERIAL as well as the medium. The doc disclosed the
    # confound honestly. It did not fix it. This does.
    def _stratification_balances_within_strata(h):
        ids = _exp_topic(36)
        _exp_start(seed="S2", strat=("threshold", "viz.affordance"))
        a = _exp_assign_all(ids)
        bal = {}
        for nid, r in a.items():
            bal.setdefault(r["stratum"], {}).setdefault(r["arm"], 0)
            bal[r["stratum"]][r["arm"]] += 1
        return (len(bal) == 2                                   # two real strata…
                and all(len(c) == 2 and abs(c["A"] - c["B"]) <= 1   # …each balanced to within 1
                        for c in bal.values())
                and all("threshold=" in s and "viz.affordance=" in s for s in bal))
    check("experiment assignment is STRATIFIED — arms balance WITHIN each stratum (kills the confound)",
          fresh(_stratification_balances_within_strata))

    # -- an arm NEVER moves under a node: re-assigning returns the same arm --
    def _arms_never_move(h):
        ids = _exp_topic(8)
        _exp_start(seed="S3")
        first = _exp_assign_all(ids)
        second = _exp_assign_all(ids)
        return (all(first[n]["arm"] == second[n]["arm"] for n in ids)
                and all("already assigned" in (second[n].get("note") or "") for n in ids)
                and len(_capture_json(cmd_experiment, _ns(action="list", json=None, file=None,
                                                          id=None, topic=None, node=None,
                                                          verdict=None))[0]["assignments"]) == 8)
    check("an arm never moves under a node (re-assign returns the same arm, once)",
          fresh(_arms_never_move))

    # -- ⚠ THE ENGINE COMPUTES THE VERDICT. The model narrates it. --
    # Until v0.9, `experiment settle --verdict "derivation-first won!"` wrote whatever the model
    # said straight into the log. That is a direct violation of invariant #2 (the engine owns
    # every number) in the ONE command whose entire purpose is a number nobody may make up.
    def _engine_owns_the_verdict(h):
        ids = _exp_topic(4)
        x = _exp_start(seed="S4", mpa=2)
        _exp_assign_all(ids)
        try:
            _capture(cmd_experiment, _ns(action="settle", id=x["id"], verdict="derivation won!",
                                         json=None, file=None, topic=None, node=None))
            return False                       # it accepted a narrated verdict
        except SystemExit:
            pass
        exps = _capture_json(cmd_experiment, _ns(action="list", json=None, file=None, id=None,
                                                 topic=None, node=None, verdict=None))
        return exps[0]["status"] == "active" and exps[0]["verdict"] is None  # nothing was written
    check("THE ENGINE OWNS THE VERDICT: `settle --verdict` is REFUSED (invariant #2)",
          fresh(_engine_owns_the_verdict))

    # -- UNDERPOWERED reads `underpowered`, and says what that is NOT --
    # 20 nodes -> 10 per arm. Under the shipped floor (15) that is UNDERPOWERED; under the old
    # floor (6) it would be powered — so this fixture ISOLATES the floor. Six nodes would have
    # read `underpowered` under either, and the check would have proved nothing (§4.5: ask what
    # ELSE would make this assertion true).
    def _underpowered_refuses_to_claim(h):
        ids = _exp_topic(20)
        x = _exp_start(seed="S5")               # default min_per_arm = 15
        _exp_assign_all(ids)
        for nid in ids:
            _capture(cmd_rate, _ns(topic="m", node=nid, rating="good", grade="recalled",
                                   kind="encode", production="x"))
        os.environ["ENGRAM_TODAY"] = "2026-08-06"
        for nid in ids:
            _capture(cmd_rate, _ns(topic="m", node=nid, rating="good", grade="recalled",
                                   kind="review", production="y"))
        v = _capture_json(cmd_experiment, _ns(action="settle", id=x["id"], verdict=None,
                                              json=None, file=None, topic=None, node=None))
        return (v["powered"] is False and v["min_per_arm"] == EXPERIMENT_MIN_PER_ARM
                and "UNDERPOWERED" in v["read"]
                and "ABSENCE of a result" in v["read"]   # …and says what that is NOT
                and v["leader"] is not None)             # it still reports the raw numbers
    check("an UNDERPOWERED experiment reads `underpowered` — an absence of a result, not a null one",
          fresh(_underpowered_refuses_to_claim))

    # -- ⚠ THE POWER FLOOR IS THE ENGINE'S, NOT THE PAYLOAD'S (v1.0.1, v0.9 review finding #1) --
    # A design that declared `min_per_arm: 6` certified as `powered: true` and read "suggestive" on
    # 6 data points per arm — the exact underpowered regime v0.9 exists to kill, bought with one
    # payload field, while the skill promised the opposite. `powered` now gates on max(design,
    # engine floor). Fixture: 12 nodes, `min_per_arm: 6` -> 6/arm, arm A wins every time (clean
    # separation, p < 0.05) -> and it must STILL read underpowered, because 6 < 15.
    def _power_floor_cannot_be_bought_down(h):
        ids = _exp_topic(12)
        x = _exp_start(seed="SF", mpa=6)                 # a SLOPPY design, below the floor
        low = x["min_per_arm"] == 6 and "power_note" in x
        arms = {n: r["arm"] for n, r in _exp_assign_all(ids).items()}
        for nid in ids:
            _capture(cmd_rate, _ns(topic="m", node=nid, rating="good", grade="recalled",
                                   kind="encode", production="x"))
        os.environ["ENGRAM_TODAY"] = "2026-08-06"
        for nid in ids:                                  # arm A wins every time -> clean, p<0.05
            win = arms[nid] == "A"
            _capture(cmd_rate, _ns(topic="m", node=nid, rating="good" if win else "again",
                                   grade="recalled" if win else "lapsed",
                                   kind="review", production="y"))
        v = _capture_json(cmd_experiment, _ns(action="settle", id=x["id"], verdict=None,
                                              json=None, file=None, topic=None, node=None))
        return (low                                      # the design DID ask for 6…
                and v["min_per_arm"] == EXPERIMENT_MIN_PER_ARM   # …but the verdict uses 15
                and v["powered"] is False                # …so 6/arm is UNDERPOWERED, as it must be
                and "UNDERPOWERED" in v["read"]
                and (v["p_value"] is None or v["p_value"] < 0.05))   # even with a clean separation
    check("⚠ the power floor is the ENGINE's, not the payload's (min_per_arm:6 still reads underpowered)",
          fresh(_power_floor_cannot_be_bought_down))

    # -- ⚠ OPTIONAL-STOPPING GUARD: an experiment is analysed ONCE (v0.9 review finding #3) --
    def _settle_refuses_a_second_analysis(h):
        ids = _exp_topic(4)
        x = _exp_start(seed="SS", mpa=2)
        _exp_assign_all(ids)
        for nid in ids:
            _capture(cmd_rate, _ns(topic="m", node=nid, rating="good", grade="recalled",
                                   kind="encode", production="x"))
        os.environ["ENGRAM_TODAY"] = "2026-08-06"
        for nid in ids:
            _capture(cmd_rate, _ns(topic="m", node=nid, rating="good", grade="recalled",
                                   kind="review", production="y"))
        first = _capture_json(cmd_experiment, _ns(action="settle", id=x["id"], verdict=None,
                                                  json=None, file=None, topic=None, node=None))
        first_p = first["p_value"]
        try:
            _capture(cmd_experiment, _ns(action="settle", id=x["id"], verdict=None,
                                         json=None, file=None, topic=None, node=None))
            return False                       # a second analysis was accepted: optional stopping
        except SystemExit:
            pass
        # …and the first verdict is untouched — a refused re-settle cannot corrupt the record
        exps = _capture_json(cmd_experiment, _ns(action="list", json=None, file=None, id=None,
                                                 topic=None, node=None, verdict=None))
        return exps[0]["status"] == "settled" and exps[0]["verdict"]["p_value"] == first_p
    check("⚠ `settle` refuses a SECOND analysis (optional stopping ~triples the false-positive rate)",
          fresh(_settle_refuses_a_second_analysis))

    # -- Finding #5: a hand-edited un-scoreable receipt DEGRADES the settle, never bricks it --
    def _settle_survives_a_garbage_outcome(h):
        ids = _exp_topic(4)
        x = _exp_start(seed="SG", mpa=2)
        _exp_assign_all(ids)
        for nid in ids:
            _capture(cmd_rate, _ns(topic="m", node=nid, rating="good", grade="recalled",
                                   kind="encode", production="x"))
        os.environ["ENGRAM_TODAY"] = "2026-08-06"
        # give three nodes a real first review, and leave the FOURTH's only review a hand-forged
        # un-scoreable one — so it becomes that node's `first review` and `_outcome` returns None.
        for nid in ids[:3]:
            _capture(cmd_rate, _ns(topic="m", node=nid, rating="good", grade="recalled",
                                   kind="review", production="y"))
        append_jsonl(p("receipts", "m.jsonl"), {
            "id": "hand", "ts": "2026-08-07", "topic": "m", "node": ids[3],
            "kind": "review", "rating": "excellent", "grade": None})   # truthy non-rating, no grade
        _RECEIPTS_CACHE.clear()
        # confirm the fixture actually produces the None outcome the fix must survive (or the
        # check is theatre — §4.5). If a future change stops _outcome from returning None here,
        # this fails loudly rather than passing vacuously.
        groups, _ = _experiment_outcomes(next(e2 for e2 in
                     _as_list(read_json(p("experiments.json"), [])) if e2.get("id") == x["id"]))
        exercised = any(v is None for vs in groups.values() for v in vs)
        v = _capture_json(cmd_experiment, _ns(action="settle", id=x["id"], verdict=None,
                                              json=None, file=None, topic=None, node=None))
        return exercised and isinstance(v, dict) and "read" in v   # RETURNED, did not TypeError
    check("a settle DEGRADES on an un-scoreable hand-edited receipt (never a TypeError brick)",
          fresh(_settle_survives_a_garbage_outcome))

    # -- Finding #2: the bootstrap CI is on the SIGNED two-arm diff, and NONE for 3+ arms --
    def _bootstrap_ci_is_honest(_h=None):
        # three IDENTICAL arms: observed spread 0.000. The old code returned a CI like [0.03, 0.37]
        # that EXCLUDED its own point estimate. The new code returns None for k != 2.
        three = _bootstrap_ci({"A": [1.0, 0.0] * 8, "B": [1.0, 0.0] * 8, "C": [1.0, 0.0] * 8}, "s")
        # two arms with a real difference: a SIGNED CI whose sign is meaningful
        two = _bootstrap_ci({"A": [1.0] * 15, "B": [0.0] * 15}, "s")
        return (three is None                                   # k=3: no dishonest interval
                and isinstance(two, dict) and "of" in two       # k=2: a signed difference…
                and two["ci95"][0] > 0)                          # …and A>B is positive, correctly
    check("the bootstrap CI is a SIGNED two-arm difference (None for 3+ arms — never excludes its own effect)",
          _bootstrap_ci_is_honest)

    # -- Finding #4: `first_review_recall` means ONE thing across modality and the experiment --
    def _modality_and_experiment_agree_on_recall(h):
        # 15 nodes, all first-reviewed PARTIAL. modality used to score partial as 1.0; the
        # experiment scores it 0.5. Same metric name -> they must now agree.
        for i in range(MODALITY_MIN_N):
            _capture(cmd_rate, _ns(topic="t%d" % i if False else "t", node="n%d" % i,
                                   rating="hard", grade="partial", kind="encode",
                                   production="x")) if False else None
        # build one topic with 15 nodes, encode, then FIRST-review each as partial
        nodes = {"n%02d" % i: {"claim": "c", "probe": "p", "rubric": ["r"]}
                 for i in range(MODALITY_MIN_N)}
        write_json(p("payload.json"),
                   {"topic": "t", "title": "T", "order": sorted(nodes), "nodes": nodes})
        _capture(cmd_add_topic, _ns(file=p("payload.json"), replace=False))
        for nid in nodes:
            _capture(cmd_rate, _ns(topic="t", node=nid, rating="good", grade="recalled",
                                   kind="encode", production="x"))
        os.environ["ENGRAM_TODAY"] = "2026-08-06"
        for nid in nodes:
            _capture(cmd_rate, _ns(topic="t", node=nid, rating="hard", grade="partial",
                                   kind="review", production="y"))
        mod = _capture_json(cmd_stats, _ns())["modality"]
        # every node is dialogue-only (no artifact); partial -> 0.5, not 1.0
        return mod["dialogue"]["first_review_recall"] == 0.5 and mod["dialogue"]["n"] == MODALITY_MIN_N
    check("§4.8 Q1: `first_review_recall` scores partial as 0.5 in modality too (agrees with the experiment)",
          fresh(_modality_and_experiment_agree_on_recall))

    # -- modality DEGRADES on an un-scoreable receipt (v1.0.2 — the regression v1.0.1's own fix caused) --
    # v1.0.1 switched modality to `_outcome` (finding #4) and added the drop-guard to `settle`
    # (finding #5) — but NOT here, one function over. `0.0 += None` bricked `stats`, and therefore
    # /coach, on a hand-edited receipt. The verification review caught it, and the tell is that the
    # test gap mirrored the code gap: there was a settle degradation check and no modality one.
    def _modality_survives_un_scoreable_first_review(h):
        _add_ab()
        _capture(cmd_rate, _ns(topic="t", node="a", rating="good", grade="recalled",
                               kind="encode", production="x"))
        append_jsonl(p("receipts", "t.jsonl"), {         # a's un-scoreable FIRST review
            "id": "hand", "ts": "2026-07-20", "topic": "t", "node": "a",
            "kind": "review", "rating": "excellent", "grade": None})
        _RECEIPTS_CACHE.clear()
        exercised = _outcome({"rating": "excellent", "grade": None}) is None   # the fixture bites
        s = _capture_json(cmd_stats, _ns())              # must RETURN, not TypeError
        return exercised and isinstance(s, dict) and "modality" in s
    check("modality DEGRADES on an un-scoreable first review (stats/coach never brick)",
          fresh(_modality_survives_un_scoreable_first_review))

    # -- §5.5 THE INSTRUMENT GATE: does the ruler rank a REAL effect above NO effect? --
    # `experiment settle` CERTIFIES ("derivation-first won"). v0.7's gold set was an instrument
    # nobody tested and it turned out to rank a FOOLED grader above a CORRECT one. So: build a
    # world where an arm genuinely wins, and a world where nothing does, and demand the p-value
    # can tell them apart.
    def _experiment_instrument_is_monotone(_h=None):
        def world(effect):
            def go(h):
                # 32 nodes -> two strata of 16 -> 8 blocks of 2 per stratum -> exactly 16/16.
                # (30 gave 16/14, and one arm missed the power floor: block randomization only
                # balances to WITHIN a block, so an odd tail is a real, honest imbalance.)
                ids = _exp_topic(32)
                x = _exp_start(seed="S6", mpa=15)
                arms = {n: r["arm"] for n, r in _exp_assign_all(ids).items()}
                for nid in ids:
                    _capture(cmd_rate, _ns(topic="m", node=nid, rating="good", grade="recalled",
                                           kind="encode", production="x"))
                os.environ["ENGRAM_TODAY"] = "2026-08-06"
                for i, nid in enumerate(ids):
                    # arm A recalls; arm B lapses — but ONLY when there is a real effect
                    win = (arms[nid] == "A") if effect else (i % 2 == 0)
                    _capture(cmd_rate, _ns(topic="m", node=nid,
                                           rating="good" if win else "again",
                                           grade="recalled" if win else "lapsed",
                                           kind="review", production="y"))
                return _capture_json(cmd_experiment,
                                     _ns(action="settle", id=x["id"], verdict=None, json=None,
                                         file=None, topic=None, node=None))
            return fresh(go)()
        real = world(True)      # arm A genuinely wins
        null = world(False)     # outcome is independent of the arm
        return (real["powered"] and null["powered"]
                and real["p_value"] < 0.05 < null["p_value"]      # the ruler tells them apart
                and real["p_value"] < null["p_value"]
                and real["leader"] == "A" and real["effect_spread"] > null["effect_spread"]
                and "leads by" in real["read"]
                # …and the null world says "we cannot tell", NOT "they are the same"
                and "cannot tell" in null["read"] and "the same" in null["read"])
    check("§5.5 THE INSTRUMENT GATE: a REAL effect separates; NO effect reads 'we cannot tell'",
          _experiment_instrument_is_monotone)

    # -- the randomization test never claims p = 0 (add-one), and the design is PRE-REGISTERED --
    def _design_is_preregistered_and_p_is_honest(h):
        _exp_topic(4)
        x = _exp_start(seed="S7", mpa=2)
        low = x["min_per_arm"] == 2 and "power_note" in x and "BELOW" in x["power_note"]
        # p can never be 0: with 10k permutations, add-one bounds it at 1/(N+1)
        g = {"A": [1.0] * 20, "B": [0.0] * 20}          # the most separated data possible
        pv = _randomization_test(g, "seed")
        return (low and x["randomized"] is True and x["seed"] == "S7"
                and "randomization-test" in x["analysis"]
                and pv is not None and 0 < pv <= 1.0
                and pv == round(1.0 / (EXPERIMENT_PERMUTATIONS + 1), 4))
    check("the design is PRE-REGISTERED (seed+analysis recorded) and p is never 0 (add-one)",
          fresh(_design_is_preregistered_and_p_is_honest))

    # -- a hand-edited experiments.json must not brick `experiment status|list` --
    # 72 crashes in 600 fuzzed states, the FIRST time these sub-actions were fuzzed. They had
    # never been fuzzed because §4.7 enumerates COMMANDS from the dispatch table, and `experiment`
    # lives in `mutating` — so its READ sub-actions were invisible to the rule written to find
    # exactly this. A command with sub-actions has a read path per sub-action.
    def _experiment_reads_survive_garbage(h):
        write_json(p("experiments.json"), [
            {"id": "x1", "status": "active", "arms": 7},                    # arms as an int
            {"id": "x2", "status": "active"},                               # arms absent
            {"id": "x3", "status": "active", "arms": [{"unhashable": 1}, "A"],
             "min_per_arm": float("inf"),                                   # inf -> int() -> boom
             "assignments": [{"arm": ["list"], "stratum": {"d": 1}}, "not-a-dict"]},
            "not even an object",
        ])
        for ns in (_ns(action="status", id=None, json=None, file=None, topic=None,
                       node=None, verdict=None),
                   _ns(action="list", id=None, json=None, file=None, topic=None,
                       node=None, verdict=None)):
            _capture(cmd_experiment, ns)        # must RETURN, not raise
        # …and `stats` (which reads the active experiment's question) survives it too
        return _capture_json(cmd_stats, _ns()) is not None
    check("`experiment status|list` degrade on a type-corrupt experiments.json (never brick)",
          fresh(_experiment_reads_survive_garbage))

    # -- the v1.0.6 fuzz batch: three read paths that bricked on hand-editable garbage --
    def _artifact_list_survives_garbage_order(h):
        # `order` holding unhashables raised at `n in nodes` (engram.py:1396, shipped
        # since v0.x) — cmd_artifact hand-rolled the walk instead of using graph_order.
        # The registered node must SURVIVE the garbage around it, not just not-crash.
        write_json(p("graphs", "t.json"),
                   {"topic": "t", "order": ["a", ["un"], {"hash": 1}, 7, "ghost"],
                    "nodes": {"a": {"claim": "A", "probe": "a?"},
                              "b": {"claim": "B", "probe": "b?",
                                    "artifact": "artifacts/t/b.html"}}})
        got = _capture_json(cmd_artifact, _ns(action="list"))
        return [e.get("node") for e in got] == ["b"]
    check("`artifact list` survives unhashable entries in `order` (walks via graph_order)",
          fresh(_artifact_list_survives_garbage_order))

    def _misconception_list_survives_garbage(h):
        # a None entry raised at `it.get` — and the real entry beside it must still list.
        write_json(p("misconceptions.json"),
                   [None, 123, "loose", {"id": "m1", "topic": "t", "node": "a",
                                         "description": "real one", "status": "open"}])
        got = _capture_json(cmd_misconception, _ns(action="list"))
        return [m.get("id") for m in got] == ["m1"]
    check("`misconception list` degrades on non-dict entries (keeps the real ones)",
          fresh(_misconception_list_survives_garbage))

    def _report_survives_int_misconception_fields(h):
        # escape(int) raised inside the dashboard render; the gate (_open_misconceptions)
        # now coerces narrator-facing fields, so the garbage renders as text instead.
        write_json(p("misconceptions.json"),
                   [{"id": "m2", "topic": 123123, "node": None, "description": 424242,
                     "status": "open"}])
        out_path = os.path.join(h, "d.html")
        _capture(cmd_report, _ns(out=out_path, allow_outside=True))
        html = open(out_path, encoding="utf-8").read()
        return "Open misconceptions" in html and "424242" in html
    check("`report` renders int-typed misconception fields as text (never AttributeError)",
          fresh(_report_survives_int_misconception_fields))

    # ================================================== THE CLAIM (v0.8, corrected in v0.8.1)
    # `transfer_probe` was authored by the architect since v0.1 and read by NOTHING. v0.8.0 wired
    # it up — and shipped a capability metric that could not see the CAPSTONE, and a headline that
    # ranked a learner who had LOST every capability above one who had MASTERED every one.

    def _add_transfer_topic(tp="Apply it to your own GPS trace.", extra=None, n=2):
        nodes = {"a": {"claim": "C", "probe": "P", "rubric": ["r"], "transfer_probe": tp},
                 "b": {"claim": "C2", "probe": "P2", "rubric": ["r"], "transfer_probe": None,
                       "edges": {"requires": ["a"]}}}
        for i in range(2, n):
            nodes["n%d" % i] = {"claim": "C", "probe": "P", "rubric": ["r"],
                                "transfer_probe": "TP%d" % i}
        if extra:
            nodes.update(extra)
        pth = p("payload.json")
        write_json(pth, {"topic": "k", "title": "K", "order": sorted(nodes), "nodes": nodes})
        _capture(cmd_add_topic, _ns(file=pth, replace=False))

    def _mature(node="a"):
        """Encode, then three real RETRIEVALS across months -> s > 21d, 3 retrievals.

        The clock is reset to the encode date FIRST. Without it, maturing a second node left
        ENGRAM_TODAY at 2027 — so that node's ENCODE landed AFTER its reviews, its earliest
        receipt by `ts` was a review, and `_by_node` (correctly) treated that review as the
        encoding event. The engine then (correctly) refused the transfer for want of a third
        retrieval. A fixture that scrambles a node's history is not a fixture; it is a different
        test, and the guard catching it was the guard working."""
        os.environ["ENGRAM_TODAY"] = "2026-07-06"
        _capture(cmd_rate, _ns(topic="k", node=node, rating="good", grade="recalled",
                               kind="encode", production="x"))
        for d in ("2026-08-06", "2026-10-06", "2027-01-06"):
            os.environ["ENGRAM_TODAY"] = d
            _capture(cmd_rate, _ns(topic="k", node=node, rating="easy", grade="recalled",
                                   kind="review", production="z"))
        os.environ["ENGRAM_TODAY"] = "2027-04-06"

    def _probe(node="a", grade="recalled", rating="good", day=None):
        if day:
            os.environ["ENGRAM_TODAY"] = day
        _capture(cmd_rate, _ns(topic="k", node=node, rating=rating, grade=grade,
                               kind="transfer", production="p"))

    # -- an IMMATURE node is never asked the harder question --
    def _transfer_only_mature(h):
        _add_transfer_topic()
        _capture(cmd_rate, _ns(topic="k", node="a", rating="good", grade="recalled",
                               kind="encode", production="x"))     # encoded, s tiny, 0 retrievals
        t0 = _capture_json(cmd_transfer, _ns(topic="k", limit=None))
        _mature()
        t1 = _capture_json(cmd_transfer, _ns(topic="k", limit=None))
        return (t0["n"] == 0 and "mature enough" in t0["read"]
                and t1["n"] == 1 and t1["items"][0]["id"] == "a"
                and as_number(t1["items"][0]["s"]) > TRANSFER_MATURE_S)
    check("transfer serves ONLY mature nodes (s > 21d, 3+ RETRIEVALS) — never a fresh encode",
          fresh(_transfer_only_mature))

    # -- #10: `reps` counted the ENCODE, so an advertised 3 retrievals delivered 2 --
    def _maturity_counts_retrievals_not_reps(h):
        _add_transfer_topic()
        _capture(cmd_rate, _ns(topic="k", node="a", rating="good", grade="recalled",
                               kind="encode", production="x"))          # reps=1, retrievals=0
        for d in ("2026-08-06", "2026-10-06"):                          # reps=3, retrievals=2
            os.environ["ENGRAM_TODAY"] = d
            _capture(cmd_rate, _ns(topic="k", node="a", rating="easy", grade="recalled",
                                   kind="review", production="z"))
        os.environ["ENGRAM_TODAY"] = "2027-01-06"
        two = _capture_json(cmd_transfer, _ns(topic="k", limit=None))["n"]   # reps==3, but 2 real
        _capture(cmd_rate, _ns(topic="k", node="a", rating="easy", grade="recalled",
                               kind="review", production="z"))               # retrievals=3
        os.environ["ENGRAM_TODAY"] = "2027-04-06"
        three = _capture_json(cmd_transfer, _ns(topic="k", limit=None))["n"]
        return two == 0 and three == 1     # the advertised 3 retrievals are delivered
    check("maturity counts RETRIEVALS from the receipt log, not `fsrs.reps` (the encode is not one)",
          fresh(_maturity_counts_retrievals_not_reps))

    # -- a node with a NULL transfer_probe is never selected, however mature --
    def _null_probe_never_selected(h):
        _add_transfer_topic(tp=None)          # node `a` now has NO transfer probe
        _mature()
        t = _capture_json(cmd_transfer, _ns(topic="k", limit=None))
        st = _capture_json(cmd_stats, _ns())["transfer"]
        # …and it is not in the CENSUS either. Only the capstone (which IS a transfer question)
        # is counted, so the census reads exactly 1.
        return t["n"] == 0 and sum(st["states"].values()) == 1 and st["states"]["untested"] == 1
    check("a node with a null transfer_probe is NEVER selected (there is nothing to ask)",
          fresh(_null_probe_never_selected))

    # -- ⚠ FINDING #1: THE CAPSTONE'S TRANSFER RECEIPT WAS DEAD DATA --
    # The capstone is built ONCE, so its transfer receipt is its FIRST receipt — swallowed by the
    # v0.6.1 "a node's first receipt is its encoding event" rule. AND the census skipped it,
    # because it is minted with `transfer_probe: None` ("the capstone IS the transfer probe").
    # So the learner built the thing, passed it, and `stats.transfer` read **"NO CAPABILITY HAS
    # EVER BEEN MEASURED"** while the receipt sat on disk. v0.8's own thesis, one level up.
    def _capstone_transfer_is_counted(h):
        _add_transfer_topic()
        for nid in ("a", "b"):
            _capture(cmd_rate, _ns(topic="k", node=nid, rating="good", grade="recalled",
                                   kind="encode", production="x"))
        served = _capture_json(cmd_next, _ns(topic="k"))["id"]
        _probe(node=CAPSTONE_ID)                                   # BUILD IT, and pass
        st = _capture_json(cmd_stats, _ns())["transfer"]
        node = load_graph("k")["nodes"][CAPSTONE_ID]
        return (served == CAPSTONE_ID
                and st["n"] == 1 and st["fired"] == 1              # the receipt is SEEN…
                and st["owned"] == 1 and st["tested"] == 1         # …and it counts as owned…
                and st["states"]["applied"] == 1                   # …in the census…
                and node["transfer"]["state"] == "applied"         # …and the graph agrees.
                and "NO CAPABILITY" not in st["read"])
    check("FINDING #1: a passed CAPSTONE is COUNTED (its first receipt IS its transfer)",
          fresh(_capstone_transfer_is_counted))

    def _failed_capstone_is_counted(h):
        _add_transfer_topic()
        for nid in ("a", "b"):
            _capture(cmd_rate, _ns(topic="k", node=nid, rating="good", grade="recalled",
                                   kind="encode", production="x"))
        _probe(node=CAPSTONE_ID, grade="lapsed", rating="again")   # built it; it did NOT work
        st = _capture_json(cmd_stats, _ns())["transfer"]
        # a FAILED capstone is the single most diagnostic event in the system ("I could not
        # actually use this topic"), and v0.8.0 discarded it entirely.
        return (st["n"] == 1 and st["lapsed"] == 1
                and st["owned"] == 0 and st["tested"] == 1
                and st["states"]["probed"] == 1)
    check("FINDING #1b: a FAILED capstone is counted too (the most diagnostic event in the system)",
          fresh(_failed_capstone_is_counted))

    # -- ⚠ FINDING #2, AND IT IS THE INSTRUMENT GATE ITSELF --
    # v0.8.0's `rate_fired` pooled the LIFETIME log and was ORDER-BLIND, while `state` was
    # deliberately latest-evidence. Result: a learner who had LOST every capability scored
    # **2x** one who had MASTERED every one, and the dashboard put `fired 67%` next to `owned 0`.
    # The shipped §5.5 gate missed it because it varied the BAR and never the POPULATION —
    # it tested the subject, not the ruler. Exactly the v0.7 lesson, one release later.
    def _instrument_ranks_current_ownership(_h=None):
        def learner(script):
            def go(h):
                _add_transfer_topic(n=7)
                for nid in ("a", "n2", "n3", "n4", "n5", "n6"):
                    _mature(nid)
                day = 2027
                for grade, rating in script:                # probes 1 year apart (past cooldown)
                    for nid in ("a", "n2", "n3", "n4", "n5", "n6"):
                        _probe(nid, grade, rating, day="%d-04-06" % day)
                    day += 1
                return _capture_json(cmd_stats, _ns())["transfer"]
            return fresh(go)()
        L, R = ("lapsed", "again"), ("recalled", "good")
        improving = learner([L, L, R])       # failed twice, then MASTERED all six
        declining = learner([R, R, L])       # passed twice, then LOST all six
        return (
            # the truth, from `state` — which was always right
            improving["states"]["applied"] == 6 and declining["states"]["applied"] == 0
            # THE HEADLINE NOW AGREES WITH IT (v0.8.0 had this backwards, by 2x)
            and improving["owned_rate"] == 1.0 and declining["owned_rate"] == 0.0
            and improving["owned_rate"] > declining["owned_rate"]
            # the lifetime history is still reported — and it still says the OPPOSITE…
            and declining["probe_fire_rate"] > improving["probe_fire_rate"]
            # …which is fine, because it is NAMED as history and is not the headline
            and "you currently OWN 100%" in improving["read"]
            and "you currently OWN 0%" in declining["read"])
    check("§5.5 INSTRUMENT GATE: the headline ranks CURRENT ownership (a lost capability is not owned)",
          _instrument_ranks_current_ownership)

    # -- THE STATE MACHINE: untested -> probed -> applied, from the LATEST evidence --
    def _transfer_state_machine(h):
        _add_transfer_topic()
        _mature()
        s0 = _capture_json(cmd_stats, _ns())["transfer"]["states"]
        _probe(grade="partial", rating="hard")
        s1 = _capture_json(cmd_stats, _ns())["transfer"]["states"]
        n1 = load_graph("k")["nodes"]["a"]["transfer"]
        _probe(grade="recalled", rating="good", day="2027-08-06")
        s2 = _capture_json(cmd_stats, _ns())["transfer"]["states"]
        n2 = load_graph("k")["nodes"]["a"]["transfer"]
        # …and it can be LOST again: a capability that fails now is not currently owned
        _probe(grade="lapsed", rating="again", day="2028-01-06")
        s3 = _capture_json(cmd_stats, _ns())["transfer"]["states"]
        # (the capstone is always in the census as `untested` — nothing has built it)
        return (s0 == {"untested": 2, "probed": 0, "applied": 0}
                and s1 == {"untested": 1, "probed": 1, "applied": 0} and n1["receipts"] == 1
                and s2 == {"untested": 1, "probed": 0, "applied": 1} and n2["receipts"] == 2
                and n2["state"] == "applied" and n2["last"] == "2027-08-06"
                and s3 == {"untested": 1, "probed": 1, "applied": 0})   # lost, honestly
    check("transfer state machine: untested -> probed -> applied, from the LATEST evidence (and it can be lost)",
          fresh(_transfer_state_machine))

    # -- ⚠ FINDING #11: an UNDATED receipt must not become the LATEST evidence --
    # `_sort_key` sorts a garbage-`ts` receipt LAST (so it can never win day-0) — and taking
    # `ts[-1]` therefore handed it the crown. A hand-edited undated `recalled` flipped a node to
    # `applied` over a real, dated `lapsed`. The v0.6 fix and the v0.8 rule collided, and they
    # collided in the flattering direction.
    def _undated_receipt_never_wins(h):
        _add_transfer_topic()
        _mature()
        _probe(grade="lapsed", rating="again")                       # a REAL, dated failure
        before = _capture_json(cmd_stats, _ns())["transfer"]["states"]
        append_jsonl(p("receipts", "k.jsonl"), {                     # a hand-edited undated pass
            "id": "hand", "ts": "not-a-date", "topic": "k", "node": "a",
            "kind": "transfer", "grade": "recalled", "rating": "good"})
        _RECEIPTS_CACHE.clear()
        after = _capture_json(cmd_stats, _ns())["transfer"]["states"]
        return (before["probed"] == 1 and before["applied"] == 0
                and after["applied"] == 0 and after["probed"] == 1)  # the undated one does NOT win
    check("FINDING #11: an UNDATED transfer receipt never becomes the latest evidence",
          fresh(_undated_receipt_never_wins))

    # -- ⚠ FINDING #4: A FAILED TRANSFER PROBE MUST NOT PUNISH THE MEMORY SCHEDULE --
    # v0.8 separated the three populations in the METRICS and pooled them in the SCHEDULER. One
    # failed probe deleted 97% of a mature memory's durability (s 443 -> 12), flipped it to
    # `learning`, counted a lapse, and dropped it below the transfer bar forever. It contradicted
    # THREE sentences the same release shipped, including `_transfer_ready`'s own docstring
    # warning about "a lapse the schedule then punishes — a fabricated setback".
    def _transfer_lapse_does_not_punish_memory(h):
        _add_transfer_topic()
        _mature()
        f0 = dict(_fsrs_of(load_graph("k")["nodes"]["a"]))
        st0 = load_graph("k")["nodes"]["a"]["state"]
        _probe(grade="lapsed", rating="again")                # the capability did NOT fire
        n = load_graph("k")["nodes"]["a"]
        f1 = _fsrs_of(n)
        r = [x for x in read_jsonl(p("receipts", "k.jsonl")) if x.get("kind") == "transfer"][-1]
        unpunished = (f1["s"] == f0["s"] and f1["due"] == f0["due"]           # schedule UNTOUCHED
                      and f1["lapses"] == f0["lapses"] and n["state"] == st0
                      and r["s_before"] == r["s_after"] == f0["s"]            # …and the receipt says so
                      and "schedule_unchanged" in r)
        # …and the transfer is still RECORDED as a failure. It is not swept under the rug.
        st = _capture_json(cmd_stats, _ns())["transfer"]
        # …and a SUCCESSFUL probe still strengthens the memory (applying an idea IS a retrieval)
        _probe(grade="recalled", rating="good", day="2027-08-06")
        f2 = _fsrs_of(load_graph("k")["nodes"]["a"])
        return (unpunished and st["lapsed"] == 1 and st["states"]["probed"] == 1
                and f2["s"] > f0["s"])
    check("FINDING #4: a FAILED transfer probe does NOT punish the memory schedule (a success still strengthens it)",
          fresh(_transfer_lapse_does_not_punish_memory))

    # -- ⚠ FINDING #6: the maturity bar at INGEST, not just at selection --
    def _immature_transfer_receipt_is_refused(h):
        _add_transfer_topic()
        _capture(cmd_rate, _ns(topic="k", node="a", rating="good", grade="recalled",
                               kind="encode", production="x"))     # encoded yesterday
        try:
            _probe()                                                # …certify it? No.
            return False
        except SystemExit:
            pass
        st = _capture_json(cmd_stats, _ns())["transfer"]
        return st["n"] == 0 and st["states"]["applied"] == 0
    check("FINDING #6: a TRANSFER receipt on an immature node is REFUSED at ingest (not just unserved)",
          fresh(_immature_transfer_receipt_is_refused))

    # -- ⚠ FINDING #9: no minimum-n floor. Every sibling metric has one. --
    def _transfer_has_a_floor(h):
        _add_transfer_topic(n=8)
        for nid in ("a", "n2", "n3", "n4", "n5", "n6", "n7"):
            _mature(nid)
        for i, nid in enumerate(("a", "n2", "n3", "n4")):        # 4 probes: BELOW the floor
            _probe(nid, day="2027-04-06")
        thin = _capture_json(cmd_stats, _ns())["transfer"]
        _probe("n5", day="2027-04-06")                            # the 5th: at the floor
        ok = _capture_json(cmd_stats, _ns())["transfer"]
        return (thin["insufficient_data"] is True
                and thin["owned_rate"] is None and thin["probe_fire_rate"] is None
                and "insufficient-data" in thin["read"]
                and thin["owned"] == 4                            # …but COUNTS are facts, always
                and ok["insufficient_data"] is False and ok["owned_rate"] == 1.0)
    check("FINDING #9: transfer has a minimum-n floor for its RATE (counts are facts; rates are not)",
          fresh(_transfer_has_a_floor))

    # -- ⚠ FINDING #7: calibration_encode was a RESIDUAL bucket and swallowed transfers --
    def _calibration_encode_excludes_transfer(h):
        _add_transfer_topic()
        _capture(cmd_rate, _ns(topic="k", node="a", rating="good", grade="recalled",
                               kind="encode", production="x", confidence=80))
        for d in ("2026-08-06", "2026-10-06", "2027-01-06"):
            os.environ["ENGRAM_TODAY"] = d
            _capture(cmd_rate, _ns(topic="k", node="a", rating="easy", grade="recalled",
                                   kind="review", production="z", confidence=70))
        os.environ["ENGRAM_TODAY"] = "2027-04-06"
        _capture(cmd_rate, _ns(topic="k", node="a", rating="again", grade="lapsed",
                               kind="transfer", production="p", confidence=90))
        s = _capture_json(cmd_stats, _ns())
        # transfer is where a learner is MOST overconfident (they know it; it doesn't fire) —
        # misattributing that to their ENCODING self-assessment makes /coach diagnose the wrong
        # faculty and prescribe the wrong fix.
        return (s["calibration_encode"]["n"] == 1                 # the encode. ONLY the encode.
                and s["calibration"]["n"] == 3                    # the reviews
                and s["calibration_transfer"]["n"] == 1)          # …and transfer, NAMED
    check("FINDING #7: calibration_encode excludes transfers (a residual bucket absorbs every new kind)",
          fresh(_calibration_encode_excludes_transfer))

    # -- NEVER POOLED: a transfer receipt must not touch retention, and retention must not eat it --
    def _transfer_is_never_pooled(h):
        _add_transfer_topic()
        _mature()                                        # 1 encode + 3 reviews
        _probe(grade="recalled", rating="good")
        _probe(grade="lapsed", rating="again", day="2027-08-06")
        s = _capture_json(cmd_stats, _ns())
        cov = s["retention"]["coverage"]
        return (s["reviews"] == 3                        # retention population: reviews only
                and s["transfer"]["n"] == 2              # transfer population: transfers only
                and sum(v["n"] for v in s["recall_by_stability"].values()) == 3
                and cov["reviews_bucketed"] == cov["reviews_total"] == 3
                and cov["complete"] is True              # a transfer is not a dropped review
                and s["adherence"]["loop_closure"]["first_review_done"] == 1)
    check("a transfer receipt is NEVER pooled into retention — and never breaks its coverage",
          fresh(_transfer_is_never_pooled))

    # -- …but momentum DOES count them, because durability is durability --
    # A transfer probe advances the FSRS schedule exactly like any other successful rating, so
    # counting only `kind == "review"` here would report LESS durability than the learner actually
    # built. Undercounting real progress is its own dishonesty — in the direction that quietly
    # tells someone their work did not land. (Three populations, three questions; this is the one
    # that asks "how much did you actually grow?")
    def _momentum_counts_transfer_retrievals(h):
        _add_transfer_topic()
        _mature()
        _probe(grade="recalled", rating="good")       # a SUCCESSFUL transfer: strengthens memory
        s = _capture_json(cmd_stats, _ns())
        return (s["momentum"]["reviews_7d"] == 1               # the transfer IS in the window…
                and s["momentum"]["stability_gained_7d"] > 0   # …and its durability gain counts…
                and s["reviews"] == 3                          # …while retention sees reviews only
                and s["transfer"]["n"] == 1)
    check("momentum counts TRANSFER retrievals too (durability is durability)",
          fresh(_momentum_counts_transfer_retrievals))

    # -- THE CAPSTONE IS A NODE, NOT A HOPE --
    def _capstone_is_in_the_dag(h):
        _add_transfer_topic()
        g = load_graph("k")
        cap = g["nodes"].get(CAPSTONE_ID)
        born = (cap is not None and cap["capstone"] is True and cap["state"] == "new"
                and sorted(cap["edges"]["requires"]) == ["a", "b"]   # requires EVERYTHING…
                and CAPSTONE_ID not in cap["edges"]["requires"]      # …and NEVER itself
                and g["order"][-1] == CAPSTONE_ID)
        n0 = _capture_json(cmd_next, _ns(topic="k"))["id"]
        _capture(cmd_rate, _ns(topic="k", node="a", rating="good", grade="recalled",
                               kind="encode", production="x"))
        n1 = _capture_json(cmd_next, _ns(topic="k"))["id"]
        _capture(cmd_rate, _ns(topic="k", node="b", rating="good", grade="recalled",
                               kind="encode", production="y"))
        n2 = _capture_json(cmd_next, _ns(topic="k"))["id"]
        return born and n0 == "a" and n1 == "b" and n2 == CAPSTONE_ID
    check("THE CAPSTONE IS A NODE: it requires every concept (never itself), and `next` serves it",
          fresh(_capstone_is_in_the_dag))

    # -- ⚠ FINDING #8: a payload node named `capstone` was SILENTLY destroyed, and then required itself --
    def _reserved_capstone_id_is_refused(h):
        pth = p("payload.json")
        write_json(pth, {"topic": "k", "title": "K", "order": ["intro", "capstone"], "nodes": {
            "intro": {"claim": "C", "probe": "P"},
            "capstone": {"claim": "MY OWN NODE", "probe": "P"}}})
        try:
            _capture(cmd_add_topic, _ns(file=pth, replace=False))
            return False                       # it silently ate the learner's node
        except SystemExit:
            return "reserved" in "".join(all_topics()) or True    # a guarded refusal
    check("FINDING #8: a payload node named `capstone` is REFUSED (it would be eaten, then require itself)",
          fresh(_reserved_capstone_id_is_refused))

    # -- ⚠ FINDING #3 + #5: `--replace` destroyed the capstone's schedule and wiped node.transfer --
    def _replace_preserves_the_capstone(h):
        _add_transfer_topic()
        for nid in ("a", "b"):
            _capture(cmd_rate, _ns(topic="k", node=nid, rating="good", grade="recalled",
                                   kind="encode", production="x"))
        _probe(node=CAPSTONE_ID)                              # build it, pass it
        before = load_graph("k")["nodes"][CAPSTONE_ID]
        s_before = _fsrs_of(before).get("s")
        # …now restructure the topic (the architect adds a node)
        write_json(p("payload.json"), {"topic": "k", "title": "K",
                                       "order": ["a", "b", "c"], "nodes": {
            "a": {"claim": "C", "probe": "P", "rubric": ["r"], "transfer_probe": "TP"},
            "b": {"claim": "C2", "probe": "P2", "rubric": ["r"]},
            "c": {"claim": "C3", "probe": "P3", "rubric": ["r"]}}})
        _capture(cmd_add_topic, _ns(file=p("payload.json"), replace=True))
        after = load_graph("k")["nodes"][CAPSTONE_ID]
        st = _capture_json(cmd_stats, _ns())["transfer"]
        ret = _capture_json(cmd_retention, _ns())
        return (
            # #3: the SCHEDULE survives (v0.8.0 reset it to `new`, which also erased the node
            # from retention's honest denominator — survivorship bias, through a new door)
            after["state"] == before["state"] and _fsrs_of(after).get("s") == s_before
            and _fsrs_of(after).get("due") == _fsrs_of(before).get("due")
            # …and the capstone now requires the NEW node too
            and sorted(after["edges"]["requires"]) == ["a", "b", "c"]
            # #5: node.transfer is REBUILT from the receipt log (not left as a hole)
            and after["transfer"]["state"] == "applied" and after["transfer"]["receipts"] == 1
            and st["states"]["applied"] == 1                  # …and stats AGREES with the graph
            and st["owned"] == 1)
    check("FINDING #3+#5: `--replace` preserves the capstone's schedule and REBUILDS node.transfer",
          fresh(_replace_preserves_the_capstone))

    # -- materializing a capstone into an EXISTING (pre-v0.8) graph is idempotent --
    def _capstone_materialization_is_idempotent(h):
        _add_transfer_topic()
        g = load_graph("k")
        del g["nodes"][CAPSTONE_ID]                       # simulate a pre-v0.8 graph
        g["order"] = [n for n in g["order"] if n != CAPSTONE_ID]
        save_graph(g)
        for nid in ("a", "b"):
            _capture(cmd_rate, _ns(topic="k", node=nid, rating="good", grade="recalled",
                                   kind="encode", production="x"))
        empty = _capture_json(cmd_next, _ns(topic="k"))   # frontier empty, no capstone
        told = (empty["id"] is None and empty["capstone"]["exists"] is False
                and "NO CAPSTONE" in empty["note"]
                and "capstone --topic k" in empty["capstone"]["materialize"])
        r1 = _capture_json(cmd_capstone, _ns(topic="k"))
        r2 = _capture_json(cmd_capstone, _ns(topic="k"))  # …twice
        caps = [nid for nid, n in load_graph("k")["nodes"].items() if n.get("capstone")]
        return (told and r1["created"] is True and r2["created"] is False
                and len(caps) == 1                        # runs twice -> ONE node
                and _capture_json(cmd_next, _ns(topic="k"))["id"] == CAPSTONE_ID)
    check("capstone materialization is idempotent (twice -> one node) and `next` then serves it",
          fresh(_capstone_materialization_is_idempotent))

    # -- a payload may NEVER claim a capability nobody measured (invariant #4) --
    def _payload_cannot_claim_transfer(h):
        write_json(p("payload.json"), {"topic": "k", "title": "K", "order": ["a"], "nodes": {
            "a": {"claim": "C", "probe": "P", "transfer_probe": "TP",
                  "transfer": {"state": "applied", "last": "2026-01-01", "receipts": 99},
                  "capstone": True}}})       # a payload trying to mint its own capstone, too
        _capture(cmd_add_topic, _ns(file=p("payload.json"), replace=False))
        node = load_graph("k")["nodes"]["a"]
        st = _capture_json(cmd_stats, _ns())["transfer"]
        return ("transfer" not in node and node.get("capstone") is not True
                and st["states"]["applied"] == 0)
    check("a payload cannot CLAIM a transfer state or mint a capstone (state advances only through receipts)",
          fresh(_payload_cannot_claim_transfer))

    # -- the cooldown: a mature node is not re-probed every single session --
    def _transfer_has_a_cooldown(h):
        _add_transfer_topic()
        _mature()
        _probe()
        hot = _capture_json(cmd_transfer, _ns(topic="k", limit=None))["n"]
        os.environ["ENGRAM_TODAY"] = "2027-05-05"     # 29 days later: still cooling
        warm = _capture_json(cmd_transfer, _ns(topic="k", limit=None))["n"]
        os.environ["ENGRAM_TODAY"] = "2027-07-06"     # 91 days later: askable again
        cold = _capture_json(cmd_transfer, _ns(topic="k", limit=None))["n"]
        return hot == 0 and warm == 0 and cold == 1
    check("transfer honours a %dd cooldown — it is a tool, not a quiz show" % TRANSFER_COOLDOWN_DAYS,
          fresh(_transfer_has_a_cooldown))

    # -- `due` flags a mature node so /review can serve the harder probe without a 2nd call --
    def _due_flags_transfer_ready(h):
        _add_transfer_topic()
        _mature()                                     # node `a`: mature, has a transfer_probe
        _capture(cmd_rate, _ns(topic="k", node="b", rating="again", grade="lapsed",
                               kind="encode", production="y"))   # `b`: encoded, immature, no probe
        os.environ["ENGRAM_TODAY"] = "2099-01-01"     # everything is due by now
        due = {d["id"]: d for d in due_items("k")}
        return (due["a"]["transfer_ready"] is True
                and due["a"]["transfer_probe"] is not None
                and due["b"]["transfer_ready"] is False    # immature AND no probe
                and due["b"]["transfer_probe"] is None)
    check("`due` flags a transfer-ready node (so /review serves the probe the architect wrote)",
          fresh(_due_flags_transfer_ready))

    # -- §4.8 Q4 (the NEW rule): the dashboard is a surface too. OPEN IT. --
    def _dashboard_shows_the_capability_claim(h):
        _add_transfer_topic()
        _mature()
        html0 = open(_capture_json(cmd_report, _ns(out=None, allow_outside=False))["path"],
                     encoding="utf-8").read()
        never = ("NO CAPABILITY HAS EVER BEEN MEASURED" in html0
                 and "Never pooled with retention" in html0)
        _probe(grade="lapsed", rating="again")
        html1 = open(_capture_json(cmd_report, _ns(out=None, allow_outside=False))["path"],
                     encoding="utf-8").read()
        # the CURRENT-ownership headline must be on the page — never the order-blind pool
        measured = ("OWNED NOW" in html1 and "Transfer" in html1
                    and "insufficient-data" in html1)          # 1 probe < the floor
        return never and measured
    check("§4.8 Q4: the DASHBOARD leads with CURRENT ownership (never the order-blind lifetime pool)",
          fresh(_dashboard_shows_the_capability_claim))

    # -- the CAPSTONE gets NO provisional credit: it may not be built on ungraded prerequisites --
    def _capstone_needs_graded_prereqs(h):
        _add_transfer_topic()
        for nid in ("a", "b"):
            _capture(cmd_stash, _ns(action="add", json=json.dumps(
                {"topic": "k", "node": nid, "probe": "p", "production": "ans"}), file=None))
        blocked = _capture_json(cmd_next, _ns(topic="k"))     # both stashed, none GRADED
        for nid in ("a", "b"):
            _capture(cmd_rate, _ns(topic="k", node=nid, rating="good", grade="recalled",
                                   kind="encode", production="x"))
        served = _capture_json(cmd_next, _ns(topic="k"))      # now graded -> the capstone unlocks
        return (blocked["id"] is None and blocked["pending_verify"] == 2
                and served["id"] == CAPSTONE_ID)
    check("the capstone gets NO provisional credit — it needs GRADED prerequisites, not stashed ones",
          fresh(_capstone_needs_graded_prereqs))

    # ================================================== THE ORACLE (v0.7)
    # The grader that writes every receipt, finally graded. Every check below exists because
    # a grader can be wrong in a way that FLATTERS, and a flattering number gets believed.

    def _gold_file(h, items):
        path = os.path.join(h, "g.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            for it in items:
                f.write(json.dumps(it) + "\n")
        return path

    def _gitem(sid, grade, case="synthetic"):
        return {"sid": sid, "case_type": case, "topic": "t", "node": "n",
                "claim": "c", "rubric": ["r1"], "probe": "p", "production": "prod",
                "confidence": 50, "kind": "review", "gold_grade": grade,
                "rationale": "because %s" % sid}

    def _audit(h, gold_items, runs, grader="g"):
        gp = _gold_file(h, gold_items)
        rp = os.path.join(h, "runs.json")
        with open(rp, "w", encoding="utf-8") as f:
            json.dump({"grader": grader, "runs": runs}, f)
        return _capture_json(cmd_assessor_audit, _ns(file=rp, json=None, gold=gp))

    # -- QWK against hand-computed confusion matrices (a behavior, not a restatement) --
    _ORD = ("lapsed", "partial", "recalled")          # the ORDINAL scale QWK weights against
    def _from_matrix(m):
        return [(_ORD[i], _ORD[j]) for i in range(3) for j in range(3) for _ in range(m[i][j])]
    # A: gold rows / grader cols, errors ALL one step. n=30, num=2.0, den=9.5 -> 1 - 2/9.5.
    check("QWK matches a hand-computed confusion matrix (all 1-step errors -> 0.789)",
          approx(_qwk(_from_matrix([[7, 3, 0], [2, 7, 1], [0, 2, 8]])), 0.7895, 0.001))
    # B: one- AND two-step errors, UNBALANCED marginals. THIS is the fixture that pins the
    # weighting SCHEME: quadratic -> 0.3827, linear -> 0.4068.
    #
    # The first draft of this check was theatre and the §4.5 mutation test caught it. It
    # asserted only that a 2-step error hurts MORE than a 1-step one — which LINEAR weights
    # satisfy just as happily, so reverting the fix left the check green. (A balanced matrix
    # is no good either: with equal marginals the two schemes normalize to the SAME kappa and
    # prove nothing.) The quadratic penalty is the entire reason lapsed->recalled costs 4x
    # lapsed->partial — the difference between "the grader is noisy" and "the grader called a
    # total blank a full recall".
    check("QWK weights are QUADRATIC, not linear (hand-computed 1-and-2-step matrix -> 0.383)",
          approx(_qwk(_from_matrix([[8, 4, 3], [1, 9, 2], [0, 1, 2]])), 0.3827, 0.001))
    check("QWK is 1.0 only on perfect agreement",
          approx(_qwk([(g, g) for g in _ORD] * 10), 1.0, 1e-9))
    check("QWK is None (never 1.0) when both raters are degenerate on one category",
          _qwk([("recalled", "recalled")] * 40) is None)

    # -- THE QWK FLOOR, ISOLATED: a NOISY but UNBIASED grader (the bias gate cannot see it) --
    # Mutation-testing exposed that the raw-agreement check below does not isolate the floor:
    # its always-says-recalled grader also trips the BIAS ceiling, so reverting the floor left
    # it green. This grader is symmetric — it inflates as often as it deflates — so its bias is
    # exactly 0.00 and the ONLY thing that can catch it is QWK. A grader can be perfectly
    # unbiased on average and still be worthless, and the floor is what says so.
    def _qwk_floor_is_load_bearing(h):
        gold = [_gitem("q%02d" % i, _ORD[i % 3]) for i in range(36)]
        up = {"lapsed": "partial", "partial": "recalled", "recalled": "recalled"}
        down = {"lapsed": "lapsed", "partial": "lapsed", "recalled": "partial"}
        def mk(run):
            out = []
            for k, g in enumerate(gold):
                gr = g["gold_grade"]
                gr = up[gr] if (k + run) % 2 == 0 else down[gr]   # symmetric noise -> bias 0.00
                out.append({"sid": g["sid"], "grade": gr})
            return out
        a = _audit(h, gold, [mk(0), mk(1), mk(2)])
        return (a["qwk"] < QWK_FLOOR                       # the only gate that fires
                and abs(a["leniency_bias"]) <= BIAS_MAX    # bias ceiling silent
                and a["paradox_triggered"] is False        # paradox silent
                and a["verdict"] == "fail" and a["grader_unvalidated"] is True)
    check("a NOISY but perfectly UNBIASED grader still fails (the QWK floor is load-bearing)",
          fresh(_qwk_floor_is_load_bearing))

    # -- RAW AGREEMENT IS A LIAR: 90% raw, kappa 0.00 -- and it must NOT pass --
    # The literature's central number: raw accuracy overstates chance-corrected agreement by
    # 33.8-41.2 points (docs/07 §3). A grader that always says "recalled" against a gold set
    # that is 90% recalled looks 90% right and has learned nothing.
    def _raw_agreement_is_a_liar(h):
        gold = ([_gitem("s%02d" % i, "recalled") for i in range(27)]
                + [_gitem("s%02d" % i, "lapsed") for i in range(27, 30)])
        run = [{"sid": g["sid"], "grade": "recalled"} for g in gold]     # always "recalled"
        a = _audit(h, gold, [run, run, run])
        return (a["exact_agreement"] == 0.9          # looks excellent
                and approx(a["qwk"], 0.0, 0.001)     # and is worth nothing
                and a["verdict"] == "fail"           # and is NOT allowed to pass
                and a["grader_unvalidated"] is True)
    check("a grader with 90% RAW agreement and QWK 0.00 fails (raw agreement never certifies)",
          fresh(_raw_agreement_is_a_liar))

    # -- leniency bias sign convention: POSITIVE = inflating --
    def _bias_sign(h):
        gold = [_gitem("s%02d" % i, "partial") for i in range(30)]
        up = [{"sid": g["sid"], "grade": "recalled"} for g in gold]   # grader inflates
        down = [{"sid": g["sid"], "grade": "lapsed"} for g in gold]   # grader deflates
        a_up = _audit(h, gold, [up, up, up])
        a_dn = _audit(h, gold, [down, down, down])
        return (a_up["leniency_bias"] == 1.0 and a_dn["leniency_bias"] == -1.0
                and a_up["grader_unvalidated"] is True
                and "INFLATES" in " ".join(a_up["reasons"]))
    check("leniency_bias is signed: + inflates (and only + trips the ceiling)",
          fresh(_bias_sign))

    # -- THE LENIENCY GATE, ISOLATED: a grader ABOVE the QWK target, failed for bias alone --
    # The single most important check in this release. This grader scores QWK 0.72 — over the
    # 0.70 conventional target — is not degenerate, is not inconsistent enough to trip the
    # paradox, and would sail through any QWK-only audit. It systematically inflates every
    # other item, so every retention number it feeds is too high. Only the bias ceiling sees
    # it. (This fixture is also what makes the bias term in `teeth` mutation-testable: the
    # floor is silent and the paradox is silent, so reverting the bias gate turns this green.)
    def _bias_gate_is_load_bearing(h):
        gold = [_gitem("g%02d" % i, ("lapsed", "partial", "recalled")[i % 3]) for i in range(36)]
        up = {"lapsed": "partial", "partial": "recalled", "recalled": "recalled"}
        down = {"lapsed": "lapsed", "partial": "lapsed", "recalled": "partial"}
        def mk(run):
            out = []
            for k, g in enumerate(gold):
                gr = g["gold_grade"]
                if k % 2 == 0:                     # systematic inflation on every other item
                    gr = up[gr]
                elif k % 6 == run:                 # per-run noise -> test-retest 0.89, paradox silent
                    gr = down[gr]
                out.append({"sid": g["sid"], "grade": gr})
            return out
        a = _audit(h, gold, [mk(0), mk(1), mk(2)])
        return (a["qwk"] > QWK_TARGET               # would PASS on QWK alone
                and a["test_retest"] < PARADOX_RETEST    # paradox gate silent
                and a["paradox_triggered"] is False
                and a["leniency_bias"] > BIAS_MAX        # …and the ONLY thing that fires
                and a["verdict"] == "fail" and a["grader_unvalidated"] is True)
    check("a grader ABOVE the QWK target still FAILS for leniency alone (the bias gate is load-bearing)",
          fresh(_bias_gate_is_load_bearing))

    # -- THE PARADOX GATE: perfectly consistent AND lenient is a FAIL, not a pass --
    # This is the failure mode Engram's own prompt design selects for: the assessor is told
    # to be a skeptic, round down, cite the rubric -> it will be extremely self-consistent.
    # The literature records a judge at test-retest 0.992 with bias 0.192: perfectly
    # reproducible, systematically wrong. Consistency is not validity, and may never certify.
    def _paradox_gate(h):
        # A grader with a HIGH QWK (0.81 — above the 0.70 target!) that inflates. QWK alone
        # would have passed it. Only the bias gate and the paradox catch it.
        gold = ([_gitem("s%02d" % i, "partial") for i in range(10)]
                + [_gitem("s%02d" % i, "lapsed") for i in range(10, 20)]
                + [_gitem("s%02d" % i, "recalled") for i in range(20, 34)])
        up = {"partial": "recalled", "lapsed": "partial", "recalled": "recalled"}
        run = [{"sid": g["sid"], "grade": up[g["gold_grade"]]} for g in gold]
        a = _audit(h, gold, [run, run, run])          # identical runs -> test_retest 1.0
        return (a["test_retest"] == 1.0 and a["leniency_bias"] > BIAS_MAX
                and a["paradox_triggered"] is True
                and a["verdict"] == "fail" and a["grader_unvalidated"] is True
                and "PARADOX" in " ".join(a["reasons"]))
    check("THE PARADOX: test-retest 1.0 + leniency over the ceiling = fail, never pass",
          fresh(_paradox_gate))

    # -- consistency alone cannot certify: fewer than 3 runs may not pass, however perfect --
    def _one_run_cannot_certify(h):
        gold = [_gitem("s%02d" % i, GRADES[i % 3]) for i in range(33)]
        run = [{"sid": g["sid"], "grade": g["gold_grade"]} for g in gold]   # perfect
        a = _audit(h, gold, [run])
        return (a["qwk"] == 1.0 and a["verdict"] == "insufficient-runs"
                and a["grader_unvalidated"] is True and a["test_retest"] is None)
    check("a PERFECT single-run audit cannot certify (the paradox check never ran)",
          fresh(_one_run_cannot_certify))

    # -- COVERAGE: a grader that drops sids must never report a flattering QWK over the rest --
    # This is issue #3's bug class aimed at the audit itself: the assessor's strict output
    # schema once dropped `sid` silently. A grader that answers 46 of 66 perfectly is not a
    # validated grader; it is an unmeasured one.
    # Each run drops a DIFFERENT 5 sids. This is deliberate and it is the whole check: with
    # three identical runs (the first draft) the intersection and the UNION of graded sids are
    # the same set, so swapping `all(...)` for `any(...)` in the denominator changed nothing
    # and the check stayed green. The §4.5 mutation test caught it — the second of this
    # release's three theatre checks, and the same coincidental-fixture failure the protocol
    # names. Here: union = 45 (looks complete, would PASS), intersection = 30 (the honest
    # denominator — only these were graded by every run).
    def _dropped_sids_are_not_a_pass(h):
        gold = [_gitem("s%02d" % i, _ORD[i % 3]) for i in range(45)]
        def run(drop):
            return [{"sid": g["sid"], "grade": g["gold_grade"]}
                    for k, g in enumerate(gold) if k not in drop]
        runs = [run(set(range(30, 35))), run(set(range(35, 40))), run(set(range(40, 45)))]
        a = _audit(h, gold, runs)
        return (a["qwk"] == 1.0                       # perfect on everything it DID grade
                and a["n"] == 30 and a["gold_n"] == 45     # intersection, not union
                and a["verdict"] == "incomplete" and a["grader_unvalidated"] is True
                and a["coverage"]["complete"] is False
                and len(a["coverage"]["ungraded"]) == 15
                and "coverage" in " ".join(a["reasons"]))
    check("a grader that drops sids reports `incomplete`, not a flattering QWK 1.00 pass",
          fresh(_dropped_sids_are_not_a_pass))

    # -- n < 30 reads insufficient-data rather than emitting a verdict --
    def _thin_audit_says_so(h):
        gold = [_gitem("s%02d" % i, GRADES[i % 3]) for i in range(12)]
        run = [{"sid": g["sid"], "grade": g["gold_grade"]} for g in gold]
        a = _audit(h, gold, [run, run, run])
        return (a["verdict"] == "insufficient-data" and a["grader_unvalidated"] is True
                and a["n"] == 12)
    check("an audit with n < 30 reads insufficient-data, never a verdict", fresh(_thin_audit_says_so))

    # -- §4.8 Q3: ITEMS and JUDGMENTS are different denominators and must be named separately --
    # The first cut of by_case_type emitted `n: 30` for a case type holding TEN items — 30 was
    # judgments (10 x 3 runs) and nothing said so. That is the v0.6.4 unlabelled-denominator bug,
    # reproduced INSIDE the release built to catch unlabelled denominators. Found by running the
    # numbers audit on this release, not by any test written before it.
    def _items_and_judgments_are_named(h):
        gold = ([dict(_gitem("c%02d" % i, _ORD[i % 3]), case_type="tricky") for i in range(15)]
                + [dict(_gitem("d%02d" % i, _ORD[i % 3]), case_type="easy") for i in range(15, 33)])
        run = [{"sid": g["sid"], "grade": g["gold_grade"]} for g in gold]
        a = _audit(h, gold, [run, run, run])
        bc = a["by_case_type"]
        return ("n" not in bc["tricky"]                       # the ambiguous key is GONE
                and bc["tricky"]["items"] == 15               # 15 items…
                and bc["tricky"]["judgments"] == 45           # …but 45 judgments (15 x 3 runs)
                and bc["easy"]["items"] == 18
                and bc["easy"]["judgments"] == 54
                # and the confusion matrix totals JUDGMENTS, which must reconcile with n x runs
                and sum(a["confusion"].values()) == a["n"] * a["runs"] == 99)
    check("§4.8 Q3: by_case_type names ITEMS and JUDGMENTS separately (never a bare `n`)",
          fresh(_items_and_judgments_are_named))

    # -- §4.8 Q4: the DIRECTION of error reaches the narrator (a mean bias of 0.00 hides it) --
    # THE most decision-relevant fact in the audit, and the first cut left it derivable-but-unsaid
    # inside `confusion`, which nothing reads. These two graders have the SAME mean leniency bias
    # (+0.00) and opposite safety profiles: one is perfect, the other inflates 1/3 of the set and
    # deflates another 1/3. Only `direction` can tell them apart.
    def _direction_of_error_is_stated(h):
        gold = [_gitem("e%02d" % i, _ORD[i % 3]) for i in range(33)]
        perfect = [{"sid": g["sid"], "grade": g["gold_grade"]} for g in gold]
        up = {"lapsed": "partial", "partial": "recalled", "recalled": "recalled"}
        down = {"lapsed": "lapsed", "partial": "lapsed", "recalled": "partial"}
        churn = [{"sid": g["sid"],
                  "grade": (up if k % 3 == 0 else down if k % 3 == 1 else lambda x: x)[g["gold_grade"]]
                           if k % 3 < 2 else g["gold_grade"]}
                 for k, g in enumerate(gold)]
        a_ok = _audit(h, gold, [perfect] * 3)
        a_churn = _audit(h, gold, [churn] * 3)
        clean = (a_ok["direction"]["graded_up"] == 0
                 and a_ok["direction"]["graded_down"] == 0
                 and a_ok["direction"]["judgments"] == 99
                 and "graded UP 0 times" in a_ok["read"])          # …and it SAYS so
        # the churner inflates AND deflates: near-zero mean bias, real inflation underneath
        noisy = (a_churn["direction"]["graded_up"] > 0
                 and a_churn["direction"]["graded_down"] > 0
                 and abs(a_churn["leniency_bias"]) < 0.10          # the mean HIDES it…
                 and "graded UP" in a_churn["read"])               # …and the read does not
        return clean and noisy
    check("§4.8 Q4: the DIRECTION of error reaches the read string (a mean bias of 0 hides inflation)",
          fresh(_direction_of_error_is_stated))

    # -- §4.8 Q5: the audit records WHICH ground truth produced the verdict --
    # The skills always use the bundled gold set. The CLI's `--gold` accepts any file, so a `pass`
    # against a hand-made 30-item set would otherwise be indistinguishable from a pass against the
    # shipped adversarial one — and the whole meaning of the number is which set it was measured
    # against. Every metric keys off exact literals; the CLI has defaults, and they bite (v0.6.1).
    def _audit_records_its_ground_truth(h):
        gold = [_gitem("f%02d" % i, _ORD[i % 3]) for i in range(33)]
        run = [{"sid": g["sid"], "grade": g["gold_grade"]} for g in gold]
        a = _audit(h, gold, [run, run, run])            # _audit always passes --gold
        gh = _capture_json(cmd_grader_health, _ns())
        return (a["gold_source"].endswith("g.jsonl") and os.path.isabs(a["gold_source"])
                and gh["gold_source"] == a["gold_source"])   # …and it survives to grader-health
    check("§4.8 Q5: the audit records WHICH gold set produced the verdict (--gold is not the shipped one)",
          fresh(_audit_records_its_ground_truth))

    # ===== THE INDEPENDENT REVIEWER'S FINDINGS (§4.6) — every one of these shipped-in-branch =====

    # -- THE TEETH ON THE SCREEN: the HTML dashboard rendered the flattered number, unstamped --
    # `ret["read"]` was the ONLY carrier of the grader stamp, and cmd_report rendered it solely
    # in the branch that fires when there is NO retention data. On the happy path it drew a
    # full-width green bar reading 100% — produced by a grader that inflates every second item —
    # with nothing anywhere to say so. Bug class #1 and #4 at once, on the surface where a number
    # is MOST believed. The live test, the fuzz, the numbers audit and the user session all
    # walked past it, because every one of them reads JSON.
    def _dashboard_carries_the_teeth(h):
        _add_ab()
        _capture(cmd_rate, _ns(topic="t", node="a", rating="good", grade="recalled",
                               kind="encode", production="x"))      # encoded 2026-07-06
        os.environ["ENGRAM_TODAY"] = "2026-08-05"                   # +30d -> the HEADLINE bucket
        _capture(cmd_rate, _ns(topic="t", node="a", rating="good", grade="recalled",
                               kind="review", production="y"))      # a real 100% retention bar
        gold = [_gitem("z%02d" % i, "partial") for i in range(33)]
        run = [{"sid": g["sid"], "grade": "recalled"} for g in gold]        # inflates everything
        a = _audit(h, gold, [run, run, run])
        path = _capture_json(cmd_report, _ns(out=None, allow_outside=False))["path"]
        html = open(path, encoding="utf-8").read()
        # Three carriers, asserted SEPARATELY, because a marker that any of them could have
        # produced tests none of them. (The first draft asserted `"QWK" in html`, which the
        # static "QWK is the headline" footnote satisfies all by itself — theatre, caught by
        # §4.5, and the third time this release that a check turned out to prove nothing.)
        return (a["verdict"] == "fail"
                # 1. the retention read renders EVEN WHEN there are bars (the actual bug)
                and "30-day recall 100%" in html
                # 2. the stamp appears TWICE: once standalone, once inside that read
                and html.count("GRADER UNVALIDATED") >= 2
                # 3. …and the grader block itself is on the page
                and "The grader behind every number above" in html)
    check("THE DASHBOARD carries the teeth (a failed grader's 100% bar is stamped, not silent)",
          fresh(_dashboard_carries_the_teeth))

    # -- a local gold set that re-adjudicates the answer must not certify SILENTLY --
    # `gold/local-gold.jsonl` wins on a sid collision, on the DEFAULT path, no flag required —
    # so a local file that re-grades every item to agree with the grader turns a `fail` into a
    # `pass`. The first `gold_source` fix wrote "bundled:gold/assessor-gold.jsonl" into that
    # audit anyway: not merely silent, but ACTIVELY FALSE, in the flattering direction. A
    # provenance field that lies is worse than none, because it is believed.
    def _local_gold_cannot_certify_silently(h):
        os.makedirs(p("gold"), exist_ok=True)
        # re-adjudicate two REAL bundled sids, and add one of our own
        with open(p("gold", "local-gold.jsonl"), "w", encoding="utf-8") as f:
            f.write(json.dumps(dict(_gitem("g_001", "recalled"), case_type="disputed")) + "\n")
            f.write(json.dumps(dict(_gitem("g_002", "recalled"), case_type="disputed")) + "\n")
            f.write(json.dumps(_gitem("mine_01", "partial")) + "\n")
        items, meta = load_gold()
        return (meta["modified"] is True
                and meta["local_overrides"] == 2          # two bundled adjudications REPLACED
                and meta["local_added"] == 1              # one new item
                and "local-gold.jsonl" in meta["source"]
                and "bundled:gold/assessor-gold.jsonl" != meta["source"]
                # the override actually took effect (so the flag is not decorative)…
                and next(g["gold_grade"] for g in items if g["sid"] == "g_001") == "recalled"
                # …and the blindness whitelist still holds for the local items
                # (node_kind is optional-per-item since v1.1: subset, never beyond)
                and all(set(it) <= set(GOLD_ASSESSOR_KEYS)
                        for it in _capture_json(cmd_gold, _ns())))
    check("a local gold set that RE-ADJUDICATES the answer is recorded, never passed off as bundled",
          fresh(_local_gold_cannot_certify_silently))

    # -- a grader may not mark its own homework twice and keep the better score --
    # The mirror of the dropped-sid bug: `out[sid] = grade` was LAST-WINS, so a grader that got
    # 12 items wrong and re-emitted those sids later in the array (exactly what an LLM
    # self-correcting mid-array produces) turned a `fail` into a `pass`, silently, with n intact.
    def _duplicate_sids_are_a_coverage_failure(h):
        gold = [_gitem("y%02d" % i, "lapsed") for i in range(33)]
        wrong = [{"sid": g["sid"], "grade": "recalled"} for g in gold]      # all 33 badly wrong
        fixed = [{"sid": g["sid"], "grade": "lapsed"} for g in gold[:12]]   # …then "corrected"
        a = _audit(h, gold, [wrong + fixed] * 3)
        return (a["verdict"] == "incomplete" and a["grader_unvalidated"] is True
                and len(a["duplicate_sids"]) == 12
                and a["coverage"]["complete"] is False
                and a["leniency_bias"] > BIAS_MAX          # the FIRST verdict is the one that counts
                and "MORE THAN ONCE" in " ".join(a["reasons"]))
    check("a grader that grades a sid TWICE gets `incomplete` — the first verdict stands",
          fresh(_duplicate_sids_are_a_coverage_failure))

    # -- three copy-pasted runs are not three runs, and test-retest may not pretend otherwise --
    def _identical_runs_are_flagged(h):
        gold = [_gitem("x%02d" % i, _ORD[i % 3]) for i in range(33)]
        run = [{"sid": g["sid"], "grade": g["gold_grade"]} for g in gold]
        a = _audit(h, gold, [run, run, run])       # the same object, three times
        return (a["identical_runs"] is True and a["test_retest"] == 1.0
                and "not independent" in " ".join(a["reasons"]))
    check("three IDENTICAL runs are flagged — test-retest cannot certify what it never measured",
          fresh(_identical_runs_are_flagged))

    # -- A `pass` MUST CARRY ITS CAVEATS. `pass` is the ONE verdict where the teeth are off. --
    # The pass branch built a fresh `read` and threw `reasons` away — and `compute_grader_health`
    # never returned the key at all, though `skills/coach` is told to "read `reasons` aloud". So
    # three copy-pasted runs produced `identical_runs: true`, the engine wrote "test-retest
    # measures nothing here" to disk, and then printed **"test-retest 1.00"** as a validated
    # figure. The most reassuring number in the payload, quoted as evidence, by the branch that
    # had just discarded the note saying it was evidence of nothing.
    #
    # This is bug class #4 reproduced inside the release built to catch it — and the check above
    # was complicit: it asserted `reasons` CONTAINED the caveat, which proves nothing about
    # whether any runtime surface ever reads it. **A field is not a narrator.** So this check
    # follows the caveat all the way to the strings a human actually sees.
    def _a_pass_still_carries_its_caveats(h):
        gold = [_gitem("v%02d" % i, _ORD[i % 3]) for i in range(33)]
        run = [{"sid": g["sid"], "grade": g["gold_grade"]} for g in gold]
        a = _audit(h, gold, [run, run, run])                  # perfect, and copy-pasted
        gh = _capture_json(cmd_grader_health, _ns())
        return (a["verdict"] == "pass"
                and "not independent" in a["read"]            # …the AUDIT read says so…
                and "BUT:" in a["read"]
                and gh["reasons"]                             # …grader-health EXPOSES them…
                and any("not independent" in r for r in gh["reasons"])
                and "not independent" in gh["read"])          # …and its read carries them too
    check("a PASS carries its caveats into the read (a field nobody narrates is not a guard)",
          fresh(_a_pass_still_carries_its_caveats))

    # -- the instrument's OWN limit rides on every audit: this gold set cannot certify a peer --
    def _gold_declares_its_own_circularity(h):
        gold = [_gitem("u%02d" % i, _ORD[i % 3]) for i in range(33)]
        run = [{"sid": g["sid"], "grade": g["gold_grade"]} for g in gold]
        # a --gold OVERRIDE is the caller's own ground truth, so the bundled set's caveat is moot
        a_over = _audit(h, gold, [run, run, run])
        # …but the BUNDLED set must always declare it
        rp = os.path.join(h, "r.json")
        with open(rp, "w", encoding="utf-8") as f:
            bundled, _ = load_gold()
            br = [{"sid": g["sid"], "grade": g["gold_grade"]} for g in bundled]
            json.dump({"runs": [br, br, br]}, f)
        a_bundled = _capture_json(cmd_assessor_audit, _ns(file=rp, json=None, gold=None))
        gh = _capture_json(cmd_grader_health, _ns())
        return (a_bundled["gold_adjudication"] == "authored"
                and any("AUTHORED" in r for r in a_bundled["reasons"])
                and "AUTHORED" in a_bundled["read"]           # …it reaches the narrator…
                and gh["gold_adjudication"] == "authored"
                and any("AUTHORED" in r for r in gh["reasons"])
                and not any("AUTHORED" in r for r in a_over["reasons"]))   # …but not on --gold
    check("the gold set declares its OWN circularity on every audit (authored != adjudicated)",
          fresh(_gold_declares_its_own_circularity))

    # -- `grader_unvalidated` is DERIVED from the verdict, never trusted from the file --
    def _teeth_derive_from_the_verdict(h):
        os.makedirs(p("audits"), exist_ok=True)
        write_json(p("audits", "2026-07-11-01.json"), {
            "ts": "2026-07-11", "verdict": "fail", "qwk": 0.20, "n": 60, "runs": 3,
            "grader_unvalidated": False,          # ← the LIE, hand-edited or torn
            "read": "r", "reasons": []})
        gh = _capture_json(cmd_grader_health, _ns())
        return (gh["verdict"] == "fail"
                and gh["grader_unvalidated"] is True          # derived, not believed
                and "GRADER UNVALIDATED" in (gh["stamp"] or ""))
    check("grader_unvalidated is DERIVED from the verdict — a file cannot switch the teeth off",
          fresh(_teeth_derive_from_the_verdict))

    # -- `artifact set|clear` refuses a corrupt node instead of crashing on it --
    # The last mutator reading a raw node value. And `doctor` RECOMMENDS `artifact clear` as the
    # fix for a corrupt artifact field — so the repair the tool told you to run was the thing
    # that blew up.
    def _artifact_refuses_a_corrupt_node(h):
        _add_ab()
        g = load_graph("t")
        g["nodes"]["b"] = ["not", "a", "node"]
        save_graph(g)
        for action in ("clear", "set"):
            try:
                _capture(cmd_artifact, _ns(action=action, topic="t", node="b",
                                           path=p("payload.json")))
                return False                                  # it crashed or half-wrote
            except SystemExit:
                pass                                          # a guarded refusal: correct
        return load_graph("t")["nodes"]["b"] == ["not", "a", "node"]   # untouched
    check("`artifact set|clear` REFUSES a corrupt node (doctor recommends it as the fix — it must not crash)",
          fresh(_artifact_refuses_a_corrupt_node))

    # -- a corrupt node must not TEAR a receipt batch in half (receipts are append-only) --
    def _corrupt_node_does_not_tear_the_batch(h):
        _add_ab()
        g = load_graph("t")
        g["nodes"]["b"] = ["not", "a", "node"]                     # hand-corrupt the 2nd item
        save_graph(g)
        rp = os.path.join(h, "batch.json")
        with open(rp, "w", encoding="utf-8") as f:
            json.dump([{"topic": "t", "node": "a", "rating": "good", "grade": "recalled",
                        "kind": "encode", "production": "x"},
                       {"topic": "t", "node": "b", "rating": "good", "grade": "recalled",
                        "kind": "encode", "production": "y"}], f)
        try:
            _capture(cmd_receipt, _ns(file=rp, json=None))
            return False                                   # it must refuse the whole batch
        except SystemExit:
            pass
        # NOTHING was written — not even item 1, which was perfectly valid
        return (not read_jsonl(p("receipts", "t.jsonl"))
                and load_graph("t")["nodes"]["a"].get("state") == "new")
    check("a corrupt node refuses the WHOLE receipt batch (never half-applies an append-only log)",
          fresh(_corrupt_node_does_not_tear_the_batch))

    # -- the 100th audit of a day must not be shadowed by the 99th (lexicographic sort) --
    def _audit_seq_sorts_numerically(h):
        os.makedirs(p("audits"), exist_ok=True)
        for name, verdict, qwk in (("2026-07-11-99.json", "pass", 0.95),
                                   ("2026-07-11-100.json", "fail", 0.20)):
            write_json(p("audits", name), {"ts": "2026-07-11", "verdict": verdict, "qwk": qwk,
                                           "grader_unvalidated": verdict != "pass", "n": 60,
                                           "runs": 3, "read": "r"})
        gh = _capture_json(cmd_grader_health, _ns())
        return (gh["verdict"] == "fail" and gh["qwk"] == 0.20      # the 100th, not the 99th
                and gh["grader_unvalidated"] is True)
    check("audit 100 outranks audit 99 (numeric sequence, never a lexicographic stale pass)",
          fresh(_audit_seq_sorts_numerically))

    # -- the contamination guard must not FALSELY ACCUSE a grader that invents `rationale` --
    def _rationale_is_not_an_accusation(h):
        gold = [_gitem("w%02d" % i, _ORD[i % 3]) for i in range(33)]
        run = [{"sid": g["sid"], "grade": g["gold_grade"],
                "rationale": "criterion 2 was missing"}          # a grader may invent this key
               for g in gold]
        a = _audit(h, gold, [run, run, run])                     # …and must NOT be killed for it
        ok = a["verdict"] == "pass"
        # …but the two keys that could ONLY come from the gold schema still kill it
        for key in GOLD_ANSWER_KEYS:
            bad = [{"sid": g["sid"], "grade": g["gold_grade"], key: "x"} for g in gold]
            gp, rp = _gold_file(h, gold), os.path.join(h, "bad.json")
            with open(rp, "w", encoding="utf-8") as f:
                json.dump({"runs": [bad] * 3}, f)
            try:
                _capture(cmd_assessor_audit, _ns(file=rp, json=None, gold=gp))
                return False
            except SystemExit:
                pass
        return ok
    check("the contamination guard fires on the ANSWER, not on a grader that invents `rationale`",
          fresh(_rationale_is_not_an_accusation))

    # -- a genuinely good grader passes (the gate is passable, or it is not a gate) --
    def _good_grader_passes(h):
        gold = [_gitem("s%02d" % i, GRADES[i % 3]) for i in range(36)]
        # 3 of 36 wrong by ONE step, in both directions -> unbiased, QWK ~0.87
        def mk(off):
            out = []
            for k, g in enumerate(gold):
                gr = g["gold_grade"]
                if k % 12 == off:
                    gr = {"lapsed": "partial", "partial": "lapsed", "recalled": "partial"}[gr]
                out.append({"sid": g["sid"], "grade": gr})
            return out
        a = _audit(h, gold, [mk(0), mk(1), mk(2)])
        return (a["verdict"] == "pass" and a["grader_unvalidated"] is False
                and a["qwk"] >= QWK_TARGET and abs(a["leniency_bias"]) <= BIAS_MAX
                and "validated" in a["read"])
    check("a genuinely good grader PASSES (the gate is passable)", fresh(_good_grader_passes))

    # -- CONTAMINATION: an audit payload carrying the answer must DIE, not certify --
    # RELEASE_PROTOCOL §5.5, in code: v0.6's dogfood certified a dead feature because the
    # prompt handed the assessor the answer. A grader whose output carries `gold_grade` was
    # shown `gold_grade`. That audit is theatre and must never write an audits/ file.
    def _contamination_dies(h):
        gold = [_gitem("s%02d" % i, GRADES[i % 3]) for i in range(33)]
        run = [{"sid": g["sid"], "grade": g["gold_grade"], "gold_grade": g["gold_grade"]}
               for g in gold]
        gp, rp = _gold_file(h, gold), os.path.join(h, "r.json")
        with open(rp, "w", encoding="utf-8") as f:
            json.dump({"runs": [run, run, run]}, f)
        try:
            _capture(cmd_assessor_audit, _ns(file=rp, json=None, gold=gp))
            return False                       # it certified a contaminated audit
        except SystemExit:
            return not os.path.isdir(p("audits")) or not os.listdir(p("audits"))
    check("an audit payload carrying gold_grade DIES (a test that hands over the answer is not a test)",
          fresh(_contamination_dies))

    # -- BLINDNESS: `gold` can never leak the answer, by construction (whitelist, not blacklist) --
    def _gold_is_blind(h):
        items = _capture_json(cmd_gold, _ns())
        gold, _ = load_gold()
        blob = json.dumps(items)
        # subset per item (node_kind rides only on procedure items since v1.1), union
        # exactly the whitelist — nothing beyond it may ever appear
        keys_exact = (all(set(it) <= set(GOLD_ASSESSOR_KEYS) for it in items)
                      and set().union(*(set(it) for it in items)) == set(GOLD_ASSESSOR_KEYS))
        no_secret_key = all(k not in blob for k in GOLD_SECRET_KEYS)
        # property-based: not one rationale or case_type VALUE may survive into the payload
        no_values = (all(g["rationale"] not in blob for g in gold)
                     and all(g["case_type"] not in blob for g in gold))
        return keys_exact and no_secret_key and no_values and len(items) == len(gold)
    check("the assessor is BLIND to the gold answer: no gold_grade/case_type/rationale survives `gold`",
          fresh(_gold_is_blind))

    # -- the audit feeds the assessor EXACTLY what /learn feeds it (uncontaminated dogfood, in code) --
    def _gold_matches_stash_shape(h):
        _add_ab()
        _capture(cmd_stash, _ns(action="add", json=json.dumps([{
            "topic": "t", "node": "a", "claim": "c", "rubric": ["r"], "probe": "p",
            "production": "prod", "confidence": 60, "kind": "encode",
            "node_kind": "procedure"}]), file=None))
        stashed = _capture_json(cmd_stash, _ns(action="list", json=None, file=None))
        gold_items = _capture_json(cmd_gold, _ns())
        # both are BARE ARRAYS; every gold key is a stash-shape key; `node_kind` appears
        # exactly where a real stash would carry it (procedure items) and is ABSENT, not
        # null, elsewhere — the payload must be indistinguishable from a real settle
        concept_like = [it for it in gold_items if "node_kind" not in it]
        proc_like = [it for it in gold_items if it.get("node_kind") == "procedure"]
        return (isinstance(stashed, list) and isinstance(gold_items, list)
                and set(GOLD_ASSESSOR_KEYS) <= set(stashed[0])
                and all(set(it) <= set(GOLD_ASSESSOR_KEYS) for it in gold_items)
                and set().union(*(set(it) for it in gold_items)) == set(GOLD_ASSESSOR_KEYS)
                and concept_like and proc_like
                and all(it["node_kind"] == "procedure" for it in gold_items
                        if "node_kind" in it))
    check("`gold` is shaped exactly like `stash list` (the audit grades the REAL assessor)",
          fresh(_gold_matches_stash_shape))

    # -- THE TEETH: an unaudited grader stamps retention, and the stamp reaches the READ STRING --
    # A guard nobody reads cannot trip (§4.8 Q4). `grader_unvalidated` in a nested key that
    # only a test ever opens is not teeth; it is decoration.
    def _teeth_reach_the_narrator(h):
        _add_ab()
        _capture(cmd_rate, _ns(topic="t", node="a", rating="good", grade="recalled",
                               kind="encode", production="x"))
        os.environ["ENGRAM_TODAY"] = "2026-07-20"           # …and come back to REVIEW it
        _capture(cmd_rate, _ns(topic="t", node="a", rating="good", grade="recalled",
                               kind="review", production="y"))
        r0 = _capture_json(cmd_retention, _ns())
        s0 = _capture_json(cmd_stats, _ns())
        unaudited = (r0["grader_unvalidated"] is True and r0["grader_verdict"] == "unaudited"
                     and "unaudited" in r0["read"]              # ← the STAMP, on a real figure
                     and s0["grader_health"]["grader_unvalidated"] is True
                     and s0["retention"]["grader_unvalidated"] is True)
        # …and a PASSING audit clears the stamp from the very same read string
        gold = [_gitem("s%02d" % i, _ORD[i % 3]) for i in range(33)]
        run = [{"sid": g["sid"], "grade": g["gold_grade"]} for g in gold]
        a = _audit(h, gold, [run, run, run])
        r1 = _capture_json(cmd_retention, _ns())
        cleared = (a["verdict"] == "pass" and r1["grader_unvalidated"] is False
                   and "unaudited" not in r1["read"] and "UNVALIDATED" not in r1["read"])
        return unaudited and cleared
    check("THE TEETH: an unaudited grader stamps retention's READ string; a passing audit clears it",
          fresh(_teeth_reach_the_narrator))

    # -- …but the stamp NEVER qualifies a figure that does not exist (§5.6 user session) --
    # Run against the founder's real state (7 encoded, 0 reviewed), the first cut produced:
    #   "[grader unaudited — QWK unknown; run /coach audit] insufficient-data (no reviews yet)"
    # A caveat on a measurement nobody made — and a SECOND reproach stacked on top of "THE LOOP
    # HAS NEVER CLOSED", which is the wall-of-debt the constitution forbids. The flag stays true
    # in the payload (it is a true fact, and /coach reads it); the narrator is simply not handed
    # a disclaimer for a number that is not there. No selftest could have found this. A person had
    # to look at the screen.
    def _no_disclaimer_without_a_figure(h):
        _add_ab()
        _capture(cmd_rate, _ns(topic="t", node="a", rating="good", grade="recalled",
                               kind="encode", production="x"))       # encoded…
        os.environ["ENGRAM_TODAY"] = "2026-08-20"                    # …came due, never reviewed.
        r = _capture_json(cmd_retention, _ns())                      # THE FOUNDER'S OWN STATE.
        return (r["grader_unvalidated"] is True                      # the FACT survives…
                and "unaudited" not in r["read"]                     # …but the read is not scolded
                and "insufficient-data" in r["read"]
                and "past due and unretrieved" in r["read"])         # the REAL debt still lands
    check("the grader stamp never qualifies a figure that does not exist (no reviews -> no disclaimer)",
          fresh(_no_disclaimer_without_a_figure))

    # -- a FAILED audit stamps retention louder, and /coach cannot miss it --
    def _failed_audit_stamps_loud(h):
        _add_ab()                                   # a real retrieval, so there IS a figure
        _capture(cmd_rate, _ns(topic="t", node="a", rating="good", grade="recalled",
                               kind="encode", production="x"))
        os.environ["ENGRAM_TODAY"] = "2026-07-20"
        _capture(cmd_rate, _ns(topic="t", node="a", rating="good", grade="recalled",
                               kind="review", production="y"))
        gold = [_gitem("s%02d" % i, "partial") for i in range(33)]
        run = [{"sid": g["sid"], "grade": "recalled"} for g in gold]     # inflates every item
        a = _audit(h, gold, [run, run, run])
        r = _capture_json(cmd_retention, _ns())
        gh = _capture_json(cmd_grader_health, _ns())
        return (a["verdict"] == "fail" and r["grader_unvalidated"] is True
                and "GRADER UNVALIDATED" in r["read"]
                and gh["grader_unvalidated"] is True and gh["audited"] is True)
    check("a FAILED audit stamps 'GRADER UNVALIDATED' into retention's read", fresh(_failed_audit_stamps_loud))

    # -- audits are EVIDENCE: append-only, and a same-day re-audit never overwrites --
    def _audits_are_append_only(h):
        gold = [_gitem("s%02d" % i, GRADES[i % 3]) for i in range(33)]
        run = [{"sid": g["sid"], "grade": g["gold_grade"]} for g in gold]
        _audit(h, gold, [run, run, run])
        _audit(h, gold, [run, run, run])            # same day, again
        return len([f for f in os.listdir(p("audits")) if f.endswith(".json")]) == 2
    check("audits are append-only: a same-day re-audit writes a second file, never overwrites",
          fresh(_audits_are_append_only))

    # -- a corrupt latest audit reads `unreadable` and NEVER falls back to a stale pass --
    def _corrupt_audit_never_flatters(h):
        gold = [_gitem("s%02d" % i, GRADES[i % 3]) for i in range(33)]
        run = [{"sid": g["sid"], "grade": g["gold_grade"]} for g in gold]
        _audit(h, gold, [run, run, run])                       # a genuine PASS on disk
        with open(p("audits", "2099-01-01-01.json"), "w", encoding="utf-8") as f:
            f.write("{ not json at all")                       # a newer, corrupt one
        gh = _capture_json(cmd_grader_health, _ns())
        r = _capture_json(cmd_retention, _ns())
        return (gh["verdict"] == "unreadable" and gh["grader_unvalidated"] is True
                and r["grader_unvalidated"] is True)
    check("a corrupt LATEST audit reads `unreadable` — never falls back to an older pass",
          fresh(_corrupt_audit_never_flatters))

    # -- the receipt records its grader when stated, and NEVER invents one --
    def _receipt_carries_grader(h):
        _add_ab()
        rp = os.path.join(h, "rec.json")
        with open(rp, "w", encoding="utf-8") as f:
            json.dump([{"topic": "t", "node": "a", "rating": "good", "grade": "recalled",
                        "kind": "encode", "production": "x", "source": "assessor",
                        "grader": "engram-assessor"},
                       {"topic": "t", "node": "b", "rating": "good", "grade": "recalled",
                        "kind": "encode", "production": "y", "source": "self"}], f)
        _capture(cmd_receipt, _ns(file=rp, json=None))
        rs = {r["node"]: r for r in read_jsonl(p("receipts", "t.jsonl"))}
        return (rs["a"].get("grader") == "engram-assessor"
                and "grader" not in rs["b"])       # never invented for a self-rating
    check("a receipt records its grader when stated and never invents one", fresh(_receipt_carries_grader))

    # -- EVERY review-counter must agree on what a review IS (v0.6.4) --
    # v0.6.1 established "a node's first receipt is its encoding event" in _by_node (feeding
    # adherence + retention) and left stats.reviews, momentum, modality and the calibration
    # split filtering `kind == "review"` DIRECTLY — four implementations of one rule, three
    # wrong. A bare CLI `rate` (argparse default kind="review") on a never-encoded node made
    # `adherence` say 0 reviews while `stats` said 1, and handed `compute_modality` an ENCODING
    # receipt as that node's "first review" — corrupting the medium telemetry docs/06 exists to
    # produce. (RELEASE_PROTOCOL §4.8 Q1: the engine's own commands must agree with each other.)
    def _one_definition_of_review(h):
        _add_ab()
        _capture(cmd_rate, _ns(topic="t", node="a", rating="good", grade="recalled",
                               confidence=80, kind="review", production="x"))  # bare-CLI default
        os.environ["ENGRAM_TODAY"] = "2026-07-25"
        ad = _capture_json(cmd_adherence, _ns())
        st = _capture_json(cmd_stats, _ns())
        ret = _capture_json(cmd_retention, _ns())
        os.environ["ENGRAM_TODAY"] = "2026-07-06"
        return (ad["loop_closure"]["first_review_done"] == 0     # adherence: not a review ✓
                and ret["coverage"]["reviews_total"] == 0         # retention: not a review ✓
                and st["reviews"] == 0                            # stats: WAS 1 before this fix
                and st["momentum"]["reviews_7d"] == 0
                and st["modality"]["dialogue"]["n"] == 0          # modality: WAS 1 — corrupting
                and st["calibration"]["n"] == 0                   # …and it was in the wrong pool
                and st["calibration_encode"]["n"] == 1)           # it belongs HERE
    check("every review-counter shares one definition (adherence/retention/stats/momentum/modality)",
          fresh(_one_definition_of_review))
    # -- the three "current recall" surfaces must RECONCILE (v0.6.4) --
    # `decay.now.mean_recall` averages over ALL encoded nodes; `retention.unmeasured` and the
    # ambient hook average over the PAST-DUE ones. Both correct, both called "current recall",
    # ~10 points apart on the same state — a learner could not tell which to believe. Neither
    # number was lying; the labels were. (RELEASE_PROTOCOL §4.8 Q1.)
    def _recall_surfaces_reconcile(h):
        g = {"topic": "t", "title": "T", "order": ["a", "b", "c"], "nodes": {
            "a": {"claim": "A", "probe": "pa"}, "b": {"claim": "B", "probe": "pb"},
            "c": {"claim": "C", "probe": "pc"}}}
        _capture(cmd_add_topic, _ns(json=json.dumps(g), replace=False))
        for nid in ("a", "b", "c"):
            _capture(cmd_rate, _ns(topic="t", node=nid, rating="good", grade="recalled",
                                   kind="encode", production="x"))
        os.environ["ENGRAM_TODAY"] = "2026-07-13"
        _capture(cmd_rate, _ns(topic="t", node="a", rating="easy", grade="recalled",
                               kind="review", production="x"))      # `a` becomes healthy/far-out
        os.environ["ENGRAM_TODAY"] = "2026-08-20"                   # b, c now rotting
        d = _capture_json(cmd_decay, _ns(topic="t", horizon=30))
        r = _capture_json(cmd_retention, _ns())
        os.environ["ENGRAM_TODAY"] = "2026-07-06"
        # decay must expose BOTH, and its due-only figure must equal retention's projection
        return (d["now"]["mean_recall_due"] is not None
                and d["now"]["mean_recall"] != d["now"]["mean_recall_due"]   # they DO differ
                and "encoded node" in d["now"]["population"]                 # …and it says why
                and abs(d["now"]["mean_recall_due"]
                        - r["unmeasured"]["projected_recall_now"]) < 0.02)   # …and they reconcile
    check("decay's due-only recall reconciles with retention.unmeasured (denominators labelled)",
          fresh(_recall_surfaces_reconcile))
    # -- COMMIT: the implementation intention round-trips, and is off-switchable --
    def _commit(h):
        c = _capture_json(cmd_commit, _ns(cue="when I open the terminal",
                                          action="I clear one review", clear=False))
        stored = read_json(os.path.join(h, "learner-model.json"))["settings"]["commitment"]
        got = (c["commitment"]["cue"] == "when I open the terminal"
               and stored["action"] == "I clear one review" and stored["set"])
        cleared = _capture_json(cmd_commit, _ns(cue=None, action=None, clear=True))
        return got and cleared["commitment"] is None and "no commitment" in cleared["note"]
    check("commit: if-then plan round-trips and clears", fresh(_commit))
    check("commit: half a plan is refused (cue without action)",
          fresh(lambda h: raises(cmd_commit, _ns(cue="when X", action=None, clear=False))))

    # -- the ambient decay line: fires on a never-closed loop, and OFF means off --
    # It is a return-event line, not a per-session nag (docs/05 P13: information, never
    # pressure). This check is the guard against it ever becoming one.
    def _decay_line(h):
        _add_ab()
        _capture(cmd_rate, _ns(topic="t", node="a", rating="good", grade="recalled",
                               kind="encode", production="x"))
        os.environ["ENGRAM_TODAY"] = "2026-08-06"           # long overdue, never reviewed
        on = _capture(cmd_session_start, _ns())
        _capture(cmd_model, _ns(set=["settings.decay_notice=off"],
                                add_interest=None, add_goal=None))
        off = _capture(cmd_session_start, _ns())
        os.environ["ENGRAM_TODAY"] = "2026-07-06"
        return ("still falling" in on and "review due" in on            # informs
                and "still falling" not in off and "review due" in off  # …and off means off
                and "should" not in on.lower())                         # never a should-statement
    check("ambient decay line fires on a never-closed loop, and decay_notice=off silences it",
          fresh(_decay_line))

    # -- the decay line's recall figure is EXACT, not reconstructed --
    # It must read each item's `last` off the graph. Deriving elapsed from
    # `interval_for(s, RETENTION_DEFAULT) + overdue` breaks for any learner who moved
    # `desired_retention` (measured: 3.3pp of OVERSTATED decay at 0.97) — and an honesty
    # feature does not get to err in the direction of alarming the learner.
    def _recall_now_is_exact(h):
        _add_ab()
        _capture(cmd_model, _ns(set=["memory.desired_retention=0.97"],
                                add_interest=None, add_goal=None))
        _capture(cmd_rate, _ns(topic="t", node="a", rating="good", grade="recalled",
                               kind="encode", production="x"))            # last = 2026-07-06
        os.environ["ENGRAM_TODAY"] = "2026-07-20"                         # 14 days elapsed
        due = due_items()
        exact = _mean_recall_now(due)
        s = as_number(due[0]["s"])
        truth = retrievability(14, s)                                     # hand-computed
        os.environ["ENGRAM_TODAY"] = "2026-07-06"
        return due[0].get("last") == "2026-07-06" and approx(exact, truth, 0.001)
    check("decay line reads `last` for exact elapsed (never reconstructs the interval)",
          fresh(_recall_now_is_exact))

    # -- and it stays SILENT on a healthy loop (the anti-nag guard) --
    def _no_nag_when_healthy(h):
        _add_ab()
        _capture(cmd_rate, _ns(topic="t", node="a", rating="good", grade="recalled",
                               kind="encode", production="x"))
        os.environ["ENGRAM_TODAY"] = "2026-07-18"
        _capture(cmd_rate, _ns(topic="t", node="a", rating="good", grade="recalled",
                               kind="review", production="x"))   # loop closed
        _capture(cmd_log_session, _ns(kind="review", mode="quick", minutes=2, items=1, notes=None))
        out = _capture(cmd_session_start, _ns())
        os.environ["ENGRAM_TODAY"] = "2026-07-06"
        return "still falling" not in out        # loop is closing + no absence -> no line
    check("ambient decay line stays silent on a healthy loop (anti-nag)",
          fresh(_no_nag_when_healthy))

    # -- settings self-heal: a v0.5 model gains the v0.6 keys without breaking --
    healed6 = _deep_heal({"schema": SCHEMA, "settings": {"momentum": "off"}}, DEFAULT_MODEL)
    check("v0.5 model self-heals to v0.6 settings (commitment/decay_notice)",
          healed6["settings"]["commitment"] is None
          and healed6["settings"]["decay_notice"] == "on"
          and healed6["settings"]["momentum"] == "off")     # and does not clobber the old one

    # -- READ-ONLY COMMANDS MUST NOT WRITE (lock-discipline race, found in v0.6 live test) --
    # `decay`/`doctor`/`report` take no lock because they are reads. But load_model()
    # *persists* its self-heal, so an unlocked read could flush a stale snapshot over a
    # concurrent locked mutator's write — silently reverting a refit or a commitment. This
    # was latent in report/doctor since v0.5. read_model() heals in memory and never writes.
    def _reads_never_write(h):
        stale = {"schema": SCHEMA, "settings": {"default_mode": "sprint"}}   # needs healing
        mpath = os.path.join(h, "learner-model.json")
        write_json(mpath, stale)
        _add_ab()
        _capture(cmd_rate, _ns(topic="t", node="a", rating="good", grade="recalled",
                               kind="encode", production="x"))
        write_json(mpath, stale)                    # reset: rate() legitimately heals it
        before = open(mpath, encoding="utf-8").read()
        for fn, ns in ((cmd_decay, _ns(topic=None, horizon=30)),
                       (cmd_doctor, _ns()),
                       (cmd_report, _ns(out=None, allow_outside=False))):
            _capture(fn, ns)
        unchanged = open(mpath, encoding="utf-8").read() == before
        # …and a *mutating* command (which holds the lock) still does heal it
        _capture(cmd_model, _ns(set=None, add_interest=None, add_goal=None))
        healed = read_json(mpath)["settings"].get("decay_notice") == "on"
        return unchanged and healed
    check("read-only commands never persist a heal (decay/doctor/report take no lock)",
          fresh(_reads_never_write))

    # -- IDEMPOTENCY (issue #3): the same settle file applied twice is a no-op --
    def _receipt_idempotent(h):
        _add_ab()
        item = {"topic": "t", "node": "a", "probe": "pa", "production": "ans"}
        _capture(cmd_stash, _ns(action="add", json=json.dumps(item)))
        stashed = _capture_json(cmd_stash, _ns(action="list"))[0]
        sid = stashed.get("sid")
        graded = [{"topic": "t", "node": "a", "rating": "good", "grade": "recalled",
                   "kind": "review", "sid": sid, "production": "ans"}]
        write_json(os.path.join(h, "graded.json"), graded)
        first = _capture_json(cmd_receipt, _ns(file=os.path.join(h, "graded.json")))
        second = _capture_json(cmd_receipt, _ns(file=os.path.join(h, "graded.json")))
        reps = load_graph("t")["nodes"]["a"]["fsrs"]["reps"]
        on_disk = len([r for r in read_jsonl(os.path.join(h, "receipts", "t.jsonl"))
                       if r.get("sid") == sid])
        return (bool(sid) and first[0]["applied"] is True
                and second[0]["applied"] is False and second[0]["idempotent"] is True
                and reps == 1 and on_disk == 1)
    check("receipt --file is idempotent: re-applying the same sid is a no-op (issue #3)",
          fresh(_receipt_idempotent))

    # -- the SAME sid twice inside ONE batch: the second must be a no-op --
    # The receipt-log cache exists for speed; this check is what keeps it honest. It must be
    # kept in sync on append, or a duplicate later in the same batch would slip through
    # against a stale snapshot — reintroducing exactly the bug the sid was added to kill.
    def _dup_sid_one_batch(h):
        _add_ab()
        dup = [{"topic": "t", "node": "a", "rating": "good", "grade": "recalled",
                "kind": "review", "sid": "DUP", "production": "x"}] * 2
        write_json(os.path.join(h, "dup.json"), dup)
        res = _capture_json(cmd_receipt, _ns(file=os.path.join(h, "dup.json")))
        on_disk = len([r for r in read_jsonl(os.path.join(h, "receipts", "t.jsonl"))
                       if r.get("sid") == "DUP"])
        return (res[0]["applied"] is True and res[1]["applied"] is False
                and load_graph("t")["nodes"]["a"]["fsrs"]["reps"] == 1 and on_disk == 1)
    check("the same sid twice in ONE batch: second is a no-op (cache stays in sync)",
          fresh(_dup_sid_one_batch))

    # -- the receipt cache is keyed by PATH, so it cannot leak across ENGRAM_HOMEs --
    def _cache_home_isolated(_h):
        with tempfile.TemporaryDirectory() as h1, tempfile.TemporaryDirectory() as h2:
            for h in (h1, h2):
                os.environ["ENGRAM_HOME"] = h
                _capture(cmd_init, _ns())
                _add_ab()
            os.environ["ENGRAM_HOME"] = h1
            _capture(cmd_rate, _ns(topic="t", node="a", rating="good", grade="recalled",
                                   kind="encode", production="x"))
            seen1 = len(_receipts_for("t"))
            os.environ["ENGRAM_HOME"] = h2                 # different home, same topic name
            seen2 = len(_receipts_for("t"))
            return seen1 == 1 and seen2 == 0               # h2 must NOT see h1's receipt
    check("receipt cache is path-keyed: a topic in one ENGRAM_HOME cannot read another's",
          fresh(_cache_home_isolated))

    # -- a receipt WITHOUT a sid still applies (back-compat with hand-rolled `rate`) --
    def _no_sid_still_applies(h):
        _add_ab()
        batch = [{"topic": "t", "node": "a", "rating": "good", "kind": "encode"}]
        write_json(os.path.join(h, "b.json"), batch)
        _capture(cmd_receipt, _ns(file=os.path.join(h, "b.json")))
        _capture(cmd_receipt, _ns(file=os.path.join(h, "b.json")))
        return load_graph("t")["nodes"]["a"]["fsrs"]["reps"] == 2   # unchanged old behavior
    check("sid is additive: a receipt without one applies as before (back-compat)",
          fresh(_no_sid_still_applies))

    # -- days_since_encode is stamped, and day 0 is the first receipt --
    def _dse(h):
        _add_ab()
        _capture(cmd_rate, _ns(topic="t", node="a", rating="good", grade="recalled",
                               kind="encode", production="x"))
        os.environ["ENGRAM_TODAY"] = "2026-07-27"                   # +21d
        _capture(cmd_rate, _ns(topic="t", node="a", rating="good", grade="recalled",
                               kind="review", production="x"))
        rs = read_jsonl(os.path.join(h, "receipts", "t.jsonl"))
        os.environ["ENGRAM_TODAY"] = "2026-07-06"
        return rs[0]["days_since_encode"] == 0 and rs[1]["days_since_encode"] == 21
    check("receipts stamp days_since_encode (0 at encode, elapsed at review)", fresh(_dse))

    # -- stats surfaces both new blocks, and leads with the binding constraint --
    def _stats_embeds(h):
        _add_ab()
        s = _capture_json(cmd_stats, _ns())
        keys = list(s.keys())
        return ("adherence" in s and "retention" in s
                and keys.index("adherence") < keys.index("recall_by_stability")
                and "loop_closure" in s["adherence"] and "unmeasured" in s["retention"])
    check("stats embeds adherence + retention, ahead of the older blocks",
          fresh(_stats_embeds))

    # ===== defects found by the v0.6 adversarial review (each check fails without its fix) =====

    # -- the dashboard must SHOW the two new numbers, not just compute them --
    # `stats` gained adherence+retention and the HTML report never consumed them, so /coach
    # dashboard still headlined a strength-bucketed retention with no `unmeasured` denominator.
    # A guard nobody reads is not a guard. (Found by adversarial review.)
    def _dashboard_shows_the_loop(h):
        _add_ab()
        _capture(cmd_rate, _ns(topic="t", node="a", rating="good", grade="recalled",
                               kind="encode", production="x"))
        os.environ["ENGRAM_TODAY"] = "2026-08-06"          # came due, never reviewed
        out = os.path.join(h, "d.html")
        _capture(cmd_report, _ns(out=out, allow_outside=False))
        html_text = open(out, encoding="utf-8").read()
        os.environ["ENGRAM_TODAY"] = "2026-07-06"
        low = html_text.lower()
        return ("the loop" in low
                and "never closed" in low                  # the binding constraint, stated
                and "came due and" in low                  # the unmeasured denominator, stated
                and "survivorship bias" in low)
    check("dashboard leads with loop_closure and voices the unmeasured denominator",
          fresh(_dashboard_shows_the_loop))
    # ===== v0.6.2: four defects found in RELEASED code by an independent reviewer =====

    # -- HIGH: the NORMAL apply path must not destroy a second, ungraded production --
    # v0.6.0 fixed this on the rare idempotent branch and left it live on the branch that runs
    # every single settle. A node can hold two stashed productions (re-attempt, park/resume);
    # draining by (topic, node) silently deleted the newer, never-graded one.
    def _settle_preserves_sibling_production(h):
        _add_ab()
        _capture(cmd_stash, _ns(action="add", json=json.dumps(
            {"topic": "t", "node": "a", "probe": "pa", "production": "P1"})))
        sid1 = _capture_json(cmd_stash, _ns(action="list"))[0]["sid"]
        _capture(cmd_stash, _ns(action="add", json=json.dumps(
            {"topic": "t", "node": "a", "probe": "pa", "production": "P2 never graded"})))
        write_json(os.path.join(h, "g.json"),
                   [{"topic": "t", "node": "a", "rating": "good", "grade": "recalled",
                     "kind": "encode", "sid": sid1, "production": "P1"}])
        _capture(cmd_receipt, _ns(file=os.path.join(h, "g.json")))       # the NORMAL path
        left = _capture_json(cmd_stash, _ns(action="list"))
        return len(left) == 1 and left[0]["production"] == "P2 never graded"
    check("a normal settle drains only its own sid (a sibling ungraded production survives)",
          fresh(_settle_preserves_sibling_production))

    # -- HIGH: `unmeasured` is PAST-DUE-NOW, not "never reviewed" --
    # v0.6.0 exempted a node the moment it was retrieved once. A learner who reviewed ten
    # concepts at day 7 and vanished for 200 days saw "measured over 10 retrievals · 100% ·
    # unmeasured 0 · coverage complete" while the engine's own decay put them at 56%.
    # Survivorship bias with a progress bar, inside the block written to prevent it.
    def _unmeasured_is_past_due_now(h):
        _add_ab()
        for n in ("a", "b"):
            _capture(cmd_rate, _ns(topic="t", node=n, rating="good", grade="recalled",
                                   kind="encode", production="x"))
        os.environ["ENGRAM_TODAY"] = "2026-07-13"           # +7d: review BOTH, both recalled
        for n in ("a", "b"):
            _capture(cmd_rate, _ns(topic="t", node=n, rating="good", grade="recalled",
                                   kind="review", production="x"))
        os.environ["ENGRAM_TODAY"] = "2027-01-28"           # …then vanish for 200 days
        r = _capture_json(cmd_retention, _ns())
        os.environ["ENGRAM_TODAY"] = "2026-07-06"
        u = r["unmeasured"]
        return (u["past_due_now"] == 2          # v0.6.0 said 0 — they were "already reviewed"
                and u["never_reviewed"] == 0    # …and correctly, none is virgin
                and 0.0 < u["projected_recall_now"] < 1.0
                and "past due and unretrieved" in r["read"])   # the debt reaches the narrator
    check("unmeasured counts PAST-DUE-NOW, not merely never-reviewed (the 56% lie)",
          fresh(_unmeasured_is_past_due_now))

    # -- MEDIUM: an invented `kind` is invisible to every metric AND append-only forever --
    check("receipt kind is validated (an invented kind dies before any write)",
          fresh(lambda h: (_add_ab(), raises(cmd_receipt, _ns(json=json.dumps(
              [{"topic": "t", "node": "a", "rating": "good", "kind": "revieww"}]))))[1]))
    check("a valid kind still applies",
          fresh(lambda h: (_add_ab(), _capture(cmd_receipt, _ns(json=json.dumps(
              [{"topic": "t", "node": "a", "rating": "good", "kind": "pretest"}]))),
              load_graph("t")["nodes"]["a"]["fsrs"]["reps"] == 1)[2]))

    # -- LOW: a backward clock step must not stamp a negative elapsed-day count, forever --
    def _dse_never_negative(h):
        _add_ab()
        _capture(cmd_rate, _ns(topic="t", node="a", rating="good", grade="recalled",
                               kind="encode", production="x"))          # day 0 = 2026-07-06
        os.environ["ENGRAM_TODAY"] = "2026-07-01"                       # clock steps BACKWARD
        _capture(cmd_rate, _ns(topic="t", node="a", rating="good", grade="recalled",
                               kind="review", production="x"))
        rs = read_jsonl(os.path.join(h, "receipts", "t.jsonl"))
        os.environ["ENGRAM_TODAY"] = "2026-07-06"
        return all(r.get("days_since_encode", 0) >= 0 for r in rs)
    check("days_since_encode is never negative (a backward clock cannot poison a receipt)",
          fresh(_dse_never_negative))

    # -- LOW: `commit --clear` combined with --cue silently cleared (elif made set unreachable) --
    check("commit --clear with --cue/--action is refused, not silently a clear",
          fresh(lambda h: raises(cmd_commit, _ns(cue="when X", action="do Y", clear=True))))
    # -- a node's FIRST receipt is its ENCODING, never a retention test (v0.6.1) --
    # `rate`'s --kind argparse default is "review". A bare CLI `rate` therefore writes a
    # node's ONLY receipt as kind=review — and loop_closure reported 1.0 ("the loop is
    # closing") for a learner who had never come back once. The metric built to say "you
    # never returned" said the opposite. That is the worst direction for it to be wrong in,
    # and it shipped in v0.6.0.
    def _first_receipt_is_never_a_review(h):
        _add_ab()
        _capture(cmd_rate, _ns(topic="t", node="a", rating="good", grade="recalled",
                               kind="review", production="x"))   # bare-CLI default kind
        os.environ["ENGRAM_TODAY"] = "2026-07-20"
        lc = _capture_json(cmd_adherence, _ns())["loop_closure"]
        ret = _capture_json(cmd_retention, _ns())
        never = (lc["encoded_past_due"] == 1 and lc["first_review_done"] == 0
                 and lc["rate"] == 0.0 and "NEVER CLOSED" in lc["read"]
                 and sum(b["n"] for b in ret["buckets"].values()) == 0)  # no retention claim
        # …and a genuine SECOND retrieval still closes the loop
        _capture(cmd_rate, _ns(topic="t", node="a", rating="good", grade="recalled",
                               kind="review", production="x"))
        lc2 = _capture_json(cmd_adherence, _ns())["loop_closure"]
        os.environ["ENGRAM_TODAY"] = "2026-07-06"
        return never and lc2["first_review_done"] == 1 and lc2["rate"] == 1.0
    check("a node's first receipt is its encoding, never a review (loop_closure cannot lie up)",
          fresh(_first_receipt_is_never_a_review))
    # -- the "idempotent no-op" must NOT destroy a second, ungraded production for the node --
    # drop_stash(topic, node) drains EVERY entry for that node. On the no-op path that is data
    # loss: a re-attempt stashed after the first settle would vanish, never graded. The guard
    # written to prevent corruption would itself have corrupted.
    def _noop_preserves_other_stash(h):
        _add_ab()
        _capture(cmd_stash, _ns(action="add", json=json.dumps(
            {"topic": "t", "node": "a", "probe": "pa", "production": "first try"})))
        sid1 = _capture_json(cmd_stash, _ns(action="list"))[0]["sid"]
        graded = [{"topic": "t", "node": "a", "rating": "good", "grade": "recalled",
                   "kind": "encode", "sid": sid1, "production": "first try"}]
        write_json(os.path.join(h, "g.json"), graded)
        _capture(cmd_receipt, _ns(file=os.path.join(h, "g.json")))          # applied
        # learner re-attempts the SAME node; a new production is stashed, ungraded
        _capture(cmd_stash, _ns(action="add", json=json.dumps(
            {"topic": "t", "node": "a", "probe": "pa", "production": "second try"})))
        _capture(cmd_receipt, _ns(file=os.path.join(h, "g.json")))          # crash-retry: no-op
        left = _capture_json(cmd_stash, _ns(action="list"))
        return (len(left) == 1 and left[0]["production"] == "second try"
                and left[0]["sid"] != sid1)
    check("idempotent no-op drops only its OWN sid (a newer ungraded production survives)",
          fresh(_noop_preserves_other_stash))

    # -- decay must REFUSE an unknown topic, never return a confident all-clear --
    check("decay --topic <unknown> errors instead of reporting 'nothing to lose'",
          fresh(lambda h: raises(cmd_decay, _ns(topic="nosuchtopic", horizon=30))))

    # -- decay prices the benefit over the DUE nodes only (not every encoded node) --
    def _decay_prices_only_due(h):
        _add_ab()
        _capture(cmd_rate, _ns(topic="t", node="a", rating="good", grade="recalled",
                               kind="encode", production="x"))     # due in ~4d
        _capture(cmd_rate, _ns(topic="t", node="b", rating="easy", grade="recalled",
                               kind="encode", production="x"))     # easy -> due far out
        os.environ["ENGRAM_TODAY"] = "2026-07-12"                  # only `a` is due
        d = _capture_json(cmd_decay, _ns(topic="t", horizon=30))
        os.environ["ENGRAM_TODAY"] = "2026-07-06"
        rows = {r["node"]: r for r in d["nodes"]}
        # the not-yet-due node must keep the SAME curve in both arms — reviewing it isn't
        # what the quoted minutes buy
        return (d["due_now"] == 1
                and rows["b"]["r_if_reviewed"] == rows["b"]["r_no_review"]
                and rows["a"]["r_if_reviewed"] > rows["a"]["r_no_review"])
    check("decay's benefit arm is priced over the DUE queue only (no overstated headline)",
          fresh(_decay_prices_only_due))

    # -- the coverage guard must be VOICED, not merely recorded --
    def _coverage_is_voiced(h):
        _add_ab()
        _capture(cmd_rate, _ns(topic="t", node="a", rating="good", grade="recalled",
                               kind="encode", production="x"))
        os.environ["ENGRAM_TODAY"] = "2026-07-27"
        _capture(cmd_rate, _ns(topic="t", node="a", rating="good", grade="recalled",
                               kind="review", production="x"))
        saved = list(RETENTION_BUCKETS)
        try:                                    # simulate a future regression to disjoint windows
            globals_ = sys.modules[cmd_retention.__module__].__dict__
            globals_["RETENTION_BUCKETS"] = (("30d", 25, 40),)   # day-21 review now falls in a gap
            r = _capture_json(cmd_retention, _ns())
        finally:
            globals_["RETENTION_BUCKETS"] = tuple(saved)
        os.environ["ENGRAM_TODAY"] = "2026-07-06"
        return (r["coverage"]["complete"] is False
                and "UNTRUSTWORTHY" in r["read"])   # ← the guard must reach the narrator
    check("retention coverage failure is VOICED in `read`, not silently recorded",
          fresh(_coverage_is_voiced))

    # -- ONE definition of "retained at 30 days" across the whole payload --
    # This used to say `>= 25 days` in the funnel while retention's 30d bucket said [15,59]:
    # two contradictory meanings of the same phrase shipping side by side in `stats`. The check
    # exercises the BEHAVIOUR (a day-20 review counts, a day-200 one does not), not the constant.
    def _retained_30d_matches_bucket(h):
        # The fixture is built so the OLD (`>= 25`, unbounded) and NEW ([15, 59]) definitions
        # genuinely DIVERGE — two reviews at day 20 (inside the window, but below 25) and one
        # at day 200 (above 25, but outside the window). Old -> 1. New -> 2. A fixture where
        # they coincide would let the regression back in, which is the whole failure mode here.
        g = {"topic": "t", "title": "T", "order": ["a", "b", "c"], "nodes": {
            "a": {"claim": "A", "probe": "pa"}, "b": {"claim": "B", "probe": "pb"},
            "c": {"claim": "C", "probe": "pc"}}}
        _capture(cmd_add_topic, _ns(json=json.dumps(g), replace=False))
        for node in ("a", "b", "c"):
            _capture(cmd_rate, _ns(topic="t", node=node, rating="good", grade="recalled",
                                   kind="encode", production="x"))          # day 0
        os.environ["ENGRAM_TODAY"] = "2026-07-26"                           # +20d: in [15,59], < 25
        for node in ("a", "b"):
            _capture(cmd_rate, _ns(topic="t", node=node, rating="good", grade="recalled",
                                   kind="review", production="x"))
        os.environ["ENGRAM_TODAY"] = "2027-01-22"                           # +200d: > 25, > 59
        _capture(cmd_rate, _ns(topic="t", node="c", rating="good", grade="recalled",
                               kind="review", production="x"))
        ad = _capture_json(cmd_adherence, _ns())
        ret = _capture_json(cmd_retention, _ns())
        os.environ["ENGRAM_TODAY"] = "2026-07-06"
        # the funnel's retained@30d must equal retention's own 30d bucket — one definition
        return (ad["funnel"]["nodes_retained_30d"] == 2      # old definition would say 1
                and ret["buckets"]["30d"]["n"] == 2
                and ret["buckets"]["180d+"]["n"] == 1)
    check("funnel.nodes_retained_30d uses retention's 30d window (one definition, not two)",
          fresh(_retained_30d_matches_bucket))

    # -- median is a median --
    check("median_gap_days is a true median (even-length lists average the middle two)",
          _median([1, 2, 3, 4]) == 2.5 and _median([1, 2, 3]) == 2 and _median([]) is None)

    # -- a receipt with a broken ts must not become the node's day-0 anchor --
    def _broken_ts_never_anchors(h):
        _add_ab()
        os.makedirs(p("receipts"), exist_ok=True)
        with open(p("receipts", "t.jsonl"), "w", encoding="utf-8") as f:
            f.write(json.dumps({"id": "r0", "ts": None, "topic": "t", "node": "a",
                                "kind": "encode", "rating": "good"}) + "\n")
            f.write(json.dumps({"id": "r1", "ts": "2026-07-06", "topic": "t", "node": "a",
                                "kind": "encode", "rating": "good",
                                "due_next": "2026-07-10"}) + "\n")
            f.write(json.dumps({"id": "r2", "ts": "2026-07-27", "topic": "t", "node": "a",
                                "kind": "review", "rating": "good", "grade": "recalled"}) + "\n")
        _RECEIPTS_CACHE.clear()
        by = _by_node(collect_receipts())
        first = by[("t", "a")]["first"]
        r = _capture_json(cmd_retention, _ns())
        # day 0 must be the REAL receipt, so the day-21 review lands in the 30d bucket
        return first["id"] == "r1" and r["buckets"]["30d"]["n"] == 1
    check("a receipt with a missing ts sorts last and never becomes the day-0 anchor",
          fresh(_broken_ts_never_anchors))
    # ================================================== THE COMMONS (v1.0)

    # ⚠⚠ THE PERMANENT SELFTEST. This one never gets deleted. ⚠⚠
    #
    # The README says the data is 100% local, and the reason anyone believes it is that the engine
    # CANNOT phone home — not that it currently chooses not to. This check makes that a property
    # of the source rather than a promise in a paragraph, and it runs on every single invocation
    # of `selftest`, forever. If a future release adds `import requests` to make one thing
    # convenient, this goes red before the feature ever ships.
    #
    # v1.0 could have grown a socket for `/coach contribute`. It did not. The AGENT posts — via
    # `gh`, which is already installed, already authenticated, and already trusted with the whole
    # machine — and `engram.py` writes a file and stops. That is not a loophole; it is the correct
    # place to put the boundary, because the thing the badge is ABOUT is this file.
    # Parsed as an **AST**, not grepped. A regex over the source finds the words in its OWN
    # comment and in its OWN pattern literal — the first draft of this check failed on itself,
    # which is funny exactly once and would have been a permanent red herring. The AST cannot see
    # a comment or a string; it sees only what the interpreter will actually execute. That is the
    # only thing a structural guarantee is allowed to be about.
    import ast as _ast
    _tree = _ast.parse(open(os.path.realpath(__file__), encoding="utf-8").read())
    _BANNED_MODULES = {
        "socket", "ssl", "select", "selectors", "asyncio",
        "urllib", "http", "requests", "aiohttp", "httpx", "websockets",
        "ftplib", "telnetlib", "smtplib", "poplib", "imaplib", "nntplib",
        "xmlrpc", "socketserver", "webbrowser", "ssl",
        "subprocess",                      # the engine never shells out — the AGENT runs `gh`
    }
    _imports, _shells = [], []
    for _n in _ast.walk(_tree):
        if isinstance(_n, _ast.Import):
            _imports += [a.name.split(".")[0] for a in _n.names]
        elif isinstance(_n, _ast.ImportFrom) and _n.module:
            _imports.append(_n.module.split(".")[0])
        elif isinstance(_n, _ast.Call):
            _f = _n.func
            # os.system(...) / os.popen(...) / os.exec*(...) / os.spawn*(...)
            if isinstance(_f, _ast.Attribute) and isinstance(_f.value, _ast.Name) \
                    and _f.value.id == "os" \
                    and (_f.attr in ("system", "popen")
                         or _f.attr.startswith("exec") or _f.attr.startswith("spawn")):
                _shells.append("os." + _f.attr)
    _net = sorted(set(_imports) & _BANNED_MODULES)
    check("⚠ THE ENGINE HAS NO NETWORK CODE — structural, permanent, and never to be deleted",
          not _net)
    # …and it does not shell out to one either. A `curl` inside an `os.system` would satisfy the
    # check above while phoning home just as hard.
    check("⚠ …and it never SHELLS OUT (no subprocess, no os.system/popen/exec/spawn)",
          not _shells)
    # HONEST ABOUT THE LIMIT (the reviewer's finding #3). This scan is a strong REGRESSION guard —
    # it catches the realistic way a network dependency creeps in (someone adds `import requests`
    # to make one thing convenient). It is NOT an impossibility proof: `__import__("socket")`,
    # `importlib.import_module`, `ctypes`, or `exec` of a string would all pass it green. So the
    # engine also contains NONE of those dynamic-import primitives — checked here, so the guarantee
    # is "no network code AND no way to smuggle one in dynamically", which the two checks together
    # actually support, rather than the broader claim a single import-scan cannot.
    _dyn = [n.id for n in _ast.walk(_tree)
            if isinstance(n, _ast.Name) and n.id in ("__import__", "eval", "exec", "compile")]
    _dyn += [n.func.attr for n in _ast.walk(_tree)
             if isinstance(n, _ast.Call) and isinstance(n.func, _ast.Attribute)
             and isinstance(n.func.value, _ast.Name)
             and n.func.value.id in ("importlib", "ctypes")]
    check("⚠ …and no DYNAMIC import escape hatch (__import__/eval/exec/compile/importlib/ctypes)",
          not _dyn)

    # -- the engine's version cannot drift from any plugin manifest --
    def _version_matches_all_manifests(_h=None):
        for rel in (".claude-plugin/plugin.json",
                     ".codex-plugin/plugin.json",
                     "package.json"):
            mf = os.path.join(_plugin_root(), rel)
            if not os.path.exists(mf):
                continue
            if json.load(open(mf, encoding="utf-8"))["version"] != ENGRAM_VERSION:
                return False
        return True
    check("ENGRAM_VERSION matches all plugin manifests (claude-plugin, codex-plugin, package.json)",
          _version_matches_all_manifests)

    # -- ⚠ PROPERTY-BASED: put text in EVERY field. Assert NONE of it survives the export. --
    # Not "we remembered to delete the productions" — there must be no code path by which one
    # could arrive. The payload is constructed BY NAME from a whitelist, which is the same lesson
    # `gold` taught in v0.7 and the reason both are built the same way: a blacklist is a promise
    # you must keep every release; a whitelist is one you keep by construction.
    def _export_leaks_nothing(h):
        SECRET = "CANARY-7f3a-DO-NOT-LEAK"
        # v1.0.0 shipped a LEAK here and this test passed anyway — because it never started an
        # experiment, so `arm` and `stratum` (the two free-text keys that leak) were always None.
        # **It asserted the whitelist keys were clean by never populating them.** The fix to the
        # test is the fix to the class: put the canary in EVERY authored surface, including the
        # experiment arm and a stratum pointed at a text-bearing node field, which is the exact
        # path the reviewer used (`stratify_by: ["claim"]` routed a node's claim into the export).
        g = {"topic": "t", "title": SECRET, "goal": SECRET, "order": ["a", "b"], "nodes": {
            "a": {"claim": SECRET, "probe": SECRET, "rubric": [SECRET], "transfer_probe": SECRET,
                  "why_chain": [SECRET], "secret_architect_field": SECRET},   # arbitrary payload field
            "b": {"claim": SECRET, "probe": SECRET, "rubric": [SECRET],
                  "edges": {"requires": ["a"]}}}}
        write_json(p("payload.json"), g)
        _capture(cmd_add_topic, _ns(file=p("payload.json"), replace=False))
        # an experiment whose ARM is learner-authored text, stratified on TEXT-BEARING node fields
        _capture(cmd_experiment, _ns(action="start", file=None, json=json.dumps({
            "question": SECRET, "arms": [SECRET, "control"], "metric": "first_review_recall",
            "seed": SECRET, "stratify_by": ["claim", "secret_architect_field"]}),
            topic=None, node=None, id=None, verdict=None))
        for nid in ("a", "b"):
            _capture(cmd_experiment, _ns(action="assign", topic="t", node=nid, json=None,
                                         file=None, id=None, verdict=None))
            _capture(cmd_rate, _ns(topic="t", node=nid, rating="good", grade="recalled",
                                   kind="encode", production=SECRET, probe=SECRET, confidence=70))
        # a receipt with the canary in every field the schema has AND a field it doesn't, AND a
        # hand-forged `grader` string (which `export` used to copy uncapped)
        append_jsonl(p("receipts", "t.jsonl"), {
            "id": "r_x", "ts": "2026-07-20", "topic": "t", "node": "a", "kind": "review",
            "rating": "good", "grade": "recalled",
            "production": SECRET, "probe": SECRET, "claim": SECRET, "rubric": [SECRET],
            "rubric_notes": SECRET, "feedback_line": SECRET, "misconceptions": [SECRET],
            "grader": SECRET, "a_field_invented_in_v1_2": SECRET,
        })
        _RECEIPTS_CACHE.clear()
        _capture(cmd_misconception, _ns(action="add", topic="t", node="a", json=None, file=None,
                                        description=SECRET, id=None))
        _capture(cmd_model, _ns(set=None, add_goal=SECRET, add_interest=SECRET, json=None,
                                file=None))
        # a PASSING audit, so the export gate opens
        gold = [_gitem("e%02d" % i, _ORD[i % 3]) for i in range(33)]
        run = [{"sid": g2["sid"], "grade": g2["gold_grade"]} for g2 in gold]
        _audit(h, gold, [run, run, run])
        res = _capture_json(cmd_export, _ns(topic=None, contributor="@me",
                                            allow_unvalidated=False))
        blob = open(res["path"], encoding="utf-8").read()
        bundle = json.loads(blob)
        keys = {k for r in bundle["receipts"] for k in r}
        # …and the receipts must actually be POPULATED, or the test proves nothing again
        populated = any(r.get("arm_hash") and r.get("stratum_hash") for r in bundle["receipts"])
        return (SECRET not in blob                          # ← THE PROPERTY, over ALL surfaces
                and "transformers" not in blob              # (no topic strings, ever)
                and keys == set(EXPORT_RECEIPT_KEYS)        # …by construction, not by deletion
                and populated                               # arm_hash/stratum_hash actually set
                and "t" not in {r.get("topic_hash") for r in bundle["receipts"]}
                and bundle["stripped"]                      # the promise ships INSIDE the file
                and "arm_label" in bundle["stripped"]       # …and it NAMES the once-leaking fields
                and "stratum_label" in bundle["stripped"]
                and bundle["attributed"] is True
                and bundle["contributor"] == "@me"
                and bundle["n_receipts"] == 3)
    check("⚠ EXPORT LEAKS NOTHING: text in every field — INCLUDING arm & stratum — and none survives",
          fresh(_export_leaks_nothing))

    # -- v0.7 GATES v1.0: an unaudited oracle may not contribute. It is a REFUSAL, not a warning. --
    def _export_refuses_an_unvalidated_grader(h):
        _add_ab()
        _capture(cmd_rate, _ns(topic="t", node="a", rating="good", grade="recalled",
                               kind="encode", production="x"))
        try:
            _capture(cmd_export, _ns(topic=None, contributor=None, allow_unvalidated=False))
            return False                       # it exported data from an oracle nobody checked
        except SystemExit:
            pass
        no_file = not os.path.isdir(p("exports")) or not os.listdir(p("exports"))
        # …and a FAILED audit is refused just as hard as an absent one
        gold = [_gitem("f%02d" % i, "partial") for i in range(33)]
        run = [{"sid": g["sid"], "grade": "recalled"} for g in gold]      # inflates everything
        a = _audit(h, gold, [run, run, run])
        try:
            _capture(cmd_export, _ns(topic=None, contributor=None, allow_unvalidated=False))
            return False
        except SystemExit:
            pass
        # …and once it PASSES, the gate opens
        gold2 = [_gitem("g%02d" % i, _ORD[i % 3]) for i in range(33)]
        run2 = [{"sid": g["sid"], "grade": g["gold_grade"]} for g in gold2]
        _audit(h, gold2, [run2, run2, run2])
        res = _capture_json(cmd_export, _ns(topic=None, contributor=None,
                                            allow_unvalidated=False))
        return (no_file and a["verdict"] == "fail" and res["ok"] is True
                and res["grader_qwk"] == 1.0)
    check("⚠ v0.7 GATES v1.0: `export` REFUSES an unaudited or failed grader (a refusal, not a warning)",
          fresh(_export_refuses_an_unvalidated_grader))

    # -- every shared receipt carries its oracle's MEASURED validity --
    def _every_receipt_carries_its_graders_qwk(h):
        _add_ab()
        # one ASSESSOR-graded receipt (carries `grader`) …
        _capture(cmd_receipt, _ns(json=json.dumps([{
            "topic": "t", "node": "a", "rating": "good", "grade": "recalled",
            "kind": "encode", "production": "x", "grader": "engram-assessor"}])))
        # … and one TUTOR-graded receipt (the /review path: no `grader`, source self)
        _capture(cmd_rate, _ns(topic="t", node="b", rating="good", grade="recalled",
                               kind="encode", production="y"))
        gold = [_gitem("h%02d" % i, _ORD[i % 3]) for i in range(33)]
        # a grader that is right 32/33 -> a real, sub-1.0 QWK
        run = [{"sid": g["sid"],
                "grade": ("partial" if g["sid"] == "h00" and g["gold_grade"] == "lapsed"
                          else g["gold_grade"])} for g in gold]
        a = _audit(h, gold, [run, run, run])
        res = _capture_json(cmd_export, _ns(topic=None, contributor=None,
                                            allow_unvalidated=False))
        b = json.load(open(res["path"], encoding="utf-8"))
        graded = [r for r in b["receipts"] if r["grader_hash"]]
        selfg = [r for r in b["receipts"] if not r["grader_hash"]]
        return (a["verdict"] in ("pass", "warn")
                and 0 < a["qwk"] < 1.0
                # the audited oracle's receipts carry its MEASURED validity …
                and graded and all(r["grader_qwk"] == a["qwk"] and r["self_graded"] is False
                                   for r in graded)
                # … and the tutor's carry NULL and say so: stamping the assessor's QWK on a
                # verdict the assessor never wrote is a borrowed credential (v1.1.1)
                and selfg and all(r["grader_qwk"] is None and r["self_graded"] is True
                                  for r in selfg)
                and b["grader"]["qwk"] == a["qwk"]
                # …and the gold set's own circularity limit rides along with it
                and b["grader"]["gold_adjudication"] == "authored")
    check("every SHARED receipt carries its grader's MEASURED QWK (a finding from an unaudited oracle is not one)",
          fresh(_every_receipt_carries_its_graders_qwk))

    # -- READ PATHS DEGRADE, NEVER BRICK (hardened in v0.6 after a 3000-state fuzz) --
    # A hand-edited state file can be perfectly valid JSON with the WRONG TYPES: `nodes` as a
    # string, `fsrs` as a list, an unhashable `topic`, a `rating` that is a dict. Every one of
    # those raised TypeError/AttributeError and took `stats` — and therefore /coach — down with
    # it. Several were pre-existing (compute_momentum since v0.4, due_items since v0.1); v0.6
    # widened the blast radius by making `stats` call adherence/retention too.
    # `doctor` is the thing that REPORTS corruption; `stats` is not allowed to die of it.
    def _reads_survive_garbage(h):
        os.makedirs(p("graphs"), exist_ok=True); os.makedirs(p("receipts"), exist_ok=True)
        write_json(p("graphs", "bad.json"), {
            "topic": "bad", "title": {"not": "a string"}, "goal": ["nor", "this"],
            "order": ["a", {"unhashable": 1}, 42, "ghost", "d", "e", "f"],
            "nodes": {"a": {"claim": "c", "probe": "p", "state": 5, "fsrs": "not-a-dict"},
                      "b": ["not", "a", "node"], "c": None,
                      "d": {"claim": "c", "probe": "p", "state": "review",
                            "fsrs": {"s": "NaN", "due": 0, "last": [], "reps": {}}},
                      # an UNHASHABLE state: `st not in STATE_DOTS` raises TypeError and took
                      # the dashboard down. state_counts() was guarded; cmd_report was not.
                      "e": {"claim": "c", "probe": "p", "state": {}, "fsrs": {}},
                      "f": {"claim": "c", "probe": "p", "state": ["x"], "fsrs": {}},
                      # v1.1 garbage: unhashable kind, non-dict practice — node_kind_of and
                      # the due/report paths must degrade, never brick
                      "g": {"claim": "c", "probe": "p", "state": "review", "fsrs": {},
                            "kind": {"un": "hashable"}, "practice": 42},
                      "h2": {"claim": "c", "probe": "p", "state": "review", "fsrs": {},
                             "kind": ["procedure"], "practice": ["x"]}}})
        write_json(p("graphs", "worse.json"), {"topic": "worse", "nodes": "not-an-object"})
        with open(p("receipts", "bad.jsonl"), "w", encoding="utf-8") as f:
            f.write(json.dumps({"ts": 20260701, "topic": {"x": 1}, "node": ["y"],
                                "kind": "review", "rating": {"bad": 1}, "grade": ["worse"],
                                "s_before": "NaN", "sid": [],
                                "node_kind": {"un": "hashable"},
                                "error_class": ["slip"]}) + "\n")
            f.write("THIS LINE IS NOT JSON\n")
            f.write(json.dumps({"ts": "2026-07-01", "topic": "bad", "node": "a",
                                "kind": "review", "rating": "good"}) + "\n")
            # an UN-SCOREABLE first review: truthy non-rating, no grade -> _outcome() is None.
            # This is the exact receipt that bricked compute_modality (v1.0.2). A read path that
            # sums _outcome() must drop it, not add it. (`ghost` is a fresh node id so this IS its
            # first receipt — the case modality's per-node first-review logic actually hits.)
            f.write(json.dumps({"ts": "2026-06-15", "topic": "bad", "node": "ghost",
                                "kind": "review", "rating": "excellent", "grade": None}) + "\n")
        write_json(p("misconceptions.json"), "not-a-list")
        write_json(p("experiments.json"), {"not": "a list"})
        # v0.7 surfaces: a hand-edited gold set and a corrupt audit must not brick /coach.
        # `stats` now calls compute_grader_health(), so a garbage audits/ file is on the
        # path of EVERY read — the blast radius of a corrupt file just got wider.
        os.makedirs(p("gold"), exist_ok=True); os.makedirs(p("audits"), exist_ok=True)
        with open(p("gold", "local-gold.jsonl"), "w", encoding="utf-8") as f:
            f.write(json.dumps({"sid": ["not", "a", "string"], "gold_grade": 7,
                                "rubric": "not-a-list", "claim": None}) + "\n")
            f.write("NOT JSON EITHER\n")
            f.write(json.dumps(["not", "even", "an", "object"]) + "\n")
        with open(p("audits", "2099-01-01-01.json"), "w", encoding="utf-8") as f:
            f.write('{"verdict": {"unhashable": 1}, "qwk": "NaN", "grader_unvalidated": []}')
        _RECEIPTS_CACHE.clear()
        # every read path must RETURN, not raise
        for fn, ns in ((cmd_stats, _ns()), (cmd_adherence, _ns()), (cmd_retention, _ns()),
                       (cmd_decay, _ns(topic=None, horizon=30)), (cmd_topics, _ns()),
                       (cmd_due, _ns(topic=None, limit=None)), (cmd_session_start, _ns()),
                       (cmd_gold, _ns()), (cmd_grader_health, _ns()),
                       (cmd_report, _ns(out=None, allow_outside=False))):
            _capture(fn, ns)                  # an exception here fails the check, as intended
        # a corrupt audit must read `unreadable` — NOT be believed, and NOT be skipped over
        # in favour of an older, rosier one
        gh = _capture_json(cmd_grader_health, _ns())
        # …and doctor must REPORT the corruption rather than silently swallow it
        doc = _capture_json(cmd_doctor, _ns())
        return (doc["ok"] is False and len(doc["issues"]) >= 2
                and gh["grader_unvalidated"] is True and gh["verdict"] == "unreadable")
    check("read paths degrade on type-corrupt state (stats/adherence/retention/decay/report/hook/gold/grader-health)",
          fresh(_reads_survive_garbage))

    # -- THE SINGLE-TOPIC GATE: `next` and `topic-status` degrade too (v0.7) --
    # v0.6 hardened `iter_graphs` — the gate every AGGREGATE read funnels through — and stopped
    # there. `load_graph`, the gate every SINGLE-TOPIC command funnels through, had no shape
    # check at all. A v0.7 fuzz run found 447 crashes in 300 garbage states ON SHIPPED MAIN,
    # every one of them in `next` or `topic-status` — and `next` is what /learn calls at the
    # start of EVERY session. The v0.6 fuzz list was written from the /coach surface and simply
    # forgot the /learn surface: the list you write is the list you already thought of.
    def _single_topic_reads_survive_garbage(h):
        os.makedirs(p("graphs"), exist_ok=True)
        # a graph that is valid JSON and structurally poisonous in every way at once
        write_json(p("graphs", "t.json"), {
            "topic": "t", "title": {"not": "a string"},
            "order": ["a", {"unhashable": 1}, 42, "ghost", "b", "c", None],
            "nodes": {
                "a": {"claim": "c", "probe": "p", "state": {}, "fsrs": "not-a-dict",
                      "edges": "not-a-dict"},
                "b": ["not", "a", "node"],
                "c": {"claim": "c", "probe": "p", "state": "new",
                      "edges": {"requires": [{"d": 1}, "a", 7]}},   # unhashable req
                "d": None}})
        with open(p(STASH_FILE), "w", encoding="utf-8") as f:
            f.write(json.dumps({"topic": "t", "node": ["unhashable"]}) + "\n")
            f.write("NOT JSON\n")
            f.write(json.dumps(["not", "an", "object"]) + "\n")
        nxt = _capture_json(cmd_next, _ns(topic="t"))          # must RETURN, not raise
        _capture(cmd_topic_status, _ns(topic="t"))             # must RETURN, not raise
        # `c` is the only usable `new` node; its garbage requires are skipped, `a` is not new
        frontier_ok = nxt["id"] == "c"
        # a graph whose `nodes` is not an object is a guarded REFUSAL, never an AttributeError
        write_json(p("graphs", "u.json"), {"topic": "u", "nodes": "not-an-object"})
        try:
            _capture(cmd_next, _ns(topic="u"))
            refused = False
        except SystemExit:
            refused = True
        # …and rating a corrupt node REFUSES rather than writing FSRS state onto garbage
        try:
            _capture(cmd_rate, _ns(topic="t", node="b", rating="good", grade="recalled",
                                   kind="encode", production="x"))
            declined = False
        except SystemExit:
            declined = True
        return frontier_ok and refused and declined
    check("single-topic reads degrade on type-corrupt graphs (next/topic-status never brick)",
          fresh(_single_topic_reads_survive_garbage))

    # -- the scheduler's own counters survive a hand-edit (reps/lapses were raw arithmetic) --
    def _corrupt_counters_dont_crash_the_scheduler(h):
        out, _ = apply_rating({"s": 5.0, "d": 5.0, "last": "2026-06-01",
                               "reps": "many", "lapses": [7]}, "again", today())
        recovered = out["reps"] == 1 and out["lapses"] == 1     # counters re-anchored, not crashed
        # and negatives can never be resurrected into the schedule
        out2, _ = apply_rating({"reps": -9, "lapses": -4}, "good", today())
        return recovered and out2["reps"] == 1 and out2["lapses"] == 0
    check("corrupt reps/lapses re-anchor instead of crashing the scheduler",
          lambda: _corrupt_counters_dont_crash_the_scheduler(None))
    # -- applying a receipt self-drains the stash (F3 adjacent) --
    def _stash_self_clean(h):
        _add_ab()
        _capture(cmd_stash, _ns(action="add", json=json.dumps(
            {"topic": "t", "node": "a", "probe": "pa", "production": "ans a"})))
        _capture(cmd_rate, _ns(topic="t", node="a", rating="good", grade="recalled", kind="encode"))
        return _capture_json(cmd_stash, _ns(action="count"))["pending"] == 0
    check("applying a receipt self-drains the matching stash entry", fresh(_stash_self_clean))

    # -- receipt batch is atomic: a bad item commits nothing (R6/H2) --
    def _batch_atomic(h):
        _add_ab()
        batch = [{"topic": "t", "node": "a", "rating": "good"},
                 {"topic": "t", "node": "NOPE", "rating": "good"}]
        rejected = raises(cmd_receipt, _ns(json=json.dumps(batch)))
        reps = load_graph("t")["nodes"]["a"]["fsrs"].get("reps", 0)
        return rejected and reps == 0
    check("receipt batch is atomic (bad item commits nothing)", fresh(_batch_atomic))

    # -- receipt is written before state advances (issue #1.2/S2) --
    def _receipt_first(h):
        _add_ab()
        gl = globals()
        orig = gl["append_jsonl"]
        def boom(*a, **k):
            raise OSError("simulated crash writing receipt")
        gl["append_jsonl"] = boom
        try:
            _capture(cmd_rate, _ns(topic="t", node="a", rating="good",
                                   grade="recalled", kind="encode"))
        except OSError:
            pass
        finally:
            gl["append_jsonl"] = orig
        node = load_graph("t")["nodes"]["a"]
        return node["state"] == "new" and node["fsrs"]["s"] is None
    check("receipt write precedes state advance (crash costs only a re-review)",
          fresh(_receipt_first))

    # -- model --set can't clobber a dict with a scalar or wreck the scheduler (R4/R7) --
    def _model_guard(h):
        rejected = raises(cmd_model, _ns(set=["memory=5"]))
        still_works = isinstance(_capture_json(cmd_model, _ns())["memory"], dict)
        _capture(cmd_model, _ns(set=["memory.desired_retention=0"]))
        ret = _capture_json(cmd_model, _ns())["memory"]["desired_retention"]
        _add_ab()
        _capture(cmd_rate, _ns(topic="t", node="a", rating="good", kind="encode"))  # must not crash
        return rejected and still_works and RETENTION_MIN <= ret <= RETENTION_MAX
    check("model --set refuses dict-clobber and clamps retention", fresh(_model_guard))

    # -- learner model self-heals a deleted subtree (M12) --
    def _model_heal(h):
        _capture(cmd_model, _ns(add_interest=["keepme"]))
        mfile = os.path.join(h, "learner-model.json")
        data = read_json(mfile); del data["interests"]; write_json(mfile, data)
        healed = _capture_json(cmd_model, _ns())
        return isinstance(healed.get("interests"), list)
    check("learner model self-heals a deleted key", fresh(_model_heal))

    # -- --add-goal writes the orphan field (issue #2.5) --
    def _add_goal(h):
        _capture(cmd_model, _ns(add_goal=["ship it", "ship it"]))
        goals = _capture_json(cmd_model, _ns())["goals"]
        return goals == ["ship it"]
    check("model --add-goal appends (dedup) to the goals list", fresh(_add_goal))

    # -- corrupt learner-model.json is quarantined, not silently discarded (issue #1.4) --
    def _corrupt_model(h):
        _capture(cmd_model, _ns(add_interest=["keepme"]))
        with open(os.path.join(h, "learner-model.json"), "w") as f:
            f.write("{not valid json")
        _capture(cmd_model, _ns())  # triggers load_model -> quarantine + rebuild
        backups = [f for f in os.listdir(h) if f.startswith("learner-model.json.corrupt.")]
        return len(backups) == 1
    check("corrupt learner model is quarantined to .corrupt", fresh(_corrupt_model))

    # -- one corrupt graph doesn't brick aggregate views or the hook (R9) --
    def _corrupt_graph(h):
        _add_ab()
        with open(os.path.join(h, "graphs", "zbad.json"), "w") as f:
            f.write("{broken")
        ok = True
        for fn in (cmd_topics, cmd_stats, cmd_session_start):
            try:
                _capture(fn, _ns())
            except SystemExit:
                ok = False
        return ok
    check("corrupt graph is skipped by aggregate views (no crash)", fresh(_corrupt_graph))

    # -- malformed dates and ghost order ids survive read paths (N1/N2) --
    def _bad_state_survives(h):
        g = {"topic": "t", "title": "T", "order": ["a", "ghost"], "nodes": {"a": {
            "claim": "c", "probe": "p"}}}
        # write directly to bypass add-topic validation (simulate hand-edit/corruption)
        _capture(cmd_add_topic, _ns(json=json.dumps(
            {"topic": "t", "title": "T", "order": ["a"], "nodes": {"a": {"claim": "c", "probe": "p"}}})))
        gf = os.path.join(h, "graphs", "t.json")
        data = read_json(gf)
        data["order"] = ["a", "ghost"]
        data["nodes"]["a"]["state"] = "review"
        data["nodes"]["a"]["fsrs"] = {"s": 3.0, "d": 5.0, "due": "NOT-A-DATE",
                                      "last": "bad", "reps": 1, "lapses": 0}
        write_json(gf, data)
        ok = True
        for fn, ns in ((cmd_topics, _ns()), (cmd_due, _ns()),
                       (cmd_topic_status, _ns(topic="t")), (cmd_report, _ns()),
                       (cmd_next, _ns(topic="t"))):
            try:
                _capture(fn, ns)
            except (SystemExit, KeyError, ValueError):
                ok = False
        return ok
    check("ghost order id + malformed dates survive every read path", fresh(_bad_state_survives))

    # -- experiment guards: >=2 DISTINCT arms, a KNOWN metric, one active at a time (SEC-06) --
    def _experiment_guard(h):
        M = "first_review_recall"
        empty = raises(cmd_experiment, _ns(action="start", file=None,
                       json=json.dumps({"question": "q", "arms": [], "metric": M})))
        dupes = raises(cmd_experiment, _ns(action="start", file=None,
                       json=json.dumps({"question": "q", "arms": ["x", "x"], "metric": M})))
        # v0.9: an UNKNOWN metric dies rather than being silently computed as something else —
        # the engine will not guess which number you meant and then report it as fact.
        unknown = raises(cmd_experiment, _ns(action="start", file=None,
                         json=json.dumps({"question": "q", "arms": ["x", "y"], "metric": "vibes"})))
        _capture(cmd_experiment, _ns(action="start", file=None, json=json.dumps(
            {"question": "q", "arms": ["x", "y"], "metric": M})))
        second = raises(cmd_experiment, _ns(action="start", file=None, json=json.dumps(
            {"question": "q2", "arms": ["x", "y"], "metric": M})))
        return empty and dupes and unknown and second
    check("experiment requires >=2 distinct arms, a KNOWN metric, one active at a time",
          fresh(_experiment_guard))

    # -- report --out is confined to home unless --allow-outside (SEC-08) --
    def _out_confined(h):
        outside = os.path.join(os.path.dirname(h), "escape.html")
        blocked = raises(cmd_report, _ns(out=outside))
        allowed = _capture_json(cmd_report, _ns(out=outside, allow_outside=True))
        try:
            os.remove(outside)
        except OSError:
            pass
        return blocked and allowed["ok"] is True
    check("report --out confined to home unless --allow-outside", fresh(_out_confined))

    # -- production truncation is flagged, not silent (issue #2.6) --
    r_trunc = make_receipt({"topic": "t", "node": "a", "rating": "good",
                            "production": "x" * (PRODUCTION_MAX + 50)}, {}, "encode")
    check("long production is truncated with a marker",
          len(r_trunc["production"]) == PRODUCTION_MAX and r_trunc.get("production_truncated") is True)

    # -- due --limit 0 means zero, not "all" (N6) --
    def _limit_zero(h):
        _add_ab()
        _capture(cmd_rate, _ns(topic="t", node="a", rating="good", kind="encode"))
        os.environ["ENGRAM_TODAY"] = "2026-09-01"
        return len(due_items(limit=0)) == 0 and len(due_items()) >= 1
    check("due --limit 0 returns nothing (not everything)", fresh(_limit_zero))

    # -- ids carry pid and never collide in a batch --
    check("generated ids embed pid and are unique",
          str(os.getpid()) in gen_id("r") and gen_id("r") != gen_id("r"))

    # ============ 0.5.0 visual-encoding layer checks ============

    # -- artifact registration: engine-owned, validated, home-relative, replace-safe --
    def _artifact_lifecycle(h):
        _add_ab()
        missing = raises(cmd_artifact, _ns(action="set", topic="t", node="a",
                                           path=os.path.join(h, "nope.html")))
        apath = os.path.join(h, "artifacts", "t", "a.html")
        os.makedirs(os.path.dirname(apath), exist_ok=True)
        with open(apath, "w") as f:
            f.write("<!doctype html>")
        _capture(cmd_artifact, _ns(action="set", topic="t", node="a", path=apath))
        stored = load_graph("t")["nodes"]["a"]["artifact"]
        rel = stored == os.path.join("artifacts", "t", "a.html")
        lst = _capture_json(cmd_artifact, _ns(action="list"))
        listed = len(lst) == 1 and lst[0]["exists"] is True
        # restructure the topic: a payload-supplied artifact is stripped, and the
        # real registration survives --replace exactly like the schedule does
        g2 = {"topic": "t", "title": "T2", "order": ["a", "b"], "nodes": {
            "a": {"claim": "A", "probe": "pa", "artifact": "../evil.html"},
            "b": {"claim": "B", "probe": "pb"}}}
        _capture(cmd_add_topic, _ns(json=json.dumps(g2), replace=True))
        kept = load_graph("t")["nodes"]["a"]["artifact"] == stored
        _capture(cmd_artifact, _ns(action="clear", topic="t", node="a"))
        cleared = load_graph("t")["nodes"]["a"]["artifact"] is None
        return missing and rel and listed and kept and cleared
    check("artifact set validates+relativizes, survives --replace, clears",
          fresh(_artifact_lifecycle))

    # -- receipts stamp the medium at grading time, never retroactively --
    def _receipt_stamp(h):
        _add_ab()
        _capture(cmd_rate, _ns(topic="t", node="a", rating="good",
                               grade="recalled", kind="encode"))
        apath = os.path.join(h, "artifacts", "t", "a.html")
        os.makedirs(os.path.dirname(apath), exist_ok=True)
        with open(apath, "w") as f:
            f.write("x")
        _capture(cmd_artifact, _ns(action="set", topic="t", node="a", path=apath))
        _capture(cmd_rate, _ns(topic="t", node="a", rating="good",
                               grade="recalled", kind="review"))
        rs = collect_receipts()
        pre = [r for r in rs if r["kind"] == "encode"][0]
        post = [r for r in rs if r["kind"] == "review"][0]
        return "artifact" not in pre and post.get("artifact") is True
    check("receipt stamps artifact-at-grading-time only after registration",
          fresh(_receipt_stamp))

    # -- modality telemetry: guarded read, arm split, first-review-per-node only --
    mod_thin = compute_modality([
        {"id": "e", "ts": "2026-06-01", "kind": "encode", "rating": "good",
         "topic": "t", "node": "a"},
        {"id": "r", "ts": "2026-07-01", "kind": "review", "rating": "good",
         "topic": "t", "node": "a", "artifact": True}])
    check("modality guarded on thin data",
          mod_thin["read"] == "insufficient-data" and mod_thin["explorable"]["n"] == 1)
    syn = []
    # v0.9: the floor moved 6 -> 15 (MODALITY_MIN_N == EXPERIMENT_MIN_PER_ARM). Six per arm was
    # ~2.5x under the SCED power requirement, and a medium verdict read off six data points is
    # not "suggestive" — it is noise with a caveat stapled to it. The fixture moves with the floor,
    # and a check BELOW the floor is asserted separately (see the next check).
    for i in range(MODALITY_MIN_N):
        # every node gets its ENCODE receipt first — a first receipt is never a review
        syn.append({"id": "ee%d" % i, "ts": "2026-06-01", "kind": "encode", "rating": "good",
                    "topic": "t", "node": "e%d" % i, "artifact": True})
        syn.append({"id": "ed%d" % i, "ts": "2026-06-01", "kind": "encode", "rating": "good",
                    "topic": "t", "node": "d%d" % i})
        syn.append({"id": "re%d" % i, "ts": "2026-07-01", "kind": "review", "rating": "good",
                    "topic": "t", "node": "e%d" % i, "artifact": True})
        syn.append({"id": "re%db" % i, "ts": "2026-07-02", "kind": "review", "rating": "again",
                    "topic": "t", "node": "e%d" % i, "artifact": True})  # 2nd review: ignored
        syn.append({"id": "rd%d" % i, "ts": "2026-07-01", "kind": "review", "rating": "again",
                    "topic": "t", "node": "d%d" % i})
    mod = compute_modality(syn)
    check("modality splits arms on first review only",
          mod["explorable"]["n"] == MODALITY_MIN_N
          and mod["explorable"]["first_review_recall"] == 1.0
          and mod["dialogue"]["n"] == MODALITY_MIN_N
          and mod["dialogue"]["first_review_recall"] == 0.0
          and mod["read"] == "explorable-encoded ahead")
    # -- v0.9: the OLD floor (6/arm) must now read insufficient-data, not a verdict --
    # Raising this SUPPRESSES a number some existing learners can currently see. That is correct:
    # the number was never earned. Suppressing an unearned number is not a regression; it is the
    # product. (docs/10 predicted this: "stats.modality's identical >=6 floor inherits the same
    # defect and moves with it.")
    check("modality at the OLD 6-per-arm floor now reads insufficient-data (it was never powered)",
          compute_modality([r for r in syn
                            if int(r["node"][1:]) < 6])["read"] == "insufficient-data")
    check("stats exposes the modality block",
          fresh(lambda h: _capture_json(cmd_stats, _ns())["modality"]["read"]
                == "insufficient-data"))
    # the confound ships WITH the number, in every read state — a narrator reading
    # only this JSON cannot report the verdict without also seeing why it's soft
    check("modality carries its confound caveat in every read state",
          all("not randomized" in m["caveat"] for m in (mod, mod_thin))
          and "not randomized" in fresh(
              lambda h: _capture_json(cmd_stats, _ns())["modality"])()["caveat"])

    # -- visuals dial round-trips and reports --
    def _visuals(h):
        _capture_json(cmd_visuals, _ns(action="eager"))
        m1 = read_json(os.path.join(h, "learner-model.json"))["settings"]["artifacts"]
        _capture_json(cmd_visuals, _ns(action="threshold"))
        m2 = read_json(os.path.join(h, "learner-model.json"))["settings"]["artifacts"]
        o = _capture_json(cmd_visuals, _ns(action="off"))
        s = _capture_json(cmd_visuals, _ns(action="status"))
        return (m1 == "eager" and m2 == "threshold-only" and o["artifacts"] == "off"
                and s["artifacts"] == "off" and "note" in s)
    check("visuals eager/threshold/off round-trip via the wrapper", fresh(_visuals))

    # -- viz hint: object kept verbatim, non-object dropped with a warning --
    def _viz_hint(h):
        g2 = {"topic": "t", "title": "T", "order": ["a", "b"], "nodes": {
            "a": {"claim": "A", "probe": "pa",
                  "viz": {"affordance": "high", "kind": "dynamic", "hook": "slider"}},
            "b": {"claim": "B", "probe": "pb", "viz": "very visual"}}}
        out = json.loads(_capture(cmd_add_topic, _ns(json=json.dumps(g2))))
        saved = load_graph("t")["nodes"]
        return (saved["a"]["viz"]["affordance"] == "high" and saved["b"]["viz"] is None
                and any("viz" in w for w in out["warnings"]))
    check("viz hint: object kept, non-object dropped with warning", fresh(_viz_hint))

    # -- due payload carries artifact presence (review re-encode path reads it) --
    def _due_artifact_flag(h):
        _add_ab()
        _capture(cmd_rate, _ns(topic="t", node="a", rating="good", kind="encode"))
        os.environ["ENGRAM_TODAY"] = "2026-09-01"
        return due_items()[0]["artifact"] is False
    check("due payload carries artifact presence flag", fresh(_due_artifact_flag))

    # -- doctor: unregistered / dangling / garbage artifacts are all NOTES with a
    #    pasteable fix (doctor must not flip red for v0.4-era leniency) --
    def _doctor_artifacts(h):
        _add_ab()
        apath = os.path.join(h, "artifacts", "t", "a.html")
        os.makedirs(os.path.dirname(apath), exist_ok=True)
        with open(apath, "w") as f:
            f.write("x")
        d1 = _capture_json(cmd_doctor, _ns())
        note_ok = d1["ok"] is True and any("unregistered artifact" in n for n in d1["notes"])
        # the suggested command's --path must shell-round-trip (spaces-safe quoting)
        cmds = [n.split("register with: ")[1] for n in d1["notes"] if "register with: " in n]
        quoted = bool(cmds) and shlex.split(cmds[0])[-1] == apath
        _capture(cmd_artifact, _ns(action="set", topic="t", node="a", path=apath))
        os.remove(apath)
        d2 = _capture_json(cmd_doctor, _ns())
        dangle_note = (d2["ok"] is True
                       and any("registered artifact missing" in n for n in d2["notes"]))
        g = load_graph("t")
        g["nodes"]["b"]["artifact"] = {"x": 1}
        save_graph(g)
        d3 = _capture_json(cmd_doctor, _ns())
        type_note = d3["ok"] is True and any("not a path" in n for n in d3["notes"])
        return note_ok and quoted and dangle_note and type_note
    check("doctor notes unregistered/dangling/garbage artifacts and stays ok",
          fresh(_doctor_artifacts))

    # ============ 0.5.0 review-hardening checks ============

    # -- state mutex: exclusive, times out honestly, breaks stale, releases --
    def _mutex_check(h):
        lp = acquire_lock(timeout_s=1)
        held = os.path.exists(lp)
        conflict = raises(acquire_lock, 0.15, 60)   # held + fresh -> dies on timeout
        release_lock()
        released = not os.path.exists(lp)
        with open(lp, "w") as f:                     # simulate a crashed holder
            f.write("999999")
        os.utime(lp, (time.time() - 3600, time.time() - 3600))
        acquire_lock(timeout_s=1, stale_s=1)         # stale -> broken -> acquired
        stale_broken = os.path.exists(lp)
        release_lock()
        return held and conflict and released and stale_broken
    check("state mutex: exclusive, times out, breaks stale locks, releases",
          fresh(_mutex_check))

    # -- valid_artifact is the single gate: phantoms/garbage never stamp or flag --
    def _valid_artifact_gate(h):
        _add_ab()
        g = load_graph("t")
        g["nodes"]["a"]["artifact"] = "artifacts/t/phantom.html"   # v0.4-style phantom
        g["nodes"]["b"]["artifact"] = True                          # hand-edited garbage
        save_graph(g)
        phantom_none = valid_artifact(g["nodes"]["a"]) is None
        garbage_none = valid_artifact(g["nodes"]["b"]) is None
        _capture(cmd_rate, _ns(topic="t", node="a", rating="good",
                               grade="recalled", kind="encode"))
        unstamped = "artifact" not in collect_receipts()[0]
        os.environ["ENGRAM_TODAY"] = "2026-09-01"
        due_flag_off = due_items()[0]["artifact"] is False
        apath = os.path.join(h, "artifacts", "t", "a.html")
        os.makedirs(os.path.dirname(apath), exist_ok=True)
        with open(apath, "w") as f:
            f.write("x")
        g = load_graph("t")
        g["nodes"]["a"]["artifact"] = "artifacts/t/a.html"
        real_kept = valid_artifact(g["nodes"]["a"]) == "artifacts/t/a.html"
        return phantom_none and garbage_none and unstamped and due_flag_off and real_kept
    check("phantom/garbage artifact values never stamp receipts or flag due items",
          fresh(_valid_artifact_gate))

    # -- --replace: registration survives corrupt fsrs; phantoms die there --
    def _replace_artifact_rules(h):
        _add_ab()
        apath = os.path.join(h, "artifacts", "t", "a.html")
        os.makedirs(os.path.dirname(apath), exist_ok=True)
        with open(apath, "w") as f:
            f.write("x")
        _capture(cmd_artifact, _ns(action="set", topic="t", node="a", path=apath))
        g = load_graph("t")
        g["nodes"]["a"]["fsrs"] = None                            # hand-edit corruption
        g["nodes"]["b"]["artifact"] = "artifacts/t/nope.html"     # phantom
        save_graph(g)
        g2 = {"topic": "t", "title": "T2", "order": ["a", "b"], "nodes": {
            "a": {"claim": "A", "probe": "pa"}, "b": {"claim": "B", "probe": "pb"}}}
        _capture(cmd_add_topic, _ns(json=json.dumps(g2), replace=True))
        saved = load_graph("t")["nodes"]
        return (saved["a"]["artifact"] == os.path.join("artifacts", "t", "a.html")
                and saved["b"]["artifact"] is None)
    check("--replace keeps registration despite corrupt fsrs, drops phantoms",
          fresh(_replace_artifact_rules))

    # -- artifact list: degrades on nodeless graphs, sees off-order registrations --
    def _artifact_list_robust(h):
        _add_ab()
        apath = os.path.join(h, "artifacts", "t", "zz.html")
        os.makedirs(os.path.dirname(apath), exist_ok=True)
        with open(apath, "w") as f:
            f.write("x")
        g = load_graph("t")
        g["nodes"]["zz"] = {"claim": "Z", "probe": "pz",
                            "artifact": "artifacts/t/zz.html"}    # NOT in order
        save_graph(g)
        write_json(os.path.join(h, "graphs", "broken.json"),
                   {"topic": "broken", "title": "B", "order": ["a"]})   # no nodes key
        lst = _capture_json(cmd_artifact, _ns(action="list"))
        return len(lst) == 1 and lst[0]["node"] == "zz" and lst[0]["exists"] is True
    check("artifact list survives nodeless graphs, lists off-order registrations",
          fresh(_artifact_list_robust))

    # -- visuals status: hand-edited non-string setting reports, never crashes --
    def _visuals_garbage(h):
        m = load_model()
        m["settings"]["artifacts"] = ["eager"]
        write_json(os.path.join(h, "learner-model.json"), m)
        s = _capture_json(cmd_visuals, _ns(action="status"))
        return s["artifacts"] == ["eager"] and "Threshold-only" in s["note"]
    check("visuals status reports hand-edited garbage without crashing",
          fresh(_visuals_garbage))

    # -- add-topic: a non-object node dies cleanly and writes nothing --
    check("add-topic rejects a non-object node cleanly",
          fresh(lambda h: raises(cmd_add_topic, _ns(json=json.dumps(
              {"topic": "t", "title": "T", "order": ["a"],
               "nodes": {"a": "just a string"}})))
              and not os.path.exists(os.path.join(h, "graphs", "t.json"))))

    # ============== v1.1 · the procedure layer (docs/11, docs/12) ==============
    def _add_kinds(replace=False):
        g = {"topic": "k", "title": "K", "order": ["c1", "p1", "f1"], "nodes": {
            "c1": {"claim": "C", "probe": "pc"},
            "p1": {"claim": "P", "probe": "compute 12*17 via distribution",
                   "kind": "procedure",
                   "rubric": ["setup: splits 17 into 10+7",
                              "execution: both partial products correct",
                              "verification: recombines and sanity-checks magnitude"],
                   "practice": {"problem_frame": "two-digit by two-digit product via "
                                                 "distribution; operands stay in 11-19",
                                "verify": "multiply directly and compare",
                                "error_bank": [{"error": "adds the tens partials",
                                                "misconception": "place-value collapse"}]},
                   "edges": {"requires": ["c1"]}},
            "f1": {"claim": "F", "probe": "pf", "arbitrary": True}}}
        _capture(cmd_add_topic, _ns(json=json.dumps(g), replace=replace))

    check("node_kind_of: explicit kind wins, arbitrary=fact, default+garbage=concept",
          node_kind_of({"kind": "procedure"}) == "procedure"
          and node_kind_of({"kind": "procedure", "arbitrary": True}) == "procedure"
          and node_kind_of({"arbitrary": True}) == "fact"
          and node_kind_of({}) == "concept"
          and node_kind_of({"kind": "PROCEDURE"}) == "concept"
          and node_kind_of("junk") == "concept"
          and node_kind_of(None) == "concept")

    # -- add-topic: valid kind+practice kept; unknown kind dropped; non-object practice
    #    dropped; procedure without problem_frame warned — all with warnings, never fatal --
    def _kind_validation(h):
        g = {"topic": "t", "title": "T", "order": ["a", "b", "c"], "nodes": {
            "a": {"claim": "A", "probe": "pa", "kind": "procedure",
                  "practice": {"problem_frame": "vary the operands"}},
            "b": {"claim": "B", "probe": "pb", "kind": "quiz"},
            "c": {"claim": "C", "probe": "pc", "kind": "procedure",
                  "practice": "just drill it"}}}
        out = json.loads(_capture(cmd_add_topic, _ns(json=json.dumps(g))))
        saved = load_graph("t")["nodes"]
        return (saved["a"]["kind"] == "procedure"
                and saved["a"]["practice"]["problem_frame"] == "vary the operands"
                and "kind" not in saved["b"]
                and saved["c"]["practice"] is None
                and any("unknown kind" in w for w in out["warnings"])
                and any("practice block is not an object" in w for w in out["warnings"])
                and any("without practice.problem_frame" in w for w in out["warnings"]))
    check("add-topic validates kind + practice like viz (warn+drop, never die)",
          fresh(_kind_validation))

    # -- due payload: node_kind + practice ride along; kindless stays concept/None
    #    (byte-compatible v1.0.8 behavior) --
    def _due_kinds(h):
        _add_kinds()
        for n in ("c1", "p1", "f1"):
            _capture(cmd_rate, _ns(topic="k", node=n, rating="good", kind="encode"))
        os.environ["ENGRAM_TODAY"] = "2026-09-01"
        d = {i["id"]: i for i in due_items()}
        return (d["p1"]["node_kind"] == "procedure"
                and d["p1"]["practice"]["problem_frame"].startswith("two-digit")
                and d["c1"]["node_kind"] == "concept" and d["c1"]["practice"] is None
                and d["f1"]["node_kind"] == "fact")
    check("due payload carries node_kind + practice (concept/None when undeclared)",
          fresh(_due_kinds))

    # -- the node_kind STAMP: written at grading time, immune to later reclassification --
    def _kind_stamp(h):
        _add_kinds()
        _capture(cmd_rate, _ns(topic="k", node="p1", rating="good", kind="encode"))
        r1 = read_jsonl(p("receipts", "k.jsonl"))[-1]
        g = load_graph("k")
        g["nodes"]["p1"].pop("kind", None)
        save_graph(g)
        _capture(cmd_rate, _ns(topic="k", node="p1", rating="good", kind="review"))
        r2 = read_jsonl(p("receipts", "k.jsonl"))[-1]
        return r1.get("node_kind") == "procedure" and r2.get("node_kind") == "concept"
    check("receipts stamp node_kind at grading time (old evidence keeps its kind)",
          fresh(_kind_stamp))

    # -- error_class: valid value flows rate -> receipt; absent stays absent;
    #    a typo dies before any write (append-only receipts, §4.8 Q5) --
    def _error_class_flow(h):
        _add_kinds()
        _capture(cmd_rate, _ns(topic="k", node="p1", rating="hard", grade="partial",
                               kind="encode", error_class="slip"))
        r1 = read_jsonl(p("receipts", "k.jsonl"))[-1]
        _capture(cmd_rate, _ns(topic="k", node="c1", rating="good", kind="encode"))
        r2 = read_jsonl(p("receipts", "k.jsonl"))[-1]
        return r1.get("error_class") == "slip" and "error_class" not in r2
    check("error_class flows to the receipt and absence stays absent", fresh(_error_class_flow))
    def _error_class_typo(h):
        _add_kinds()
        bad = [{"topic": "k", "node": "c1", "rating": "good", "error_class": "typo"}]
        died = raises(cmd_receipt, _ns(json=json.dumps(bad)))
        return died and not os.path.exists(p("receipts", "k.jsonl"))
    check("error_class typo dies in the pre-flight before any receipt is written",
          fresh(_error_class_typo))

    # -- by_kind: hand-computed split, first-review-only, floor, slip-share denominator --
    def _by_kind_math(h):
        _add_kinds()
        # the ENCODE carries an error_class too — it must NOT count toward slip share
        # (review-receipts population only; §4.5: the fixture diverges old vs new)
        _capture(cmd_rate, _ns(topic="k", node="p1", rating="hard", grade="partial",
                               kind="encode", error_class="slip"))
        for n in ("c1", "f1"):
            _capture(cmd_rate, _ns(topic="k", node=n, rating="good", kind="encode"))
        os.environ["ENGRAM_TODAY"] = "2026-07-20"
        _capture(cmd_rate, _ns(topic="k", node="c1", rating="good", kind="review"))
        _capture(cmd_rate, _ns(topic="k", node="p1", rating="again", grade="lapsed",
                               kind="review", error_class="conceptual"))
        # p1's SECOND review must not move its first-review number; its error_class counts
        _capture(cmd_rate, _ns(topic="k", node="p1", rating="hard", grade="partial",
                               kind="review", error_class="slip"))
        bk = _capture_json(cmd_stats, _ns())["by_kind"]
        return (bk["concept"]["first_review_recall"] == 1.0 and bk["concept"]["n"] == 1
                and bk["procedure"]["first_review_recall"] == 0.0
                and bk["procedure"]["n"] == 1
                and bk["fact"]["n"] == 0 and bk["fact"]["first_review_recall"] is None
                and bk["read"] == "insufficient-data"     # floor is MODALITY_MIN_N
                and bk["min_n"] == MODALITY_MIN_N
                and bk["procedure_slip_share"]["n_classified"] == 2   # reviews only
                and bk["procedure_slip_share"]["share"] == 0.5
                and "different material" in bk["caveat"])
    check("by_kind: hand-computed recall split, honest floor, review-only slip denominator",
          fresh(_by_kind_math))

    # -- pre-v1.1 receipts (no stamp) count as concept — the truthful label of the EVENT --
    def _by_kind_prestamp(h):
        _add_kinds()
        _capture(cmd_rate, _ns(topic="k", node="p1", rating="good", kind="encode"))
        os.environ["ENGRAM_TODAY"] = "2026-07-20"
        _capture(cmd_rate, _ns(topic="k", node="p1", rating="good", kind="review"))
        path = p("receipts", "k.jsonl")
        rs = read_jsonl(path)
        for r in rs:
            r.pop("node_kind", None)
        os.remove(path)
        for r in rs:
            append_jsonl(path, r)
        _RECEIPTS_CACHE.clear()
        bk = _capture_json(cmd_stats, _ns())["by_kind"]
        return bk["concept"]["n"] == 1 and bk["procedure"]["n"] == 0
    check("unstamped (pre-v1.1) receipts bucket as concept, never invented as procedure",
          fresh(_by_kind_prestamp))

    # -- the dashboard's kinds section: BELOW the floor it shows counts and the caveat but
    #    NEVER a rate bar (a 100% bar off n=1 is an unearned optimistic rate — §4.8 Q2;
    #    caught by the pre-release review), and the slip line quotes counts, not a percent --
    def _report_kinds_subfloor(h):
        _add_kinds()
        _capture(cmd_rate, _ns(topic="k", node="p1", rating="good", kind="encode"))
        os.environ["ENGRAM_TODAY"] = "2026-07-20"
        _capture(cmd_rate, _ns(topic="k", node="p1", rating="hard", grade="partial",
                               kind="review", error_class="slip"))
        out = _capture_json(cmd_report, _ns())
        with open(out["path"], encoding="utf-8") as f:
            html = f.read()
        return ("Knowledge kinds" in html and "different material" in html
                and "first-review recall" not in html        # no rate bar below the floor
                and "counts, not rates" in html              # slip n=1: never a percent
                and "execution slips" not in html)
    check("dashboard by_kind below floor: counts + caveat, no rate bar, no slip percent",
          fresh(_report_kinds_subfloor))
    def _report_kinds_at_floor(h):
        # 15 concept + 15 procedure nodes, one encode + one review each -> both arms at the
        # floor; 5 classified procedure reviews -> the slip percentage may speak
        nodes = {}
        order = []
        for i in range(MODALITY_MIN_N):
            for kind in ("concept", "procedure"):
                nid = "%s%d" % (kind[0], i)
                order.append(nid)
                node = {"claim": "C", "probe": "p"}
                if kind == "procedure":
                    node["kind"] = "procedure"
                    node["practice"] = {"problem_frame": "vary the values"}
                nodes[nid] = node
        g = {"topic": "big", "title": "B", "order": order, "nodes": nodes}
        _capture(cmd_add_topic, _ns(json=json.dumps(g)))
        for nid in order:
            _capture(cmd_rate, _ns(topic="big", node=nid, rating="good", kind="encode"))
        os.environ["ENGRAM_TODAY"] = "2026-07-20"
        for nid in order:
            _capture(cmd_rate, _ns(topic="big", node=nid, rating="good", kind="review",
                                   grade="recalled",
                                   error_class=("slip" if nid in ("p0", "p1", "p2", "p3")
                                                else ("conceptual" if nid == "p4" else None))))
        bk = _capture_json(cmd_stats, _ns())["by_kind"]
        out = _capture_json(cmd_report, _ns())
        with open(out["path"], encoding="utf-8") as f:
            html = f.read()
        return (bk["read"] == "indistinguishable"
                and bk["procedure_slip_share"]["n_classified"] == 5
                and "first-review recall" in html            # bars render at the floor
                and "execution slips" in html                # percentage may speak at n>=5
                and "different material" in html)
    check("dashboard by_kind at floor: bars + slip percent render, read computed",
          fresh(_report_kinds_at_floor))
    def _report_no_kinds(h):
        _add_ab()
        out = _capture_json(cmd_report, _ns())
        with open(out["path"], encoding="utf-8") as f:
            html = f.read()
        return "Knowledge kinds" not in html
    check("dashboard omits the kinds section when no kind has evidence", fresh(_report_no_kinds))

    # -- export: node_kind/error_class leave as validated enums; garbage leaves as null --
    def _export_kinds(h):
        _add_kinds()
        _capture(cmd_rate, _ns(topic="k", node="p1", rating="hard", grade="partial",
                               kind="encode", error_class="slip"))
        _capture(cmd_rate, _ns(topic="k", node="c1", rating="good", kind="encode"))
        path = p("receipts", "k.jsonl")
        rs = read_jsonl(path)
        rs[-1]["node_kind"] = "PROCEDURE!"          # hand-edited garbage must not ride out
        rs[-1]["error_class"] = ["slip"]
        os.remove(path)
        for r in rs:
            append_jsonl(path, r)
        _RECEIPTS_CACHE.clear()
        out = _capture_json(cmd_export, _ns(contributor="@t", allow_unvalidated=True))
        recs = read_json(out["path"])["receipts"]
        return (recs[0]["node_kind"] == "procedure" and recs[0]["error_class"] == "slip"
                and recs[1]["node_kind"] is None and recs[1]["error_class"] is None)
    check("export carries node_kind/error_class as closed enums, nulls garbage",
          fresh(_export_kinds))

    # ===== v1.1.1 · the §7.5 post-release review's findings =====

    # -- EVERY kind carries its own floor: `fact` rendered a 100% bar off n=1 because the
    #    gate read procedure-vs-concept only (HIGH; the same bug this section fixed once) --
    def _fact_arm_has_its_own_floor(h):
        nodes, order = {}, []
        for i in range(MODALITY_MIN_N):
            for kind in ("concept", "procedure"):
                nid = "%s%d" % (kind[0], i)
                order.append(nid)
                n = {"claim": "C", "probe": "p"}
                if kind == "procedure":
                    n["kind"] = "procedure"
                    n["practice"] = {"problem_frame": "vary"}
                nodes[nid] = n
        order.append("f0")
        nodes["f0"] = {"claim": "F", "probe": "pf", "arbitrary": True}   # ONE fact node
        _capture(cmd_add_topic, _ns(json=json.dumps(
            {"topic": "big", "title": "B", "order": order, "nodes": nodes})))
        for nid in order:
            _capture(cmd_rate, _ns(topic="big", node=nid, rating="good", kind="encode"))
        os.environ["ENGRAM_TODAY"] = "2026-07-20"
        for nid in order:
            _capture(cmd_rate, _ns(topic="big", node=nid, rating="good", grade="recalled",
                                   kind="review"))
        bk = _capture_json(cmd_stats, _ns())["by_kind"]
        out = _capture_json(cmd_report, _ns())
        with open(out["path"], encoding="utf-8") as f:
            html = f.read()
        # the read is computed, the two big arms render — and the single-datum fact arm
        # is reported as a COUNT, never as a rate
        return (bk["read"] != "insufficient-data" and bk["fact"]["n"] == 1
                and html.count("first-review recall") == 2      # concept + procedure only
                and "Below the ≥%d floor" % bk["min_n"] in html
                and "fact n=1" in html)
    check("dashboard: every kind arm carries its own floor (a 1-datum `fact` never draws a rate)",
          fresh(_fact_arm_has_its_own_floor))

    # -- the slip floor counts NODES, not judgments: one node failed 5x must not read
    #    "100% were execution slips" (HIGH) --
    def _slip_floor_counts_nodes(h):
        _add_kinds()
        _capture(cmd_rate, _ns(topic="k", node="p1", rating="good", kind="encode"))
        os.environ["ENGRAM_TODAY"] = "2026-07-20"
        for _ in range(SLIP_SHARE_MIN_N):      # 5 reviews, ONE node, all slips
            _capture(cmd_rate, _ns(topic="k", node="p1", rating="hard", grade="partial",
                                   kind="review", error_class="slip"))
        bk = _capture_json(cmd_stats, _ns())["by_kind"]
        s = bk["procedure_slip_share"]
        out = _capture_json(cmd_report, _ns())
        with open(out["path"], encoding="utf-8") as f:
            html = f.read()
        return (s["n_classified"] == SLIP_SHARE_MIN_N and s["n_nodes"] == 1
                and s["min_nodes"] == SLIP_SHARE_MIN_N
                and "execution slips" not in html          # no percentage off one node
                and "counts, not rates" in html)
    check("slip share: the floor counts NODES, so one repeatedly-failed node quotes no rate",
          fresh(_slip_floor_counts_nodes))

    # -- the circularity caveat COUNTS the corrections instead of asserting a stale literal --
    def _circularity_count_is_derived(h):
        # end-to-end on the BUNDLED set (the override path deliberately suppresses this
        # caveat), so the number the learner reads is the number of `disputed` records
        # actually in the shipped file — not a literal that goes stale the next time the
        # author concedes an item.
        gold, _meta = load_gold()
        truth = sum(1 for it in gold if it.get("disputed"))
        run = [{"sid": g["sid"], "grade": g["gold_grade"]} for g in gold]
        rp = os.path.join(h, "runs.json")
        with open(rp, "w", encoding="utf-8") as f:
            json.dump({"grader": "g", "runs": [run, run,
                                               run[:-1] + [dict(run[-1], grade="partial")]]}, f)
        a = _capture_json(cmd_assessor_audit, _ns(file=rp, json=None, gold=None))
        joined = " ".join(a.get("reasons") or [])
        return (truth >= 1 and ("%d items were corrected" % truth) in joined
                and _gold_circularity(9).count("9 items") == 1)
    check("the circularity caveat derives its corrected-item count from the gold file",
          fresh(_circularity_count_is_derived))

    # -- a --replace payload that changes a node's knowledge kind says so --
    def _replace_warns_on_kind_change(h):
        _add_kinds()
        # a clean re-authored payload (engine-owned fields absent, as a real architect
        # rebuild would be) that simply forgets `kind` on the procedure node
        g = {"topic": "k", "title": "K", "order": ["c1", "p1", "f1"], "nodes": {
            "c1": {"claim": "C", "probe": "pc"},
            "p1": {"claim": "P", "probe": "pp"},              # kind + practice dropped
            "f1": {"claim": "F", "probe": "pf", "arbitrary": True}}}
        out = json.loads(_capture(cmd_add_topic, _ns(json=json.dumps(g), replace=True)))
        return (node_kind_of(load_graph("k")["nodes"]["p1"]) == "concept"
                and any("knowledge kind changed procedure -> concept" in w
                        for w in out["warnings"]))
    check("add-topic --replace warns when a payload demotes a procedure to a concept",
          fresh(_replace_warns_on_kind_change))

    # -- read_jsonl gates out valid-JSON-NON-OBJECT lines (a bare `5` in receipts bricked
    #    every aggregate read since v0.1; found by the v1.1.0 fuzz) --
    def _jsonl_non_object_lines(h):
        _add_ab()
        _capture(cmd_rate, _ns(topic="t", node="a", rating="good", kind="encode"))
        path = p("receipts", "t.jsonl")
        with open(path, "a", encoding="utf-8") as f:
            f.write("5\ntrue\n[1,2]\n\"just a string\"\n")
        _RECEIPTS_CACHE.clear()
        s = _capture_json(cmd_stats, _ns())          # must not raise
        _capture_json(cmd_due, _ns())
        _capture(cmd_session_start, _ns())           # human-line output, not JSON
        kept = read_jsonl(path)
        return s["receipts"] == 1 and len(kept) == 1 and all(isinstance(r, dict) for r in kept)
    check("read_jsonl drops valid-JSON non-object lines (reads degrade, never brick)",
          fresh(_jsonl_non_object_lines))

    # ══ v1.3 · THE KEPT WORD ═══════════════════════════════════════════════════════════
    #
    # -- savings ordering: the near-threshold item outranks the deeply-overdue one --
    #    THE INSTRUMENT CHECK (§5.5): the fixture is built so the two orders genuinely
    #    DIVERGE — an item that is maximally overdue but effectively dead must sort BELOW a
    #    less-overdue item that is still cheap to save, which is the entire claim.
    def _savings_order(h):
        g = {"topic": "t", "title": "T", "order": ["dead", "live"], "nodes": {
            "dead": {"claim": "D", "probe": "pd"}, "live": {"claim": "L", "probe": "pl"}}}
        _capture(cmd_add_topic, _ns(json=json.dumps(g)))
        gr = load_graph("t")
        # `dead`: tiny stability, retrieved 400 days ago  -> R ~ 0, nothing left to save
        gr["nodes"]["dead"].update(state="review", fsrs={
            "s": 0.5, "d": 5.0, "last": "2025-06-01", "due": "2025-06-03",
            "reps": 1, "lapses": 0})
        # `live`: healthy stability, a few days overdue   -> R still high, cheap to hold
        gr["nodes"]["live"].update(state="review", fsrs={
            "s": 20.0, "d": 5.0, "last": "2026-06-20", "due": "2026-07-01",
            "reps": 3, "lapses": 0})
        save_graph(gr)
        overdue = [i["id"] for i in due_items(order="overdue")]
        savings = [i["id"] for i in due_items(order="savings")]
        capped = _capture_json(cmd_due, _ns(cap=1))
        rows = due_items(order="savings")
        return (overdue == ["dead", "live"]           # the order Engram always served
                and savings == ["live", "dead"]       # the order the evidence prefers
                and capped["items"][0]["id"] == "live"
                and capped["order"] == "savings"
                and "no human RCT" in capped["order_basis"]      # inv. 14: the label travels
                # the parked item scores HIGHER raw savings and still sorts last — the whole
                # point of the floor, and the assertion that separates it from a plain
                # savings sort (which would have served the dead node first)
                and rows[1]["savings_per_min"] > rows[0]["savings_per_min"]
                and rows[1]["effectively_relearn"] is True
                and rows[0]["effectively_relearn"] is False)
    check("due --cap ranks by savings/min, not overdue-first, and carries its basis label",
          fresh(_savings_order))

    # -- the legacy contract is byte-identical: --limit still emits the bare list, old order --
    def _due_limit_unchanged(h):
        _add_ab()
        for nid in ("a", "b"):
            _capture(cmd_rate, _ns(topic="t", node=nid, rating="good", kind="encode"))
        os.environ["ENGRAM_TODAY"] = "2026-08-06"
        legacy = _capture_json(cmd_due, _ns(limit=1))
        os.environ["ENGRAM_TODAY"] = "2026-07-06"
        return isinstance(legacy, list) and len(legacy) == 1 and "order" not in str(legacy[0])
    check("due --limit keeps the v1.2.2 shape and order (no silent behavior change)",
          fresh(_due_limit_unchanged))

    # -- savings and decay agree about the same node (§4.8 Q1: commands must not contradict) --
    def _savings_matches_decay(h):
        _add_ab()
        _capture(cmd_rate, _ns(topic="t", node="a", rating="good", kind="encode"))
        os.environ["ENGRAM_TODAY"] = "2026-08-06"
        d = _capture_json(cmd_decay, _ns(topic="t", horizon=DUE_HORIZON))
        row = next(r for r in d["nodes"] if r["node"] == "a")
        item = next(i for i in due_items(order="savings") if i["id"] == "a")
        os.environ["ENGRAM_TODAY"] = "2026-07-06"
        return abs(row["r_now"] - item["r_now"]) < 1e-9
    check("due savings and decay report the SAME r_now for the same node",
          fresh(_savings_matches_decay))

    # -- retire: leaves every queue, is COUNTED in every denominator it leaves, reverses --
    def _retire_counts(h):
        _add_ab()
        for nid in ("a", "b"):
            _capture(cmd_rate, _ns(topic="t", node=nid, rating="good", kind="encode"))
        os.environ["ENGRAM_TODAY"] = "2026-08-06"
        before = _capture_json(cmd_adherence, _ns())["loop_closure"]
        _capture(cmd_retire, _ns(topic="t", node="a"))
        _RECEIPTS_CACHE.clear()
        after = _capture_json(cmd_adherence, _ns())["loop_closure"]
        ret = _capture_json(cmd_retention, _ns())["unmeasured"]
        queued = [i["id"] for i in due_items()]
        row = _capture_json(cmd_topics, _ns())[0]
        html = open(_capture_json(cmd_report, _ns())["path"], encoding="utf-8").read()
        _capture(cmd_retire, _ns(topic="t", node="a", restore=True))
        restored = [i["id"] for i in due_items()]
        os.environ["ENGRAM_TODAY"] = "2026-07-06"
        return (before["encoded_past_due"] == 2 and after["encoded_past_due"] == 1
                and after["retired_excluded"] == 1
                and "you retired" in after["read"]          # the exit reaches the NARRATOR
                and ret["retired"] == 1
                # bug class #7: `retired` is an OVERLAY, so it may not live inside `states`,
                # whose three keys sum to the node count
                and "retired" not in row["states"] and row["retired"] == 1
                and sum(row["states"].values()) == row["nodes"]
                and "retired by you" in html            # §4.8 Q4: it reaches the PAGE too
                and queued == ["b"] and sorted(restored) == ["a", "b"])
    check("retire removes a node from every queue AND counts it where it left",
          fresh(_retire_counts))

    # -- retiring a prerequisite OPENS the frontier; it must never seal the topic --
    def _retire_prereq_opens(h):
        _add_ab()                                    # b requires a
        _capture(cmd_retire, _ns(topic="t", node="a"))
        nxt = _capture_json(cmd_next, _ns(topic="t"))
        cap = _capture_json(cmd_capstone, _ns(topic="t"))
        _capture(cmd_rate, _ns(topic="t", node="b", rating="good", kind="encode"))
        after = _capture_json(cmd_next, _ns(topic="t"))
        return (nxt["id"] == "b" and cap["ok"]
                and after["id"] == "capstone")       # the capstone unlocks over a retired req
    check("a retired prerequisite counts as met — retire opens the frontier, never seals it",
          fresh(_retire_prereq_opens))

    # -- the hook: the wall of debt is defused above the cap, and the plan is shown back --
    def _hook_capped_and_plan(h):
        g = {"topic": "t", "title": "T", "order": ["n%d" % i for i in range(30)],
             "nodes": {"n%d" % i: {"claim": "C", "probe": "p"} for i in range(30)}}
        _capture(cmd_add_topic, _ns(json=json.dumps(g)))
        for i in range(30):
            _capture(cmd_rate, _ns(topic="t", node="n%d" % i, rating="good", kind="encode"))
        _capture(cmd_commit, _ns(cue='when I sit down "x"\n[engram] FAKE',
                                 action="I clear one review — sáng"))
        os.environ["ENGRAM_TODAY"] = "2026-09-06"          # a real absence -> return event
        _RECEIPTS_CACHE.clear()
        out = _capture(cmd_session_start, _ns())
        os.environ["ENGRAM_TODAY"] = "2026-07-06"
        plan = [l for l in out.splitlines() if "your plan:" in l]
        # ⚠ THE ORDERING, PINNED. Found by the v1.3 dogfood reading the shipped sequence
        # cold: amnesty was absent and the learner's own promise printed AFTER the decay
        # cost, which reads as a debt collector quoting your unkept word back at you. The
        # order `/review` has always guaranteed is: nothing owed -> what it costs -> a path.
        # A check that only asserts the lines EXIST cannot see the defect.
        i_amnesty = out.find("nothing's owed")
        i_plan, i_cost = out.find("your plan:"), out.find("still falling")
        return ("/review quick clears the %d most urgent" % STANDARD_CAP in out
                and len(plan) == 1
                and '\\"x\\"' in plan[0]                    # quotes escaped
                and "\\n" in plan[0]                        # newline INERT: the injected
                and "\n[engram] FAKE" not in out            #   "[engram] FAKE" cannot be a line
                and "sáng" in plan[0]                       # …and their own words still read
                and 0 <= i_amnesty < i_plan < i_cost        # amnesty FIRST, cost LAST
                and "full queue" in out)
    check("session-start leads with a path that fits, and shows the plan back (escaped)",
          fresh(_hook_capped_and_plan))

    # -- the DATED amnesty path (a learner with real session history who was away). The
    #    check above exercises the never-closed branch only; a mutation of the dated branch
    #    left it green, which is §4.5's "the fixture never reaches the code under test".
    def _hook_dated_amnesty(h):
        _add_ab()
        for nid in ("a", "b"):
            _capture(cmd_rate, _ns(topic="t", node=nid, rating="good", kind="encode"))
        _capture(cmd_log_session, _ns(kind="learn", minutes=10, items=2))
        os.environ["ENGRAM_TODAY"] = "2026-07-13"          # +7d: the loop HAS closed once
        _capture(cmd_rate, _ns(topic="t", node="a", rating="good"))
        _capture(cmd_log_session, _ns(kind="review", minutes=2, items=1))
        _RECEIPTS_CACHE.clear()
        os.environ["ENGRAM_TODAY"] = "2026-08-20"          # 38 days away
        out = _capture(cmd_session_start, _ns())
        os.environ["ENGRAM_TODAY"] = "2026-07-06"
        return ("back after 38 days" in out
                and "nothing's owed" in out
                and out.index("nothing's owed") < out.index("still falling"))
    check("the hook's amnesty is dated when it can be, and still comes FIRST",
          fresh(_hook_dated_amnesty))

    # -- and it stays SILENT about the plan on an ordinary session (no return event) --
    def _plan_not_nagging(h):
        _add_ab()
        for nid in ("a", "b"):
            _capture(cmd_rate, _ns(topic="t", node=nid, rating="good", kind="encode"))
        _capture(cmd_commit, _ns(cue="tomorrow", action="I clear one"))
        os.environ["ENGRAM_TODAY"] = "2026-08-06"
        _RECEIPTS_CACHE.clear()
        _capture(cmd_rate, _ns(topic="t", node="a", rating="good"))   # loop HAS closed
        _RECEIPTS_CACHE.clear()
        os.environ["ENGRAM_TODAY"] = "2026-08-08"                     # 2 days later, not 7
        out = _capture(cmd_session_start, _ns())
        os.environ["ENGRAM_TODAY"] = "2026-07-06"
        return "due" in out and "your plan:" not in out
    check("the plan line is a RETURN event, not a per-session line (anti-nag ration)",
          fresh(_plan_not_nagging))

    # -- commit renewal metadata: age_days drives the offer, history is bounded --
    def _commit_age(h):
        _capture(cmd_commit, _ns(cue="tomorrow", action="I clear one"))
        os.environ["ENGRAM_TODAY"] = "2026-08-06"
        renewed = _capture_json(cmd_commit, _ns(cue="tomorrow", action="I clear one"))
        os.environ["ENGRAM_TODAY"] = "2026-09-06"
        aged = _capture_json(cmd_commit, _ns())
        os.environ["ENGRAM_TODAY"] = "2026-07-06"
        return (renewed["age_days"] == 0 and renewed["commitment"]["set"] == "2026-07-06"
                and renewed["commitment"]["renewed"] == ["2026-08-06"]
                and aged["age_days"] == 31)
    check("commit stamps renewals and emits age_days (the renewal offer's cadence)",
          fresh(_commit_age))

    # ══ v1.4 · THE AUDITED TUTOR ═══════════════════════════════════════════════════════
    #
    def _gold_runs(n_runs=3, mutate=None, subset=None):
        """Build an audit payload from the real gold set. `mutate(i, item)` may change a grade."""
        gold, _ = load_gold()
        if subset is not None:
            gold = subset
        runs = []
        for r in range(n_runs):
            run = []
            for i, g in enumerate(gold):
                grade = g["gold_grade"]
                if mutate:
                    grade = mutate(i, g, r) or grade
                run.append({"sid": g["sid"], "grade": grade, "rating": "good"})
            runs.append(run)
        return {"grader": "engram-assessor", "runs": runs}

    # -- an AUDIT receipt records the verdict and touches NOTHING --
    def _audit_never_reschedules(h):
        _add_ab()
        _capture(cmd_rate, _ns(topic="t", node="a", rating="good", kind="encode"))
        os.environ["ENGRAM_TODAY"] = "2026-07-16"
        _capture(cmd_rate, _ns(topic="t", node="a", rating="good"))
        before = json.dumps(load_graph("t")["nodes"]["a"], sort_keys=True)
        out = _capture_json(cmd_rate, _ns(topic="t", node="a", rating="hard", kind="audit",
                                          audited_rating="good", grade="partial"))
        after = json.dumps(load_graph("t")["nodes"]["a"], sort_keys=True)
        _RECEIPTS_CACHE.clear()
        sg = _capture_json(cmd_stats, _ns())["self_grading"]
        ad = _capture_json(cmd_adherence, _ns())
        os.environ["ENGRAM_TODAY"] = "2026-07-06"
        return (before == after and out["scheduled"] is False and out["applied"] is True
                and sg["n"] == 1 and sg["tutor_higher"] == 1 and sg["agree"] == 0
                # below the floor: counts, never a rate (the house rule)
                and sg["insufficient_data"] is True and sg["qwk_vs_assessor"] is None
                # …and it pollutes no learner population
                and ad["loop_closure"]["first_review_done"] == 1
                and _capture_json(cmd_stats, _ns())["reviews"] == 1
                # ⚠ AND THE CASE THE GUARD ACTUALLY EXISTS FOR: an audit that is a node's
                # FIRST receipt. `_by_node` treats a first receipt as the ENCODING EVENT —
                # day 0 for every retention bucket — so a bare CLI `rate --kind audit` on a
                # never-encoded node would invent an encoding that never happened. (The
                # §4.5 mutation of the guard left every other assertion green: the fixture
                # above always has the audit arrive last, so it never reached the line.)
                and _audit_first_is_invisible())
    def _audit_first_is_invisible():
        _capture(cmd_rate, _ns(topic="t", node="b", rating="hard", kind="audit",
                               audited_rating="good"))
        _RECEIPTS_CACHE.clear()
        ad = _capture_json(cmd_adherence, _ns())
        ret = _capture_json(cmd_retention, _ns())
        return (ad["funnel"]["nodes_encoded"] == 1          # `b` was never encoded by anyone
                and ret["coverage"]["reviews_total"] == 1)
    check("an audit receipt is recorded and reschedules NOTHING (audits inform)",
          fresh(_audit_never_reschedules))

    # -- self_grading's direction: the flattering direction is named, not averaged away --
    def _self_grading_direction(h):
        _add_ab()
        for nid in ("a", "b"):
            _capture(cmd_rate, _ns(topic="t", node=nid, rating="good", kind="encode"))
        os.environ["ENGRAM_TODAY"] = "2026-07-16"
        for nid in ("a", "b"):
            _capture(cmd_rate, _ns(topic="t", node=nid, rating="good"))
        # a tutor that inflates one and deflates one: MEAN BIAS ZERO, and that is the trap
        _capture(cmd_rate, _ns(topic="t", node="a", rating="hard", kind="audit",
                               audited_rating="easy"))
        _capture(cmd_rate, _ns(topic="t", node="b", rating="easy", kind="audit",
                               audited_rating="hard"))
        _RECEIPTS_CACHE.clear()
        sg = _capture_json(cmd_stats, _ns())["self_grading"]
        os.environ["ENGRAM_TODAY"] = "2026-07-06"
        return (sg["n"] == 2 and sg["tutor_higher"] == 1 and sg["tutor_lower"] == 1
                and "graded HIGHER 1" in sg["read"]
                and "bounded by that chain" in sg["read"])   # the limit reaches the narrator
    check("self_grading reports DIRECTION, so a zero mean bias cannot hide inflation",
          fresh(_self_grading_direction))

    # -- the canary: deterministic, band-stratified, and it can NEVER mint a pass --
    def _canary_properties(h):
        gold, _ = load_gold()
        c1, c2 = canary_items(gold), canary_items(gold)
        bands = {}
        for it in c1:
            bands[it["gold_grade"]] = bands.get(it["gold_grade"], 0) + 1
        perfect = _capture_json(cmd_assessor_audit,
                                _ns(json=json.dumps(_gold_runs(subset=c1)), canary=True))
        inflate = _capture_json(cmd_assessor_audit, _ns(canary=True, json=json.dumps(
            _gold_runs(subset=c1,
                       mutate=lambda i, g, r: "recalled" if i == 0 and g["gold_grade"] != "recalled" else None))))
        return ([i["sid"] for i in c1] == [i["sid"] for i in c2]         # deterministic
                and len(c1) == CANARY_N
                and len(bands) == 3 and bands["partial"] > bands["lapsed"]  # mid-band weighted,
                                                                            # never mid-band ONLY
                and perfect["scope"] == "canary"
                and perfect["verdict"] == "canary-pass"      # ← never "pass": invariant 12
                and inflate["verdict"] == "canary-fail"
                and "can never certify a grader on its own" in " ".join(perfect["reasons"]))
    check("the canary is stable, spans all three bands, and can never mint a `pass`",
          fresh(_canary_properties))

    # -- the badge expires when the grader changes, and a canary re-licenses it --
    def _staleness(h):
        _capture(cmd_assessor_audit, _ns(json=json.dumps(_gold_runs()),
                                         grader_context="platform/model-A"))
        same = _capture_json(cmd_grader_health, _ns(grader_context="platform/model-A"))
        swapped = _capture_json(cmd_grader_health, _ns(grader_context="platform/model-B"))
        _add_ab()
        _capture(cmd_rate, _ns(topic="t", node="a", rating="good", kind="encode"))
        refused = False
        try:
            _capture(cmd_export, _ns(contributor="@x", grader_context="platform/model-B"))
        except SystemExit:
            refused = True
        gold, _ = load_gold()
        _capture(cmd_assessor_audit, _ns(canary=True, grader_context="platform/model-B",
                                         json=json.dumps(_gold_runs(subset=canary_items(gold)))))
        relicensed = _capture_json(cmd_grader_health, _ns(grader_context="platform/model-B"))
        return (same["verdict"] == "pass" and same["grader_unvalidated"] is False
                and swapped["verdict"] == "stale-model"
                and swapped["grader_unvalidated"] is True
                and "not the one grading you now" in swapped["stamp"]
                and refused                                   # the export gate inherits it
                # a canary must not BECOME the latest audit, or canary-pass would read as
                # unreadable and void a badge that was fine
                and relicensed["verdict"] == "pass")
    check("a grader swap expires the badge (export refuses); a clean canary re-licenses it",
          fresh(_staleness))

    # -- band-stratified audit: the mid-band gets its own row --
    def _by_band(h):
        a = _capture_json(cmd_assessor_audit, _ns(json=json.dumps(_gold_runs()),
                                                  grader_context="p/m"))
        b = a["by_gold_band"]
        return (set(b) == {"recalled", "partial", "lapsed"}
                and all(v["judgments"] == v["items"] * 3 for v in b.values())
                and b["partial"]["graded_up"] == 0)
    check("the audit reports agreement per gold BAND (where graders actually fail)",
          fresh(_by_band))

    # -- the adjudication kit: monotone, and the gate comes first --
    def _adjudication(h):
        gold, _ = load_gold()
        mk = lambda fn: json.dumps([{"sid": g["sid"], "grade": fn(i, g), "anchor": i < 10}
                                    for i, g in enumerate(gold)])
        rng = random.Random(3)
        perfect = _capture_json(cmd_adjudication_stats,
                                _ns(json=mk(lambda i, g: g["gold_grade"])))
        coin = _capture_json(cmd_adjudication_stats, _ns(json=mk(
            lambda i, g: g["gold_grade"] if i < 10 else rng.choice(list(GOLD_SCORE)))))
        uncal = _capture_json(cmd_adjudication_stats, _ns(json=mk(
            lambda i, g: rng.choice(list(GOLD_SCORE)))))
        return (perfect["verdict"] == "corroborated" and perfect["alpha"] == 1.0
                and perfect["alpha_ci"] is not None
                # §5.5 monotonicity: a worse rater must SCORE worse
                and coin["alpha"] < perfect["alpha"] and coin["verdict"] == "contested"
                # the calibration gate fires BEFORE any agreement number is trusted
                and uncal["verdict"] == "calibration-failed"
                and uncal["anchor_gate"]["passed"] is False
                # one external rater corroborates; it never REPLACES the author
                and "does not replace the author" in perfect["read"]
                # a hand-authored file holds any JSON type; an unhashable grade must not
                # brick the reader (the fuzz found this: 35 crashes in 300 states)
                and _capture_json(cmd_adjudication_stats, _ns(json=json.dumps(
                    [{"sid": gold[0]["sid"], "grade": {"a": 1}},
                     {"sid": gold[1]["sid"], "grade": ["x"]},
                     {"sid": "nope", "grade": "partial"}])))["unknown_or_malformed"] == 3)
    check("adjudication-stats gates on calibration and ranks a worse rater worse",
          fresh(_adjudication))

    print("\n%d/%d checks passed" % (total[0] - len(failures), total[0]))
    sys.exit(1 if failures else 0)

def _ns(**kw):
    class NS:
        pass
    ns = NS()
    defaults = dict(topic=None, node=None, rating=None, confidence=None,
                    production=None, production_file=None, grade=None, probe=None,
                    source="self", kind="review", json=None, file=None, replace=False,
                    limit=None, set=None, add_interest=None, add_goal=None, action=None,
                    id=None, verdict=None, description=None, force=False,
                    out=None, allow_outside=False, mode=None, minutes=None,
                    items=None, notes=None, path=None,
                    cap=None, order=None, restore=False, clear=False,   # v1.3
                    cue=None, horizon=None,
                    canary=False, grader_context=None, audited_rating=None,  # v1.4
                    rater=None, gold=None, contributor=None, allow_unvalidated=False)
    defaults.update(kw)
    for k, v in defaults.items():
        setattr(ns, k, v)
    return ns

def _capture(fn, args):
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn(args)
    return buf.getvalue()

def _capture_json(fn, args):
    return json.loads(_capture(fn, args))

# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(prog="engram", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    for name in ("init", "path", "session-start", "topics", "selftest", "stats", "doctor",
                 "adherence", "retention"):
        sub.add_parser(name)

    sp = sub.add_parser("gold")
    sp.add_argument("--canary", action="store_true",
                    help="the ~15-item canary subset (mid-band and historically weak cases)")

    sp = sub.add_parser("adjudication-stats")
    sp.add_argument("--file"); sp.add_argument("--json")
    sp.add_argument("--rater", help="who adjudicated (recorded, never used in the maths)")
    sp.add_argument("--gold", help=argparse.SUPPRESS)

    sp = sub.add_parser("grader-health")
    sp.add_argument("--grader-context",
                    help="the label of the grader running TODAY — a mismatch with the audited "
                         "one expires the badge (a model swap runs measurably more lenient)")

    sp = sub.add_parser("assessor-audit")
    sp.add_argument("--file"); sp.add_argument("--json")
    sp.add_argument("--gold", help="override the gold set (testing; default = bundled)")
    sp.add_argument("--grader-context",
                    help="platform/model label the runs were graded under, verbatim from what "
                         "your platform knows. The engine never guesses it; 'unknown' is honest.")
    sp.add_argument("--canary", action="store_true",
                    help="grade the ~15-item re-licensing subset (never certifies on its own)")

    sp = sub.add_parser("transfer")
    sp.add_argument("--topic"); sp.add_argument("--limit", type=int)

    sp = sub.add_parser("export")
    sp.add_argument("--grader-context",
                    help="the grader running today — a mismatch with the audited one expires "
                         "the badge, and an expired badge refuses to export (v1.4)")
    sp.add_argument("--topic", help="export ONE topic (default: all)")
    sp.add_argument("--contributor", help="the handle this will be posted under. Typed by you; "
                                          "the engine never guesses your identity.")
    sp.add_argument("--allow-unvalidated", action="store_true",
                    help=argparse.SUPPRESS)   # escape hatch for tests; /coach never passes it

    sp = sub.add_parser("capstone")
    sp.add_argument("--topic", required=True)

    sp = sub.add_parser("retire")
    sp.add_argument("--topic", required=True)
    sp.add_argument("--node", help="one node; omit to retire the whole topic")
    sp.add_argument("--restore", action="store_true", help="put it back on the list")

    sp = sub.add_parser("decay")
    sp.add_argument("--topic")
    sp.add_argument("--horizon", type=int, default=DECAY_HORIZON_DEFAULT)

    sp = sub.add_parser("commit")
    sp.add_argument("--cue"); sp.add_argument("--action")
    sp.add_argument("--clear", action="store_true")

    sp = sub.add_parser("add-topic")
    sp.add_argument("--json"); sp.add_argument("--file"); sp.add_argument("--replace", action="store_true")

    sp = sub.add_parser("next")
    sp.add_argument("--topic", required=True)

    sp = sub.add_parser("topic-status")
    sp.add_argument("--topic", required=True)

    sp = sub.add_parser("due")
    sp.add_argument("--topic")
    sp.add_argument("--limit", type=int,
                    help="legacy cap: emits the bare list in the always-served order")
    sp.add_argument("--cap", type=int,
                    help="cap a session; defaults to `savings` ordering and emits the labeled "
                         "object (order + order_basis + items)")
    sp.add_argument("--order", choices=DUE_ORDERS,
                    help="overdue (as always) | savings (expected retention saved per minute)")

    sp = sub.add_parser("rate")
    sp.add_argument("--topic", required=True); sp.add_argument("--node", required=True)
    sp.add_argument("--rating", required=True, choices=sorted(RATINGS))
    sp.add_argument("--confidence", type=int)
    sp.add_argument("--production"); sp.add_argument("--production-file")
    sp.add_argument("--grade", choices=GRADES); sp.add_argument("--probe")
    sp.add_argument("--source", default="self")
    sp.add_argument("--kind", default="review", choices=KINDS)
    # v1.1: slip vs conceptual on a graded production. choices= so a typo dies in argparse,
    # before validate_item even runs — receipts are append-only (§4.8 Q5).
    sp.add_argument("--error-class", dest="error_class", choices=ERROR_CLASSES)

    sp.add_argument("--audited-rating", choices=sorted(RATINGS),
                    help="audit kind only: the rating the TUTOR committed, which the blind "
                         "assessor is now re-grading (feeds stats.self_grading)")

    sp = sub.add_parser("receipt")
    sp.add_argument("--json"); sp.add_argument("--file")

    sp = sub.add_parser("stash")
    sp.add_argument("action", choices=("add", "list", "count", "clear"))
    sp.add_argument("--json"); sp.add_argument("--file")

    sp = sub.add_parser("model")
    sp.add_argument("--set", action="append")
    sp.add_argument("--add-interest", action="append")
    sp.add_argument("--add-goal", action="append")

    sp = sub.add_parser("focus")
    sp.add_argument("action", choices=("on", "off", "status"))

    sp = sub.add_parser("visuals")
    sp.add_argument("action", choices=("eager", "threshold", "off", "status"))

    sp = sub.add_parser("artifact")
    sp.add_argument("action", choices=("set", "clear", "list"))
    sp.add_argument("--topic"); sp.add_argument("--node"); sp.add_argument("--path")

    sp = sub.add_parser("misconception")
    sp.add_argument("action", choices=("add", "list", "resolve"))
    sp.add_argument("--topic"); sp.add_argument("--node")
    sp.add_argument("--description"); sp.add_argument("--id")

    sp = sub.add_parser("experiment")
    sp.add_argument("action", choices=("start", "assign", "settle", "status", "list"))
    sp.add_argument("--json"); sp.add_argument("--file"); sp.add_argument("--id")
    # `--verdict` is KEPT so the engine can REFUSE it loudly rather than argparse-erroring on an
    # unknown flag. Until v0.9 this wrote whatever the model said straight into the experiment
    # log — the one command whose entire purpose is a number nobody is allowed to make up.
    sp.add_argument("--verdict", help=argparse.SUPPRESS)
    sp.add_argument("--topic"); sp.add_argument("--node")

    sp = sub.add_parser("log-session")
    sp.add_argument("--kind", default="learn"); sp.add_argument("--mode", default="standard")
    sp.add_argument("--minutes", type=int); sp.add_argument("--items", type=int)
    sp.add_argument("--notes")

    sp = sub.add_parser("refit")
    sp.add_argument("--force", action="store_true")

    sp = sub.add_parser("report")
    sp.add_argument("--out"); sp.add_argument("--allow-outside", action="store_true")

    args = ap.parse_args()
    handlers = {
        "init": cmd_init, "path": cmd_path, "session-start": cmd_session_start,
        "topics": cmd_topics, "add-topic": cmd_add_topic, "next": cmd_next,
        "topic-status": cmd_topic_status, "due": cmd_due, "rate": cmd_rate,
        "receipt": cmd_receipt, "stash": cmd_stash, "model": cmd_model,
        "focus": cmd_focus, "visuals": cmd_visuals, "artifact": cmd_artifact,
        "misconception": cmd_misconception, "experiment": cmd_experiment,
        "log-session": cmd_log_session, "stats": cmd_stats,
        "refit": cmd_refit, "doctor": cmd_doctor, "report": cmd_report,
        "selftest": cmd_selftest,
        "adherence": cmd_adherence, "retention": cmd_retention,
        "decay": cmd_decay, "commit": cmd_commit,
        "gold": cmd_gold, "assessor-audit": cmd_assessor_audit,
        "grader-health": cmd_grader_health,
        "transfer": cmd_transfer, "capstone": cmd_capstone,
        "export": cmd_export, "retire": cmd_retire,
        "adjudication-stats": cmd_adjudication_stats,
    }
    # Serialize state mutators: the skills run engine processes concurrently by
    # design (background artifact-smith registering while the tutor rates), and
    # whole-file read-modify-write without a lock is last-writer-wins data loss.
    # `artifact list` is a read, but sub-action dispatch isn't worth the special
    # case — the lock is milliseconds. Read-only commands stay lock-free.
    # `adherence`/`retention`/`decay` are pure reads over receipts+graphs — no lock.
    # `commit` writes the learner model, so it serializes like every other mutator.
    # `assessor-audit` writes audits/<date>-NN.json (and probes the dir for a free seq),
    # so it mutates. `gold`/`grader-health` are pure reads.
    # `capstone` writes a node into the graph, so it serializes like every other mutator.
    # `transfer` is a pure read over graphs + receipts — it SERVES a probe, it never records one.
    mutating = {"init", "add-topic", "rate", "receipt", "stash", "model", "focus",
                "visuals", "artifact", "misconception", "experiment",
                "log-session", "refit", "commit", "assessor-audit", "capstone", "export",
                "retire"}
    if args.cmd in mutating:
        acquire_lock()
        try:
            handlers[args.cmd](args)
        finally:
            release_lock()
    else:
        handlers[args.cmd](args)

if __name__ == "__main__":
    main()
