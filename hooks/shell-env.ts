/**
 * Engram — Shell Environment Hook
 * ================================
 *
 * Injects OPENCODE_PLUGIN_ROOT and ENGRAM_ROOT into every shell execution.
 * Resolves to the extracted .opencode/ target if engram.py exists there,
 * falling back to the npm package root (pre-extract).
 *
 * Also forwards ENGRAM_HOME and ENGRAM_TODAY from the process environment
 * to child shells (used by the engine for state isolation and time-travel tests).
 */

import { existsSync } from "node:fs"
import { resolve } from "node:path"

/**
 * Creates the shell.env hook. Injects ENGRAM_ROOT and OPENCODE_PLUGIN_ROOT
 * at every shell execution.
 * @param packageRoot npm cache path (fallback when not yet extracted)
 */
export function createShellEnvHook(packageRoot: string) {
  return {
    async "shell.env"(input: any, output: { env: Record<string, string> }) {
      try {
        const cwd = input.cwd || process.cwd()
        const target = extractTarget(cwd)
        const pluginRoot = existsSync(resolve(target, "scripts", "engram.py")) ? target : packageRoot

        output.env["ENGRAM_ROOT"] = pluginRoot
        output.env["OPENCODE_PLUGIN_ROOT"] = pluginRoot
        if (process.env.ENGRAM_HOME) output.env["ENGRAM_HOME"] = process.env.ENGRAM_HOME
        if (process.env.ENGRAM_TODAY) output.env["ENGRAM_TODAY"] = process.env.ENGRAM_TODAY
      } catch {}
    },
  }
}

function extractTarget(cwd: string): string {
  const home = process.env.HOME || process.env.USERPROFILE || "/tmp"
  const projectJson = resolve(cwd, "opencode.json")
  const projectJsonc = resolve(cwd, "opencode.jsonc")
  if (existsSync(projectJson) || existsSync(projectJsonc)) {
    return resolve(cwd, ".opencode")
  }
  return resolve(home, ".config", "opencode")
}
