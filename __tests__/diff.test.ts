import { describe, it, expect } from "vitest"
import { diffLines } from "../.opencode/diff"

describe("diffLines", () => {
  it("returns null for identical texts", () => {
    expect(diffLines("same\ncontent", "same\ncontent")).toBeNull()
  })

  it("returns null for two empty strings", () => {
    expect(diffLines("", "")).toBeNull()
  })

  it("detects added lines", () => {
    const result = diffLines("a\nb", "a\nb\nc")
    expect(result).toContain("+c")
    expect(result).toContain("@@")
  })

  it("detects removed lines", () => {
    const result = diffLines("a\nb\nc", "a\nc")
    expect(result).toContain("-b")
    expect(result).toContain("@@")
  })

  it("detects modified lines", () => {
    const result = diffLines("a\nold\nc", "a\nnew\nc")
    expect(result).toContain("-old")
    expect(result).toContain("+new")
    expect(result).toContain("@@")
  })

  it("handles trailing newline differences consistently", () => {
    expect(diffLines("a\nb", "a\nb")).toBeNull()
    expect(diffLines("a\nb\n", "a\nb\n")).toBeNull()
  })

  it("normalizes CRLF to LF", () => {
    const result = diffLines("a\r\nold", "a\r\nnew")
    expect(result).toContain("-old")
    expect(result).toContain("+new")
  })

  it("includes context lines around diff region", () => {
    const text = Array.from({ length: 10 }, (_, i) => `line${i + 1}`).join("\n")
    const modified = Array.from({ length: 10 }, (_, i) => `line${i + 1}`).join("\n")
      .replace("line5", "CHANGED")
    const result = diffLines(text, modified)!
    expect(result).toContain("-line5")
    expect(result).toContain("+CHANGED")
    expect(result).toContain(" line4")
    expect(result).toContain(" line6")
  })

  it("trailing context is correct on insertions (different diff lengths)", () => {
    const result = diffLines("p\n2\ns1\ns2\ns3", "p\nX\nY\ns1\ns2\ns3")
    expect(result).not.toBeNull()
    expect(result).toContain("-2")
    expect(result).toContain("+X")
    expect(result).toContain("+Y")
    expect(result).toContain(" s1")
    expect(result).toContain(" s2")
    expect(result).toContain(" s3")
  })
})
