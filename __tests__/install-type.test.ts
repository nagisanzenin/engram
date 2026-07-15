import { describe, it, expect } from "vitest"
import { detectInstallType } from "../.opencode/install-type"

describe("detectInstallType", () => {
  it("detects npm when path contains node_modules", () => {
    const result = detectInstallType("/home/user/.cache/opencode/node_modules/opencode-engram-learning")
    expect(result.type).toBe("npm")
    expect(result.isNpm).toBe(true)
    expect(result.isLocal).toBe(false)
  })

  it("detects local when path does not contain node_modules", () => {
    const result = detectInstallType("/home/user/projects/engram")
    expect(result.type).toBe("local")
    expect(result.isNpm).toBe(false)
    expect(result.isLocal).toBe(true)
  })

  it("returns correct root", () => {
    const root = "/some/path"
    const result = detectInstallType(root)
    expect(result.root).toBe(root)
  })
})
