#!/usr/bin/env bash
# Engram re-anchor hook: surfaces due reviews at session start.
# Prints at most two lines (or nothing) — ambient, never nagging (Constitution art. 8).
# Must never break a session: degrade to silence on any failure.
# Portable across Claude Code and Codex: uses the plugin-root env var if set,
# else self-resolves relative to this script's own location.
set -u
command -v python3 >/dev/null 2>&1 || exit 0
ROOT="${CLAUDE_PLUGIN_ROOT:-${CODEX_PLUGIN_ROOT:-}}"
if [ -z "$ROOT" ] || [ ! -f "$ROOT/scripts/engram.py" ]; then
  ROOT="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]:-$0}")/.." 2>/dev/null && pwd)"
fi
[ -f "$ROOT/scripts/engram.py" ] || exit 0
python3 "$ROOT/scripts/engram.py" session-start 2>/dev/null || true
exit 0
