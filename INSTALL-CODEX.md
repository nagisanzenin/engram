# Engram on OpenAI Codex

Engram is an **omni-repo**: one codebase that runs on both Claude Code and OpenAI Codex. The core is the same everywhere — the `skills/` (Agent Skills standard `SKILL.md`) and the dependency-free `scripts/engram.py` engine are shared verbatim. This file covers the Codex-specific glue. Claude Code users need none of this; see the main README.

> Codex's plugin, skills, and hooks systems are modeled closely on Claude Code's, so most of this is 1:1. The two genuine differences are called out as **⚠ Codex difference** below.

## What ships for Codex

```
.codex-plugin/plugin.json          # Codex plugin manifest (mirrors .claude-plugin/plugin.json)
.agents/plugins/marketplace.json   # Codex marketplace catalog (source: "./")
codex/agents/*.toml                # TOML ports of the 3 subagents (assessor, architect, artifact-smith)
skills/                            # SHARED — the same skills Claude Code uses
scripts/engram.py                  # SHARED — the same engine
hooks/                             # SHARED — SessionStart hook (self-resolving)
```

## Install

### Route A — as a plugin (skills + SessionStart hook)

```bash
codex plugin marketplace add nagisanzenin/engram     # or /plugin marketplace add in-session
codex plugin add engram@engram                        # or /plugin install engram@engram
# restart Codex / reload plugins
```

The three skills become available as `$learn`, `$review`, `$coach` (Codex invokes skills by `$name` mention or via the `/skills` picker — there is no `/learn` slash command as on Claude Code).

### Route B — skills only (no plugin machinery)

Any Agent Skills installer works, because `skills/*/SKILL.md` is the open standard:

```bash
npx skills add nagisanzenin/engram          # symlinks the skills into your agent dirs
# or, with Codex's bundled installer:
#   $skill-installer install learn from nagisanzenin/engram
```

Skills land in `~/.agents/skills/<name>/` (some tool versions still use the legacy `~/.codex/skills/`; both are read).

## The two Codex differences

### ⚠ 1. Subagents are TOML, and explicit-invocation only

Claude Code auto-delegates to `agents/*.md` subagents ("MUST BE USED"). Codex subagents are **TOML** and are spawned **only when you ask by name**. So:

- Install the ports into your Codex agents dir (the installer below does this):
  ```bash
  bash scripts/install-codex.sh          # copies codex/agents/*.toml -> ~/.codex/agents/
  ```
- When a skill says "spawn the engram-assessor", on Codex you invoke it explicitly:
  `$engram-assessor, grade these: <paste the stash JSON>`. The assessor stays **blind to the tutoring dialogue** exactly as on Claude Code — that separation of powers is preserved; only the *trigger* is manual.
- Plugin-distributed TOML agents are not yet a documented Codex feature, which is why they install separately rather than riding along in the plugin.

### ⚠ 2. Where state lives, and the sandbox

`engram.py` defaults its state to `~/.claude/learning` and respects **`ENGRAM_HOME`**. On Codex, either keep the default or point it somewhere neutral:

```bash
export ENGRAM_HOME="$HOME/.engram"       # optional; add to your shell rc
```

Codex's default `workspace-write` sandbox restricts writes to the current workspace. If your `ENGRAM_HOME` (or the default `~/.claude/learning`) is **outside** the workspace, `engram.py` writes and the artifact-smith's HTML output may prompt for approval. Setting `ENGRAM_HOME` inside your project, or granting the engram commands standing approval, avoids the prompts. (`engram.py` itself has no network code — the sandbox concern is purely local file writes.)

## Verify the install

```bash
python3 scripts/engram.py selftest     # 63/63 checks — same engine on every agent
python3 scripts/engram.py doctor       # state + environment diagnostics
```

## Honest status of the Codex glue

Verified: the shared skills and engine (identical to Claude Code), the self-resolving SessionStart hook, and the TOML agent ports. **Not independently verified against a live Codex binary** (this release was built without one): the exact Codex marketplace-manifest schema, whether Codex expands a plugin-root env var inside `hooks.json` (the hook self-resolves regardless, and degrades to silence on any failure, so a mismatch is harmless), and the precise on-disk plugin cache path. If any plugin route misbehaves, **Route B (skills only) is the robust fallback** — the skills are the portable core and carry the whole learning loop. Please open an issue with what you see.
