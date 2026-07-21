import { describe, it, expect, beforeEach, afterEach } from "vitest"
import { tmpdir } from "node:os"
import { mkdtempSync, rmSync, writeFileSync, mkdirSync, existsSync, readFileSync } from "node:fs"
import { resolve } from "node:path"
import { getExtractTarget, needsExtract, readPrevVersion, copyMissing, selfExtract, getVERSION, resolveAgentsPath, writeOrPrependAgentsMd } from "../.opencode/install"

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

  it("removes legacy instructions.md on version bump", () => {
    const target = resolve(tmp, ".opencode")
    mkdirSync(target, { recursive: true })
    writeFileSync(resolve(target, ".engram-version.jsonc"), JSON.stringify({ version: "0.9.0" }))
    writeFileSync(resolve(target, "instructions.md"), "legacy content")

    selfExtract(pkg, tmp, "1.0.2")
    expect(existsSync(resolve(target, "instructions.md"))).toBe(false)
  })

  it("writes .engram-smudge-template on extract", () => {
    const target = resolve(tmp, ".opencode")
    mkdirSync(target, { recursive: true })

    selfExtract(pkg, tmp, "1.0.2")
    const tmpl = resolve(target, ".engram-smudge-template")
    expect(existsSync(tmpl)).toBe(true)
    expect(readFileSync(tmpl, "utf-8")).toContain("<!-- engram v1.0.2 -->")
    expect(readFileSync(tmpl, "utf-8")).toContain("<!-- /engram -->")
  })

})

describe("resolveAgentsPath", () => {
  it("returns project root for project-level target", () => {
    expect(resolveAgentsPath(resolve("/project", ".opencode"))).toBe(resolve("/project", "AGENTS.md"))
  })

  it("returns inside target for global target", () => {
    expect(resolveAgentsPath(resolve("/home/u", ".config", "opencode"))).toBe(resolve("/home/u", ".config", "opencode", "AGENTS.md"))
  })
})

describe("writeOrPrependAgentsMd", () => {
  let tmp: string

  beforeEach(() => {
    tmp = mkdtempSync(resolve(tmpdir(), "engram-test-"))
    writeFileSync(resolve(tmp, "opencode.jsonc"), "{}")
  })
  afterEach(() => rmSync(tmp, { recursive: true }))

  function projectTarget() { return resolve(tmp, ".opencode") }
  function agentsPath() { return resolve(tmp, "AGENTS.md") }

  it("creates AGENTS.md with versioned marker block when file does not exist", () => {
    writeOrPrependAgentsMd(projectTarget(), "1.0.0")
    expect(existsSync(agentsPath())).toBe(true)
    const content = readFileSync(agentsPath(), "utf-8")
    expect(content).toContain("<!-- engram v1.0.0 -->")
    expect(content).toContain("<!-- /engram -->")
    expect(content).toContain("Engram — Evidence-Based Learning Engine")
  })

  it("is no-op when file already has the same version marker", () => {
    writeOrPrependAgentsMd(projectTarget(), "1.0.0")
    const content1 = readFileSync(agentsPath(), "utf-8")
    writeOrPrependAgentsMd(projectTarget(), "1.0.0")
    const content2 = readFileSync(agentsPath(), "utf-8")
    expect(content1).toBe(content2)
  })

  it("replaces old block and preserves user content on version bump", () => {
    writeOrPrependAgentsMd(projectTarget(), "1.0.0")
    writeFileSync(agentsPath(), readFileSync(agentsPath(), "utf-8") + "\n\nMy custom rule.")

    writeOrPrependAgentsMd(projectTarget(), "1.0.1")
    const content = readFileSync(agentsPath(), "utf-8")
    expect(content).toContain("<!-- engram v1.0.1 -->")
    expect(content).toContain("My custom rule.")
    expect(content).not.toContain("<!-- engram v1.0.0 -->")
  })

  it("prepends block at top when no marker exists, preserving existing content", () => {
    writeFileSync(agentsPath(), "Existing user rules.")

    writeOrPrependAgentsMd(projectTarget(), "1.0.0")
    const content = readFileSync(agentsPath(), "utf-8")
    expect(content.startsWith("<!-- engram v1.0.0 -->")).toBe(true)
    expect(content).toContain("Existing user rules.")
  })

  it("handles multiple version bumps", () => {
    writeOrPrependAgentsMd(projectTarget(), "1.0.0")
    writeOrPrependAgentsMd(projectTarget(), "1.0.1")
    writeOrPrependAgentsMd(projectTarget(), "2.0.0")
    const content = readFileSync(agentsPath(), "utf-8")
    expect(content).toContain("<!-- engram v2.0.0 -->")
    expect(content).not.toContain("<!-- engram v1.0.0 -->")
    expect(content).not.toContain("<!-- engram v1.0.1 -->")
  })

  it("writes AGENTS.md at correct global location", () => {
    const globalTarget = resolve(tmp, ".config", "opencode")
    mkdirSync(globalTarget, { recursive: true })
    writeOrPrependAgentsMd(globalTarget, "1.0.0")
    expect(existsSync(resolve(globalTarget, "AGENTS.md"))).toBe(true)
  })

  it("preserves content with special characters below the block", () => {
    writeOrPrependAgentsMd(projectTarget(), "1.0.0")
    writeFileSync(agentsPath(), readFileSync(agentsPath(), "utf-8") + "\n\n## My Rules\n- rule 1\n- rule 2\n\n```json\n{\"key\": \"value\"}\n```")

    writeOrPrependAgentsMd(projectTarget(), "1.0.1")
    const content = readFileSync(agentsPath(), "utf-8")
    expect(content).toContain("<!-- engram v1.0.1 -->")
    expect(content).toContain("## My Rules")
    expect(content).toContain("```json")
    expect(content).toContain('"key"')
  })

  it("handles empty existing file", () => {
    writeFileSync(agentsPath(), "")
    writeOrPrependAgentsMd(projectTarget(), "1.0.0")
    const content = readFileSync(agentsPath(), "utf-8")
    expect(content).toContain("<!-- engram v1.0.0 -->")
    expect(content).not.toMatch(/\n\n$/)
  })

  it("handles whitespace-only existing file", () => {
    writeFileSync(agentsPath(), " \n\n  \t  ")
    writeOrPrependAgentsMd(projectTarget(), "1.0.0")
    const content = readFileSync(agentsPath(), "utf-8")
    expect(content.startsWith("<!-- engram v1.0.0 -->")).toBe(true)
  })

  it("prepends when close marker exists without opening marker", () => {
    writeFileSync(agentsPath(), "<!-- /engram -->\norphan close marker")
    writeOrPrependAgentsMd(projectTarget(), "1.0.0")
    const content = readFileSync(agentsPath(), "utf-8")
    expect(content.startsWith("<!-- engram v1.0.0 -->")).toBe(true)
    expect(content).toContain("orphan close marker")
  })

  it("prepends when opening marker exists without matching close marker", () => {
    writeFileSync(agentsPath(), "<!-- engram v0.9.0 -->\n# incomplete block\nno close marker")
    writeOrPrependAgentsMd(projectTarget(), "1.0.0")
    const content = readFileSync(agentsPath(), "utf-8")
    expect(content.startsWith("<!-- engram v1.0.0 -->")).toBe(true)
    expect(content).toContain("<!-- engram v0.9.0 -->")
    expect(content).toContain("no close marker")
  })

  it("writes to same dir when target basename is not .opencode", () => {
    const t = resolve(tmp, "custom-dir")
    mkdirSync(t, { recursive: true })
    writeOrPrependAgentsMd(t, "1.0.0")
    expect(existsSync(resolve(t, "AGENTS.md"))).toBe(true)
  })

  it("handles semver versions with pre-release tags", () => {
    writeOrPrependAgentsMd(projectTarget(), "1.0.0-alpha.1")
    const content = readFileSync(agentsPath(), "utf-8")
    expect(content).toContain("<!-- engram v1.0.0-alpha.1 -->")
  })

  it("replaces block and preserves user content with leading blank lines", () => {
    writeOrPrependAgentsMd(projectTarget(), "1.0.0")
    writeFileSync(agentsPath(), readFileSync(agentsPath(), "utf-8") + "\n\n\n\nUser content after blank lines.")

    writeOrPrependAgentsMd(projectTarget(), "1.0.1")
    const content = readFileSync(agentsPath(), "utf-8")
    expect(content).toContain("<!-- engram v1.0.1 -->")
    expect(content).toContain("User content after blank lines.")
    expect(content).not.toMatch(/\n\n\n\nUser content/)
  })

  it("does not introduce double newlines when user content follows immediately after close marker", () => {
    writeOrPrependAgentsMd(projectTarget(), "1.0.0")
    const raw = readFileSync(agentsPath(), "utf-8")
    writeFileSync(agentsPath(), raw.replace(/\n$/, "") + "\nuser content")

    writeOrPrependAgentsMd(projectTarget(), "1.0.1")
    const content = readFileSync(agentsPath(), "utf-8")
    expect(content).toContain("<!-- /engram -->")
    expect(content).toContain("user content")
  })

  it("preserves content above the marker on replace", () => {
    writeOrPrependAgentsMd(projectTarget(), "1.0.0")
    const raw = readFileSync(agentsPath(), "utf-8")
    writeFileSync(agentsPath(), "User header above.\n" + raw + "\n\nFooter below.")

    writeOrPrependAgentsMd(projectTarget(), "1.0.1")
    const content = readFileSync(agentsPath(), "utf-8")
    expect(content).toContain("User header above.")
    expect(content).toContain("Footer below.")
    expect(content).toContain("<!-- engram v1.0.1 -->")
    expect(content).not.toContain("<!-- engram v1.0.0 -->")
  })
})
