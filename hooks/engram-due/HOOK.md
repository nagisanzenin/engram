---
name: engram-due
description: "Surface due Engram reviews when a session starts — one ambient line, or nothing."
metadata:
  {
    "openclaw":
      {
        "emoji": "🧠",
        "events": ["command:new", "command:reset"],
        "requires": { "bins": ["python3"] },
      },
  }
---

# engram-due

The OpenClaw port of Engram's re-anchor hook. On `/new` and `/reset` it runs
`engram.py session-start` and delivers whatever that prints as a chat reply.

`session-start` prints **at most two lines, and usually nothing** — it stays
silent unless reviews are actually due or ungraded work is stashed. That
silence is the contract (Constitution art. 8: ambient, never nagging), so the
handler never manufactures output of its own.

`command:new` and `command:reset` are the only two internal hook events whose
`event.messages` are routed back to the originating conversation, which is why
the nudge binds to those rather than `session:*` or `gateway:startup`.

## Failure behavior

Every failure path degrades to silence: no `python3`, no engine on disk, a
non-zero exit, a timeout, or unparseable output all return without pushing a
message. A learning tool that breaks someone's chat session has already lost
more than the nudge was worth.

## Enabling

Installing the plugin registers the hook — `openclaw hooks info engram-due`
reports it ready and *"Managed by plugin"*, so `openclaw hooks enable` neither
applies nor works here. But the Gateway **skips internal hook discovery
entirely** until something opts in, and a plugin-provided hook pack does not
count. Without the flag below the hook is listed, ready, and never runs:

```bash
openclaw config set hooks.internal.enabled true
openclaw gateway restart
```

Verify with `openclaw --log-level debug gateway run`; the loader prints
`Registered hook: engram-due -> command:new, command:reset`.

## Discovery note

OpenClaw reads engram as a **Codex bundle** (`.codex-plugin/plugin.json` is
matched before any other marker, including `openclaw.plugin.json`). For Codex
bundles it treats the manifest's `hooks` value as a list of *directories* to
scan for hook packs. Engram therefore declares no `hooks` key at all: Codex
auto-discovers `./hooks/hooks.json` by convention, and OpenClaw falls back to
scanning `./hooks/`, which is where this pack lives. Re-adding an explicit
`"hooks": "./hooks/hooks.json"` would point OpenClaw's scanner at a *file* and
silently break this hook.
