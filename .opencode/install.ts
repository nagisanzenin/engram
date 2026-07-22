/**
 * Engram — Self-Extract & Installation
 * =====================================
 *
 * Copies plugin files from the npm package cache into OpenCode's config directory.
 * copyMissing() never overwrites existing files — preserves user edits across updates.
 *
 * Extraction (DIRS): skills/, agents/, scripts/ (new files only, never overwrite)
 * Generated (versioned marker block): AGENTS.md (project root or global)
 * Generated (always overwritten): command/, .engram-version.jsonc
 *
 * Version bump detection via .engram-version.jsonc idempotency guard.
 * On version bump, writes .engram-update.jsonc for /engram-update pseudo-command.
 * On fresh install, no manifest — bridge registers agents/commands/skills in config hook.
 */

import { existsSync, mkdirSync, writeFileSync, readFileSync, readdirSync, copyFileSync, unlinkSync } from "node:fs"
import { resolve, basename } from "node:path"
import { execSync } from "node:child_process"
import { parseFrontmatter } from "./parse-frontmatter.js"
import { writeUpdateManifest } from "./update.js"
import { warnClaudeMdCollision } from "./claude-warning.js"

/** Directory categories copied by selfExtract. docs/ deliberately excluded. */
const DIRS = ["skills", "agents", "scripts"]

const INSTRUCTIONS_TEXT = `# Engram — Evidence-Based Learning Engine

OPENCODE_PLUGIN_ROOT is set in shell env automatically on every session start.

## References

The following references are available and resolve to the extracted copy in .opencode/:

- **engram-shared** — skills/_shared/ (dialogue grammar, explorable contract, subagent spawning)
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

// ---------------------------------------------------------------------------
// AGENTS.md helpers — versioned marker-based prepend (option B)
// ---------------------------------------------------------------------------

const MARKER_OPEN = "<!-- engram v"
const MARKER_CLOSE = "<!-- /engram -->"
const MARKER_OPEN_RE = /^<!-- engram v(.+?) -->$/gm
const MARKER_CLOSE_RE = /^<!-- \/engram -->$/m

function buildEngramBlock(version: string): string {
  return `${MARKER_OPEN}${version} -->\n${INSTRUCTIONS_TEXT}${MARKER_CLOSE}\n`
}

/**
 * Locates the Engram block: the LAST opening marker before the first closing one.
 *
 * Taking the *first* opening marker looks equivalent and is not. A user who
 * documents Engram's own marker syntax at line start — above the block — would
 * have everything from their line down to the real close marker deleted, and
 * (via the clean filter) that truncated version is what git stores. Anchoring
 * to the last opening marker keeps their prose. Both markers must be alone on
 * their line; an inline mention is prose, not a marker.
 */
function findEngramBlock(content: string): { version: string; start: number; end: number } | null {
  const close = content.match(MARKER_CLOSE_RE)
  if (close?.index === undefined) return null
  const closeStart = close.index

  let open: RegExpExecArray | null = null
  const re = new RegExp(MARKER_OPEN_RE.source, "gm")
  for (let m = re.exec(content); m !== null && m.index < closeStart; m = re.exec(content)) open = m
  if (open === null) return null

  return { version: open[1], start: open.index, end: closeStart + close[0].length }
}

/** Resolves the AGENTS.md path based on extraction target.
 *  Project-level (target basename is ".opencode") → {parent}/AGENTS.md
 *  Global (target is ~/.config/opencode) → {target}/AGENTS.md */
export function resolveAgentsPath(target: string): string {
  if (basename(target) === ".opencode") {
    return resolve(target, "..", "AGENTS.md")
  }
  return resolve(target, "AGENTS.md")
}

/**
 * Writes or prepends the Engram instruction block to AGENTS.md.
 *
 * Returns true if the file was created by Engram (didn't exist before),
 * false otherwise. Used to conditionally install git exclude.
 *
 * - File absent → create with versioned marker block (returns true).
 * - Block present with matching version → no-op (idempotent).
 * - Block present with different version → replace old block, preserve user content below.
 * - Block absent → prepend new block at top, preserve existing content.
 *
 * No data loss — user content below the block is never modified.
 */
export function writeOrPrependAgentsMd(target: string, version: string): boolean {
  const agentsPath = resolveAgentsPath(target)
  const block = buildEngramBlock(version)

  if (!existsSync(agentsPath)) {
    writeFileSync(agentsPath, block)
    return true
  }

  const existing = readFileSync(agentsPath, "utf-8")
  const found = findEngramBlock(existing)

  if (found && found.version === version) return false

  if (found) {
    const before = existing.slice(0, found.start)
    const after = existing.slice(found.end).replace(/^\n+/, "")
    writeFileSync(agentsPath, before + block + (after ? "\n\n" + after : ""))
  } else {
    writeFileSync(agentsPath, existing.trim() ? block + "\n\n" + existing : block)
  }
  return false
}

/**
 * Installs git infrastructure for AGENTS.md lifecycle management.
 *
 * Three mechanisms, each covering a different scenario:
 *
 * 1. SMUDGE/CLEAN FILTER (.git/config)
 *      clean — strips the Engram block on git add (git stores only user content).
 *      smudge — prepends the Engram block on git checkout (disk always has it).
 *      Guarded: if scripts don't exist, falls back to cat (harmless passthrough).
 *      Depends on python3 on PATH — skipped with a warning if absent.
 *
 * 2. PATH ATTRIBUTES (.git/info/attributes)
 *      Assigns AGENTS.md filter=engram so git knows to apply the filter.
 *      Local (not versioned), affects only this clone.
 *
 * 3. LOCAL EXCLUDE (.git/info/exclude)
 *      Prevents git from tracking an otherwise-empty AGENTS.md (no user
 *      content yet) and .engram-* internal files. Combined with the filter,
 *      the file is still tracked if the user explicitly git add --force
 *      (filter strips the block). Local (not versioned), affects only this clone.
 *      Entry tracks CONTENT, not authorship: present while the file is
 *      Engram-only, removed as soon as the user adds rules of their own.
 *
 * Each mechanism is checked independently — partial-state repair is supported.
 * Each mechanism is wrapped in try/catch — a failure in one does not block the others.
 * Only operates on project-level installs (where .git/config exists).
 *
 * Uninstall note: removing Engram leaves the filter config in .git/config,
 * .git/info/attributes, and .git/info/exclude. Without the scripts, the
 * filter falls back to cat — harmless. To fully clean up, remove the
 * [filter "engram"] section from .git/config and the engram lines from
 * .git/info/attributes and .git/info/exclude.
 */
function installGitFilter(projectRoot: string, log: (msg: string) => void) {
  const gitConfig = resolve(projectRoot, ".git", "config")
  if (!existsSync(gitConfig)) return

  // Skip git filter when python3 is not available — the clean/smudge scripts
  // depend on it. Without the filter, every git add/checkout would print
  // "python3: not found" errors and leak the block.
  try { execSync("python3 --version", { stdio: "ignore" }) } catch {
    log("Engram: WARNING — python3 not found, skipping git filter. AGENTS.md will not be filtered.")
    return
  }

  const infoDir = resolve(projectRoot, ".git", "info")

  // 1. SMUDGE/CLEAN FILTER — check independently, no early return.
  //
  //    Deliberately a plain file append rather than `git config --local`.
  //    `git config` is the tidier API, but it hard-fails with "can only be used
  //    inside a git repository" whenever .git/config exists while git does not
  //    consider the directory a valid repo — a partially initialised repo, an
  //    unusual GIT_DIR. That trades a guarded, idempotent fs write for a
  //    subprocess plus a new failure mode, and buys nothing a user can see.
  try {
    const configContent = readFileSync(gitConfig, "utf-8")
    if (!configContent.includes('[filter "engram"]')) {
      const filterBlock = `[filter "engram"]
\tclean = "if [ -f .opencode/scripts/opencode-engram-clean ]; then python3 .opencode/scripts/opencode-engram-clean; else cat; fi"
\tsmudge = "if [ -f .opencode/scripts/opencode-engram-smudge ]; then python3 .opencode/scripts/opencode-engram-smudge; else cat; fi"
`
      writeFileSync(gitConfig, configContent.trimEnd() + "\n" + filterBlock)
    }
  } catch {}

  // 2. PATH ATTRIBUTES — check independently
  try {
    const gitAttrsInfo = resolve(infoDir, "attributes")
    if (existsSync(gitAttrsInfo)) {
      const attrs = readFileSync(gitAttrsInfo, "utf-8")
      if (!attrs.includes("AGENTS.md filter=engram")) {
        writeFileSync(gitAttrsInfo, attrs.trimEnd() + "\nAGENTS.md filter=engram\n")
      }
    } else {
      mkdirSync(infoDir, { recursive: true })
      writeFileSync(gitAttrsInfo, "AGENTS.md filter=engram\n")
    }
  } catch {}

  syncAgentsExclude(projectRoot, log)

  log("Engram: installed git filter (clean+smudge) for AGENTS.md")
}

/**
 * Keeps AGENTS.md out of git only while the file is Engram's alone.
 *
 * The exclude entry stops an otherwise-empty AGENTS.md from being committed —
 * with the block stripped by the clean filter there would be nothing in it.
 * But `.git/info/exclude` is invisible from the working tree; it is not
 * `.gitignore`, and finding it takes `git check-ignore -v`. So an exclude that
 * outlives its reason is a trap: the user adds their own rules below the block,
 * `git status` stays silent, and their rules are never committed.
 *
 * So the entry tracks the file's contents rather than who created it — present
 * while the file is Engram-only, removed the moment there is user content to
 * commit. `.engram-*` is unconditional; those files are always internal.
 *
 * `.opencode/` is deliberately NOT excluded. It holds the extracted install but
 * can also hold the user's own commands and agents, and hiding those would be
 * the same bug this function exists to avoid.
 */
function syncAgentsExclude(projectRoot: string, log: (msg: string) => void) {
  try {
    const infoDir = resolve(projectRoot, ".git", "info")
    const excludeFile = resolve(infoDir, "exclude")
    const userOwnsIt = agentsHasUserContent(resolve(projectRoot, "AGENTS.md"))

    const existing = existsSync(excludeFile) ? readFileSync(excludeFile, "utf-8") : ""
    const lines = existing.length ? existing.split("\n") : []
    const has = (needle: string) => lines.some(l => l.trim() === needle)

    let next = lines
    let changed = false

    if (!has(".engram-*")) {
      next = [...next, "# Engram internal files", ".engram-*"]
      changed = true
    }

    if (userOwnsIt && has("AGENTS.md")) {
      // The user has rules of their own in there now — stop hiding the file.
      next = next.filter(l => l.trim() !== "AGENTS.md" && l.trim() !== "# Engram plugin instructions")
      changed = true
      log("Engram: AGENTS.md now has your own content below the block — un-excluded it so git can track it. The Engram block is stripped on commit.")
    } else if (!userOwnsIt && !has("AGENTS.md")) {
      next = [...next, "# Engram plugin instructions", "AGENTS.md"]
      changed = true
      log("Engram: AGENTS.md is excluded from git locally (.git/info/exclude) while it holds only Engram's block. Add your own rules below it and Engram will un-exclude it; or `git add -f AGENTS.md` to track it now.")
    }

    if (!changed) return

    mkdirSync(infoDir, { recursive: true })
    writeFileSync(excludeFile, next.join("\n").trimEnd() + "\n")
  } catch {}
}

/** True when AGENTS.md holds anything beyond the Engram block. */
function agentsHasUserContent(agentsPath: string): boolean {
  if (!existsSync(agentsPath)) return false
  try {
    const content = readFileSync(agentsPath, "utf-8")
    const found = findEngramBlock(content)
    const rest = found ? content.slice(0, found.start) + content.slice(found.end) : content
    return rest.trim().length > 0
  } catch {
    return false
  }
}

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
 * 4. Generate AGENTS.md (versioned marker block), command/ (always overwritten)
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

    writeOrPrependAgentsMd(target, version)

    const smudgeTemplate = resolve(target, ".engram-smudge-template")
    writeFileSync(smudgeTemplate, buildEngramBlock(version))

    const legacyInstructions = resolve(target, "instructions.md")
    if (existsSync(legacyInstructions)) {
      unlinkSync(legacyInstructions)
    }

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

    if (basename(target) === ".opencode") {
      try {
        installGitFilter(resolve(target, ".."), log)
      } catch {}
    }
    // The CLAUDE.md warning and the exclude sync deliberately do NOT live here.
    // selfExtract only runs on a version bump, and both conditions can arise at
    // any time — a CLAUDE.md added next week, user rules added to AGENTS.md this
    // afternoon. They run from the config hook, once per session. See
    // syncProjectState().

    return { target, freshlyExtracted: !prevVersion, prevVersion }
  } catch (e) {
    if (logger) logger(`Engram: extract failed — ${String(e)}`)
    return { target, freshlyExtracted: false }
  }
}

/**
 * Per-session project state sync — cheap, pure-fs, no subprocess.
 *
 * selfExtract runs only on a version bump, but the two conditions below can
 * arise at any moment: a CLAUDE.md added long after Engram was installed, or
 * user rules typed into AGENTS.md this afternoon. Both are silent failures if
 * nobody looks, so the config hook calls this every session.
 */
export function syncProjectState(target: string, log: (msg: string) => void) {
  if (basename(target) !== ".opencode") return
  const projectRoot = resolve(target, "..")
  if (!existsSync(resolve(projectRoot, ".git"))) return

  try { syncAgentsExclude(projectRoot, log) } catch {}
  try { warnClaudeMdCollision(projectRoot, log) } catch {}
}
