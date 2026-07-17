/**
 * Engram — Unified Diff Generator
 * ================================
 *
 * Generates unified diff output (.engram-update.diff) so the model and user
 * can inspect changes between versions before deciding to overwrite.
 *
 * Algorithm:
 *   1. Normalize line endings, split lines
 *   2. Find common prefix (matching from start) and suffix (matching from end)
 *   3. The remaining middle is the diff region — all old lines shown as -,
 *      all new lines shown as +
 *   4. Format as unified diff with hunk header and context lines
 *
 * Files with identical content produce no diff entry.
 */

import { existsSync, readFileSync, writeFileSync } from "node:fs"
import { resolve } from "node:path"

function normalize(text: string): string {
  return text.replace(/\r\n/g, "\n").replace(/\r/g, "\n")
}

function splitLines(text: string): string[] {
  const lines = normalize(text).split("\n")
  if (lines.length > 0 && lines[lines.length - 1] === "") lines.pop()
  return lines
}

/**
 * Produces a unified diff string between two texts, or null if identical.
 * Normalizes CRLF → LF and strips trailing newlines before comparison,
 * so files differing only in line endings produce no diff entry.
 *
 * Edge case: contentsMatch (used by diffCategory) compares byte-level
 * buffers via Buffer.equals, so CRLF-only differences ARE flagged as
 * "modified" and land in skipped[]. diffLines normalizes those differences
 * away and returns null. The result is a manifest exists but
 * .engram-update.diff may not contain an entry for that file.
 * If ALL skipped files differ only in line endings, no .diff is written
 * at all. The template guard in STEP 4e handles this gracefully:
 * "If Read tool fails, say no diff is available and return to STEP 4."
 *
 * Format: @@ hunk header, context lines ( ), deletions (-), additions (+).
 */
export function diffLines(a: string, b: string): string | null {
  const linesA = splitLines(a)
  const linesB = splitLines(b)

  if (linesA.length === linesB.length && linesA.every((l, i) => l === linesB[i]))
    return null

  let prefix = 0
  while (prefix < linesA.length && prefix < linesB.length && linesA[prefix] === linesB[prefix])
    prefix++

  let suffixA = linesA.length - 1
  let suffixB = linesB.length - 1
  while (suffixA >= prefix && suffixB >= prefix && linesA[suffixA] === linesB[suffixB]) {
    suffixA--
    suffixB--
  }

  if (prefix > suffixA && prefix > suffixB) return null

  const ctxBefore = Math.min(3, prefix)
  const ctxAfterA = Math.min(3, linesA.length - 1 - suffixA)
  const ctxAfterB = Math.min(3, linesB.length - 1 - suffixB)
  const ctxAfter = Math.max(ctxAfterA, ctxAfterB)

  const hunkOldStart = prefix - ctxBefore + 1
  const hunkNewStart = prefix - ctxBefore + 1
  const hunkOldLen = (suffixA - prefix + 1) + ctxBefore + ctxAfter
  const hunkNewLen = (suffixB - prefix + 1) + ctxBefore + ctxAfter

  const out: string[] = []
  out.push(`@@ -${hunkOldStart},${hunkOldLen} +${hunkNewStart},${hunkNewLen} @@`)

  for (let i = prefix - ctxBefore; i < prefix; i++)
    out.push(` ${linesA[i]}`)

  for (let i = prefix; i <= suffixA; i++)
    out.push(`-${linesA[i]}`)
  for (let i = prefix; i <= suffixB; i++)
    out.push(`+${linesB[i]}`)

  for (let k = 1; k <= ctxAfter; k++) {
    const idx = suffixB + k
    if (idx < linesB.length) out.push(` ${linesB[idx]}`)
  }

  return out.join("\n")
}

/**
 * Generates .engram-update.diff comparing source (npm cache) vs destination
 * (.opencode/) for every file in the skipped arrays. Skips binaries and
 * unreadable files silently.
 *
 * @returns Number of files with differences found (0 = no diff written).
 */
export function writeUpdateDiff(
  packageRoot: string,
  target: string,
  categories: Record<string, { added: string[]; skipped: string[] }> | undefined,
  to: string,
): number {
  if (!categories) return 0

  const output: string[] = []
  let diffCount = 0

  for (const [, diffEntry] of Object.entries(categories)) {
    for (const file of diffEntry.skipped) {
      const srcPath = resolve(packageRoot, file)
      const destPath = resolve(target, file)
      if (!existsSync(srcPath) || !existsSync(destPath)) continue
      try {
        const a = readFileSync(srcPath, "utf-8")
        const b = readFileSync(destPath, "utf-8")
        const diff = diffLines(b, a)
        if (diff) {
          output.push(`--- ${file} (preserved)`)
          output.push(`+++ ${file} (v${to})`)
          output.push(diff)
          diffCount++
        }
      } catch {}
    }
  }

  if (diffCount > 0) {
    writeFileSync(resolve(target, ".engram-update.diff"), output.join("\n") + "\n")
  }

  return diffCount
}
