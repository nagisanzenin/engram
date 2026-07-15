/**
 * Engram — Deterministic Update Tool
 * ===================================
 *
 * Custom OpenCode tool (registered via @opencode-ai/plugin's `tool()` API)
 * that handles ALL destructive operations for the update system — file deletion,
 * manifest checkpoint, and cleanup — in deterministic TypeScript with zero LLM
 * interpolation risk.
 *
 * The tool is registered statically in the server return but conditionally
 * enabled/disabled via cfg.tools["engram_update"] in the config hook, using
 * the same existsSync gate as the /engram-update pseudo-command.
 *
 * When the manifest is resolved and deleted, cfg.tools["engram_update"] = false
 * hides the tool from the LLM on the next session.
 *
 * --- Modes ---
 *
 * auto        — Deletes ALL files in every category's skipped array, then deletes
 *               the manifest + version guard. One-shot, no checkpoint needed.
 *               Called from STEP 4a (Auto mode) in the template.
 *
 * per_file    — Receives a decisions array (per-file delete/keep choices collected
 *               by the model via question tool). Validates every file path against
 *               manifest.categories.*.skipped — paths not in the manifest are
 *               rejected. Deletes or keeps, removes from skipped, and saves
 *               checkpoint (saveManifest). When all categories are empty,
 *               deletes manifest + version guard.
 *               Called from STEP 4b (Manual mode) in the template.
 *
 * keep_as_is  — Deletes manifest + version guard without touching any user files.
 *               User edits preserved. Next start = fresh extract via selfExtract.
 *               Called from STEP 4d (Keep as-is) and STEP 5 cleanup.
 *
 * skip        — Read-only: returns current state without modifying anything.
 *               Called from STEP 4c and STEP 5 (to show status before resume).
 *
 * checkpoint  — Sets manifest.state = "in_progress" and persists.
 *               Called once at the start of STEP 4b (Manual mode).
 *
 * --- Validation ---
 *
 * Every file path in per_file decisions is checked:
 *   1. Category extracted from path prefix (e.g., "skills/learn.md" → "skills")
 *   2. Category must exist in manifest.categories
 *   3. File must be present in the category's skipped[] array
 *   → Rejected paths are reported but never cause a crash.
 *
 * --- Lifecycle ---
 *
 * Manifest exists (version bump detected by selfExtract)
 *   → config hook: cfg.command["engram-update"] registered + cfg.tools["engram_update"] = true
 *   → /engram-update executed by user
 *   → model calls this tool via template instructions
 *   → tool processes files, deletes manifest + version guard
 *   → next reload:
 *       existsSync → false → pseudo-command gone
 *       cfg.tools["engram_update"] = false → tool hidden
 *       .engram-version.jsonc deleted → selfExtract treats as fresh install
 *       copyMissing with existsSync guard → user edits preserved
 *
 * All operations are synchronous — if the process dies mid-execution (crash, power
 * loss), the manifest persists and STEP 5 resumes. In auto mode, files already
 * deleted are simply not re-deleted (existsSync check is idempotent).
 */

import { tool } from "@opencode-ai/plugin"
import { existsSync, unlinkSync, readFileSync, writeFileSync } from "node:fs"
import { resolve } from "node:path"
import { readManifest, saveManifest } from "./update.js"

export const engramUpdateTool = tool({
  description: "Apply Engram plugin updates — delete preserved files and update the manifest. Only call when the /engram-update command instructs you.",
  args: {
    target: tool.schema.string().describe("Target .opencode/ directory"),
    mode: tool.schema.enum(["auto", "per_file", "keep_as_is", "skip", "checkpoint"]).describe("Update mode"),
    decisions: tool.schema.array(tool.schema.object({
      file: tool.schema.string().describe("Relative file path from manifest categories"),
      action: tool.schema.enum(["delete", "keep"]).describe("What to do with this file"),
    })).optional().describe("Per-file decisions (required for per_file mode)"),
  },
  async execute(args) {
    const manifestPath = resolve(args.target, ".engram-update.jsonc")
    const versionPath = resolve(args.target, ".engram-version.jsonc")

    let manifest = readManifest(args.target)
    if (!manifest) {
      if (existsSync(manifestPath)) {
        return "[engram] Corrupt manifest: run /engram-update to clean up."
      }
      return "[engram] No pending update. Manifest not found."
    }

    switch (args.mode) {
      case "auto": {
        let deleted = 0
        for (const diff of Object.values(manifest.categories)) {
          for (const file of diff.skipped) {
            const filePath = resolve(args.target, file)
            if (existsSync(filePath)) {
              unlinkSync(filePath)
              deleted++
            }
          }
        }
        if (existsSync(versionPath)) unlinkSync(versionPath)
        unlinkSync(manifestPath)
        return `[engram] Auto update applied. ${deleted} files deleted. Restart OpenCode or reload plugins.`
      }

      case "per_file": {
        if (!args.decisions || !args.decisions.length) {
          return "[engram] decisions array required for per_file mode."
        }

        const results: string[] = []
        for (const d of args.decisions) {
          const category = d.file.split("/")[0]
          const cat = manifest.categories[category]
          if (!cat || !cat.skipped.includes(d.file)) {
            results.push(`SKIP ${d.file}: not in manifest skipped list`)
            continue
          }

          if (d.action === "delete") {
            const filePath = resolve(args.target, d.file)
            if (existsSync(filePath)) {
              unlinkSync(filePath)
              results.push(`DELETED ${d.file}`)
            } else {
              results.push(`SKIP ${d.file}: already deleted`)
            }
          } else {
            results.push(`KEPT ${d.file}`)
          }

          cat.skipped = cat.skipped.filter((f: string) => f !== d.file)
        }

        for (const [name, diff] of Object.entries(manifest.categories)) {
          if (diff.skipped.length === 0) {
            const idx = manifest.remaining.indexOf(name)
            if (idx > -1) {
              manifest.remaining.splice(idx, 1)
              if (!manifest.applied.includes(name)) {
                manifest.applied.push(name)
              }
            }
          }
        }

        if (manifest.remaining.length === 0) {
          if (existsSync(versionPath)) unlinkSync(versionPath)
          unlinkSync(manifestPath)
          return `[engram] All files processed.\n${results.join("\n")}\n\nRestart OpenCode or reload plugins.`
        }

        saveManifest(args.target, manifest)
        return `[engram] Checkpoint saved.\n${results.join("\n")}\n\nRemaining: ${manifest.remaining.join(", ")}. Continue with /engram-update.`
      }

      case "keep_as_is": {
        if (existsSync(versionPath)) unlinkSync(versionPath)
        if (existsSync(manifestPath)) unlinkSync(manifestPath)
        return "[engram] Update skipped permanently. Restart for fresh extract."
      }

      case "skip": {
        return `[engram] Update deferred. State: ${manifest.state}. ${manifest.remaining.length} categories remaining.`
      }

      case "checkpoint": {
        manifest.state = "in_progress"
        writeFileSync(manifestPath, JSON.stringify(manifest, null, 2))
        return `[engram] State set to in_progress. ${manifest.remaining.length} categories pending.`
      }

      default:
        return "[engram] Unknown mode."
    }
  },
})
