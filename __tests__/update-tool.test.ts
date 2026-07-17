import { describe, it, expect, beforeEach, afterEach } from "vitest"
import { tmpdir } from "node:os"
import { mkdtempSync, rmSync, writeFileSync, mkdirSync, existsSync, readFileSync } from "node:fs"
import { resolve } from "node:path"
import { engramUpdateTool } from "../.opencode/update-tool"

function createManifestDir(): string {
  const tmp = mkdtempSync(resolve(tmpdir(), "engram-tool-test-"))
  const t = resolve(tmp, ".opencode")
  mkdirSync(resolve(t, "skills"), { recursive: true })
  mkdirSync(resolve(t, "agents"), { recursive: true })
  writeFileSync(resolve(t, "skills", "learn.md"), "skill learn")
  writeFileSync(resolve(t, "skills", "review.md"), "skill review")
  writeFileSync(resolve(t, "agents", "assessor.md"), "agent assessor")
  writeFileSync(resolve(t, ".engram-version.jsonc"), JSON.stringify({ version: "0.9.0" }))
  writeFileSync(resolve(t, ".engram-update.jsonc"), JSON.stringify({
    from: "0.9.0",
    to: "1.0.2",
    state: "pending",
    applied: [],
    remaining: ["skills", "agents"],
    categories: {
      skills: {
        added: [],
        skipped: ["skills/learn.md", "skills/review.md"],
      },
      agents: {
        added: [],
        skipped: ["agents/assessor.md"],
      },
      scripts: { added: [], skipped: [] },
      command: { added: [], skipped: [] },
    },
  }))
  writeFileSync(resolve(t, ".engram-update.diff"), "--- a\n+++ b\n@@ -1 +1 @@\n-old\n+new\n")
  return tmp
}

function t(tmp: string): string {
  return resolve(tmp, ".opencode")
}

describe("engramUpdateTool", () => {
  let tmp: string

  beforeEach(() => { tmp = createManifestDir() })
  afterEach(() => rmSync(tmp, { recursive: true }))

  async function call(mode: string, decisions?: { file: string; action: string }[]) {
    return engramUpdateTool.execute(
      { target: t(tmp), mode: mode as any, decisions: decisions as any },
      { directory: tmp } as any,
    )
  }

  describe("auto mode", () => {
    it("deletes all skipped files and cleans up manifest and version", async () => {
      const result = await call("auto")
      expect(result).toContain("Auto update applied")
      expect(result).toContain("3 files deleted")
      expect(existsSync(resolve(t(tmp), "skills", "learn.md"))).toBe(false)
      expect(existsSync(resolve(t(tmp), "skills", "review.md"))).toBe(false)
      expect(existsSync(resolve(t(tmp), "agents", "assessor.md"))).toBe(false)
      expect(existsSync(resolve(t(tmp), ".engram-update.jsonc"))).toBe(false)
      expect(existsSync(resolve(t(tmp), ".engram-version.jsonc"))).toBe(false)
      expect(existsSync(resolve(t(tmp), ".engram-update.diff"))).toBe(false)
    })

    it("rejects path traversal paths silently", async () => {
      const m = JSON.parse(readFileSync(resolve(t(tmp), ".engram-update.jsonc"), "utf-8"))
      m.categories.skills.skipped.push("../../etc/passwd")
      writeFileSync(resolve(t(tmp), ".engram-update.jsonc"), JSON.stringify(m))
      const result = await call("auto")
      expect(result).toContain("3 files deleted")
      expect(result).not.toContain("4 files deleted")
    })
  })

  describe("per_file mode", () => {
    it("deletes file when action is delete", async () => {
      const result = await call("per_file", [
        { file: "skills/learn.md", action: "delete" },
      ])
      expect(result).toContain("DELETED skills/learn.md")
      expect(existsSync(resolve(t(tmp), "skills", "learn.md"))).toBe(false)
      expect(existsSync(resolve(t(tmp), "skills", "review.md"))).toBe(true)
      expect(existsSync(resolve(t(tmp), "agents", "assessor.md"))).toBe(true)
    })

    it("keeps file when action is keep", async () => {
      const result = await call("per_file", [
        { file: "skills/learn.md", action: "keep" },
      ])
      expect(result).toContain("KEPT skills/learn.md")
      expect(existsSync(resolve(t(tmp), "skills", "learn.md"))).toBe(true)
    })

    it("rejects files not in manifest skipped list", async () => {
      const result = await call("per_file", [
        { file: "skills/nonexistent.md", action: "delete" },
      ])
      expect(result).toContain("not in manifest skipped list")
    })

    it("rejects files from unknown category", async () => {
      const result = await call("per_file", [
        { file: "unknown/file.md", action: "delete" },
      ])
      expect(result).toContain("not in manifest skipped list")
    })

    it("rejects path traversal paths", async () => {
      const result = await call("per_file", [
        { file: "../../etc/passwd", action: "delete" },
      ])
      expect(result).toContain("path outside target")
    })

    it("returns error when decisions array is empty", async () => {
      const result = await call("per_file", [])
      expect(result).toContain("decisions array required")
    })

    it("returns error when decisions is undefined", async () => {
      const result = await call("per_file")
      expect(result).toContain("decisions array required")
    })

    it("saves checkpoint when some files remain", async () => {
      const result = await call("per_file", [
        { file: "skills/learn.md", action: "delete" },
      ])
      expect(result).toContain("Checkpoint saved")
      expect(result).toContain("Remaining:")
      expect(existsSync(resolve(t(tmp), ".engram-update.jsonc"))).toBe(true)
      expect(existsSync(resolve(t(tmp), ".engram-version.jsonc"))).toBe(true)

      const manifest = JSON.parse(readFileSync(resolve(t(tmp), ".engram-update.jsonc"), "utf-8"))
      expect(manifest.categories.skills.skipped).toEqual(["skills/review.md"])
      expect(manifest.remaining).toEqual(["skills", "agents"])
    })

    it("deletes manifest and version when all files processed", async () => {
      const result = await call("per_file", [
        { file: "skills/learn.md", action: "delete" },
        { file: "skills/review.md", action: "delete" },
        { file: "agents/assessor.md", action: "delete" },
      ])
      expect(result).toContain("All files processed")
      expect(result).toContain("DELETED skills/learn.md")
      expect(result).toContain("DELETED skills/review.md")
      expect(result).toContain("DELETED agents/assessor.md")
      expect(existsSync(resolve(t(tmp), ".engram-update.jsonc"))).toBe(false)
      expect(existsSync(resolve(t(tmp), ".engram-version.jsonc"))).toBe(false)
      expect(existsSync(resolve(t(tmp), ".engram-update.diff"))).toBe(false)
    })

    it("handles already-deleted files gracefully", async () => {
      rmSync(resolve(t(tmp), "skills", "learn.md"))
      const result = await call("per_file", [
        { file: "skills/learn.md", action: "delete" },
      ])
      expect(result).toContain("already deleted")
    })
  })

  describe("keep_as_is mode", () => {
    it("deletes manifest and version files", async () => {
      const result = await call("keep_as_is")
      expect(result).toContain("skipped permanently")
      expect(existsSync(resolve(t(tmp), ".engram-update.jsonc"))).toBe(false)
      expect(existsSync(resolve(t(tmp), ".engram-version.jsonc"))).toBe(false)
    })

    it("does not touch user skill files", async () => {
      await call("keep_as_is")
      expect(existsSync(resolve(t(tmp), "skills", "learn.md"))).toBe(true)
      expect(existsSync(resolve(t(tmp), "skills", "review.md"))).toBe(true)
      expect(existsSync(resolve(t(tmp), "agents", "assessor.md"))).toBe(true)
    })
  })

  describe("skip mode", () => {
    it("returns state without modifying files or manifest", async () => {
      const result = await call("skip")
      expect(result).toContain("deferred")
      expect(result).toContain("pending")
      expect(result).toContain("2 categories remaining")
      expect(existsSync(resolve(t(tmp), ".engram-update.jsonc"))).toBe(true)
      expect(existsSync(resolve(t(tmp), ".engram-version.jsonc"))).toBe(true)
      expect(existsSync(resolve(t(tmp), "skills", "learn.md"))).toBe(true)
    })
  })

  describe("checkpoint mode", () => {
    it("sets manifest state to in_progress", async () => {
      const result = await call("checkpoint")
      expect(result).toContain("in_progress")
      expect(result).toContain("2 categories pending")
      const manifest = JSON.parse(readFileSync(resolve(t(tmp), ".engram-update.jsonc"), "utf-8"))
      expect(manifest.state).toBe("in_progress")
    })
  })

  describe("cleanup mode", () => {
    it("deletes manifest and version files", async () => {
      const result = await call("cleanup")
      expect(result).toContain("State cleaned")
      expect(existsSync(resolve(t(tmp), ".engram-update.jsonc"))).toBe(false)
      expect(existsSync(resolve(t(tmp), ".engram-version.jsonc"))).toBe(false)
      expect(existsSync(resolve(t(tmp), ".engram-update.diff"))).toBe(false)
    })

    it("does not touch user skill files", async () => {
      await call("cleanup")
      expect(existsSync(resolve(t(tmp), "skills", "learn.md"))).toBe(true)
      expect(existsSync(resolve(t(tmp), "skills", "review.md"))).toBe(true)
      expect(existsSync(resolve(t(tmp), "agents", "assessor.md"))).toBe(true)
      expect(existsSync(resolve(t(tmp), ".engram-update.diff"))).toBe(false)
    })
  })

  describe("error handling", () => {
    it("returns error when no manifest exists", async () => {
      rmSync(resolve(t(tmp), ".engram-update.jsonc"))
      const result = await call("auto")
      expect(result).toContain("No pending update")
    })

    it("returns error for corrupt manifest", async () => {
      writeFileSync(resolve(t(tmp), ".engram-update.jsonc"), "not-valid-json}{")
      const result = await call("auto")
      expect(result).toContain("Corrupt")
    })
  })
})
