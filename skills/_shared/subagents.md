# Spawning Engram's agents, per platform

Engram delegates three jobs to **separate agents**, and the separation is not an
implementation detail — it is the thing that makes the receipts worth anything:

| Agent | Job | Why it must be separate |
|---|---|---|
| `engram-curriculum-architect` | decompose a topic into a first-principles DAG | fresh context; the tutoring dialogue would bias the map toward what was easy to teach |
| `engram-assessor` | grade productions blind | **load-bearing.** A grader that has watched the lesson grades the lesson, not the recall. Every mastery claim in Engram rests on this |
| `engram-artifact-smith` | build an interactive explorable | long, tool-heavy work that shouldn't block the beats |

On Claude Code, Codex, OpenCode, and Antigravity these are registered agents and
"spawn X" is literal. **OpenClaw registers none of them** — it reads Engram as a
Codex bundle, and bundles map skills only; `agents/` is not a mapped capability
in any bundle format. So on OpenClaw you construct the same isolation yourself.

## The OpenClaw shape

`sessions_spawn` starts a background child run. Its default `context: "isolated"`
creates **a clean child transcript** — the child sees the task text and nothing
else of your conversation. That is exactly the assessor's blindness requirement,
so the default is what you want; never pass `context: "fork"` for an Engram
agent. Forking hands the child the tutoring dialogue and quietly destroys the
one property the receipt is claiming.

```
sessions_spawn({
  context: "isolated",
  task: "Read <ENGRAM_ROOT>/agents/engram-assessor.md and follow it exactly as your
         operating instructions. Grade the items in <the file you wrote with `stash list > …`>.
         Return only the receipt JSON it specifies — no commentary."
})
```

Then call `sessions_yield`. `sessions_spawn` is **non-blocking**: it returns a run
id immediately, and the child's result arrives as the next model-visible message
after you yield. Do not poll `subagents list` in a loop waiting for it.

Resolve `<ENGRAM_ROOT>` as the directory holding `scripts/engram.py` — on
OpenClaw that is `${OPENCLAW_STATE_DIR:-$HOME/.openclaw}/extensions/engram`. The
`agents/*.md` files ship inside the installed plugin, so pointing the child at
the file keeps one definition of each agent across every platform. Never paste a
copy of the assessor's rules into the task text: two copies drift, and the one
that drifts is the one grading.

## Rules that do not bend

- **Items go by file path, never inline.** Learner productions in a task string
  are the same command-injection hole as learner text on a shell command line,
  and the task string is also a prompt-injection surface. Write the JSON, pass
  the path.
- **One child per independent judgment.** The coach's grader audit spawns the
  assessor three times *because* three independent contexts disagree usefully.
  Reusing one child for all three runs produces one opinion stated thrice.
- **No dialogue in the task text.** Not the lesson, not your read on how the
  session went, not "they seemed to get it." The assessor sees claims, rubrics,
  probes, productions, and pre-feedback confidence — that list is exhaustive.
- **If `sessions_spawn` is unavailable, stop and say so.** It sits behind tool
  policy: the `coding` and `full` profiles include it, `messaging` and `minimal`
  do not. Without it there is no blind grader, and Engram does not have a
  degraded mode where the tutor grades its own learner. Tell the user to set
  `tools.profile: "coding"` or add `tools.alsoAllow: ["sessions_spawn",
  "sessions_yield"]`, and do not issue receipts until they have.
