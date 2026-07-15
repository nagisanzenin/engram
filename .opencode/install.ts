/**
 * Engram — Self-Extract & Installation
 * =====================================
 *
 * Copies plugin files from the npm package cache into OpenCode's config directory.
 * copyMissing() never overwrites existing files — preserves user edits across updates.
 *
 * Extraction (DIRS): skills/, agents/, scripts/ (new files only, never overwrite)
 * Generated (always overwritten): instructions.md, command/, .engram-version.jsonc
 *
 * Version bump detection via .engram-version.jsonc idempotency guard.
 * On version bump, writes .engram-update.jsonc for /engram-update pseudo-command.
 * On fresh install, no manifest — bridge registers agents/commands/skills in config hook.
 */

import { existsSync, mkdirSync, writeFileSync, readFileSync, readdirSync, copyFileSync } from "node:fs"
import { resolve } from "node:path"
import { parseFrontmatter } from "./parse-frontmatter.js"
import { writeUpdateManifest } from "./update.js"

/** Directory categories copied by selfExtract. docs/ deliberately excluded. */
const DIRS = ["skills", "agents", "scripts"]

const INSTRUCTIONS_TEXT = `# Engram — Evidence-Based Learning Engine

OPENCODE_PLUGIN_ROOT is set in shell env automatically on every session start.

## References

The following references are available and resolve to the extracted copy in .opencode/:

- **engram-shared** — skills/_shared/ (dialogue grammar, explorable contract)
- **engram-scripts** — scripts/ (engram.py — deterministic core, FSRS scheduler, stats)
- **engram-docs** — docs/ (foundations, architecture, roadmap)

## Skills

- **/learn** — first-principles curriculum, generation-first tutoring, verified free recall
- **/review-loop** — due reviews, free recall interleaved, blind grading, FSRS scheduled
- **/coach** — retention stats, dashboard, calibration, experiments, grader audit

## Subagents

- **engram-assessor** — blind grader (never sees the lesson)
- **engram-curriculum-architect** — decomposes topics into concept DAGs
- **engram-artifact-smith** — builds interactive HTML explorables for threshold concepts
`

/** Extracts the version string from package.json. Falls back to "0.0.0". */
export function getVERSION(root: string): string {
  const pkg = JSON.parse(readFileSync(resolve(root, "package.json"), "utf-8"))
  return pkg.version || "0.0.0"
}

/** Returns project-level .opencode/ if cwd has opencode.json(c), else global ~/.config/opencode/. */
export function getExtractTarget(directory: string): string {
  const home = process.env.HOME || process.env.USERPROFILE || "/tmp"
  const projectJson = resolve(directory, "opencode.json")
  const projectJsonc = resolve(directory, "opencode.jsonc")
  if (existsSync(projectJson) || existsSync(projectJsonc)) {
    return resolve(directory, ".opencode")
  }
  return resolve(home, ".config", "opencode")
}

/** Reads .engram-version.jsonc. Returns version string or undefined if missing/corrupt. */
export function readPrevVersion(target: string): string | undefined {
  const versionFile = resolve(target, ".engram-version.jsonc")
  if (!existsSync(versionFile)) return undefined
  try {
    return JSON.parse(readFileSync(versionFile, "utf-8")).version as string | undefined
  } catch {
    return undefined
  }
}

/** True when installed version differs from package version (or no version file exists). */
export function needsExtract(target: string, version: string): boolean {
  const prev = readPrevVersion(target)
  return prev !== version
}

/** Recursively copies new files from src to dest. Never overwrites existing files (existsSync guard). No-ops silently if src absent. */
export function copyMissing(src: string, dest: string) {
  if (!existsSync(src)) return
  mkdirSync(dest, { recursive: true })
  for (const entry of readdirSync(src, { withFileTypes: true })) {
    const srcPath = resolve(src, entry.name)
    const destPath = resolve(dest, entry.name)
    if (entry.isDirectory()) {
      copyMissing(srcPath, destPath)
    } else if (!existsSync(destPath)) {
      copyFileSync(srcPath, destPath)
    }
  }
}


// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

/** Converts a flat record to simple YAML lines (one level of nesting). */
function toYAML(obj: Record<string, any>): string {
  const lines: string[] = []
  for (const [key, value] of Object.entries(obj)) {
    if (value == null) continue
    if (typeof value === "object" && !Array.isArray(value)) {
      lines.push(`${key}:`)
      for (const [k, v] of Object.entries(value)) {
        lines.push(`  ${k}: ${v}`)
      }
    } else {
      lines.push(`${key}: ${value}`)
    }
  }
  return lines.join("\n")
}

/** Transforms a Claude Code agent markdown to OpenCode YAML format (mode: subagent, hidden: true, tools string → object). */
function transformAgentForOpenCode(content: string): string {
  const { attrs, body } = parseFrontmatter(content)
  const newAttrs: Record<string, any> = {}
  if (attrs.name) newAttrs.name = attrs.name
  if (attrs.description) newAttrs.description = attrs.description
  newAttrs.mode = "subagent"
  newAttrs.hidden = true
  if (attrs.tools && typeof attrs.tools === "string") {
    const toolObj: Record<string, boolean> = {}
    for (const tool of attrs.tools.split(",")) {
      const trimmed = tool.trim()
      if (trimmed) toolObj[trimmed] = true
    }
    if (Object.keys(toolObj).length > 0) newAttrs.tools = toolObj
  }
  return `---\n${toYAML(newAttrs)}\n---\n\n${body.trimEnd()}\n`
}

const COMMANDS_DEF: Record<string, { description: string; template: string }> = {
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

/** Writes learn, review-loop, and coach command .md files to target/command/. Always overwrites. */
function generateCommands(target: string, log: (msg: string) => void) {
  const commandsDir = resolve(target, "command")
  mkdirSync(commandsDir, { recursive: true })
  for (const [name, def] of Object.entries(COMMANDS_DEF)) {
    const content = `---\ndescription: ${def.description}\n---\n\n${def.template.trimEnd()}\n`
    writeFileSync(resolve(commandsDir, `${name}.md`), content)
  }
  log(`Engram: generated commands to ${commandsDir}`)
}

/**
 * Main extraction entry point. Idempotent via .engram-version.jsonc guard.
 *
 * 1. Version check → skip if same
 * 2. copyMissing skills/, agents/, scripts/ (new files only)
 * 3. Transform agents to OpenCode YAML (mode: subagent, hidden: true)
 * 4. Generate instructions.md, command/ (always overwritten)
 * 5. Write .engram-version.jsonc with version + previous
 * 6. On version bump: writeUpdateManifest() → .engram-update.jsonc
 *
 * @param packageRoot  npm cache path (source of files to copy)
 * @param directory    OpenCode project directory (cwd)
 * @param version      current package.json version
 * @returns target path, whether this was a fresh install, and previous version
 */
export function selfExtract(packageRoot: string, directory: string, version: string, logger?: (msg: string) => void): { target: string; freshlyExtracted: boolean; prevVersion?: string } {
  const target = getExtractTarget(directory)
  const prevVersion = readPrevVersion(target)
  if (prevVersion === version) return { target, freshlyExtracted: false }

  try {
    const log = logger || (() => {})
    for (const dir of DIRS) {
      const srcDir = resolve(packageRoot, dir)
      const destDir = resolve(target, dir)
      copyMissing(srcDir, destDir)
      if (existsSync(srcDir)) {
        log(`Engram: merged ${dir} to ${destDir}`)
      }
    }

    const agentsDestDir = resolve(target, "agents")
    if (existsSync(agentsDestDir)) {
      for (const file of readdirSync(agentsDestDir)) {
        if (!file.endsWith(".md")) continue
        const filePath = resolve(agentsDestDir, file)
        const original = readFileSync(filePath, "utf-8")
        const transformed = transformAgentForOpenCode(original)
        writeFileSync(filePath, transformed)
      }
    }

    writeFileSync(resolve(target, "instructions.md"), INSTRUCTIONS_TEXT)

    generateCommands(target, log)

    const versionFile = resolve(target, ".engram-version.jsonc")
    writeFileSync(versionFile, JSON.stringify({
      version,
      previous: prevVersion || undefined,
      installed_at: new Date().toISOString(),
      source: "npm",
    }, null, 2))

    if (prevVersion) {
      writeUpdateManifest(packageRoot, target, prevVersion, version)
    }

    return { target, freshlyExtracted: !prevVersion, prevVersion }
  } catch (e) {
    if (logger) logger(`Engram: extract failed — ${String(e)}`)
    return { target, freshlyExtracted: false }
  }
}
