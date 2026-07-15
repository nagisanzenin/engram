/**
 * Engram — Agent Registration
 * ============================
 *
 * Reads agent markdown files from agents/ (frontmatter + body) and registers them
 * via cfg.agent during the first-execution bridge.
 *
 * Agents are registered as mode: "subagent", hidden: true.
 * Tools string (comma-separated in frontmatter) is converted to OpenCode's
 * { "tool_name": true } format.
 *
 * Per-file try/catch — one corrupt agent is skipped; others load normally.
 */

import { existsSync, readdirSync, readFileSync } from "node:fs"
import { resolve } from "node:path"
import { parseFrontmatter } from "./parse-frontmatter.js"

/** Finds the agents directory. Checks root/agents first, then .opencode/agents (post-extract). */
export function resolveAgentsDir(root: string): string | null {
  const candidates = [resolve(root, "agents"), resolve(root, ".opencode", "agents")]
  for (const dir of candidates) {
    if (existsSync(dir)) return dir
  }
  return null
}

/** Reads all *.md files from the agents directory and registers them in cfg.agent. Skips already-registered names. */
export function registerAgents(cfg: any, root: string) {
  const agentsDir = resolveAgentsDir(root)
  if (!agentsDir) return
  cfg.agent = cfg.agent || {}
  for (const file of readdirSync(agentsDir)) {
    if (!file.endsWith(".md")) continue
    try {
      const content = readFileSync(resolve(agentsDir, file), "utf-8")
      const { attrs, body } = parseFrontmatter(content)
      const name = attrs.name || file.replace(/^engram-/, "").replace(".md", "")
      if (cfg.agent[name]) continue
      const agentCfg: Record<string, any> = {
        mode: "subagent",
        hidden: true,
        prompt: body,
      }
      if (attrs.description) agentCfg.description = attrs.description
      if (attrs.tools) {
        agentCfg.tools = Object.fromEntries(
          attrs.tools.split(",").map((t: string) => [t.trim(), true]),
        )
      }
      cfg.agent[name] = agentCfg
    } catch {}
  }
}
