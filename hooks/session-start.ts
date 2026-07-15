/**
 * Engram — Session Start Hooks
 * =============================
 *
 * Two hooks injected into OpenCode's session lifecycle:
 *
 * system.transform   — fires once per session (firstTransform guard).
 *   Runs `engram.py session-start` for the review-due nudge, then calls
 *   readUpdateSummary() to check for pending plugin updates. Injects both
 *   messages into the system prompt.
 *
 *   readUpdateSummary() reads .engram-update.jsonc at the target directory
 *   (project-level .opencode/ or global ~/.config/opencode/) and returns:
 *     null              — no manifest → silent
 *     "pending"          → "Updates Engram Available!\nRun /engram-update"
 *     "in_progress"      → "Update partially applied. Run /engram-update to continue"
 *     corrupt/absent     → null (gracefully degrades)
 *
 * event(session.idle) — fires a TUI toast when an update manifest exists on disk.
 *   Guard: toastShown (one per session). Calls readUpdateSummary() — if non-null,
 *   shows client.tui.showToast() with "Updates Engram Available!".
 *   Best-effort — all errors caught via .catch(() => {}).
 *
 * Both hooks are wrapped in try/catch — never crash the host.
 */

import { resolve } from "node:path"
import { existsSync, readFileSync } from "node:fs"

/**
 * Creates and returns system.transform and event hooks for session start.
 * @param $      OpenCode bash executor (tagged template)
 * @param root   package root directory
 * @param client OpenCode client (for tui.showToast)
 */
export function createSessionStartHooks($: any, root: string, client: any) {
  let firstTransform = true
  let toastShown = false

  function computeTarget(): string {
    const home = process.env.HOME || process.env.USERPROFILE || "/tmp"
    const cwd = process.cwd()
    const projectJson = resolve(cwd, "opencode.json")
    const projectJsonc = resolve(cwd, "opencode.jsonc")
    if (existsSync(projectJson) || existsSync(projectJsonc)) {
      return resolve(cwd, ".opencode")
    }
    return resolve(home, ".config", "opencode")
  }

  function readUpdateSummary(): string | null {
    const target = computeTarget()
    const f = resolve(target, ".engram-update.jsonc")
    if (!existsSync(f)) return null
    try {
      const m = JSON.parse(readFileSync(f, "utf-8"))
      if (m.state === "in_progress") {
        return "Update partially applied. Run /engram-update to continue"
      }
      return "Updates Engram Available!\nRun /engram-update"
    } catch {
      return null
    }
  }

  return {
    async "experimental.chat.system.transform"(_input: any, output: { system: string[] }) {
      try {
        if (!firstTransform) return
        firstTransform = false

        const engramPy = resolve(root, "scripts", "engram.py")
        const result = await $`python3 ${engramPy} session-start`.nothrow().quiet()
        const nudge = result.stdout.toString().trim()
        if (nudge) output.system.push(`\n[engram] ${nudge}`)

        const updateSummary = readUpdateSummary()
        if (updateSummary) {
          output.system.push(`\n[engram] ${updateSummary}`)
        }
      } catch {}
    },

    async event(input: { event: any }) {
      try {
        if (toastShown) return
        if (input.event.type !== "session.idle") return

        const updateSummary = readUpdateSummary()
        if (!updateSummary) return

        toastShown = true
        client.tui.showToast({
          body: { title: "Engram", message: "Updates Engram Available!\nRun /engram-update", variant: "info", duration: 30000 },
        }).catch(() => {})
      } catch {}
    },
  }
}
