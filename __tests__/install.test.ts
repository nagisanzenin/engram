import { describe, it, expect, beforeEach, afterEach } from "vitest"
import { tmpdir } from "node:os"
import { mkdtempSync, rmSync, writeFileSync, mkdirSync, existsSync, readFileSync } from "node:fs"
import { resolve } from "node:path"
import { getExtractTarget, needsExtract, readPrevVersion, copyMissing, selfExtract, getVERSION } from "../.opencode/install"

describe("getExtractTarget", () => {
  let tmp: string

  beforeEach(() => { tmp = mkdtempSync(resolve(tmpdir(), "engram-test-")) })
  afterEach(() => rmSync(tmp, { recursive: true }))

  it("returns project-level when opencode.jsonc exists", () => {
    writeFileSync(resolve(tmp, "opencode.jsonc"), "{}")
    expect(getExtractTarget(tmp)).toBe(resolve(tmp, ".opencode"))
  })

  it("returns project-level when opencode.json exists", () => {
    writeFileSync(resolve(tmp, "opencode.json"), "{}")
    expect(getExtractTarget(tmp)).toBe(resolve(tmp, ".opencode"))
  })

  it("returns global when no opencode config exists", () => {
    const home = process.env.HOME || "/tmp"
    expect(getExtractTarget(tmp)).toBe(resolve(home, ".config", "opencode"))
  })
})

describe("needsExtract / readPrevVersion", () => {
  let tmp: string

  beforeEach(() => { tmp = mkdtempSync(resolve(tmpdir(), "engram-test-")) })
  afterEach(() => rmSync(tmp, { recursive: true }))

  it("returns undefined when no version file exists", () => {
    expect(readPrevVersion(tmp)).toBeUndefined()
  })

  it("returns true for needsExtract when no version file", () => {
    expect(needsExtract(tmp, "1.0.0")).toBe(true)
  })

  it("returns false when version matches", () => {
    writeFileSync(resolve(tmp, ".engram-version.jsonc"), JSON.stringify({ version: "1.0.0" }))
    expect(needsExtract(tmp, "1.0.0")).toBe(false)
  })

  it("returns true when version differs", () => {
    writeFileSync(resolve(tmp, ".engram-version.jsonc"), JSON.stringify({ version: "0.9.0" }))
    expect(needsExtract(tmp, "1.0.0")).toBe(true)
  })

  it("returns undefined for corrupt version file", () => {
    writeFileSync(resolve(tmp, ".engram-version.jsonc"), "not-json")
    expect(readPrevVersion(tmp)).toBeUndefined()
  })
})

describe("copyMissing", () => {
  let tmp: string

  beforeEach(() => { tmp = mkdtempSync(resolve(tmpdir(), "engram-test-")) })
  afterEach(() => rmSync(tmp, { recursive: true }))

  it("copies new files from src to dest", () => {
    const src = resolve(tmp, "src")
    const dest = resolve(tmp, "dest")
    mkdirSync(src, { recursive: true })
    writeFileSync(resolve(src, "new-file.txt"), "content")

    copyMissing(src, dest)

    expect(existsSync(resolve(dest, "new-file.txt"))).toBe(true)
    expect(readFileSync(resolve(dest, "new-file.txt"), "utf-8")).toBe("content")
  })

  it("does not overwrite existing files", () => {
    const src = resolve(tmp, "src")
    const dest = resolve(tmp, "dest")
    mkdirSync(src, { recursive: true })
    mkdirSync(dest, { recursive: true })
    writeFileSync(resolve(src, "file.txt"), "src-content")
    writeFileSync(resolve(dest, "file.txt"), "dest-content")

    copyMissing(src, dest)

    expect(readFileSync(resolve(dest, "file.txt"), "utf-8")).toBe("dest-content")
  })

  it("copies nested directory structures", () => {
    const src = resolve(tmp, "src")
    const dest = resolve(tmp, "dest")
    mkdirSync(resolve(src, "sub", "deep"), { recursive: true })
    writeFileSync(resolve(src, "sub", "deep", "nested.txt"), "nested")

    copyMissing(src, dest)

    expect(existsSync(resolve(dest, "sub", "deep", "nested.txt"))).toBe(true)
  })

  it("no-ops when src does not exist", () => {
    copyMissing(resolve(tmp, "nonexistent"), resolve(tmp, "dest"))
    expect(existsSync(resolve(tmp, "dest"))).toBe(false)
  })
})

describe("selfExtract — engram-update is never written to disk", () => {
  let tmp: string
  let pkg: string

  beforeEach(() => {
    tmp = mkdtempSync(resolve(tmpdir(), "engram-test-"))
    writeFileSync(resolve(tmp, "opencode.jsonc"), "{}")
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

  it("never writes engram-update.md to disk", () => {
    const { freshlyExtracted, prevVersion } = selfExtract(pkg, tmp, "1.0.2")
    expect(freshlyExtracted).toBe(true)
    expect(prevVersion).toBeUndefined()
    expect(existsSync(resolve(tmp, ".opencode", "command", "learn.md"))).toBe(true)
    expect(existsSync(resolve(tmp, ".opencode", "command", "review-loop.md"))).toBe(true)
    expect(existsSync(resolve(tmp, ".opencode", "command", "coach.md"))).toBe(true)
    expect(existsSync(resolve(tmp, ".opencode", "command", "engram-update.md"))).toBe(false)
  })

  it("never writes engram-update.md even on update", () => {
    const target = resolve(tmp, ".opencode")
    mkdirSync(target, { recursive: true })
    writeFileSync(resolve(target, ".engram-version.jsonc"), JSON.stringify({ version: "0.9.0" }))

    const { prevVersion } = selfExtract(pkg, tmp, "1.0.2")
    expect(prevVersion).toBe("0.9.0")
    expect(existsSync(resolve(target, "command", "engram-update.md"))).toBe(false)
  })

  it("writes .engram-update.jsonc on version bump", () => {
    const target = resolve(tmp, ".opencode")
    mkdirSync(target, { recursive: true })
    writeFileSync(resolve(target, ".engram-version.jsonc"), JSON.stringify({ version: "0.9.0" }))

    selfExtract(pkg, tmp, "1.0.2")
    expect(existsSync(resolve(target, ".engram-update.jsonc"))).toBe(true)

    const manifest = JSON.parse(readFileSync(resolve(target, ".engram-update.jsonc"), "utf-8"))
    expect(manifest.from).toBe("0.9.0")
    expect(manifest.to).toBe("1.0.2")
    expect(manifest.state).toBe("pending")
    expect(manifest.categories.skills).toBeDefined()
    expect(manifest.categories.agents).toBeDefined()
    expect(manifest.categories.scripts).toBeDefined()
    expect(manifest.categories.command).toBeDefined()
    expect(manifest.applied).toEqual([])
  })

  it("does NOT write .engram-update.jsonc on same version (no version bump)", () => {
    const target = resolve(tmp, ".opencode")
    mkdirSync(target, { recursive: true })
    writeFileSync(resolve(target, ".engram-version.jsonc"), JSON.stringify({ version: "1.0.2" }))

    const { freshlyExtracted } = selfExtract(pkg, tmp, "1.0.2")
    expect(freshlyExtracted).toBe(false)
    expect(existsSync(resolve(target, ".engram-update.jsonc"))).toBe(false)
  })

})
