/**
 * Engram — CLAUDE.md Collision Warning
 * ======================================
 *
 * OpenCode's instruction discovery breaks on the first filename match in the
 * ancestor chain (instruction.ts:64-68, :122-133). When AGENTS.md exists at
 * the project root, any existing CLAUDE.md is silently suppressed — the model
 * never sees it.
 *
 * This module logs a visible warning during selfExtract so the user knows
 * their CLAUDE.md rules are no longer reaching the model and can take action.
 *
 * CONTEXT.md is also in instructionFiles but is deprecated — no warning is
 * emitted for it. The fix for both is the same: consolidate rules into
 * AGENTS.md or remove it.
 *
 * Called by: install.ts → selfExtract (project-level installs only).
 */

import { existsSync } from "node:fs"
import { resolve } from "node:path"

const WARNING = "Engram: WARNING — CLAUDE.md exists here and will be suppressed by AGENTS.md (first match wins in instruction discovery). Review both files."

export function warnClaudeMdCollision(projectRoot: string, log: (msg: string) => void) {
  if (existsSync(resolve(projectRoot, "CLAUDE.md"))) {
    log(WARNING)
  }
}
