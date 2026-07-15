/**
 * Parses YAML frontmatter from a markdown string.
 * Returns { attrs: { key: value, … }, body: string } — the remaining markdown body.
 * Falls back to { attrs: {}, body: text } for files without frontmatter.
 */
export function parseFrontmatter(text: string): { attrs: Record<string, string>; body: string } {
  const match = text.match(/^---\n([\s\S]*?)\n---\n([\s\S]*)$/)
  if (!match) return { attrs: {}, body: text }
  const attrs: Record<string, string> = {}
  for (const line of match[1].split("\n")) {
    const kv = line.match(/^(\w+):\s*(.*)$/)
    if (kv) attrs[kv[1]] = kv[2].trim()
  }
  return { attrs, body: match[2].trim() }
}
