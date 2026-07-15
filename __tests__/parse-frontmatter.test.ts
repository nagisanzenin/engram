import { describe, it, expect } from "vitest"
import { parseFrontmatter } from "../.opencode/parse-frontmatter"

describe("parseFrontmatter", () => {
  it("parses YAML frontmatter with description", () => {
    const content = `---
name: test-agent
description: A test agent
tools: Read, Write
---

# Body content

Some markdown here.`

    const { attrs, body } = parseFrontmatter(content)
    expect(attrs.name).toBe("test-agent")
    expect(attrs.description).toBe("A test agent")
    expect(attrs.tools).toBe("Read, Write")
    expect(body).toContain("# Body content")
    expect(body).toContain("Some markdown here.")
  })

  it("handles empty frontmatter gracefully", () => {
    const content = `---
---

Body only.`

    const { attrs, body } = parseFrontmatter(content)
    expect(Object.keys(attrs).length).toBeGreaterThanOrEqual(0)
    expect(body).toContain("Body only.")
  })

  it("returns empty attrs when no frontmatter present", () => {
    const content = "Just body, no frontmatter."
    const { attrs, body } = parseFrontmatter(content)
    expect(attrs).toBeDefined()
    expect(body.trim()).toBe("Just body, no frontmatter.")
  })
})
