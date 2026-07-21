import { describe, it, expect, beforeEach, afterEach } from "vitest"
import { tmpdir } from "node:os"
import { mkdtempSync, rmSync, writeFileSync, mkdirSync, existsSync, readFileSync } from "node:fs"
import { resolve } from "node:path"
import { warnClaudeMdCollision } from "../.opencode/claude-warning"
import { selfExtract } from "../.opencode/install"

describe("warnClaudeMdCollision (unit)", () => {
  let tmp: string

  beforeEach(() => { tmp = mkdtempSync(resolve(tmpdir(), "engram-test-")) })
  afterEach(() => rmSync(tmp, { recursive: true }))

  it("logs warning when CLAUDE.md exists", () => {
    writeFileSync(resolve(tmp, "CLAUDE.md"), "# rules")
    const messages: string[] = []
    warnClaudeMdCollision(tmp, (m) => messages.push(m))
    expect(messages.length).toBe(1)
    expect(messages[0]).toContain("WARNING")
    expect(messages[0]).toContain("CLAUDE.md")
    expect(messages[0]).toContain("suppressed")
  })

  it("does NOT log when CLAUDE.md is absent", () => {
    const messages: string[] = []
    warnClaudeMdCollision(tmp, (m) => messages.push(m))
    expect(messages.length).toBe(0)
  })

  it("does NOT log when directory is empty", () => {
    const messages: string[] = []
    warnClaudeMdCollision(tmp, (m) => messages.push(m))
    expect(messages.length).toBe(0)
  })

  it("does NOT log for CLAUDE.md with different case on case-sensitive fs", () => {
    writeFileSync(resolve(tmp, "claude.md"), "# rules")
    const messages: string[] = []
    warnClaudeMdCollision(tmp, (m) => messages.push(m))
    expect(messages.length).toBe(0)
  })

  it("logs warning for a directory named CLAUDE.md (existsSync true)", () => {
    mkdirSync(resolve(tmp, "CLAUDE.md"))
    const messages: string[] = []
    warnClaudeMdCollision(tmp, (m) => messages.push(m))
    expect(messages.length).toBe(1)
    expect(messages[0]).toContain("WARNING")
  })
})

describe("warnClaudeMdCollision (integration via selfExtract)", () => {
  let tmp: string
  let pkg: string

  beforeEach(() => {
    tmp = mkdtempSync(resolve(tmpdir(), "engram-test-"))
    writeFileSync(resolve(tmp, "opencode.jsonc"), "{}")
    mkdirSync(resolve(tmp, ".git"), { recursive: true })
    writeFileSync(resolve(tmp, ".git", "config"), "[core]\n\trepositoryformatversion = 0\n")
    pkg = resolve(tmp, "pkg")
    mkdirSync(resolve(pkg, "skills"), { recursive: true })
    writeFileSync(resolve(pkg, "skills", "SKILL.md"), "skill")
    mkdirSync(resolve(pkg, "agents"), { recursive: true })
    writeFileSync(resolve(pkg, "agents", "agent.md"), "agent")
    mkdirSync(resolve(pkg, "scripts"), { recursive: true })
    writeFileSync(resolve(pkg, "scripts", "engram.py"), "script")
    writeFileSync(resolve(pkg, "package.json"), JSON.stringify({ version: "1.0.2" }))
  })
  afterEach(() => rmSync(tmp, { recursive: true }))

  it("logs CLAUDE.md warning during selfExtract when CLAUDE.md exists", () => {
    writeFileSync(resolve(tmp, "CLAUDE.md"), "# rules")
    const target = resolve(tmp, ".opencode")
    mkdirSync(target, { recursive: true })
    writeFileSync(resolve(target, ".engram-version.jsonc"), JSON.stringify({ version: "0.9.0" }))

    const messages: string[] = []
    selfExtract(pkg, tmp, "1.0.2", (m) => messages.push(m))

    expect(messages.some((m) => m.includes("WARNING") && m.includes("CLAUDE.md"))).toBe(true)
  })

  it("does NOT log CLAUDE.md warning during selfExtract when CLAUDE.md absent", () => {
    const target = resolve(tmp, ".opencode")
    mkdirSync(target, { recursive: true })
    writeFileSync(resolve(target, ".engram-version.jsonc"), JSON.stringify({ version: "0.9.0" }))

    const messages: string[] = []
    selfExtract(pkg, tmp, "1.0.2", (m) => messages.push(m))

    expect(messages.every((m) => !m.includes("CLAUDE.md"))).toBe(true)
  })

  it("does NOT log CLAUDE.md warning on same-version (no selfExtract)", () => {
    writeFileSync(resolve(tmp, "CLAUDE.md"), "# rules")
    const target = resolve(tmp, ".opencode")
    mkdirSync(target, { recursive: true })
    writeFileSync(resolve(target, ".engram-version.jsonc"), JSON.stringify({ version: "1.0.2" }))

    const messages: string[] = []
    selfExtract(pkg, tmp, "1.0.2", (m) => messages.push(m))

    expect(messages.every((m) => !m.includes("CLAUDE.md"))).toBe(true)
  })
})
