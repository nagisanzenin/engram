import { describe, it, expect, beforeEach, afterEach } from "vitest"
import { tmpdir } from "node:os"
import { mkdtempSync, rmSync, writeFileSync, mkdirSync } from "node:fs"
import { resolve } from "node:path"
import { createSessionStartHooks } from "../hooks/session-start"

const mk$ = (nudge: string) => () => ({
  nothrow: () => ({
    quiet: () => Promise.resolve({ stdout: { toString: () => nudge } }),
  }),
})

const mkClient = () => {
  const toastCalls: any[] = []
  return {
    tui: {
      showToast: (opts: any) => {
        toastCalls.push(opts)
        return Promise.resolve({ catch: () => {} })
      },
    },
    getToastCalls: () => toastCalls,
  }
}

describe("session-start notification hooks", () => {
  let tmp: string
  let originalCwd: string

  beforeEach(() => {
    tmp = mkdtempSync(resolve(tmpdir(), "engram-test-"))
    writeFileSync(resolve(tmp, "opencode.jsonc"), "{}")
    originalCwd = process.cwd()
    process.chdir(tmp)
  })
  afterEach(() => {
    process.chdir(originalCwd)
    rmSync(tmp, { recursive: true })
  })

  it("system.transform injects nudge from engram.py", async () => {
    const hooks = createSessionStartHooks(mk$("Review due!"), "/fake/root", mkClient())
    const output = { system: [] as string[] }
    await hooks["experimental.chat.system.transform"]({}, output)

    expect(output.system.some((s) => s.includes("Review due!"))).toBe(true)
  })

  it("system.transform injects update summary when manifest pending", async () => {
    const target = resolve(tmp, ".opencode")
    mkdirSync(target, { recursive: true })
    writeFileSync(resolve(target, ".engram-update.jsonc"), JSON.stringify({
      from: "0.9.0",
      to: "1.0.2",
      state: "pending",
      categories: {},
    }))

    const hooks = createSessionStartHooks(mk$(""), "/fake/root", mkClient())
    const output = { system: [] as string[] }
    await hooks["experimental.chat.system.transform"]({}, output)

    expect(output.system.some((s) => s.includes("Updates Engram Available"))).toBe(true)
  })

  it("system.transform injects in_progress message when manifest in_progress", async () => {
    const target = resolve(tmp, ".opencode")
    mkdirSync(target, { recursive: true })
    writeFileSync(resolve(target, ".engram-update.jsonc"), JSON.stringify({
      state: "in_progress",
    }))

    const hooks = createSessionStartHooks(mk$(""), "/fake/root", mkClient())
    const output = { system: [] as string[] }
    await hooks["experimental.chat.system.transform"]({}, output)

    expect(output.system.some((s) => s.includes("partially applied"))).toBe(true)
  })

  it("system.transform is silent when no manifest exists", async () => {
    const hooks = createSessionStartHooks(mk$(""), "/fake/root", mkClient())
    const output = { system: [] as string[] }
    await hooks["experimental.chat.system.transform"]({}, output)

    expect(output.system.some((s) => s.includes("Updates Engram Available"))).toBe(false)
  })

  it("event(session.idle) shows toast when manifest pending", async () => {
    const target = resolve(tmp, ".opencode")
    mkdirSync(target, { recursive: true })
    writeFileSync(resolve(target, ".engram-update.jsonc"), JSON.stringify({
      from: "0.9.0",
      to: "1.0.2",
      state: "pending",
      categories: {},
    }))

    const client = mkClient()
    const hooks = createSessionStartHooks(mk$(""), "/fake/root", client as any)
    await hooks.event({ event: { type: "session.idle" } })

    expect(client.getToastCalls().length).toBe(1)
    expect(client.getToastCalls()[0].body.title).toBe("Engram")
  })

  it("event(session.idle) does NOT show toast when no manifest", async () => {
    const client = mkClient()
    const hooks = createSessionStartHooks(mk$(""), "/fake/root", client as any)
    await hooks.event({ event: { type: "session.idle" } })

    expect(client.getToastCalls().length).toBe(0)
  })

  it("system.transform only fires once (firstTransform guard)", async () => {
    const hooks = createSessionStartHooks(mk$("Review due!"), "/fake/root", mkClient())
    const output1 = { system: [] as string[] }
    const output2 = { system: [] as string[] }

    await hooks["experimental.chat.system.transform"]({}, output1)
    await hooks["experimental.chat.system.transform"]({}, output2)

    expect(output1.system.some((s) => s.includes("Review due!"))).toBe(true)
    expect(output2.system).toEqual([])
  })
})
