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
import sys
import tempfile
import time
from datetime import date, timedelta
from html import escape

SCHEMA = 1
RETENTION_DEFAULT = 0.90
INTERVAL_MAX = 365

# FSRS-4.5 default parameters (open-spaced-repetition). w[0..3] are initial
# stabilities for Again/Hard/Good/Easy; the rest shape difficulty and growth.
W = [0.4872, 1.4003, 3.7145, 13.8206, 5.1618, 1.2298, 0.8975, 0.031,
     1.6474, 0.1367, 1.0461, 2.1072, 0.0793, 0.3246, 1.587, 0.2272, 2.8755]
DECAY = -0.5
FACTOR = 19.0 / 81.0  # chosen so R(t=S) = 0.9

RATINGS = {"again": 1, "hard": 2, "good": 3, "easy": 4}
GRADES = ("recalled", "partial", "lapsed")
NODE_STATES = ("new", "learning", "review")

_SEQ = itertools.count()

# ---------------------------------------------------------------- fsrs core

def clamp(x, lo, hi):
    return max(lo, min(hi, x))

def retrievability(elapsed_days, stability):
    if stability <= 0:
        return 0.0
    return (1.0 + FACTOR * elapsed_days / stability) ** DECAY

def interval_for(stability, retention, multiplier=1.0):
    days = stability / FACTOR * (retention ** (1.0 / DECAY) - 1.0) * multiplier
    return int(clamp(round(days), 1, INTERVAL_MAX))

def init_stability(g):
    return clamp(W[g - 1], 0.1, 100.0)

def init_difficulty(g):
    return clamp(W[4] - (g - 3) * W[5], 1.0, 10.0)

def next_difficulty(d, g):
    nd = d - W[6] * (g - 3)
    nd = W[7] * init_difficulty(4) + (1.0 - W[7]) * nd  # mean reversion
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
    s0, d0 = fsrs.get("s"), fsrs.get("d")
    last = fsrs.get("last")
    if s0 is None:  # first exposure
        s, d, r = init_stability(g), init_difficulty(g), None
    else:
        elapsed = max(0, (on_date - date.fromisoformat(last)).days) if last else 0
        r = retrievability(elapsed, s0)
        d = next_difficulty(d0, g)
        s = next_stability_forget(d0, s0, r) if g == 1 else next_stability_recall(d0, s0, r, g)
    ivl = interval_for(s, fsrs.get("retention", RETENTION_DEFAULT), fsrs.get("im", 1.0))
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

def read_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default

def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False, sort_keys=False)
        f.write("\n")
    os.replace(tmp, path)

def append_jsonl(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
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
    "settings": {"default_mode": "standard", "artifacts": "threshold-only", "ambient": "quiet"},
    "rhythms": {},
    "accessibility": [],
}

def load_model():
    m = read_json(p("learner-model.json"))
    if m is None:
        m = json.loads(json.dumps(DEFAULT_MODEL))
        m["created"] = today().isoformat()
        write_json(p("learner-model.json"), m)
    m.setdefault("memory", {}).setdefault("interval_multiplier", 1.0)
    return m

def load_graph(topic):
    g = read_json(p("graphs", topic + ".json"))
    if g is None:
        die("unknown topic: %s (run `topics` to list)" % topic)
    return g

def save_graph(g):
    write_json(p("graphs", g["topic"] + ".json"), g)

def all_topics():
    d = p("graphs")
    if not os.path.isdir(d):
        return []
    return sorted(f[:-5] for f in os.listdir(d) if f.endswith(".json"))

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

def load_payload(args):
    if getattr(args, "file", None):
        obj = read_json(args.file)
        if obj is None:
            die("cannot read JSON file: %s" % args.file)
        return obj
    if getattr(args, "json", None):
        try:
            return json.loads(args.json)
        except json.JSONDecodeError as e:
            die("bad --json: %s" % e)
    die("provide --json or --file")

def cmd_add_topic(args):
    g = load_payload(args)
    for key in ("topic", "title", "nodes", "order"):
        if key not in g:
            die("topic JSON missing key: %s" % key)
    if not g["nodes"]:
        die("topic has no nodes")
    missing = [n for n in g["order"] if n not in g["nodes"]]
    if missing:
        die("order references unknown nodes: %s" % ", ".join(missing))
    if os.path.exists(p("graphs", g["topic"] + ".json")) and not args.replace:
        die("topic exists: %s (use --replace to overwrite)" % g["topic"])
    warnings = []
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
        node.setdefault("state", "new")
        node.setdefault("artifact", None)
        node.setdefault("fsrs", {"s": None, "d": None, "due": None, "last": None,
                                 "reps": 0, "lapses": 0})
        for etype, targets in node.get("edges", {}).items():
            for t in targets:
                if t not in g["nodes"]:
                    warnings.append("%s.%s -> unknown node '%s'" % (nid, etype, t))
    g.setdefault("schema", SCHEMA)
    g.setdefault("created", today().isoformat())
    g.setdefault("goal", None)
    save_graph(g)
    emit({"ok": True, "topic": g["topic"], "nodes": len(g["nodes"]), "warnings": warnings})

def cmd_topics(_args):
    out = []
    for t in all_topics():
        g = load_graph(t)
        states = {}
        due_count = 0
        for node in g["nodes"].values():
            states[node["state"]] = states.get(node["state"], 0) + 1
            d = node["fsrs"].get("due")
            if node["state"] != "new" and d and date.fromisoformat(d) <= today():
                due_count += 1
        out.append({"topic": t, "title": g.get("title"), "goal": g.get("goal"),
                    "nodes": len(g["nodes"]), "states": states, "due": due_count})
    emit(out)

def requires_met(g, node):
    for req in node.get("edges", {}).get("requires", []):
        other = g["nodes"].get(req)
        if other is not None and other["state"] == "new":
            return False
    return True

def cmd_next(args):
    g = load_graph(args.topic)
    for nid in g["order"]:
        node = g["nodes"][nid]
        if node["state"] == "new" and requires_met(g, node):
            req_claims = {r: g["nodes"][r]["claim"]
                          for r in node.get("edges", {}).get("requires", [])
                          if r in g["nodes"]}
            emit({"topic": args.topic, "id": nid, "node": node,
                  "requires_claims": req_claims,
                  "remaining_new": sum(1 for n in g["nodes"].values() if n["state"] == "new")})
            return
    emit({"topic": args.topic, "id": None,
          "note": "no frontier nodes: everything is encoded (or blocked by unmet requires)"})

def due_items(topic_filter=None, limit=None, horizon_days=0):
    per_topic = {}
    cutoff = today() + timedelta(days=horizon_days)
    for t in all_topics():
        if topic_filter and t != topic_filter:
            continue
        g = load_graph(t)
        items = []
        for nid in g["order"]:
            node = g["nodes"][nid]
            d = node["fsrs"].get("due")
            if node["state"] == "new" or not d:
                continue
            due_d = date.fromisoformat(d)
            if due_d <= cutoff:
                items.append({
                    "topic": t, "id": nid, "probe": node["probe"],
                    "claim": node["claim"], "rubric": node.get("rubric", []),
                    "threshold": node.get("threshold", False),
                    "arbitrary": node.get("arbitrary", False),
                    "due": d,
                    "overdue_days": (today() - due_d).days,
                    "s": node["fsrs"].get("s"), "reps": node["fsrs"].get("reps", 0),
                    "lapses": node["fsrs"].get("lapses", 0),
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
    if limit:
        merged = merged[:limit]
    return merged

def cmd_due(args):
    emit(due_items(args.topic, args.limit))

def make_receipt(item, extra, kind):
    conf = item.get("confidence")
    return {
        "id": "r_%d_%03d" % (int(time.time() * 1000), next(_SEQ)),
        "ts": today().isoformat(),
        "topic": item["topic"], "node": item["node"],
        "kind": kind,
        "probe": item.get("probe"),
        "production": (item.get("production") or "")[:800] or None,
        "confidence": (int(conf) if conf is not None else None),
        "grade": item.get("grade"),
        "rating": item["rating"],
        "misconceptions": item.get("misconceptions", []),
        "rubric_notes": item.get("rubric_notes"),
        "source": item.get("source", "self"),
        **extra,
    }

def apply_item(item, kind):
    g = load_graph(item["topic"])
    node = g["nodes"].get(item["node"])
    if node is None:
        die("unknown node %s in topic %s" % (item["node"], item["topic"]))
    rating = item["rating"]
    if rating not in RATINGS:
        die("bad rating %r (use again|hard|good|easy)" % rating)
    if item.get("grade") is not None and item["grade"] not in GRADES:
        die("bad grade %r (use recalled|partial|lapsed)" % item["grade"])
    model = load_model()
    node["fsrs"]["retention"] = model["memory"].get("desired_retention", RETENTION_DEFAULT)
    node["fsrs"]["im"] = model["memory"].get("interval_multiplier", 1.0)
    was_new = node["fsrs"].get("s") is None
    node["fsrs"], extra = apply_rating(node["fsrs"], rating, today())
    node["fsrs"].pop("retention", None)
    node["fsrs"].pop("im", None)
    if rating == "again":
        node["state"] = "learning"
    elif was_new and rating == "hard":
        node["state"] = "learning"
    else:
        node["state"] = "review"
    save_graph(g)
    receipt = make_receipt(item, {**extra, "due_next": node["fsrs"]["due"]}, kind)
    append_jsonl(p("receipts", item["topic"] + ".jsonl"), receipt)
    return {"node": item["node"], "rating": rating, "state": node["state"],
            "due": node["fsrs"]["due"], **extra}

def cmd_rate(args):
    item = {"topic": args.topic, "node": args.node, "rating": args.rating,
            "confidence": args.confidence, "production": args.production,
            "grade": args.grade, "probe": args.probe, "source": args.source}
    emit(apply_item(item, args.kind))

def cmd_receipt(args):
    payload = load_payload(args)
    items = payload if isinstance(payload, list) else [payload]
    results = []
    for item in items:
        for key in ("topic", "node", "rating"):
            if key not in item:
                die("receipt item missing %s: %s" % (key, json.dumps(item)[:120]))
        results.append(apply_item(item, item.get("kind", "encode")))
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
            item.setdefault("ts", today().isoformat())
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
            ref = m
            parts = key.split(".")
            if parts[0] not in m:
                die("unknown model key: %s" % parts[0])
            for part in parts[:-1]:
                ref = ref.setdefault(part, {})
            ref[parts[-1]] = val
            changed = True
    for interest in (args.add_interest or []):
        if interest not in m["interests"]:
            m["interests"].append(interest)
            changed = True
    if changed:
        write_json(p("learner-model.json"), m)
    emit(m)

def cmd_misconception(args):
    path = p("misconceptions.json")
    items = read_json(path, [])
    if args.action == "add":
        items.append({"id": "m_%d_%03d" % (int(time.time() * 1000), next(_SEQ)),
                      "ts": today().isoformat(), "topic": args.topic,
                      "node": args.node, "description": args.description,
                      "status": "open"})
        write_json(path, items)
    elif args.action == "resolve":
        for it in items:
            if it["id"] == args.id:
                it["status"] = "resolved"
                it["resolved_ts"] = today().isoformat()
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
        exp.update({"id": "x_%d" % int(time.time() * 1000),
                    "started": today().isoformat(), "status": "active",
                    "assignments": [], "verdict": None})
        items.append(exp)
        write_json(path, items)
        emit(exp)
    elif args.action == "assign":
        active = [e for e in items if e["status"] == "active"]
        if not active:
            emit({"arm": None, "note": "no active experiment"})
            return
        exp = active[0]
        arm = exp["arms"][len(exp["assignments"]) % len(exp["arms"])]
        exp["assignments"].append({"ts": today().isoformat(), "arm": arm,
                                   "topic": args.topic, "node": args.node})
        write_json(path, items)
        emit({"id": exp["id"], "arm": arm})
    elif args.action == "settle":
        for exp in items:
            if exp["id"] == args.id:
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
    dayset = {r["ts"] for r in receipts}
    cursor = today()
    if cursor.isoformat() not in dayset:
        cursor -= timedelta(days=1)  # grace: today isn't over yet
    streak = 0
    while cursor.isoformat() in dayset:
        streak += 1
        cursor -= timedelta(days=1)
    return streak

def compute_stats():
    receipts = collect_receipts()
    reviews = [r for r in receipts if r.get("kind") == "review" and r.get("rating")]
    def bucket(r):
        s = r.get("s_before") or 0
        return "early" if s < 7 else ("week" if s < 30 else "month+")
    buckets = {}
    for r in reviews:
        b = bucket(r)
        ok = 1 if r["rating"] != "again" else 0
        agg = buckets.setdefault(b, [0, 0])
        agg[0] += ok
        agg[1] += 1
    recall = {b: {"rate": round(v[0] / v[1], 3), "n": v[1]} for b, v in buckets.items() if v[1]}
    graded = [r for r in receipts if r.get("confidence") is not None and r.get("rating")]
    brier = bias = None
    if graded:
        pairs = [((r["confidence"] / 100.0), (1.0 if r["rating"] in ("good", "easy") else 0.0))
                 for r in graded]
        brier = round(sum((c - o) ** 2 for c, o in pairs) / len(pairs), 4)
        bias = round(sum(c - o for c, o in pairs) / len(pairs), 4)
    topics = []
    for t in all_topics():
        g = load_graph(t)
        states = {}
        for node in g["nodes"].values():
            states[node["state"]] = states.get(node["state"], 0) + 1
        topics.append({"topic": t, "title": g.get("title"), "states": states})
    sessions = read_jsonl(p("sessions.jsonl"))
    last_coach = max((s["ts"] for s in sessions if s.get("kind") == "coach"), default=None)
    return {
        "receipts": len(receipts), "reviews": len(reviews),
        "recall_by_stability": recall,
        "calibration": {"brier": brier, "bias": bias, "n": len(graded),
                        "read": (None if bias is None else
                                 ("overconfident" if bias > 0.05 else
                                  "underconfident" if bias < -0.05 else "well-calibrated"))},
        "streak_days": compute_streak(receipts),
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
    counts = {"review": 0, "learning": 0, "new": 0}
    for node in g["nodes"].values():
        counts[node["state"]] = counts.get(node["state"], 0) + 1
    total = len(g["nodes"])
    width = 24
    filled = int(round(width * counts["review"] / total))
    half = int(round(width * counts["learning"] / total))
    bar = "█" * filled + "▒" * half + "░" * max(0, width - filled - half)
    lines = ["%s — %s" % (g["topic"], g.get("title", "")),
             "%s  %d retained · %d learning · %d untouched" % (
                 bar, counts["review"], counts["learning"], counts["new"]), ""]
    for nid in g["order"]:
        node = g["nodes"][nid]
        due = node["fsrs"].get("due") or "—"
        s = node["fsrs"].get("s")
        flags = ("†" if node.get("threshold") else "") + ("*" if node.get("arbitrary") else "")
        lines.append("%s %-34s%-2s due %-10s S=%s" % (
            STATE_DOTS.get(node["state"], "?"), nid, flags, due,
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
            by_topic[d["topic"]] = by_topic.get(d["topic"], 0) + 1
        summary = ", ".join("%s: %d" % kv for kv in sorted(by_topic.items(), key=lambda x: -x[1])[:3])
        minutes = max(1, round(len(due) * 0.6))
        print("[engram] %d review%s due (%s) · ~%d min · /review to clear, /learn to continue."
              % (len(due), "s" if len(due) != 1 else "", summary, minutes))
    if pending:
        print("[engram] %d production%s awaiting assessor grading — /learn or /review will finish verification."
              % (pending, "s" if pending != 1 else ""))
    sessions = read_jsonl(p("sessions.jsonl"))
    last_coach = max((s["ts"] for s in sessions if s.get("kind") == "coach"), default=None)
    if last_coach and (today() - date.fromisoformat(last_coach)).days > 7:
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
        g = read_json(p("graphs", t + ".json"))
        if g is None:
            issues.append("graph unreadable: %s" % t)
            continue
        node_count += len(g.get("nodes", {}))
        for nid in g.get("order", []):
            if nid not in g.get("nodes", {}):
                issues.append("%s: order references missing node %s" % (t, nid))
        for nid, node in g.get("nodes", {}).items():
            if node.get("state") != "new" and not node.get("fsrs", {}).get("due"):
                issues.append("%s/%s: state=%s but no due date" % (t, nid, node.get("state")))
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

    for t in all_topics():
        g = load_graph(t)
        counts = {"review": 0, "learning": 0, "new": 0}
        for node in g["nodes"].values():
            counts[node["state"]] += 1
        total = max(1, len(g["nodes"]))
        seg = lambda n, color: ("<span style='width:%.1f%%;background:var(--%s)'></span>"
                                % (100.0 * n / total, color)) if n else ""
        parts.append("<div class='card'><h2 style='margin:0'>%s</h2>" % escape(g.get("title") or t))
        if g.get("goal"):
            parts.append("<p class='goal'>goal: %s</p>" % escape(g["goal"]))
        parts.append("<div class='bar'>%s%s</div>" % (seg(counts["review"], "good"),
                                                      seg(counts["learning"], "warn")))
        parts.append("<p class='legend'>%d retained · %d learning · %d untouched</p>"
                     % (counts["review"], counts["learning"], counts["new"]))
        rows = []
        for nid in g["order"]:
            node = g["nodes"][nid]
            flags = ("<span class='flag'>†</span>" if node.get("threshold") else "") + \
                    ("<span class='flag'>*</span>" if node.get("arbitrary") else "")
            s = node["fsrs"].get("s")
            rows.append("<tr><td class='dot-%s'>%s</td><td>%s %s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
                node["state"], STATE_DOTS[node["state"]], escape(nid), flags,
                ("%.1fd" % s) if s else "—", node["fsrs"].get("due") or "—",
                node["fsrs"].get("lapses", 0) or ""))
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
        check("stats flags overconfident lapse", stats["calibration"]["read"] == "overconfident")

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

    print("\n%d/%d checks passed" % (total[0] - len(failures), total[0]))
    sys.exit(1 if failures else 0)

def _ns(**kw):
    class NS:
        pass
    ns = NS()
    defaults = dict(topic=None, node=None, rating=None, confidence=None,
                    production=None, grade=None, probe=None, source="self",
                    kind="review", json=None, file=None, replace=False,
                    limit=None, set=None, add_interest=None, action=None,
                    id=None, verdict=None, description=None, force=False,
                    out=None, mode=None, minutes=None, items=None, notes=None)
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
    sp.add_argument("--confidence", type=int); sp.add_argument("--production")
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
    sp.add_argument("--out")

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
