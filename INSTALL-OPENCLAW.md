# Engram on OpenClaw

Engram is an **omni-repo**: one codebase that runs on Claude Code, OpenAI Codex, OpenCode, Hermes Agent, Google Antigravity — and [OpenClaw](https://docs.openclaw.ai), the self-hosted gateway that puts an agent behind Discord, Slack, Telegram, WhatsApp, iMessage, Signal, and friends. The core is the same everywhere: `skills/` (Agent Skills `SKILL.md`) plus the dependency-free `scripts/engram.py`. This file covers the OpenClaw-specific glue.

> Verified against **OpenClaw 2026.7.1-2** on macOS. What was and wasn't proven is itemised in [honest status](#honest-status-of-the-openclaw-glue) — including the one thing that needs a live model and therefore isn't ticked.

OpenClaw is the first Engram platform where the tutor lives **in a chat app**. `/review` from your phone on the train is the use case the FSRS schedule was always waiting for.

## What ships for OpenClaw

```
skills/                     # SHARED — the same three skills every platform uses
scripts/engram.py           # SHARED — the same engine, same state, same schedule
hooks/engram-due/           # OpenClaw hook pack: HOOK.md + handler.js — the due-review nudge
skills/_shared/subagents.md # how to spawn the blind assessor where no agent registry exists
agents/*.md                 # prompt sources the spawned children read
```

## Requirements

- **Node 22.22.3+, 24.15+, or 25.9+.** OpenClaw refuses to start on versions in between — notably Node 25.0–25.8, which prints an `nvm use 24` hint and exits.
- **`python3`** on the machine running the Gateway (stock macOS/Linux is fine; stdlib only).

## Install

**1 · Install the plugin** — engram ships a Claude-compatible marketplace manifest, which OpenClaw reads directly from GitHub:

```bash
openclaw plugins install engram --marketplace nagisanzenin/engram
```

A local clone works the same way (`openclaw plugins install /path/to/engram`), which is the route to use if you want to track `main`.

**2 · Turn on internal hooks** — this step is not optional if you want the nudge:

```bash
openclaw config set hooks.internal.enabled true
```

**3 · Restart the Gateway:**

```bash
openclaw gateway restart
```

That's the install. `/learn`, `/review`, and `/coach` are now slash commands on every OpenClaw surface, and all three join the skill index for natural-language activation ("teach me Kalman filters").

### Why step 2 exists

OpenClaw **skips internal hook discovery entirely** until something opts in, and shipping a hook pack inside a plugin does *not* opt in on its own. Skip step 2 and `openclaw hooks list` will cheerfully show `engram-due ✓ ready` while it never runs once — the failure is silent and looks like success. Confirm it actually loaded:

```bash
openclaw --log-level debug gateway run | grep engram-due
# Registered hook: engram-due -> command:new, command:reset
```

## Invoking the skills

| You want | Type |
|---|---|
| to learn a topic | `/learn <topic>` — or just say "teach me X" |
| a review session | `/review` |
| stats & coaching | `/coach` |

The nudge fires on **`/new` and `/reset`**, not on every message. Those are the only two internal hook events whose output OpenClaw routes back to the originating conversation, so they are the honest equivalent of Claude Code's `SessionStart`. Starting a fresh conversation is what surfaces "[engram] 7 reviews due · ~4 min"; mid-conversation stays quiet, which is the intent (Constitution art. 8: ambient, never nagging).

## The assessor (blind grading) on OpenClaw

**This is the part that needs your attention**, because it is the part a careless port would quietly drop.

OpenClaw reads engram as a **Codex bundle**, and no bundle format maps an `agents/` directory into a usable agent registry — Claude-format bundles detect `agents` and explicitly do not execute them. So `engram-assessor`, `engram-curriculum-architect`, and `engram-artifact-smith` are **not registered** as agents here.

What OpenClaw does have is `sessions_spawn`, whose default `context: "isolated"` starts the child with **a clean transcript** — it sees the task text and nothing else of the parent conversation. That is precisely the assessor's blindness requirement, so the separation of powers survives structurally rather than by convention:

```
sessions_spawn({
  context: "isolated",
  task: "Read <plugin-root>/agents/engram-assessor.md and follow it exactly.
         Grade the items in <path>. Return only the receipt JSON."
})
```

Then `sessions_yield` — `sessions_spawn` is non-blocking and the child's result arrives as the next message. The skills carry these instructions; the full contract is in [`skills/_shared/subagents.md`](skills/_shared/subagents.md).

**One config check.** `sessions_spawn` sits behind tool policy: the `coding` and `full` profiles include it, `messaging` and `minimal` do not. On a narrow profile there is no blind grader — and Engram has no degraded mode where the tutor grades its own learner. If `/learn` reports the tool missing:

```bash
openclaw config set tools.profile coding
# or: tools.alsoAllow: ["sessions_spawn", "sessions_yield"]
```

## Where state lives

`engram.py` keeps state in `~/.claude/learning` (override with `ENGRAM_HOME`) **on the host running the Gateway**. Learn at your desk in Claude Code, clear the reviews from Telegram on the way home — same schedule, one memory. If the Gateway runs on a VPS, that host owns the state; point `ENGRAM_HOME` at persistent storage there.

## Verify the install

```bash
python3 ~/.openclaw/extensions/engram/scripts/engram.py selftest   # 217/217, same engine everywhere
openclaw skills list | grep -E "learn|review|coach"                # three ✓ ready rows
openclaw hooks info engram-due                                     # ready, events, python3 satisfied
openclaw plugins doctor                                            # no plugin issues
```

## A note for maintainers: the manifest trap

Engram's `.codex-plugin/plugin.json` deliberately declares **no `hooks` key**, and re-adding one will silently break the nudge.

OpenClaw matches `.codex-plugin/plugin.json` *before* `.claude-plugin/plugin.json` and before `openclaw.plugin.json`, so engram is always a Codex bundle here regardless of what other manifests it ships. For Codex bundles OpenClaw treats the manifest's `hooks` value as a list of **directories to scan for hook packs**. The old `"hooks": "./hooks/hooks.json"` therefore aimed the scanner at a *file*, found no `*/HOOK.md`, and loaded nothing — while still reporting `hooks` as a bundle capability, which is what makes the failure so easy to miss.

Dropping the key lets both platforms fall back to their documented conventions: Codex auto-discovers `./hooks/hooks.json`, and OpenClaw scans `./hooks/`, where `engram-due/` lives. (Adding an `openclaw.plugin.json` does *not* help — the Codex marker is matched first — and would become a live landmine if OpenClaw ever fixes its precedence to match its own docs, which state native manifests win.)

## Honest status of the OpenClaw glue

**Verified on 2026.7.1-2** (macOS, isolated `OPENCLAW_STATE_DIR`, live `gpt-5.4`, `ENGRAM_HOME` pointed at a throwaway store):

*Packaging* — install from a local path, a local marketplace, and the GitHub marketplace source; detection as a `codex` bundle with `skills, hooks` capabilities; `plugins doctor` clean; `engram.py selftest` 217/217 and the OpenCode suite 88/88 unchanged.

*Skills* — all three discovered `✓ ready`, and a **live model asked to name its learning-related skills answered `coach` / `learn` / `review`**. `/review` and `/coach` were driven end-to-end against a seeded store and produced real Engram output (due counts, decay arithmetic, the arrow-key opening).

*Nudge* — `engram-due` registered with the correct events and satisfied `python3`; the Gateway loader registers it (`loaded 6 internal hook handlers`) with `hooks.internal.enabled` set and registers **zero** without it; and on a live `/new` the handler was observed running, resolving the engine, and pushing the 217-character two-line nudge onto `event.messages`. Unit-tested separately for the negative cases: silent on an empty store, ignores `stop`/`message:*`/malformed events.

*Blind grading* — the full `sessions_spawn` round-trip. A child spawned with `context: "isolated"` ran in its own session (`agent:main:subagent:<uuid>`), read `agents/engram-assessor.md` from the installed plugin, and returned a valid receipt — `grade: "recalled"`, `rating: "easy"`, `rubric_notes` quoting both criteria, `grader: "engram-assessor"`. **The child's submitted prompt was inspected in the trajectory log and contained only the task text** — no tutoring dialogue, no parent transcript. The blindness is real, not aspirational. A deliberate negative was also observed: pointed at a missing instructions file, the child returned `{"status":"blocked"}` and **refused to grade** rather than improvising one.

**Not verified:** delivery of the nudge to a real chat surface. The handler demonstrably pushes the text; routing it onward needs a connected channel (Discord/Telegram/etc.), which this test did not have — the CLI `agent` path has no originating conversation to reply into, so it drops the message. Also unverified: a complete `/learn` tutoring session (long and interactive; its architect spawn uses the same `sessions_spawn` path proven above) and the artifact smith. Reports welcome — open an issue with what you see.

**Known gap:** the artifact smith writes explorable HTML to disk, which is a natural fit for a terminal and an awkward one for a chat channel. On OpenClaw it still writes and registers the file; how best to hand a learner an interactive HTML file over Discord is an open design question, not a solved one.
