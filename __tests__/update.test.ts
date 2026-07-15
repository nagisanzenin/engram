import { describe, it, expect, beforeEach, afterEach } from "vitest"
import { tmpdir } from "node:os"
import { mkdtempSync, rmSync, existsSync, writeFileSync } from "node:fs"
import { resolve } from "node:path"
import { writeUpdateManifest, readManifest, saveManifest, clearUpdate, getUpdateSummary } from "../.opencode/update"

describe("update manifest state machine", () => {
  let tmp: string

  beforeEach(() => { tmp = mkdtempSync(resolve(tmpdir(), "engram-test-")) })
  afterEach(() => rmSync(tmp, { recursive: true }))

  it("writes manifest with state: pending", () => {
    writeUpdateManifest("/fake/pkg", tmp, "0.9.0", "1.0.2")
    const m = readManifest(tmp)
    expect(m).not.toBeNull()
    expect(m!.state).toBe("pending")
    expect(m!.applied).toEqual([])
    expect(m!.from).toBe("0.9.0")
    expect(m!.to).toBe("1.0.2")
    expect(m!.source).toBe("/fake/pkg")
  })

  it("writes categories with diff info", () => {
    writeUpdateManifest("/fake/pkg", tmp, "0.9.0", "1.0.2")
    const m = readManifest(tmp)!
    expect(m.categories.skills).toBeDefined()
    expect(m.categories.agents).toBeDefined()
    expect(m.categories.scripts).toBeDefined()
    expect(m.categories.command).toBeDefined()
    expect(Array.isArray(m.categories.skills.added)).toBe(true)
    expect(Array.isArray(m.categories.skills.skipped)).toBe(true)
  })

  it("remaining only includes categories with skipped files", () => {
    writeUpdateManifest("/fake/pkg", tmp, "0.9.0", "1.0.2")
    const m = readManifest(tmp)!
    for (const cat of m.remaining) {
      expect(m.categories[cat].skipped.length).toBeGreaterThan(0)
    }
  })

  it("saveManifest persists state change", () => {
    writeUpdateManifest("/fake/pkg", tmp, "0.9.0", "1.0.2")
    const m = readManifest(tmp)!
    m.state = "in_progress"
    m.applied = ["skills"]
    m.remaining = ["agents", "scripts"]
    saveManifest(tmp, m)

    const reloaded = readManifest(tmp)!
    expect(reloaded.state).toBe("in_progress")
    expect(reloaded.applied).toEqual(["skills"])
    expect(reloaded.remaining).toEqual(["agents", "scripts"])
  })

  it("clearUpdate removes manifest file", () => {
    writeUpdateManifest("/fake/pkg", tmp, "0.9.0", "1.0.2")
    expect(existsSync(resolve(tmp, ".engram-update.jsonc"))).toBe(true)
    clearUpdate(tmp)
    expect(existsSync(resolve(tmp, ".engram-update.jsonc"))).toBe(false)
  })

  it("readManifest returns null when no manifest exists", () => {
    expect(readManifest(tmp)).toBeNull()
  })

  it("readManifest returns null for corrupt JSON", () => {
    writeFileSync(resolve(tmp, ".engram-update.jsonc"), "not-json")
    expect(readManifest(tmp)).toBeNull()
  })
})

describe("getUpdateSummary", () => {
  let tmp: string

  beforeEach(() => { tmp = mkdtempSync(resolve(tmpdir(), "engram-test-")) })
  afterEach(() => rmSync(tmp, { recursive: true }))

  it("returns summary string for valid manifest", () => {
    writeUpdateManifest("/fake/pkg", tmp, "0.9.0", "1.0.2")
    const summary = getUpdateSummary(tmp)
    expect(summary).toContain("Engram 0.9.0 → 1.0.2")
    expect(summary).toContain("/engram-update")
    expect(summary).toContain("auto")
    expect(summary).toContain("manual")
  })

  it("returns null when no manifest exists", () => {
    expect(getUpdateSummary(tmp)).toBeNull()
  })
})
