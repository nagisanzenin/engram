import { describe, it, expect, beforeEach, afterEach } from "vitest"
import { tmpdir } from "node:os"
import { mkdtempSync, rmSync, writeFileSync, mkdirSync } from "node:fs"
import { resolve } from "node:path"
import { resolveAgentsDir, registerAgents } from "../.opencode/agents"

describe("resolveAgentsDir", () => {
  let tmp: string

  beforeEach(() => { tmp = mkdtempSync(resolve(tmpdir(), "engram-test-")) })
  afterEach(() => rmSync(tmp, { recursive: true }))

  it("finds agents/ directory", () => {
    mkdirSync(resolve(tmp, "agents"), { recursive: true })
    expect(resolveAgentsDir(tmp)).toBe(resolve(tmp, "agents"))
  })

  it("returns null when no agents dir exists", () => {
    expect(resolveAgentsDir(tmp)).toBeNull()
  })

  it("prefers agents/ over .opencode/agents/", () => {
    mkdirSync(resolve(tmp, "agents"), { recursive: true })
    mkdirSync(resolve(tmp, ".opencode", "agents"), { recursive: true })
    expect(resolveAgentsDir(tmp)).toBe(resolve(tmp, "agents"))
  })
})

describe("registerAgents", () => {
  let tmp: string

  beforeEach(() => { tmp = mkdtempSync(resolve(tmpdir(), "engram-test-")) })
  afterEach(() => rmSync(tmp, { recursive: true }))

  it("registers agent with custom tools string converted to object", () => {
    mkdirSync(resolve(tmp, "agents"), { recursive: true })
    writeFileSync(resolve(tmp, "agents", "test-agent.md"), `---
name: test-agent
description: A test agent
tools: Read, Write, Bash
---

# Agent prompt body.

Some instructions here.`)

    const cfg: any = {}
    registerAgents(cfg, tmp)

    expect(cfg.agent["test-agent"]).toBeDefined()
    expect(cfg.agent["test-agent"].mode).toBe("subagent")
    expect(cfg.agent["test-agent"].hidden).toBe(true)
    expect(cfg.agent["test-agent"].description).toBe("A test agent")
    expect(cfg.agent["test-agent"].tools).toEqual({ Read: true, Write: true, Bash: true })
    expect(cfg.agent["test-agent"].prompt).toContain("Agent prompt body.")
  })

  it("skips non-md files", () => {
    mkdirSync(resolve(tmp, "agents"), { recursive: true })
    writeFileSync(resolve(tmp, "agents", "not-an-agent.txt"), "ignored")

    const cfg: any = {}
    registerAgents(cfg, tmp)

    expect(Object.keys(cfg.agent || {})).toHaveLength(0)
  })

  it("handles agent without tools gracefully", () => {
    mkdirSync(resolve(tmp, "agents"), { recursive: true })
    writeFileSync(resolve(tmp, "agents", "no-tools-agent.md"), `---
name: no-tools-agent
description: Agent without tools
---

No tools here.`)

    const cfg: any = {}
    registerAgents(cfg, tmp)

    expect(cfg.agent["no-tools-agent"]).toBeDefined()
    expect(cfg.agent["no-tools-agent"].tools).toBeUndefined()
  })
})
