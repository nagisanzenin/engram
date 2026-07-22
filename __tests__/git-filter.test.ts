import { describe, it, expect, beforeEach, afterEach } from "vitest"
import { tmpdir } from "node:os"
import { mkdtempSync, rmSync, writeFileSync, mkdirSync, existsSync, readFileSync, copyFileSync } from "node:fs"
import { resolve } from "node:path"
import { execSync } from "node:child_process"
import { selfExtract, syncProjectState } from "../.opencode/install"

describe("git filter integration", () => {
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

  it("installs git filter and .git/info/attributes on selfExtract", () => {
    const target = resolve(tmp, ".opencode")
    mkdirSync(target, { recursive: true })
    writeFileSync(resolve(target, ".engram-version.jsonc"), JSON.stringify({ version: "0.9.0" }))

    selfExtract(pkg, tmp, "1.0.2")

    const gitConfig = readFileSync(resolve(tmp, ".git", "config"), "utf-8")
    expect(gitConfig).toContain('[filter "engram"]')
    expect(gitConfig).toContain("opencode-engram-clean")
    expect(gitConfig).toContain("opencode-engram-smudge")

    const gitattrs = readFileSync(resolve(tmp, ".git", "info", "attributes"), "utf-8")
    expect(gitattrs).toContain("AGENTS.md filter=engram")

    const gitExclude = readFileSync(resolve(tmp, ".git", "info", "exclude"), "utf-8")
    expect(gitExclude).toContain("AGENTS.md")
    expect(gitExclude).toContain(".engram-*")
  })

  it("does NOT duplicate filter on second extract", () => {
    const target = resolve(tmp, ".opencode")
    mkdirSync(target, { recursive: true })
    writeFileSync(resolve(target, ".engram-version.jsonc"), JSON.stringify({ version: "0.9.0" }))

    selfExtract(pkg, tmp, "1.0.2")
    const config1 = readFileSync(resolve(tmp, ".git", "config"), "utf-8")
    writeFileSync(resolve(target, ".engram-version.jsonc"), JSON.stringify({ version: "0.9.1" }))
    selfExtract(pkg, tmp, "1.0.3")
    const config2 = readFileSync(resolve(tmp, ".git", "config"), "utf-8")

    expect(config1).toBe(config2)
  })

  it("does NOT duplicate exclude and attributes on second extract", () => {
    const target = resolve(tmp, ".opencode")
    mkdirSync(target, { recursive: true })
    writeFileSync(resolve(target, ".engram-version.jsonc"), JSON.stringify({ version: "0.9.0" }))

    selfExtract(pkg, tmp, "1.0.2")
    const exclude1 = readFileSync(resolve(tmp, ".git", "info", "exclude"), "utf-8")
    const attrs1 = readFileSync(resolve(tmp, ".git", "info", "attributes"), "utf-8")

    writeFileSync(resolve(target, ".engram-version.jsonc"), JSON.stringify({ version: "0.9.1" }))
    selfExtract(pkg, tmp, "1.0.3")
    const exclude2 = readFileSync(resolve(tmp, ".git", "info", "exclude"), "utf-8")
    const attrs2 = readFileSync(resolve(tmp, ".git", "info", "attributes"), "utf-8")

    expect(exclude1).toBe(exclude2)
    expect(attrs1).toBe(attrs2)
  })

  it("creates .git/info/attributes and appends to existing .git/info/exclude", () => {
    const target = resolve(tmp, ".opencode")
    mkdirSync(target, { recursive: true })
    writeFileSync(resolve(target, ".engram-version.jsonc"), JSON.stringify({ version: "0.9.0" }))

    const infoDir = resolve(tmp, ".git", "info")
    mkdirSync(infoDir, { recursive: true })
    const existingExclude = "# default git exclusion\nsome-other-file\n"
    writeFileSync(resolve(infoDir, "exclude"), existingExclude)

    selfExtract(pkg, tmp, "1.0.2")

    expect(existsSync(resolve(infoDir, "attributes"))).toBe(true)
    const attrs = readFileSync(resolve(infoDir, "attributes"), "utf-8")
    expect(attrs).toContain("AGENTS.md filter=engram")

    const exclude = readFileSync(resolve(infoDir, "exclude"), "utf-8")
    expect(exclude).toContain("AGENTS.md")
    expect(exclude).toContain("some-other-file")
    expect(exclude.indexOf("some-other-file")).toBeLessThan(exclude.indexOf("AGENTS.md"))
  })

  it("does not crash when .git/config is absent (no git repo)", () => {
    const tmp2 = mkdtempSync(resolve(tmpdir(), "engram-test-"))
    try {
      writeFileSync(resolve(tmp2, "opencode.jsonc"), "{}")
      const pkg2 = resolve(tmp2, "pkg")
      mkdirSync(resolve(pkg2, "skills"), { recursive: true })
      writeFileSync(resolve(pkg2, "skills", "SKILL.md"), "skill")
      mkdirSync(resolve(pkg2, "agents"), { recursive: true })
      writeFileSync(resolve(pkg2, "agents", "agent.md"), "agent")
      mkdirSync(resolve(pkg2, "scripts"), { recursive: true })
      writeFileSync(resolve(pkg2, "scripts", "engram.py"), "script")
      writeFileSync(resolve(pkg2, "package.json"), JSON.stringify({ version: "1.0.2" }))

      const target = resolve(tmp2, ".opencode")
      mkdirSync(target, { recursive: true })
      writeFileSync(resolve(target, ".engram-version.jsonc"), JSON.stringify({ version: "0.9.0" }))

      expect(() => selfExtract(pkg2, tmp2, "1.0.2")).not.toThrow()
    } finally {
      rmSync(tmp2, { recursive: true })
    }
  })

  it("filter values are double-quoted (semicolon-safe)", () => {
    const target = resolve(tmp, ".opencode")
    mkdirSync(target, { recursive: true })
    writeFileSync(resolve(target, ".engram-version.jsonc"), JSON.stringify({ version: "0.9.0" }))

    selfExtract(pkg, tmp, "1.0.2")

    const gitConfig = readFileSync(resolve(tmp, ".git", "config"), "utf-8")
    // Values must be double-quoted to survive git's ; comment parsing
    expect(gitConfig).toMatch(/clean = "if \[/)
    expect(gitConfig).toMatch(/smudge = "if \[/)
    expect(gitConfig).toMatch(/else cat; fi"/)
  })

  /**
   * 1. — exclude is conditional on engramCreated.
   *
   * When AGENTS.md already existed (user-authored), writeOrPrependAgentsMd
   * returns false and installGitFilter skips the exclude entry. Without
   * this, a user's own AGENTS.md vanishes from git status and they never
   * notice their rules aren't shared.
   */
  it("1. exclude NOT written when AGENTS.md already existed before extract", () => {

    const target = resolve(tmp, ".opencode")
    mkdirSync(target, { recursive: true })
    writeFileSync(resolve(target, ".engram-version.jsonc"), JSON.stringify({ version: "0.9.0" }))

    // Pre-create AGENTS.md (simulates user-authored file)
    writeFileSync(resolve(tmp, "AGENTS.md"), "# My custom rules\nuser content\n")

    selfExtract(pkg, tmp, "1.0.2")

    const excludePath = resolve(tmp, ".git", "info", "exclude")
    if (existsSync(excludePath)) {
      const exclude = readFileSync(excludePath, "utf-8")
      expect(exclude).not.toContain("AGENTS.md")
    }
  })

  /**
   * 2. — EACCES on .git/config does not abort the full extract.
   *
   * If .git/config is read-only (e.g., root-owned repo), the git filter
   * installation must fail gracefully without stopping generateCommands
   * or the version-file write. Both installGitFilter and
   * warnClaudeMdCollision are wrapped in individual try/catch and run
   * after the version write.
   */
  it("2. read-only .git/config does not abort the extract", () => {
    const target = resolve(tmp, ".opencode")
    mkdirSync(target, { recursive: true })
    writeFileSync(resolve(target, ".engram-version.jsonc"), JSON.stringify({ version: "0.9.0" }))

    // Make .git/config read-only
    const { chmodSync } = require("node:fs")
    chmodSync(resolve(tmp, ".git", "config"), 0o444)

    try {
      // Extract should succeed — commands and version file are written
      selfExtract(pkg, tmp, "1.0.2")
      expect(existsSync(resolve(target, "command", "learn.md"))).toBe(true)
      expect(existsSync(resolve(target, ".engram-version.jsonc"))).toBe(true)
    } finally {
      chmodSync(resolve(tmp, ".git", "config"), 0o644)
    }
  })

  /**
   * 3. — partial-state repair.
   *
   * Each git mechanism (filter config, path attributes, local exclude)
   * is checked independently. A user who deletes .git/info/attributes
   * after the first extract gets it restored on the next — no early
   * return when [filter "engram"] already exists.
   */
  it("3. filter already installed but attributes deleted — attributes get healed", () => {
    const target = resolve(tmp, ".opencode")
    mkdirSync(target, { recursive: true })
    writeFileSync(resolve(target, ".engram-version.jsonc"), JSON.stringify({ version: "0.9.0" }))

    // First extract — installs everything
    selfExtract(pkg, tmp, "1.0.2")
    expect(readFileSync(resolve(tmp, ".git", "info", "attributes"), "utf-8")).toContain("AGENTS.md filter=engram")

    // Simulate user deleting attributes
    const attrsPath = resolve(tmp, ".git", "info", "attributes")
    const { unlinkSync, chmodSync } = require("node:fs")
    unlinkSync(attrsPath)

    // Version bump — trigger second extract
    writeFileSync(resolve(target, ".engram-version.jsonc"), JSON.stringify({ version: "0.9.1" }))
    selfExtract(pkg, tmp, "1.0.3")

    // Attributes should be healed
    expect(existsSync(attrsPath)).toBe(true)
    expect(readFileSync(attrsPath, "utf-8")).toContain("AGENTS.md filter=engram")
  })

  it("logger receives CLAUDE.md warning from syncProjectState", () => {
    const target = resolve(tmp, ".opencode")
    mkdirSync(target, { recursive: true })
    writeFileSync(resolve(target, ".engram-version.jsonc"), JSON.stringify({ version: "0.9.0" }))
    writeFileSync(resolve(tmp, "CLAUDE.md"), "# rules\nSENTINEL\n")
    selfExtract(pkg, tmp, "1.0.2")

    const messages: string[] = []
    syncProjectState(target, (m: string) => messages.push(m))

    expect(messages.some((m) => m.includes("WARNING") && m.includes("CLAUDE.md"))).toBe(true)
  })
})

describe("filter scripts", () => {
  const scriptsDir = resolve(__dirname, "..", "scripts")

  it("opencode-engram-clean strips the Engram block", () => {
    const input = `<!-- engram v1.0.0 -->
# block content
<!-- /engram -->
user content
`
    const result = execSync(`python3 ${resolve(scriptsDir, "opencode-engram-clean")}`, { input })
    expect(result.toString()).toBe("user content\n")
  })

  it("opencode-engram-clean passes through content without a block", () => {
    const input = "just user content\n"
    const result = execSync(`python3 ${resolve(scriptsDir, "opencode-engram-clean")}`, { input })
    expect(result.toString()).toBe(input)
  })

  it("opencode-engram-clean strips block-only content to empty", () => {
    const input = `<!-- engram v1.0.0 -->
# block content
<!-- /engram -->
`
    const result = execSync(`python3 ${resolve(scriptsDir, "opencode-engram-clean")}`, { input })
    expect(result.toString()).toBe("")
  })

  it("opencode-engram-clean handles empty stdin", () => {
    const result = execSync(`python3 ${resolve(scriptsDir, "opencode-engram-clean")}`, { input: "" })
    expect(result.toString()).toBe("")
  })

  it("opencode-engram-clean does not strip block without closing marker", () => {
    const input = `<!-- engram v1.0.0 -->
# incomplete block
no close marker
`
    const result = execSync(`python3 ${resolve(scriptsDir, "opencode-engram-clean")}`, { input })
    expect(result.toString()).toBe(input)
  })

  it("opencode-engram-clean preserves content above the block", () => {
    const input = `My header

<!-- engram v1.0.0 -->
# block content
<!-- /engram -->
user content
`
    const result = execSync(`python3 ${resolve(scriptsDir, "opencode-engram-clean")}`, { input })
    expect(result.toString()).toBe("My header\n\nuser content\n")
  })

  it("opencode-engram-clean preserves content above and below the block", () => {
    const input = `# Header
custom rule

<!-- engram v1.0.0 -->
# block
<!-- /engram -->

# Footer
more rules
`
    const result = execSync(`python3 ${resolve(scriptsDir, "opencode-engram-clean")}`, { input })
    expect(result.toString()).toBe("# Header\ncustom rule\n\n\n# Footer\nmore rules\n")
  })

  it("opencode-engram-clean handles CRLF line endings", () => {
    const input = "<!-- engram v1.0.0 -->\r\n# block content\r\n<!-- /engram -->\r\nuser content\r\n"
    const result = execSync(`python3 ${resolve(scriptsDir, "opencode-engram-clean")}`, { input })
    expect(result.toString()).toBe("user content\r\n")
  })

  it("opencode-engram-clean handles mixed CRLF and LF line endings", () => {
    const input = "<!-- engram v1.0.0 -->\r\n# block\r\n<!-- /engram -->\n\nuser content\n"
    const result = execSync(`python3 ${resolve(scriptsDir, "opencode-engram-clean")}`, { input })
    expect(result.toString()).toBe("\r\nuser content\r\n")
  })

  it("opencode-engram-smudge prepends block from template", () => {
    const template = "<!-- engram v1.0.2 -->\n# template\n<!-- /engram -->\n"
    const tmp = mkdtempSync(resolve(tmpdir(), "engram-test-"))
    try {
      mkdirSync(resolve(tmp, ".opencode"), { recursive: true })
      writeFileSync(resolve(tmp, ".opencode", ".engram-smudge-template"), template)
      const input = "user content\n"
      const result = execSync(`python3 ${resolve(scriptsDir, "opencode-engram-smudge")}`, { input, cwd: tmp })
      expect(result.toString()).toBe(template + input)
    } finally {
      rmSync(tmp, { recursive: true })
    }
  })

  it("opencode-engram-smudge passes through when template missing", () => {
    const tmp = mkdtempSync(resolve(tmpdir(), "engram-test-"))
    try {
      const input = "user content\n"
      const result = execSync(`python3 ${resolve(scriptsDir, "opencode-engram-smudge")}`, { input, cwd: tmp })
      expect(result.toString()).toBe(input)
    } finally {
      rmSync(tmp, { recursive: true })
    }
  })

  it("opencode-engram-smudge passes through when content already has marker", () => {
    const template = "<!-- engram v1.0.2 -->\n# template\n<!-- /engram -->\n"
    const tmp = mkdtempSync(resolve(tmpdir(), "engram-test-"))
    try {
      mkdirSync(resolve(tmp, ".opencode"), { recursive: true })
      writeFileSync(resolve(tmp, ".opencode", ".engram-smudge-template"), template)
      const input = "<!-- engram v1.0.0 -->\nuser content\n"
      const result = execSync(`python3 ${resolve(scriptsDir, "opencode-engram-smudge")}`, { input, cwd: tmp })
      expect(result.toString()).toBe(input)
    } finally {
      rmSync(tmp, { recursive: true })
    }
  })

  it("opencode-engram-smudge outputs just template when content is empty", () => {
    const template = "<!-- engram v1.0.2 -->\n# template\n<!-- /engram -->\n"
    const tmp = mkdtempSync(resolve(tmpdir(), "engram-test-"))
    try {
      mkdirSync(resolve(tmp, ".opencode"), { recursive: true })
      writeFileSync(resolve(tmp, ".opencode", ".engram-smudge-template"), template)
      const result = execSync(`python3 ${resolve(scriptsDir, "opencode-engram-smudge")}`, { input: "", cwd: tmp })
      expect(result.toString()).toBe(template)
    } finally {
      rmSync(tmp, { recursive: true })
    }
  })

  it("opencode-engram-smudge passes through when template is empty", () => {
    const tmp = mkdtempSync(resolve(tmpdir(), "engram-test-"))
    try {
      mkdirSync(resolve(tmp, ".opencode"), { recursive: true })
      writeFileSync(resolve(tmp, ".opencode", ".engram-smudge-template"), "")
      const input = "user content\n"
      const result = execSync(`python3 ${resolve(scriptsDir, "opencode-engram-smudge")}`, { input, cwd: tmp })
      expect(result.toString()).toBe(input)
    } finally {
      rmSync(tmp, { recursive: true })
    }
  })

  it("opencode-engram-smudge prepends template to content without trailing newline", () => {
    const template = "<!-- engram v1.0.2 -->\n# template\n<!-- /engram -->\n"
    const tmp = mkdtempSync(resolve(tmpdir(), "engram-test-"))
    try {
      mkdirSync(resolve(tmp, ".opencode"), { recursive: true })
      writeFileSync(resolve(tmp, ".opencode", ".engram-smudge-template"), template)
      const result = execSync(`python3 ${resolve(scriptsDir, "opencode-engram-smudge")}`, { input: "inline content", cwd: tmp })
      expect(result.toString()).toBe(template + "inline content")
    } finally {
      rmSync(tmp, { recursive: true })
    }
  })
})

/**
 * Real git lifecycle tests.
 *
 * These tests execute actual git commands (init, add, commit, show, checkout)
 * against the installed filter configuration. They catch regressions that
 * piped-stdin tests cannot: unquoted semicolons in git-config (double-quoting
 * is required because ; is a comment delimiter), the .git/info/exclude
 * interaction (exclude bypass via --force), and the smudge restore cycle.
 *
 * Skipped gracefully when git is not available on the system.
 */
describe("filter lifecycle (real git)", () => {
  const scriptsDir = resolve(__dirname, "..", "scripts")

  /**
   * Full-stack test that verifies the complete smudge/clean lifecycle against a
   * real git repository:
   *
   *   1. git init → selfExtract installs the filter
   *   2. git add --force AGENTS.md  (--force bypasses .git/info/exclude)
   *   3. git commit
   *   4. git show HEAD:AGENTS.md   — block must be GONE  (clean)
   *   5. git checkout -- AGENTS.md  — block must be BACK (smudge)
   *
   * Would have caught:
   *   — unquoted ; truncation in git-config
   *   — .engram-* leaking through git
   *   — exclude blocking git add
   */
  it("git add+commit strips Engram block, checkout restores it", () => {
    const repo = mkdtempSync(resolve(tmpdir(), "engram-git-repo-"))
    try {
      // Skip if git is not available
      try { execSync("git --version", { cwd: repo, stdio: "ignore" }) } catch { return }

      execSync("git init", { cwd: repo, stdio: "ignore" })
      execSync('git config user.email "test@test.com"', { cwd: repo, stdio: "ignore" })
      execSync('git config user.name "Test"', { cwd: repo, stdio: "ignore" })
      writeFileSync(resolve(repo, "opencode.jsonc"), "{}")

      const pkg = resolve(repo, "pkg")
      mkdirSync(resolve(pkg, "skills"), { recursive: true })
      mkdirSync(resolve(pkg, "agents"), { recursive: true })
      mkdirSync(resolve(pkg, "scripts"), { recursive: true })
      writeFileSync(resolve(pkg, "skills", "SKILL.md"), "")
      writeFileSync(resolve(pkg, "agents", "agent.md"), "")
      writeFileSync(resolve(pkg, "scripts", "engram.py"), "")
      writeFileSync(resolve(pkg, "package.json"), JSON.stringify({ version: "1.0.2" }))

      // Copy filter scripts into pkg so selfExtract places them in .opencode/scripts/
      copyFileSync(resolve(scriptsDir, "opencode-engram-clean"), resolve(pkg, "scripts", "opencode-engram-clean"))
      copyFileSync(resolve(scriptsDir, "opencode-engram-smudge"), resolve(pkg, "scripts", "opencode-engram-smudge"))

      const target = resolve(repo, ".opencode")
      mkdirSync(target, { recursive: true })
      writeFileSync(resolve(target, ".engram-version.jsonc"), JSON.stringify({ version: "0.9.0" }))

      // selfExtract writes AGENTS.md + installs git filter
      selfExtract(pkg, repo, "1.0.2")

      const agentsMd = resolve(repo, "AGENTS.md")
      expect(existsSync(agentsMd)).toBe(true)

      const beforeCommit = readFileSync(agentsMd, "utf-8")
      expect(beforeCommit).toContain("<!-- engram v1.0.2 -->")

      // git add + commit (--force because .git/info/exclude ignores AGENTS.md)
      execSync("git add --force AGENTS.md", { cwd: repo, stdio: "ignore" })
      execSync('git commit -m "add AGENTS.md"', { cwd: repo, stdio: "ignore" })

      // git show HEAD:AGENTS.md has NO block (clean filter stripped it)
      const committed = execSync("git show HEAD:AGENTS.md", { cwd: repo }).toString()
      expect(committed).not.toContain("<!-- engram v")
      expect(committed).not.toContain("<!-- /engram -->")

      // git checkout restores the block (smudge filter prepends it)
      execSync("git checkout -- AGENTS.md", { cwd: repo, stdio: "ignore" })
      const afterCheckout = readFileSync(agentsMd, "utf-8")
      expect(afterCheckout).toContain("<!-- engram v1.0.2 -->")
    } finally {
      rmSync(repo, { recursive: true })
    }
  })
})

// ---------------------------------------------------------------------------
// v1.2.0 review fixes. Each check below fails if its fix is reverted (§4.5).
// ---------------------------------------------------------------------------

describe("marker anchoring — clean and smudge must agree", () => {
  const scriptsDir = resolve(__dirname, "..", "scripts")
  const clean = (input: string) =>
    execSync(`python3 ${resolve(scriptsDir, "opencode-engram-clean")}`, { input }).toString()

  // The old locator was DOTALL with no `$`, so `.+?` crossed newlines and an
  // inline mention swallowed every line down to the real marker. Reverting
  // opencode-engram-clean wholesale fails this check.
  //
  // Honest note on what each half guards: `$`-anchoring and "last open marker
  // wins" are belt-and-braces here, and either alone saves THIS fixture — so
  // flipping just one of them leaves this check green. Only the fenced-example
  // case below separates them. Mutation-test the locator as a unit.
  it("keeps user prose that mentions the marker INLINE above the block", () => {
    const out = clean([
      "# How Engram marks its block",
      "<!-- engram v1.0.0 --> is the opening marker Engram uses.",
      "IMPORTANT USER RULE — never delete this line.",
      "",
      "<!-- engram v1.1.1 -->",
      "ENGRAM BLOCK",
      "<!-- /engram -->",
      "",
      "## Real user rules",
      "",
    ].join("\n"))

    expect(out).toContain("IMPORTANT USER RULE")
    expect(out).toContain("<!-- engram v1.0.0 --> is the opening marker")
    expect(out).not.toContain("ENGRAM BLOCK")
  })

  // Fix B — LAST open marker before the close, not the first. This fixture has
  // TWO fully-anchored open markers, so opens[0] and opens[-1] genuinely
  // diverge; with `opens[0]` the user's fenced example and the sentence under
  // it are both deleted. (An earlier version of this test used an inline
  // mention, which never matched the anchored regex at all — the two
  // definitions agreed and the check proved nothing.)
  it("keeps a user's fenced marker EXAMPLE — the last open marker wins", () => {
    const out = clean([
      "# Our docs",
      "The block Engram writes opens with this exact line:",
      "",
      "<!-- engram v1.0.0 -->",
      "",
      "SENTINEL_USER_EXPLANATION — this sentence sits between the two markers.",
      "",
      "<!-- engram v1.1.1 -->",
      "ENGRAM BLOCK",
      "<!-- /engram -->",
      "",
      "## Real user rules",
      "",
    ].join("\n"))

    expect(out).toContain("SENTINEL_USER_EXPLANATION")
    expect(out).toContain("<!-- engram v1.0.0 -->")
    expect(out).toContain("## Real user rules")
    expect(out).not.toContain("ENGRAM BLOCK")
  })

  it("still strips a normal block with nothing above it", () => {
    const out = clean("<!-- engram v1.1.1 -->\nBLOCK\n<!-- /engram -->\nuser\n")
    expect(out).toBe("user\n")
  })

  // Fix: smudge's "already present" test is line-anchored like clean's. With a
  // substring test it no-ops here, the block is never restored on checkout, and
  // Engram's instructions silently stop reaching the model.
  it("smudge restores the block when the user only MENTIONS the marker inline", () => {
    const tmp = mkdtempSync(resolve(tmpdir(), "engram-smudge-"))
    mkdirSync(resolve(tmp, ".opencode"), { recursive: true })
    writeFileSync(
      resolve(tmp, ".opencode", ".engram-smudge-template"),
      "<!-- engram v1.1.1 -->\nENGRAM RULES\n<!-- /engram -->\n",
    )

    const stored = "Our style guide covers the <!-- engram v --> marker inline.\n## rules\n"
    const out = execSync(`python3 ${resolve(scriptsDir, "opencode-engram-smudge")}`, {
      input: stored,
      cwd: tmp,
    }).toString()

    expect(out).toContain("ENGRAM RULES")
    expect(out).toContain("marker inline")
    rmSync(tmp, { recursive: true })
  })

  it("smudge still no-ops when a REAL block is already present", () => {
    const tmp = mkdtempSync(resolve(tmpdir(), "engram-smudge-"))
    mkdirSync(resolve(tmp, ".opencode"), { recursive: true })
    writeFileSync(
      resolve(tmp, ".opencode", ".engram-smudge-template"),
      "<!-- engram v1.1.1 -->\nENGRAM RULES\n<!-- /engram -->\n",
    )

    const stored = "<!-- engram v1.1.1 -->\nENGRAM RULES\n<!-- /engram -->\nuser\n"
    const out = execSync(`python3 ${resolve(scriptsDir, "opencode-engram-smudge")}`, {
      input: stored,
      cwd: tmp,
    }).toString()

    expect(out).toBe(stored)
    expect((out.match(/ENGRAM RULES/g) || []).length).toBe(1)
    rmSync(tmp, { recursive: true })
  })
})

describe("AGENTS.md exclude tracks CONTENT, not authorship", () => {
  let tmp: string
  let pkg: string

  beforeEach(() => {
    tmp = mkdtempSync(resolve(tmpdir(), "engram-test-"))
    writeFileSync(resolve(tmp, "opencode.jsonc"), "{}")
    mkdirSync(resolve(tmp, ".git", "info"), { recursive: true })
    writeFileSync(resolve(tmp, ".git", "config"), "[core]\n\trepositoryformatversion = 0\n")
    pkg = resolve(tmp, "pkg")
    for (const d of ["skills", "agents", "scripts"]) mkdirSync(resolve(pkg, d), { recursive: true })
    writeFileSync(resolve(pkg, "scripts", "engram.py"), "script")
    writeFileSync(resolve(pkg, "package.json"), JSON.stringify({ version: "1.0.2" }))
  })
  afterEach(() => rmSync(tmp, { recursive: true }))

  const excludeText = () => readFileSync(resolve(tmp, ".git", "info", "exclude"), "utf-8")

  it("excludes AGENTS.md while it holds only the Engram block", () => {
    const target = resolve(tmp, ".opencode")
    mkdirSync(target, { recursive: true })
    writeFileSync(resolve(target, ".engram-version.jsonc"), JSON.stringify({ version: "0.9.0" }))

    selfExtract(pkg, tmp, "1.0.2")
    expect(excludeText().split("\n").some((l) => l.trim() === "AGENTS.md")).toBe(true)
  })

  // The trap this fixes: .git/info/exclude is invisible from the working tree,
  // so an exclude that outlives its reason means `git status` stays silent and
  // the user's own rules are never committed.
  it("un-excludes AGENTS.md once the user adds rules below the block", () => {
    const target = resolve(tmp, ".opencode")
    mkdirSync(target, { recursive: true })
    writeFileSync(resolve(target, ".engram-version.jsonc"), JSON.stringify({ version: "0.9.0" }))
    selfExtract(pkg, tmp, "1.0.2")
    expect(excludeText().split("\n").some((l) => l.trim() === "AGENTS.md")).toBe(true)

    const agents = resolve(tmp, "AGENTS.md")
    writeFileSync(agents, readFileSync(agents, "utf-8") + "\n## TEAM RULE\n- always run make lint\n")

    const messages: string[] = []
    syncProjectState(target, (m: string) => messages.push(m))

    expect(excludeText().split("\n").some((l) => l.trim() === "AGENTS.md")).toBe(false)
    expect(messages.some((m) => m.includes("un-excluded"))).toBe(true)
    // .engram-* is unconditional — those files are always internal.
    expect(excludeText().split("\n").some((l) => l.trim() === ".engram-*")).toBe(true)
  })

  it("does not re-exclude on a later session once user content is there", () => {
    const target = resolve(tmp, ".opencode")
    mkdirSync(target, { recursive: true })
    writeFileSync(resolve(target, ".engram-version.jsonc"), JSON.stringify({ version: "0.9.0" }))
    selfExtract(pkg, tmp, "1.0.2")

    const agents = resolve(tmp, "AGENTS.md")
    writeFileSync(agents, readFileSync(agents, "utf-8") + "\n## TEAM RULE\n")
    syncProjectState(target, () => {})
    syncProjectState(target, () => {})

    expect(excludeText().split("\n").some((l) => l.trim() === "AGENTS.md")).toBe(false)
  })
})
