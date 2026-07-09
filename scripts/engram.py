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
    out.update({
        "s": round(s, 4), "d": round(d, 4),
        "last": on_date.isoformat(),
        "due": (on_date + timedelta(days=ivl)).isoformat(),
        "reps": fsrs.get("reps", 0) + 1,
        "lapses": fsrs.get("lapses", 0) + (1 if (g == 1 and s0 is not None) else 0),
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

DEFAULT_MODEL = {
    "schema": SCHEMA,
    "created": None,
    "memory": {"fsrs_params": None, "desired_retention": RETENTION_DEFAULT,
               "interval_multiplier": 1.0, "last_refit": None},
    "challenge_band": {"target_success": 0.85, "hint_budget": 2},
    "interests": [],
    "goals": [],
    "strategy_weights": {"derivation_first": 0.6, "example_first": 0.4},
    "settings": {"default_mode": "standard", "artifacts": "threshold-only", "ambient": "quiet",
                 "momentum": "on", "profile": None},
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

def load_graph(topic):
    require_slug(topic)
    path = p("graphs", topic + ".json")
    existed = os.path.exists(path)
    g = read_json(path)   # quarantines corrupt JSON (renames it) and returns None
    if g is None:
        if existed:
            die("topic %s is corrupt — quarantined to a .corrupt file; run `doctor`" % topic)
        die("unknown topic: %s (run `topics` to list)" % topic)
    return g

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
    """Yield (topic, graph) for readable graphs; skip corrupt ones without dying.

    Aggregate/read-only views (topics, stats, report, due, session-start) must
    degrade gracefully when one graph file is unreadable — never brick on it."""
    for t in all_topics():
        if topic_filter and t != topic_filter:
            continue
        g = read_json(p("graphs", t + ".json"))
        if g is not None:
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
    for sub in ("graphs", "receipts", "artifacts"):
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
        for key in ("claim", "probe"):
            if not node.get(key):
                die("node %s missing %s" % (nid, key))
        node.setdefault("edges", {})
        node.setdefault("why_chain", [])
        node.setdefault("arbitrary", False)
        node.setdefault("threshold", False)
        node.setdefault("rubric", [])
        node.setdefault("transfer_probe", None)
        node.setdefault("artifact", None)
        # The engine OWNS scheduling state — never trust payload-supplied state/fsrs
        # (mastery advances only through receipts; Article 10). On --replace, carry
        # the existing schedule forward for surviving node ids so restructuring a
        # topic is not silent data loss.
        prev = old_nodes.get(nid)
        if isinstance(prev, dict) and isinstance(prev.get("fsrs"), dict):
            node["fsrs"] = prev["fsrs"]
            node["state"] = prev.get("state", "new")
        else:
            node["fsrs"] = _fresh_fsrs()
            node["state"] = "new"
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
    save_graph(g)
    emit({"ok": True, "topic": g["topic"], "nodes": len(g["nodes"]),
          "schedule_preserved": preserved, "warnings": warnings})

def state_counts(g):
    counts = {"review": 0, "learning": 0, "new": 0}
    for node in g.get("nodes", {}).values():
        st = node.get("state", "new")
        counts[st] = counts.get(st, 0) + 1
    return counts

def cmd_topics(_args):
    out = []
    for t, g in iter_graphs():
        states = state_counts(g)
        due_count = 0
        for node in g["nodes"].values():
            dd = safe_date(node.get("fsrs", {}).get("due"))
            if node.get("state") != "new" and dd and dd <= today():
                due_count += 1
        out.append({"topic": t, "title": g.get("title"), "goal": g.get("goal"),
                    "nodes": len(g["nodes"]), "states": states, "due": due_count})
    emit(out)

def pending_nodes(topic):
    """Node ids for this topic with a production stashed but not yet graded."""
    return {e.get("node") for e in read_jsonl(p(STASH_FILE))
            if e.get("topic") == topic}

def requires_met(g, node, provisional=frozenset()):
    for req in node.get("edges", {}).get("requires", []) or []:
        other = g["nodes"].get(req)
        if other is not None and other.get("state") == "new" and req not in provisional:
            return False
    return True

def cmd_next(args):
    g = load_graph(args.topic)
    stashed = pending_nodes(args.topic)  # already-produced, awaiting the assessor
    for nid in g["order"]:
        node = g["nodes"].get(nid)
        if node is None or node.get("state") != "new" or nid in stashed:
            continue  # skip a node whose production is already stashed
        # A stashed-but-ungraded prerequisite counts as provisionally met, so the
        # batch-graded /learn flow can keep advancing instead of dead-ending.
        if requires_met(g, node, stashed):
            reqs = [r for r in node.get("edges", {}).get("requires", []) or [] if r in g["nodes"]]
            emit({"topic": args.topic, "id": nid, "node": node,
                  "requires_claims": {r: g["nodes"][r].get("claim") for r in reqs},
                  "provisional_requires": [r for r in reqs
                                           if r in stashed and g["nodes"][r].get("state") == "new"],
                  "pending_verify": len(stashed),
                  "remaining_new": sum(1 for n in g["nodes"].values() if n.get("state") == "new")})
            return
    emit({"topic": args.topic, "id": None, "pending_verify": len(stashed),
          "note": ("frontier nodes remain but are awaiting assessor grading — "
                   "grade the stash to advance" if stashed else
                   "no frontier nodes: everything is encoded (or blocked by unmet requires)")})

def due_items(topic_filter=None, limit=None, horizon_days=0):
    per_topic = {}
    cutoff = today() + timedelta(days=horizon_days)
    for t, g in iter_graphs(topic_filter):
        items = []
        for nid in g["order"]:
            node = g["nodes"].get(nid)
            if node is None:
                continue  # ghost id in order (hand-edited/adversarial graph)
            fsrs = node.get("fsrs", {})
            due_d = safe_date(fsrs.get("due"))
            if node.get("state") == "new" or not due_d:
                continue
            if due_d <= cutoff:
                items.append({
                    "topic": t, "id": nid, "probe": node.get("probe"),
                    "claim": node.get("claim"), "rubric": node.get("rubric", []),
                    "threshold": node.get("threshold", False),
                    "arbitrary": node.get("arbitrary", False),
                    "due": fsrs.get("due"),
                    "overdue_days": (today() - due_d).days,
                    "s": fsrs.get("s"), "reps": fsrs.get("reps", 0),
                    "lapses": fsrs.get("lapses", 0),
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
    if truncated:
        receipt["production_truncated"] = True
    return receipt

def validate_item(item):
    """Raise (die) if an item can't be applied. Lets a batch fail before any write."""
    for key in ("topic", "node", "rating"):
        if key not in item:
            die("receipt item missing %s: %s" % (key, json.dumps(item)[:120]))
    require_slug(item["topic"])
    if item["rating"] not in RATINGS:
        die("bad rating %r (use again|hard|good|easy)" % item["rating"])
    if item.get("grade") is not None and item["grade"] not in GRADES:
        die("bad grade %r (use recalled|partial|lapsed)" % item["grade"])

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

def apply_item(item, kind):
    validate_item(item)
    g = load_graph(item["topic"])
    node = g["nodes"].get(item["node"])
    if node is None:
        die("unknown node %s in topic %s" % (item["node"], item["topic"]))
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
    receipt = make_receipt(item, {**extra, "due_next": node["fsrs"]["due"]}, kind)
    append_jsonl(p("receipts", item["topic"] + ".jsonl"), receipt)
    save_graph(g)
    drop_stash(item["topic"], item["node"])
    result = {"node": item["node"], "rating": rating, "state": node["state"],
              "due": node["fsrs"]["due"], **extra}
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
    # Validate every item AND confirm every node exists before applying ANY, so a
    # bad item (e.g. a hallucinated node id) can't half-apply the batch.
    for item in items:
        validate_item(item)
        g = load_graph(item["topic"])
        if item["node"] not in g.get("nodes", {}):
            die("unknown node %s in topic %s" % (item["node"], item["topic"]))
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
    dayset = {r.get("ts") for r in receipts if r.get("ts")}
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
    (grade) / `hard` (rating) is real partial credit, not a total miss."""
    g = r.get("grade")
    if g in OUTCOME_OF_GRADE:
        return OUTCOME_OF_GRADE[g]
    rating = r.get("rating")
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
    for r in receipts:
        d = safe_date(r.get("ts"))
        if d is None or d < cutoff:
            continue
        if r.get("kind") == "review" and r.get("rating"):
            reviews_7d += 1
            sb, sa = as_number(r.get("s_before")), as_number(r.get("s_after"))
            if sb is not None and sa is not None and sa > sb:
                gained += (sa - sb)
        if r.get("grade") == "recalled":
            recalled_7d += 1
    most_durable = None
    retained_total = 0
    for _t, g in iter_graphs():
        for nid, node in g.get("nodes", {}).items():
            if node.get("state") == "review":
                retained_total += 1
            s = as_number((node.get("fsrs") or {}).get("s"))
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

def compute_stats():
    receipts = collect_receipts()
    reviews = [r for r in receipts if r.get("kind") == "review" and r.get("rating")]
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
    calibration = _calibration([r for r in with_conf if r.get("kind") == "review"])
    calibration_encode = _calibration([r for r in with_conf if r.get("kind") != "review"])
    topics = []
    for t, g in iter_graphs():
        topics.append({"topic": t, "title": g.get("title"), "states": state_counts(g)})
    sessions = read_jsonl(p("sessions.jsonl"))
    last_coach = max((s.get("ts") for s in sessions if s.get("kind") == "coach" and s.get("ts")),
                     default=None)
    return {
        "receipts": len(receipts), "reviews": len(reviews),
        "recall_by_stability": recall,
        "calibration": calibration,
        "calibration_encode": calibration_encode,
        "streak_days": compute_streak(receipts),
        "momentum": compute_momentum(receipts),
        "due_now": len(due_items()),
        "pending_verify": len(read_jsonl(p(STASH_FILE))),
        "topics": topics,
        "misconceptions_open": len([m for m in read_json(p("misconceptions.json"), []) if m.get("status") == "open"]),
        "active_experiment": next((e["question"] for e in read_json(p("experiments.json"), []) if e.get("status") == "active"), None),
        "last_coach_checkin": last_coach,
    }

def cmd_stats(_args):
    emit(compute_stats())

STATE_DOTS = {"review": "●", "learning": "◐", "new": "·"}

def cmd_topic_status(args):
    g = load_graph(args.topic)
    counts = state_counts(g)
    total = max(1, len(g["nodes"]))
    width = 24
    filled = int(round(width * counts["review"] / total))
    half = int(round(width * counts["learning"] / total))
    bar = "█" * filled + "▒" * half + "░" * max(0, width - filled - half)
    lines = ["%s — %s" % (g["topic"], g.get("title", "")),
             "%s  %d retained · %d learning · %d untouched" % (
                 bar, counts["review"], counts["learning"], counts["new"]), ""]
    for nid in g["order"]:
        node = g["nodes"].get(nid)
        if node is None:
            continue
        fsrs = node.get("fsrs", {})
        due = fsrs.get("due") or "—"
        s = as_number(fsrs.get("s"))
        flags = ("†" if node.get("threshold") else "") + ("*" if node.get("arbitrary") else "")
        lines.append("%s %-34s%-2s due %-10s S=%s" % (
            STATE_DOTS.get(node.get("state"), "?"), nid, flags, due,
            ("%.1fd" % s) if s else "—"))
    lines.append("")
    lines.append("● retained (review)   ◐ learning   · untouched   † threshold   * memorize-only")
    print("\n".join(lines))

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
    info = {"python": "%d.%d.%d" % sys.version_info[:3], "home": home()}
    os.makedirs(home(), exist_ok=True)
    info["writable"] = os.access(home(), os.W_OK)
    if not info["writable"]:
        issues.append("state dir is not writable")
    try:
        load_model()
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
        node_count += len(g.get("nodes", {}))
        for nid in g.get("order", []):
            if nid not in g.get("nodes", {}):
                issues.append("%s: order references missing node %s" % (t, nid))
        for nid, node in g.get("nodes", {}).items():
            st = node.get("state")
            if st not in NODE_STATES:
                issues.append("%s/%s: invalid state %r" % (t, nid, st))
            due = node.get("fsrs", {}).get("due")
            if st != "new" and not due:
                issues.append("%s/%s: state=%s but no due date" % (t, nid, st))
            elif due and safe_date(due) is None:
                issues.append("%s/%s: unparseable due date %r" % (t, nid, due))
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
    model = load_model()
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
        parts.append("<div class='card'><h2 style='margin:0'>%s</h2>" % escape(g.get("title") or t))
        if g.get("goal"):
            parts.append("<p class='goal'>goal: %s</p>" % escape(str(g["goal"])))
        parts.append("<div class='bar'>%s%s</div>" % (seg(counts["review"], "good"),
                                                      seg(counts["learning"], "warn")))
        parts.append("<p class='legend'>%d retained · %d learning · %d untouched</p>"
                     % (counts["review"], counts["learning"], counts["new"]))
        rows = []
        for nid in g["order"]:
            node = g["nodes"].get(nid)
            if node is None:
                continue
            st = node.get("state", "new")
            if st not in STATE_DOTS:
                st = "new"
            fsrs = node.get("fsrs", {})
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

    parts.append("<h2>Retention by memory strength</h2>")
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

    mis = [m for m in read_json(p("misconceptions.json"), []) if m.get("status") == "open"]
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
        total[0] += 1
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
        mom = compute_momentum([
            {"ts": "2026-08-05", "kind": "review", "rating": "good",
             "s_before": 2.0, "s_after": 9.0, "grade": "recalled"},
            {"ts": "2026-08-04", "kind": "review", "rating": "hard",
             "s_before": 5.0, "s_after": 6.5},
            {"ts": "2026-08-05", "kind": "review", "rating": "again",
             "s_before": 8.0, "s_after": 3.0},          # lapse: no negative growth
            {"ts": "2026-06-01", "kind": "review", "rating": "good",
             "s_before": 1.0, "s_after": 40.0},          # outside 7-day window: excluded
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
        with tempfile.TemporaryDirectory() as h:
            os.environ["ENGRAM_HOME"] = h
            os.environ["ENGRAM_TODAY"] = "2026-07-06"
            try:
                _capture(cmd_init, _ns())
                return fn(h)
            finally:
                os.environ.pop("ENGRAM_HOME", None)
                os.environ.pop("ENGRAM_TODAY", None)

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
                    items=None, notes=None)
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

    for name in ("init", "path", "session-start", "topics", "selftest", "stats", "doctor"):
        sub.add_parser(name)

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
    sp.add_argument("--source", default="self"); sp.add_argument("--kind", default="review")

    sp = sub.add_parser("receipt")
    sp.add_argument("--json"); sp.add_argument("--file")

    sp = sub.add_parser("stash")
    sp.add_argument("action", choices=("add", "list", "count", "clear"))
    sp.add_argument("--json"); sp.add_argument("--file")

    sp = sub.add_parser("model")
    sp.add_argument("--set", action="append")
    sp.add_argument("--add-interest", action="append")
    sp.add_argument("--add-goal", action="append")

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
        "misconception": cmd_misconception, "experiment": cmd_experiment,
        "log-session": cmd_log_session, "stats": cmd_stats,
        "refit": cmd_refit, "doctor": cmd_doctor, "report": cmd_report,
        "selftest": cmd_selftest,
    }
    handlers[args.cmd](args)

if __name__ == "__main__":
    main()
