/**
 * Engram — OpenCode Plugin
 * =========================
 *
 * Self-extract + first-execution bridge
 * -------------------------------------
 *
 * NPM mode (installed via "plugin": ["git+…/engram.git"] in opencode.json):
 *   The package lives under ~/.cache/opencode/node_modules/. OpenCode does NOT
 *   treat the npm cache as a config directory, so no disk discovery happens there.
 *
 *   → The config hook triggers selfExtract() which copies files into the
 *     project's (or global) .opencode/ directory.
 *   → On the first execution (freshlyExtracted), a bridge registers agents,
 *     commands, and skills via cfg.* so they work immediately.
 *   → Disk discovery picks up .opencode/ on the next OpenCode start.
 *
 * Self-extract (install.ts)
 * -------------------------
 *
 * copyMissing() — never overwrites existing files. On version bump:
 *   skills/   → merged (new files added, existing files preserved)
 *   agents/   → merged + transformed (custom tools string → YAML objects,
 *              mode: subagent, hidden: true injected)
 *   scripts/  → merged (engram.py)
 *
 * Generated (always overwritten on extract):
 *   command/  → command/{learn,review-loop,coach}.md
 *   AGENTS.md → versioned marker block (project root or ~/.config/opencode/)
 *   .engram-version.jsonc → idempotency: {version, previous, installed_at, source}
 *   .engram-update.jsonc  → per-category diff manifest (only on version bump)
 *
 *   /engram-update is a temporary pseudo-command: never written as a file.
 *   Registered only via cfg.command when .engram-update.jsonc exists on disk.
 *   This prevents OpenCode's disk-discovery cache from locking a stale definition
 *   — the solution found for preserving user-edited skills/agents/scripts across
 *   plugin version bumps without silently clobbering them.
 *
 * Target detection:
 *   cwd has opencode.json/jsonc → {cwd}/.opencode/     (project-level)
 *   otherwise → ~/.config/opencode/                    (global)
 *
 * Config hook + bridge
 * --------------------
 *
 *   1. NPM mode: selfExtract() — idempotent via .engram-version.jsonc.
 *   2. First-execution bridge (freshlyExtracted):
 *      agents   → registerAgents(cfg, root) — reads agents/*.md frontmatter,
 *                 parses custom tools strings to OpenCode object format.
 *      skills   → cfg.skills.paths.push(target/skills) — {paths: []}.
 *      commands → cfg.command[name] = { template, description } — 3 inline.
 *      engram-update → registered conditionally when manifest exists.
 *      Shape note: targets the OpenCode v1 SDK config layer (skills.paths,
 *      command singular, agent singular). v2 uses skills: string[] and
 *      commands: plural. The bridge shapes are intentional.
 *   After first exec: bridge off, disk discovery handles everything.
 *
 * AGENTS.md (no bridge needed)
 * ------------------------------
 *
 *   AGENTS.md is written directly to disk by selfExtract. No cfg.instructions
 *   registration is required because both V1 and V2 discover it natively:
 *
 *     V1 (HTTP API / CLI) — fs.findUp("AGENTS.md") every request.
 *     V2 (InstructionContext) — fs.up({ targets: ["AGENTS.md"] }) every turn.
 *
 *   The file is re-read from disk on every LLM request — no bridge, no cache,
 *   no restart needed. Changes or creation take effect immediately.
 *
 *   selfExtract also:
 *     - Adds AGENTS.md to .git/info/exclude so the file is never committed
 *       (per-repo local gitignore, no hook, no working-tree mutation).
 *     - Warns if CLAUDE.md exists at the project root — AGENTS.md takes
 *       discovery priority over CLAUDE.md (first filename match wins).
 *
 * Update system (update.ts)
 * -------------------------
 *
 * On version bump, selfExtract writes .engram-update.jsonc with a per-category
 * diff (skills, agents, scripts, commands — files added vs preserved).
 *
 * Notification (session-start.ts):
 *   system.transform — injects "Updates Engram Available!" + "Run
 *   /engram-update" into the system prompt on every session while a pending
 *   update exists (manifest file present).
 *
 *   session.idle — fires tui.toast.show with the same message. Visible toast
 *   notification in the TUI on every session while update is pending.
 *
 * /engram-update command (pseudo-command + custom tool):
 *
 *   Conditional twins — both only active when .engram-update.jsonc exists:
 *     cfg.command["engram-update"] = { description, template }   ← pseudo-command
 *     cfg.tools["engram_update"] = true                           ← custom tool
 *   Both disappear on next session when manifest is resolved/deleted.
 *
 *   $TARGET resolution — the template uses $TARGET as a placeholder which is
 *   replaced at config-hook time via UPDATE_TEMPLATE.replace(/$TARGET/g, target).
 *   This resolves to {cwd}/.opencode/ (project-level) or ~/.config/opencode/
 *   (global), so the model always reads/writes the correct target directory.
 *
 *   Template flow:
 *     STEP 1 — Read manifest at $TARGET/.engram-update.jsonc
 *     STEP 2 — Error cleanup (Bash: rm -f hardcoded paths, no interpolation)
 *     STEP 3 — Route by manifest.state (pending / in_progress)
 *     STEP 4 — question tool presents 4 options (auto/manual/skip/keep-as-is)
 *     STEP 4a-4d — call engram_update tool (auto/per_file/keep_as_is/skip modes)
 *     STEP 5 — resume: reads state, continues per-file from checkpoint
 *   Zero Bash for destructive operations — all file deletion, manifest checkpoint,
 *   and cleanup are handled by the deterministic engram_update custom tool.
 *
 *   Full lifecycle:
 *     Manifest exists (version bump detected by selfExtract)
 *       → config hook: pseudo-command registered + tool enabled
 *       → /engram-update executed by user
 *       → engram_update tool processes files, deletes manifest + version guard
 *       → next reload:
 *           existsSync → false → pseudo-command gone, tool hidden
 *           .engram-version.jsonc deleted → selfExtract treats as fresh install
 *           copyMissing with existsSync guard → user edits preserved forever
 *     If interrupted mid-execution (crash, power loss):
 *       → manifest persists with state="in_progress" + per-file checkpoint
 *       → STEP 5 resumes exactly where it stopped
 *       → rm -f is idempotent via existsSync guard in the tool
 *
 * Error handling
 * --------------
 *
 * Every hook is wrapped in try/catch — no plugin error can crash the host:
 *   config, system.transform, event, shell.env — top-level try/catch.
 *   registerAgents — per-file try/catch (corrupt agent skipped).
 *   selfExtract — try/catch around entire extract + manifest generation.
 *   readUpdateSummary — returns null on corrupt manifest.
 *   tui.showToast — .catch(() => {}) (toast is best-effort, non-critical).
 *
 * OPENCODE_PLUGIN_ROOT (shell-env.ts)
 * -----------------------------------
 *
 * Resolved at every shell execution via input.cwd:
 *   Check if {target}/scripts/engram.py exists.
 *   true  → use target (self-extract done, engine is local).
 *   false → use packageRoot (pre-extract, engine not yet local).
 *
 * Nudge (session-start.ts)
 * ------------------------
 *
 * system.transform → first call runs `engram.py session-start`. Injects
 *   review-due message + update notification into system prompt.
 *   Single hook, no shared state, no ordering dependency.
 *
 * session.idle → toast notification if update pending.
 *
 * What was deliberately removed
 * -----------------------------
 *
 *   docs/ from extract        → end users don't need internal docs.
 *   cfg.references            → all paths local; AGENTS.md covers it.
 *   cfg.permission            → no external paths remain post-extract.
 *   cfg.{skills,commands,agents} → disk discovery (bridge on first exec).
 *   cfg.instructions push     → dropped — V1 and V2 both discover AGENTS.md
 *                               natively (re-read from disk every request).
 *   copyDir / cpSync          → copyMissing (never overwrite user files).
 *
 * Known OpenCode bug
 * ------------------
 *   anomalyco/opencode#36681 — external_directory auto-allow.
 *   Not relevant post-extract since all paths are local.
 */

import { existsSync } from "node:fs"
import { resolve, dirname, basename } from "node:path"
import { fileURLToPath } from "node:url"
import type { Plugin } from "@opencode-ai/plugin"
import { registerAgents } from "./agents.js"
import { createSessionStartHooks } from "../hooks/session-start.js"
import { createShellEnvHook } from "../hooks/shell-env.js"
import { detectInstallType } from "./install-type.js"
import { selfExtract, getExtractTarget, getVERSION, syncProjectState } from "./install.js"
import { createPluginLogger } from "./logger.js"
import { engramUpdateTool } from "./update-tool.js"

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..")

const COMMANDS: Record<string, { description: string; template: string }> = {
  learn: {
    description:
      "Learn any topic properly — first-principles curriculum, generation-first tutoring, verified free recall, FSRS scheduling",
    template: `# /learn — acquisition loop

LOAD AND FOLLOW the \`learn\` skill. Teach the learner the requested topic.

Topic: $ARGUMENTS`,
  },
  "review-loop": {
    description:
      "Review due concepts — free recall interleaved across topics, blind graded, FSRS scheduled",
    template: `# /review-loop — review loop

LOAD AND FOLLOW the \`review\` skill. Review due concepts with the learner.

Arguments: $ARGUMENTS`,
  },
  coach: {
    description:
      "Learning analytics — retention stats, dashboard, schedule tuning, experiments, audit",
    template: `# /coach — coaching & analytics

LOAD AND FOLLOW the \`coach\` skill. Show learning analytics and insights.

Arguments: $ARGUMENTS`,
  },
}

const UPDATE_DESCRIPTION =
  "Review and apply pending Engram plugin updates — auto (all) or manual (per file)"

const UPDATE_TEMPLATE = `# /engram-update — apply Engram plugin updates

## Procedure — execute in order; do NOT skip, reorder, or merge steps

### STEP 1 — Read manifest
Tool: Read
Path: $TARGET/.engram-update.jsonc

The Engram system consists of:
  AGENTS.md         — model behavioral rules (project root or global)
  skills/            — skill definitions (learn, review, coach)
  agents/            — subagent definitions (curriculum-architect, engram-assessor, artifact-smith)
  scripts/           — deterministic engine (engram.py)
  command/           — command templates (learn, review-loop, coach)

Parse the JSON. Locate field: state.

### STEP 2 — If Read fails
Condition: file not found OR JSON.parse fails.
Then execute:
  Call tool: engram_update({ target: "$TARGET", mode: "cleanup" })
Output the tool's return message. Do NOT modify or paraphrase it.
STOP. Do not continue.

### STEP 3 — Route by manifest.state
  "pending"      → go to STEP 4.
  "in_progress"  → go to STEP 5.
  any other      → treat as corrupt → go to STEP 2.

### STEP 4 — State "pending": present choices
Output: "Engram {manifest.from} → {manifest.to}"
For each category in manifest.categories, output:
  "{name}: {added.length} added, {skipped.length} preserved"
Use the question tool:
  header: "Engram Update"
  question: "How to apply Engram {manifest.from} → {manifest.to}?"
  options:
    - "Auto (Recommended)" — refresh ALL preserved files
    - "Manual" — pick per file
    - "View changes" — inspect diff before deciding
    - "Skip" — defer, remind next session
    - "Keep as-is" — skip permanently
Route by selected option:
  "Auto" → STEP 4a
  "Manual" → STEP 4b
  "View changes" → STEP 4e
  "Skip" → STEP 4c
  "Keep as-is" → STEP 4d

### STEP 4a — Auto mode
Call tool: engram_update({ target: "$TARGET", mode: "auto" })
Output the tool's return message. Do NOT modify or paraphrase it.
STOP.

### STEP 4b — Manual mode (per-file)
Call tool: engram_update({ target: "$TARGET", mode: "checkpoint" })
For each category name in manifest.remaining, in order:
  For each file in manifest.categories.{name}.skipped:
    Use the question tool:
      header: "{name}"
      question: "Overwrite {file}?"
      options:
        - "Yes" — delete and refresh on next restart
        - "No" — keep current version
    Track the decision: { file: "{file}", action: "delete" or "keep" }
After ALL files in all remaining categories have been answered:
  Call tool: engram_update({ target: "$TARGET", mode: "per_file", decisions: [ALL_TRACKED_DECISIONS] })
  Output the tool's return message. Do NOT modify or paraphrase it.
  If the message says remaining is empty → "Manual update complete. Restart or reload."
  If the message says checkpoint saved → "Checkpoint saved. Continue with /engram-update on next session."
STOP.

### STEP 4c — Skip
Call tool: engram_update({ target: "$TARGET", mode: "skip" })
Output: "Update deferred. You'll be reminded next session."
STOP.

### STEP 4d — Keep as-is
Call tool: engram_update({ target: "$TARGET", mode: "keep_as_is" })
Output the tool's return message. Do NOT modify or paraphrase it.
STOP.

### STEP 4e — View changes
// Edge case: .engram-update.diff may not exist even when the manifest
// does — contentsMatch flags CRLF-only byte differences but diffLines
// normalizes them away. The Read guard below handles this gracefully.
Use Read tool: $TARGET/.engram-update.diff
If Read tool fails (file does not exist): say "No diff available — files may differ only in line endings. Proceed with the update options." Then go back to STEP 4.
Otherwise: summarize the changes to the user (which files changed and what the diffs show).
Then go back to STEP 4 and present the options again.

### STEP 5 — State "in_progress": resume
Output: "Resuming update — checkpoint found."
Call tool: engram_update({ target: "$TARGET", mode: "skip" })
This returns current state. Proceed with STEP 4b using only files still present in manifest.categories.{name}.skipped arrays.
If all skipped arrays are empty:
  Call tool: engram_update({ target: "$TARGET", mode: "keep_as_is" })
STOP.

## Constraints — MUST follow
- Use Read tool for the manifest. NEVER use Glob.
- Do NOT use Bash for file deletion or manifest updates. Use the engram_update tool instead.
- Do NOT delete AGENTS.md or scripts/engram.py directly.
- Do NOT add, modify, or rename any file.
- If a category.skipped array is empty, skip that category silently.
- Do NOT output text beyond what each step prescribes.`

export const server: Plugin = async ({ client, $, directory }) => {
  const cwd = directory || process.cwd()
  const sessionStartHooks = createSessionStartHooks($, root, client)
  const shellEnvHooks = createShellEnvHook(root)

  return {
    async config(input) {
      try {
        const cfg = input as any
      const { type } = detectInstallType(root)

      let target: string
      let freshlyExtracted = false
      if (type === "npm") {
        const logger = createPluginLogger(client)
        const result = selfExtract(root, cwd, getVERSION(root), logger)
        target = result.target
        freshlyExtracted = result.freshlyExtracted
      } else {
        target = getExtractTarget(cwd)
      }

      // Every session, not just on a version bump — see syncProjectState().
      try { syncProjectState(target, createPluginLogger(client)) } catch {}

      if (freshlyExtracted) {
        registerAgents(cfg, root)
        cfg.skills = cfg.skills || {}
        cfg.skills.paths = cfg.skills.paths || []
        cfg.skills.paths.push(resolve(target, "skills"))
        cfg.command = cfg.command || {}
        for (const [name, def] of Object.entries(COMMANDS)) {
          if (!cfg.command[name]) cfg.command[name] = def
        }
      }

      if (existsSync(resolve(target, ".engram-update.jsonc"))) {
        cfg.command = cfg.command || {}
        cfg.command["engram-update"] = {
          description: UPDATE_DESCRIPTION,
          template: UPDATE_TEMPLATE.replace(/\$TARGET/g, target),
        }
      }
      cfg.tools = cfg.tools || {}
      cfg.tools["engram_update"] = existsSync(resolve(target, ".engram-update.jsonc"))
      } catch {}
    },
    tool: {
      engram_update: engramUpdateTool,
    },
    ...sessionStartHooks,
    ...shellEnvHooks,
  }
}

export default {
  id: "engram",
  server,
}
