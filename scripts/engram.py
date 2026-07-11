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
import itertools
import json
import math
import os
import re
import shlex
import sys
import tempfile
import time
from datetime import date, timedelta
from html import escape

SCHEMA = 1
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
# Receipt kinds. Every v0.6 metric keys off the exact literal "review", so an
# invented kind would be permanently invisible — and receipts are append-only, so
# it could never be corrected. Validated at ingest; a bad batch dies before any write.
KINDS = ("encode", "review", "pretest", "transfer", "audit")
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
    """Coerce a JSON scalar to float for math; None if not number-like."""
    if isinstance(x, bool) or x is None:
        return default
    if isinstance(x, (int, float)):
        return float(x)
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
    out = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
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
    for sub in ("graphs", "receipts", "artifacts", "audits", "gold"):
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
    real = {nid: n for nid, n in g["nodes"].items() if not n.get("capstone")}
    if real and not _has_capstone(g["nodes"]):
        g["nodes"][CAPSTONE_ID] = _capstone_node(g, real)
        g["order"] = [n for n in g["order"] if n != CAPSTONE_ID] + [CAPSTONE_ID]
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

def cmd_topics(_args):
    out = []
    for t, g in iter_graphs():
        states = state_counts(g)
        due_count = 0
        for node in (g.get("nodes") or {}).values():
            if not isinstance(node, dict):
                continue
            dd = safe_date(_fsrs_of(node).get("due"))
            if node.get("state") != "new" and dd and dd <= today():
                due_count += 1
        out.append({"topic": t, "title": g.get("title"), "goal": g.get("goal"),
                    "nodes": len(g["nodes"]), "states": states, "due": due_count})
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

def due_items(topic_filter=None, limit=None, horizon_days=0):
    per_topic = {}
    cutoff = today() + timedelta(days=horizon_days)
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
                    "transfer_ready": _transfer_ready(
                        node, node_transfer_state(_tnodes.get((t, nid))), _t),
                    "transfer_probe": node.get("transfer_probe"),
                    "capstone": node.get("capstone") is True,
                })
        items.sort(key=lambda x: -x["overdue_days"])
        if items:
            per_topic[t] = items
    # interleave topics round-robin (P3: interleaving is the default)
    merged = []
    while any(per_topic.values()):
        for t in list(per_topic):
            if per_topic[t]:
                merged.append(per_topic[t].pop(0))
    if limit is not None:
        merged = merged[:limit]
    return merged

def cmd_due(args):
    emit(due_items(args.topic, args.limit))

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
    rating = item["rating"]
    model = load_model()
    node.setdefault("fsrs", _fresh_fsrs())
    node["fsrs"]["retention"] = as_number(model["memory"].get("desired_retention"), RETENTION_DEFAULT)
    node["fsrs"]["im"] = as_number(model["memory"].get("interval_multiplier"), 1.0)
    was_new = as_number(node["fsrs"].get("s")) is None
    node["fsrs"], extra = apply_rating(node["fsrs"], rating, today())
    node["fsrs"].pop("retention", None)
    node["fsrs"].pop("im", None)
    if rating == "again":
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
    # Day 0 is the node's FIRST receipt. Stamping elapsed-days here is what makes the north
    # star (retention at 7/30/90 days — docs/04 named it in Phase 0 and never built it) a
    # one-pass query over the receipt log instead of a join against the graph. On first
    # exposure there is no prior receipt, so this is 0 by construction.
    enc_ts = _first_receipt_ts(item["topic"], item["node"])
    dse = days_between(enc_ts, today().isoformat()) if enc_ts else 0
    # clamp: a backward clock step (or a hand-edited ts) would otherwise stamp a
    # negative elapsed-day count into an append-only receipt, permanently.
    extra = {**extra, "days_since_encode": max(0, dse or 0)}
    receipt = make_receipt(item, {**extra, "due_next": node["fsrs"]["due"]}, kind)
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
            "grade": args.grade, "probe": args.probe, "source": args.source}
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
            # human order), then any hand-added nodes outside it — never invisible
            order = [n for n in g.get("order", []) if n in nodes]
            order += sorted(n for n in nodes if n not in set(order))
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
    if args.action == "add":
        items.append({"id": gen_id("m"),
                      "ts": today().isoformat(), "topic": args.topic,
                      "node": args.node, "description": args.description,
                      "status": "open"})
        write_json(path, items)
    elif args.action == "resolve":
        found = False
        for it in items:
            if it.get("id") == args.id:
                it["status"] = "resolved"
                it["resolved_ts"] = today().isoformat()
                found = True
        if not found:
            die("no misconception with id %s" % args.id)
        write_json(path, items)
    emit([it for it in items if args.topic in (None, it.get("topic"))])

def cmd_experiment(args):
    path = p("experiments.json")
    items = read_json(path, [])
    if args.action == "start":
        exp = load_payload(args)
        for key in ("question", "arms", "metric"):
            if key not in exp:
                die("experiment missing %s" % key)
        if not isinstance(exp["arms"], list) or len(exp["arms"]) < 2:
            die("experiment needs an arms list with at least 2 arms")
        if any(e.get("status") == "active" for e in items):
            die("an experiment is already active — settle it before starting another "
                "(one active experiment at a time; see /coach)")
        exp.update({"id": gen_id("x"),
                    "started": today().isoformat(), "status": "active",
                    "assignments": [], "verdict": None})
        items.append(exp)
        write_json(path, items)
        emit(exp)
    elif args.action == "assign":
        active = [e for e in items if e.get("status") == "active"]
        if not active or not active[0].get("arms"):
            emit({"arm": None, "note": "no active experiment"})
            return
        exp = active[0]
        arm = exp["arms"][len(exp["assignments"]) % len(exp["arms"])]
        exp["assignments"].append({"ts": today().isoformat(), "arm": arm,
                                   "topic": args.topic, "node": args.node})
        write_json(path, items)
        emit({"id": exp["id"], "arm": arm})
    elif args.action == "settle":
        if not any(exp.get("id") == args.id for exp in items):
            die("no experiment with id %s" % args.id)
        for exp in items:
            if exp.get("id") == args.id:
                exp["status"] = "settled"
                exp["verdict"] = args.verdict
                exp["settled"] = today().isoformat()
        write_json(path, items)
        emit(items)
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
        if r.get("grade") == "recalled":
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

MODALITY_MIN_N = 6   # same floor as the n-of-1 experiment convention (min_per_arm)

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
    arms = {"explorable": [0, 0], "dialogue": [0, 0]}
    for _d, r in first.values():
        arm = "explorable" if r.get("artifact") else "dialogue"
        arms[arm][1] += 1
        if r["rating"] != "again":
            arms[arm][0] += 1
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

def node_transfer_state(slot):
    """The node's transfer block, derived from its receipts. ENGINE-OWNED, never payload-set.

    `untested` — never probed. `probed` — probed, and it did not fire. `applied` — the most
    recent transfer probe was *recalled*: the capability fired.

    Computed from the LATEST transfer receipt, not from "ever". A capability that fired in June
    and failed in September is not currently owned, and pretending otherwise would be a wrong
    number in the flattering direction — which is bug class #1."""
    ts = slot["transfers"] if slot else []
    if not ts:
        return {"state": "untested", "last": None, "receipts": 0}
    last = ts[-1]
    grade = last.get("grade")
    if not isinstance(grade, str) or grade not in GRADES:
        rating = last.get("rating")
        grade = GRADE_OF_RATING.get(rating) if isinstance(rating, str) else None
    return {"state": "applied" if grade == "recalled" else "probed",
            "last": last.get("ts") if isinstance(last.get("ts"), str) else None,
            "receipts": len(ts)}

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
TRANSFER_MATURE_REPS = 3      # …across at least three retrievals. Not a fluke.
TRANSFER_COOLDOWN_DAYS = 30   # don't re-probe the same node every session; it is not a quiz
TRANSFER_STATES = ("untested", "probed", "applied")

GOLD_SCORE = {"lapsed": 0, "partial": 1, "recalled": 2}   # ordinal; QWK needs the order
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
                      "production", "confidence", "kind")
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
# inflating. Across 198 blind judgments it still graded UP exactly zero times. That is a safety
# property, it does not depend on the gold being perfectly calibrated, and it is the only claim
# here that was ever worth a badge.
GOLD_ADJUDICATION = "authored"      # -> "human" only when someone who is NOT the author has done it
GOLD_CIRCULARITY = (
    "GOLD SET IS AUTHORED, NOT INDEPENDENTLY HUMAN-ADJUDICATED, and 5 items were corrected after "
    "the grader disagreed with them. A QWK measured against it CANNOT certify a grader from the "
    "same model family: when the author concedes to the grader, the agreement that follows "
    "measures the author. The figure that survives this is `direction.graded_up` — a safety "
    "property that does not depend on the gold being perfectly calibrated.")

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
    if meta["skipped"]:
        sys.stderr.write("engram: %d malformed gold item(s) skipped\n" % meta["skipped"])
    if meta["modified"]:
        sys.stderr.write("engram: ground truth is %s\n" % meta["source"])
    emit([{k: it.get(k) for k in GOLD_ASSESSOR_KEYS} for it in items])

def _qwk(pairs):
    """Quadratic weighted kappa over (gold, grader) grade pairs. None if undefined.

    THE headline. Raw agreement overstates chance-corrected agreement by 34-41 points in
    the measured literature, so it is reported but never quoted alone. Returns None when
    the expected-disagreement mass is zero (both raters degenerate onto one category) —
    None, not 1.0: an undefined agreement must never read as a perfect one, because that
    is a wrong number in the flattering direction, which is bug class #1 in this repo."""
    k = len(GRADES)
    n = len(pairs)
    if not n:
        return None
    obs = [[0] * k for _ in range(k)]
    for gold, grader in pairs:
        obs[GOLD_SCORE[gold]][GOLD_SCORE[grader]] += 1
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

    per_run, confusion, by_case = [], {}, {}
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
    # A run that graded the same sid twice did not cover the gold set — it covered part of it
    # and then had a second go. Same class as a dropped sid, so it lands in the same guard.
    coverage_complete = bool(gold) and not ungraded and not unknown and not dupes
    reasons = []
    # The instrument's own limit, on every audit, first. It is not a caveat about this run — it is
    # a caveat about what a QWK from THIS gold set can mean at all, and it must outlive any
    # particular verdict. When someone who is not the author adjudicates the set, this goes away.
    if GOLD_ADJUDICATION != "human" and not getattr(args, "gold", None):
        reasons.append(GOLD_CIRCULARITY)
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
    if n < MIN_AUDIT_N:
        verdict = "insufficient-data"
        reasons.insert(0, "n=%d < %d — not enough adjudicated items to say anything about "
                          "this grader" % (n, MIN_AUDIT_N))
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
        # The gold set is 88% ADVERSARIAL BY DESIGN, so this bias is measured on the cases where
        # graders fail — not on the mix of productions a learner actually writes. It is the right
        # number for "can this grader be fooled"; it is an upper bound on "how wrong are my
        # receipts". Saying so is cheaper than being quietly misread.
        "bias_note": ("leniency_bias is measured over a deliberately adversarial gold set "
                      "(88% trap cases). It bounds how far the grader CAN be pushed; it is not "
                      "an unbiased estimate of its bias on ordinary productions."),
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
    latest = names[-1]
    a = read_json(os.path.join(d, latest), quarantine=False)
    if not isinstance(a, dict) or a.get("verdict") not in (
            "pass", "warn", "fail", "incomplete", "insufficient-runs", "insufficient-data"):
        return {"__unreadable__": latest}
    return a

def compute_grader_health():
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

def cmd_grader_health(_args):
    emit(compute_grader_health())

def _transfer_ready(node, tstate, t):
    """Is this node mature enough to be asked the harder question?

    Mature = the memory has survived real intervals (s > 21d) across real retrievals (reps >= 3).
    Probing transfer on a node the learner encoded yesterday measures nothing but their working
    memory, and failing it would be a lapse the schedule then punishes — a fabricated setback."""
    tp = node.get("transfer_probe")
    if not (isinstance(tp, str) and tp.strip()):
        return False                       # a null transfer_probe is NEVER selected
    f = _fsrs_of(node)
    s, reps = as_number(f.get("s")), as_number(f.get("reps"), 0) or 0
    if s is None or s <= TRANSFER_MATURE_S or reps < TRANSFER_MATURE_REPS:
        return False
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
            st = node_transfer_state(nodes.get((tp, nid)))
            if not _transfer_ready(node, st, t):
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
            if not (isinstance(node.get("transfer_probe"), str) and node["transfer_probe"].strip()):
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
    def _grade(r):
        gr = r.get("grade")
        if not isinstance(gr, str) or gr not in GRADES:
            gr = GRADE_OF_RATING.get(r.get("rating")) if isinstance(r.get("rating"), str) else None
        return gr
    grades = [_grade(r) for r in ts]
    fired = sum(1 for gr in grades if gr == "recalled")
    partial = sum(1 for gr in grades if gr == "partial")
    lapsed = sum(1 for gr in grades if gr == "lapsed")
    rate_fired = round(fired / len(ts), 3) if ts else None
    rate_any = round((fired + partial) / len(ts), 3) if ts else None
    have = sum(states.values())
    if not ts:
        read = ("NO CAPABILITY HAS EVER BEEN MEASURED. %d concept%s %s a transfer probe the "
                "architect wrote; %d %s mature enough to be asked it."
                % (have, "s" if have != 1 else "", "carry" if have != 1 else "carries",
                   ready, "is" if ready == 1 else "are"))
    else:
        read = ("transfer FIRED on %d%% of %d probe%s (%d%% at least partial). This is not "
                "recall — it is whether the idea works when it wears different clothes, and it "
                "is never pooled into retention."
                % (round(rate_fired * 100), len(ts), "s" if len(ts) != 1 else "",
                   round(rate_any * 100)))
    return {"n": len(ts),
            "fired": fired, "partial": partial, "lapsed": lapsed,
            "rate_fired": rate_fired,     # recalled only — the bar `state: applied` uses
            "rate_any": rate_any,         # recalled-or-partial — the SAME bar retention uses
            "states": states, "ready_now": ready,
            "definition": ("of transfer probes attempted (the same idea in different clothes): "
                           "`rate_fired` is the fraction graded `recalled` — the bar a node must "
                           "clear to reach `transfer.state: applied`. `rate_any` also counts "
                           "`partial`, which is the bar `retention` uses, so the two are "
                           "comparable. NEVER pooled: retention asks whether the memory survived; "
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

    reached = done = 0
    for slot in nodes.values():
        first_due = safe_date(slot["first"].get("due_next"))
        if first_due is None or first_due > t:
            continue                      # not yet due: the loop hasn't been asked to close
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

    return {
        "loop_closure": {"encoded_past_due": reached, "first_review_done": done,
                         "rate": rate, "read": read},
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
    stale, never, proj = 0, 0, []
    for tp, g in iter_graphs():
        for nid, node in (g.get("nodes") or {}).items():
            if not isinstance(node, dict):
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
            "projected_recall_now": (round(sum(proj) / len(proj), 3) if proj else None),
            "note": ("UNKNOWN, not absent. These are past due RIGHT NOW — not retrieved since "
                     "they came due, whatever their history. Reporting retention without them "
                     "is survivorship bias: they are exactly the concepts that decayed."),
        },
        "read": read,
    }

def _as_list(x):
    """A JSON file that should hold a list, but may hold anything after a hand-edit."""
    return x if isinstance(x, list) else []

def _open_misconceptions():
    return [m for m in _as_list(read_json(p("misconceptions.json"), []))
            if isinstance(m, dict) and m.get("status") == "open"]

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
    calibration_encode = _calibration([r for r in with_conf if id(r) not in review_ids])
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
        "streak_days": compute_streak(receipts),
        "momentum": compute_momentum(receipts),
        "modality": compute_modality(receipts),
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
            if not isinstance(node, dict):
                continue
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
    attainment; does not shrink with sample size (robust to publication-bias correction) and
    survived the post-2015 replication crisis. It is the highest-effect-size adherence move
    available that costs nothing and steers no one.

    Stored because they said it. Shown back at the moment it names. NEVER enforced — this is
    not a reminder system, it is the learner's own sentence repeated to them (docs/07 §4)."""
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
        m["settings"]["commitment"] = {"cue": args.cue, "action": args.action,
                                       "set": today().isoformat()}
    if m["settings"].get("commitment") != before:
        write_json(p("learner-model.json"), m)
    c = m["settings"].get("commitment")
    emit({"commitment": c,
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
        print("[engram] %d review%s due (%s) · ~%d min · /review to clear, /learn to continue."
              % (len(due), "s" if len(due) != 1 else "", summary, minutes))
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
                ad = compute_adherence()
                lc = ad["loop_closure"]
                gone = ad["return"]["days_since_last_session"]
                never_closed = lc["encoded_past_due"] > 0 and lc["first_review_done"] == 0
                returning = gone is not None and gone >= 7
                if never_closed or returning:
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
        parts.append("<div class='chips'>%s</div>" % "".join(
            "<span class='chip'>%s <b>%s</b></span>" % (escape(k), escape(v)) for k, v in (
                ("fired", "%d%%" % round((tr["rate_fired"] or 0) * 100)),
                ("at least partial", "%d%%" % round((tr["rate_any"] or 0) * 100)),
                ("probes", str(tr["n"])),
                ("owned", str(tr["states"]["applied"])),
                ("untested", str(tr["states"]["untested"])))))
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
        ])
        check("momentum sums only in-window durability gains",
              mom["reviews_7d"] == 3 and approx(mom["stability_gained_7d"], 8.5, 0.01))
        check("momentum counts genuine recalls in window", mom["recalled_7d"] == 1)

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

    # ================================================== THE CLAIM (v0.8)
    # `transfer_probe` was authored by the architect since v0.1 and read by NOTHING. Zero
    # transfer receipts existed anywhere, ever. Engram measured memory and claimed capability.

    def _add_transfer_topic(tp="Apply it to your own GPS trace.", extra=None):
        g = {"topic": "k", "title": "K", "order": ["a", "b"], "nodes": {
            "a": {"claim": "C", "probe": "P", "rubric": ["r"], "transfer_probe": tp},
            "b": {"claim": "C2", "probe": "P2", "rubric": ["r"], "transfer_probe": None,
                  "edges": {"requires": ["a"]}}}}
        if extra:
            g["nodes"].update(extra)
        pth = p("payload.json")
        write_json(pth, g)
        _capture(cmd_add_topic, _ns(file=pth, replace=False))

    def _mature(node="a"):
        """Encode, then three real reviews across months -> s > 21d, reps >= 3."""
        _capture(cmd_rate, _ns(topic="k", node=node, rating="good", grade="recalled",
                               kind="encode", production="x"))
        for d in ("2026-08-06", "2026-10-06", "2027-01-06"):
            os.environ["ENGRAM_TODAY"] = d
            _capture(cmd_rate, _ns(topic="k", node=node, rating="easy", grade="recalled",
                                   kind="review", production="z"))
        os.environ["ENGRAM_TODAY"] = "2027-04-06"

    # -- an IMMATURE node is never asked the harder question --
    def _transfer_only_mature(h):
        _add_transfer_topic()
        _capture(cmd_rate, _ns(topic="k", node="a", rating="good", grade="recalled",
                               kind="encode", production="x"))     # encoded, s tiny, reps 1
        t0 = _capture_json(cmd_transfer, _ns(topic="k", limit=None))
        _mature()
        t1 = _capture_json(cmd_transfer, _ns(topic="k", limit=None))
        return (t0["n"] == 0 and "mature enough" in t0["read"]
                and t1["n"] == 1 and t1["items"][0]["id"] == "a"
                and as_number(t1["items"][0]["s"]) > TRANSFER_MATURE_S
                and t1["items"][0]["reps"] >= TRANSFER_MATURE_REPS)
    check("transfer serves ONLY mature nodes (s > 21d, reps >= 3) — never a fresh encode",
          fresh(_transfer_only_mature))

    # -- a node with a NULL transfer_probe is never selected, however mature --
    def _null_probe_never_selected(h):
        _add_transfer_topic(tp=None)          # node `a` now has NO transfer probe
        _mature()
        t = _capture_json(cmd_transfer, _ns(topic="k", limit=None))
        st = _capture_json(cmd_stats, _ns())["transfer"]
        return (t["n"] == 0                    # mature, but there is nothing to ask
                and sum(st["states"].values()) == 0)   # …and it is not counted as untested
    check("a node with a null transfer_probe is NEVER selected (there is nothing to ask)",
          fresh(_null_probe_never_selected))

    # -- THE STATE MACHINE: untested -> probed -> applied, from the LATEST evidence --
    def _transfer_state_machine(h):
        _add_transfer_topic()
        _mature()
        s0 = _capture_json(cmd_stats, _ns())["transfer"]["states"]
        _capture(cmd_rate, _ns(topic="k", node="a", rating="hard", grade="partial",
                               kind="transfer", production="half"))
        s1 = _capture_json(cmd_stats, _ns())["transfer"]["states"]
        n1 = load_graph("k")["nodes"]["a"]["transfer"]
        os.environ["ENGRAM_TODAY"] = "2027-08-06"
        _capture(cmd_rate, _ns(topic="k", node="a", rating="good", grade="recalled",
                               kind="transfer", production="the whole thing"))
        s2 = _capture_json(cmd_stats, _ns())["transfer"]["states"]
        n2 = load_graph("k")["nodes"]["a"]["transfer"]
        # …and it can be LOST again: a capability that fails now is not currently owned
        os.environ["ENGRAM_TODAY"] = "2028-01-06"
        _capture(cmd_rate, _ns(topic="k", node="a", rating="again", grade="lapsed",
                               kind="transfer", production="gone"))
        s3 = _capture_json(cmd_stats, _ns())["transfer"]["states"]
        return (s0 == {"untested": 1, "probed": 0, "applied": 0}
                and s1 == {"untested": 0, "probed": 1, "applied": 0} and n1["receipts"] == 1
                and s2 == {"untested": 0, "probed": 0, "applied": 1} and n2["receipts"] == 2
                and n2["state"] == "applied" and n2["last"] == "2027-08-06"
                and s3 == {"untested": 0, "probed": 1, "applied": 0})   # lost, honestly
    check("transfer state machine: untested -> probed -> applied, from the LATEST evidence (and it can be lost)",
          fresh(_transfer_state_machine))

    # -- NEVER POOLED: a transfer receipt must not touch retention, and retention must not eat it --
    # Retention asks "did the memory survive N days?"; transfer asks "does the capability fire in
    # new clothes?". Pooling them drags the north star down with a harder question and answers
    # neither. The coverage guard must ALSO stay complete — a transfer receipt is not a review
    # that fell out of a bucket.
    def _transfer_is_never_pooled(h):
        _add_transfer_topic()
        _mature()                                        # 1 encode + 3 reviews
        _capture(cmd_rate, _ns(topic="k", node="a", rating="good", grade="recalled",
                               kind="transfer", production="applied it"))
        _capture(cmd_rate, _ns(topic="k", node="a", rating="again", grade="lapsed",
                               kind="transfer", production="failed it"))
        s = _capture_json(cmd_stats, _ns())
        cov = s["retention"]["coverage"]
        return (s["reviews"] == 3                        # retention population: reviews only
                and s["transfer"]["n"] == 2              # transfer population: transfers only
                and sum(v["n"] for v in s["recall_by_stability"].values()) == 3
                and cov["reviews_bucketed"] == cov["reviews_total"] == 3
                and cov["complete"] is True              # a transfer is not a dropped review
                # …and momentum DOES count them, because durability is durability
                and s["momentum"]["reviews_7d"] == 2)
    check("a transfer receipt is NEVER pooled into retention — and never breaks its coverage",
          fresh(_transfer_is_never_pooled))

    # -- §4.8 Q1: `rate_fired` and `transfer.state` must use the SAME bar --
    # The first cut reported one `rate` counting anything not-lapsed, so a node whose only
    # transfer receipt was `partial` read **rate 1.0** while its own state read **probed**. Two
    # numbers, one state, two silently different definitions of success — and the looser one was
    # the flattering one. Caught by the numbers audit BEFORE the gate ran.
    def _transfer_rates_agree_with_the_state(h):
        _add_transfer_topic()
        _mature()
        _capture(cmd_rate, _ns(topic="k", node="a", rating="hard", grade="partial",
                               kind="transfer", production="half an answer"))
        t = _capture_json(cmd_stats, _ns())["transfer"]
        return (t["rate_fired"] == 0.0            # the capability did NOT fire…
                and t["rate_any"] == 1.0          # …though it was not a total blank
                and t["states"]["applied"] == 0   # …and the state agrees with rate_fired
                and t["states"]["probed"] == 1
                and "rate" not in t               # the ambiguous bare key is GONE
                and "FIRED on 0%" in t["read"])   # …and the READ leads with the strict bar
    check("§4.8 Q1: transfer's `rate_fired` uses the same bar as `state: applied` (never a bare `rate`)",
          fresh(_transfer_rates_agree_with_the_state))

    # -- THE CAPSTONE IS A NODE, NOT A HOPE --
    # For four releases `skills/learn` §5 said of the build: "this is the point of the whole
    # topic — do not let it silently not happen." It silently did not happen, every time,
    # because it was a line of prose rather than a node in a graph.
    def _capstone_is_in_the_dag(h):
        _add_transfer_topic()
        g = load_graph("k")
        cap = g["nodes"].get(CAPSTONE_ID)
        born = (cap is not None and cap["capstone"] is True and cap["state"] == "new"
                and sorted(cap["edges"]["requires"]) == ["a", "b"]   # requires EVERYTHING
                and g["order"][-1] == CAPSTONE_ID)
        # it is NOT served while anything is still unencoded…
        n0 = _capture_json(cmd_next, _ns(topic="k"))["id"]
        _capture(cmd_rate, _ns(topic="k", node="a", rating="good", grade="recalled",
                               kind="encode", production="x"))
        n1 = _capture_json(cmd_next, _ns(topic="k"))["id"]
        _capture(cmd_rate, _ns(topic="k", node="b", rating="good", grade="recalled",
                               kind="encode", production="y"))
        # …and the moment the frontier empties, `next` serves it like anything else
        n2 = _capture_json(cmd_next, _ns(topic="k"))["id"]
        return born and n0 == "a" and n1 == "b" and n2 == CAPSTONE_ID
    check("THE CAPSTONE IS A NODE: it requires every concept, and `next` serves it when the frontier empties",
          fresh(_capstone_is_in_the_dag))

    # -- materializing a capstone into an EXISTING (pre-v0.8) graph is idempotent --
    def _capstone_materialization_is_idempotent(h):
        _add_transfer_topic()
        g = load_graph("k")
        del g["nodes"][CAPSTONE_ID]                       # simulate a pre-v0.8 graph
        g["order"] = [n for n in g["order"] if n != CAPSTONE_ID]
        save_graph(g)
        nx = _capture_json(cmd_next, _ns(topic="k"))
        _capture(cmd_rate, _ns(topic="k", node="a", rating="good", grade="recalled",
                               kind="encode", production="x"))
        _capture(cmd_rate, _ns(topic="k", node="b", rating="good", grade="recalled",
                               kind="encode", production="y"))
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
        g = {"topic": "k", "title": "K", "order": ["a"], "nodes": {
            "a": {"claim": "C", "probe": "P", "transfer_probe": "TP",
                  "transfer": {"state": "applied", "last": "2026-01-01", "receipts": 99},
                  "capstone": True}}}      # a payload trying to mint its own capstone, too
        pth = p("payload.json")
        write_json(pth, g)
        _capture(cmd_add_topic, _ns(file=pth, replace=False))
        node = load_graph("k")["nodes"]["a"]
        st = _capture_json(cmd_stats, _ns())["transfer"]
        return ("transfer" not in node and node.get("capstone") is not True
                and st["states"]["applied"] == 0 and st["states"]["untested"] == 1)
    check("a payload cannot CLAIM a transfer state or mint a capstone (state advances only through receipts)",
          fresh(_payload_cannot_claim_transfer))

    # -- the cooldown: a mature node is not re-probed every single session --
    def _transfer_has_a_cooldown(h):
        _add_transfer_topic()
        _mature()
        _capture(cmd_rate, _ns(topic="k", node="a", rating="good", grade="recalled",
                               kind="transfer", production="applied"))
        hot = _capture_json(cmd_transfer, _ns(topic="k", limit=None))["n"]
        os.environ["ENGRAM_TODAY"] = "2027-04-05"     # 29 days later: still cooling
        warm = _capture_json(cmd_transfer, _ns(topic="k", limit=None))["n"]
        os.environ["ENGRAM_TODAY"] = "2027-06-06"     # 61 days later: askable again
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
    # v0.7 shipped a stamp that reached the JSON, the CLI and the skill — and was thrown away by
    # the HTML page, which is the only surface a human actually looks at. The rule earned there
    # is now applied here, in the same release that wrote it down.
    def _dashboard_shows_the_capability_claim(h):
        _add_transfer_topic()
        _mature()
        html0 = open(_capture_json(cmd_report, _ns(out=None, allow_outside=False))["path"],
                     encoding="utf-8").read()
        never = ("NO CAPABILITY HAS EVER BEEN MEASURED" in html0
                 and "Never pooled with retention" in html0)
        _capture(cmd_rate, _ns(topic="k", node="a", rating="hard", grade="partial",
                               kind="transfer", production="half"))
        html1 = open(_capture_json(cmd_report, _ns(out=None, allow_outside=False))["path"],
                     encoding="utf-8").read()
        # a HALF application must read 0% fired on the page, never 100%
        measured = ("FIRED on 0%" in html1 and "Transfer" in html1)
        return never and measured
    check("§4.8 Q4: the DASHBOARD shows the capability claim (and a half-application reads 0% fired)",
          fresh(_dashboard_shows_the_capability_claim))

    # -- §5.5 THE INSTRUMENT GATE — the new protocol rule, applied to the release that wrote it --
    # `stats.transfer` does not merely report; it CERTIFIES ("this capability is yours"). v0.7's
    # gold set was an instrument nobody thought to test, and it turned out to RANK A FOOLED GRADER
    # ABOVE A CORRECT ONE — eight gates walked past it because every one tested the subject and
    # none tested the ruler. So: build a deliberately WRONG subject, run it through the instrument,
    # and demand it scores WORSE. A ruler that ranks failure above success is not a lenient ruler;
    # it is a NEGATIVE one, and every number downstream of it has its sign flipped.
    # Test the WHOLE ordering, not just the endpoints. The first draft compared only `recalled`
    # against `lapsed` — and a mutation that miscounted `partial` as a fired capability sailed
    # straight through it, because it preserved the two endpoints it happened to check. An
    # instrument gate that only exercises the extremes cannot see the middle, which is precisely
    # where a ruler gets bent. §4.5, again: ask what ELSE would make this assertion true.
    def _transfer_instrument_is_monotone(_h=None):
        def learner(grade, rating):
            def go(h):
                _add_transfer_topic()
                _mature()
                _capture(cmd_rate, _ns(topic="k", node="a", rating=rating, grade=grade,
                                       kind="transfer", production="p"))
                return _capture_json(cmd_stats, _ns())["transfer"]
            return fresh(go)()
        fired = learner("recalled", "good")     # the capability FIRED
        half = learner("partial", "hard")       # it half-fired — NOT the same thing
        none = learner("lapsed", "again")       # it did not fire at all
        return (
            # `rate_fired` is the STRICT bar (`state: applied`): a half-application is not a yes
            fired["rate_fired"] > half["rate_fired"] == none["rate_fired"] == 0.0
            # `rate_any` is the LOOSE bar (the same one retention uses): partial sits in between
            and fired["rate_any"] == half["rate_any"] == 1.0 > none["rate_any"]
            # …and the STATE agrees with the strict bar, on all three
            and fired["states"]["applied"] == 1
            and half["states"]["applied"] == 0 and half["states"]["probed"] == 1
            and none["states"]["applied"] == 0 and none["states"]["probed"] == 1
            # …and the read a human sees never calls a half-application a fired one
            and "FIRED on 100%" in fired["read"]
            and "FIRED on 0%" in half["read"] and "FIRED on 0%" in none["read"])
    check("§5.5 THE INSTRUMENT GATE: lapsed < partial < recalled — a FAILED transfer scores WORSE",
          _transfer_instrument_is_monotone)

    # -- the CAPSTONE gets NO provisional credit: it may not be built on ungraded prerequisites --
    # Found by an EXISTING check breaking the moment the capstone entered the DAG. An ordinary
    # node advances on a stashed-but-ungraded prereq (so the tutor can keep teaching while the
    # assessor works). The capstone is the claim that the learner can now USE the topic — serving
    # it on unverified mastery is exactly the unearned claim the constitution forbids.
    def _capstone_needs_graded_prereqs(h):
        _add_transfer_topic()
        for nid in ("a", "b"):
            _capture(cmd_stash, _ns(action="add", json=json.dumps(
                {"topic": "k", "node": nid, "probe": "p", "production": "ans"})))
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
                and all(set(it) == set(GOLD_ASSESSOR_KEYS)
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
        keys_exact = all(set(it) == set(GOLD_ASSESSOR_KEYS) for it in items)
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
            "production": "prod", "confidence": 60, "kind": "encode"}]), file=None))
        stashed = _capture_json(cmd_stash, _ns(action="list", json=None, file=None))
        gold_items = _capture_json(cmd_gold, _ns())
        # both are BARE ARRAYS, and every field the assessor reads is present in both
        return (isinstance(stashed, list) and isinstance(gold_items, list)
                and set(GOLD_ASSESSOR_KEYS) <= set(stashed[0])
                and set(GOLD_ASSESSOR_KEYS) == set(gold_items[0]))
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
                      "f": {"claim": "c", "probe": "p", "state": ["x"], "fsrs": {}}}})
        write_json(p("graphs", "worse.json"), {"topic": "worse", "nodes": "not-an-object"})
        with open(p("receipts", "bad.jsonl"), "w", encoding="utf-8") as f:
            f.write(json.dumps({"ts": 20260701, "topic": {"x": 1}, "node": ["y"],
                                "kind": "review", "rating": {"bad": 1}, "grade": ["worse"],
                                "s_before": "NaN", "sid": []}) + "\n")
            f.write("THIS LINE IS NOT JSON\n")
            f.write(json.dumps({"ts": "2026-07-01", "topic": "bad", "node": "a",
                                "kind": "review", "rating": "good"}) + "\n")
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

    # -- experiment guards: >=2 arms, one active at a time (SEC-06) --
    def _experiment_guard(h):
        empty = raises(cmd_experiment, _ns(action="start",
                       json=json.dumps({"question": "q", "arms": [], "metric": "m"})))
        _capture(cmd_experiment, _ns(action="start", json=json.dumps(
            {"question": "q", "arms": ["x", "y"], "metric": "m"})))
        second = raises(cmd_experiment, _ns(action="start", json=json.dumps(
            {"question": "q2", "arms": ["x", "y"], "metric": "m"})))
        return empty and second
    check("experiment requires >=2 arms and one active at a time", fresh(_experiment_guard))

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
    for i in range(6):
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
          mod["explorable"]["n"] == 6 and mod["explorable"]["first_review_recall"] == 1.0
          and mod["dialogue"]["n"] == 6 and mod["dialogue"]["first_review_recall"] == 0.0
          and mod["read"] == "explorable-encoded ahead")
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
                    items=None, notes=None, path=None)
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
                 "adherence", "retention", "gold", "grader-health"):
        sub.add_parser(name)

    sp = sub.add_parser("assessor-audit")
    sp.add_argument("--file"); sp.add_argument("--json")
    sp.add_argument("--gold", help="override the gold set (testing; default = bundled)")

    sp = sub.add_parser("transfer")
    sp.add_argument("--topic"); sp.add_argument("--limit", type=int)

    sp = sub.add_parser("capstone")
    sp.add_argument("--topic", required=True)

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
    sp.add_argument("--topic"); sp.add_argument("--limit", type=int)

    sp = sub.add_parser("rate")
    sp.add_argument("--topic", required=True); sp.add_argument("--node", required=True)
    sp.add_argument("--rating", required=True, choices=sorted(RATINGS))
    sp.add_argument("--confidence", type=int)
    sp.add_argument("--production"); sp.add_argument("--production-file")
    sp.add_argument("--grade", choices=GRADES); sp.add_argument("--probe")
    sp.add_argument("--source", default="self")
    sp.add_argument("--kind", default="review", choices=KINDS)

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
    sp.add_argument("action", choices=("start", "assign", "settle", "list"))
    sp.add_argument("--json"); sp.add_argument("--file"); sp.add_argument("--id")
    sp.add_argument("--verdict"); sp.add_argument("--topic"); sp.add_argument("--node")

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
                "log-session", "refit", "commit", "assessor-audit", "capstone"}
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
