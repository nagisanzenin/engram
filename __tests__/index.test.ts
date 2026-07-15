import { describe, it, expect, beforeEach, afterEach } from "vitest"
import { tmpdir } from "node:os"
import { mkdtempSync, rmSync, writeFileSync, mkdirSync } from "node:fs"
import { resolve } from "node:path"
import { server, default as pluginDefault } from "../.opencode/index"

const mk$ = () => (() => ({ nothrow: () => ({ quiet: () => Promise.resolve({ stdout: { toString: () => "" } }) }) })) as any
const mkClient = () => ({ tui: { showToast: async () => ({ catch: () => {} }) } }) as any

describe("server plugin", () => {
  it("plugin default has id 'engram'", () => {
    expect(pluginDefault.id).toBe("engram")
    expect(typeof pluginDefault.server).toBe("function")
  })

  it("returns a config hook", async () => {
    const tmp = mkdtempSync(resolve(tmpdir(), "engram-test-"))
    try {
      writeFileSync(resolve(tmp, "opencode.jsonc"), "{}")
      const plugin = await server({ $: mk$(), client: mkClient(), directory: tmp } as any)
      expect(typeof plugin.config).toBe("function")
    } finally {
      rmSync(tmp, { recursive: true })
    }
  })
})

describe("pseudo-command registration", () => {
  let tmp: string

  beforeEach(() => {
    tmp = mkdtempSync(resolve(tmpdir(), "engram-test-"))
    writeFileSync(resolve(tmp, "opencode.jsonc"), "{}")
  })
  afterEach(() => rmSync(tmp, { recursive: true }))

  async function getPlugin(dir: string) {
    return server({ $: mk$(), client: mkClient(), directory: dir } as any)
  }

  it("registers cfg.command['engram-update'] when manifest exists", async () => {
    const target = resolve(tmp, ".opencode")
    mkdirSync(target, { recursive: true })
    writeFileSync(resolve(target, ".engram-update.jsonc"), JSON.stringify({ state: "pending" }))

    const plugin = await getPlugin(tmp)
    const cfg: any = {}
    await plugin.config!(cfg)

    expect(cfg.command).toBeDefined()
    expect(cfg.command["engram-update"]).toBeDefined()
    expect(typeof cfg.command["engram-update"].description).toBe("string")
    expect(typeof cfg.command["engram-update"].template).toBe("string")
  })

  it("does NOT register pseudo-command when no manifest", async () => {
    const plugin = await getPlugin(tmp)
    const cfg: any = {}
    await plugin.config!(cfg)

    expect(cfg.command).toBeUndefined()
  })

  it("registers pseudo-command even with corrupt manifest (existsSync only checks presence)", async () => {
    const target = resolve(tmp, ".opencode")
    mkdirSync(target, { recursive: true })
    writeFileSync(resolve(target, ".engram-update.jsonc"), "not-valid-json}{")

    const plugin = await getPlugin(tmp)
    const cfg: any = {}
    await plugin.config!(cfg)

    expect(cfg.command).toBeDefined()
    expect(cfg.command["engram-update"]).toBeDefined()
  })

  it("registers instructions.md path when file exists", async () => {
    const target = resolve(tmp, ".opencode")
    mkdirSync(target, { recursive: true })
    writeFileSync(resolve(target, "instructions.md"), "test content")

    const plugin = await getPlugin(tmp)
    const cfg: any = {}
    await plugin.config!(cfg)

    expect(cfg.instructions).toBeDefined()
    expect(cfg.instructions).toContain(resolve(target, "instructions.md"))
  })

  it("does NOT set cfg.instructions when instructions.md is absent", async () => {
    const plugin = await getPlugin(tmp)
    const cfg: any = {}
    await plugin.config!(cfg)

    expect(cfg.instructions).toBeUndefined()
  })
})
