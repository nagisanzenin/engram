#!/usr/bin/env bash
# Engram — Codex glue installer.
# Copies the TOML subagent ports into your Codex agents dir and prints the
# ENGRAM_HOME hint. Idempotent; safe to re-run. Claude Code users don't need this.
set -eu

REPO_ROOT="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
AGENTS_DIR="$CODEX_HOME/agents"

echo "engram: installing Codex subagent ports"
echo "  repo:        $REPO_ROOT"
echo "  codex home:  $CODEX_HOME"

if [ ! -d "$REPO_ROOT/codex/agents" ]; then
  echo "engram: error: codex/agents not found under $REPO_ROOT" >&2
  exit 1
fi

mkdir -p "$AGENTS_DIR"
n=0
for f in "$REPO_ROOT"/codex/agents/*.toml; do
  [ -e "$f" ] || continue
  cp "$f" "$AGENTS_DIR/"
  echo "  + $(basename "$f") -> $AGENTS_DIR/"
  n=$((n + 1))
done
echo "engram: installed $n agent(s)."

# Sanity: the shared engine must run.
if command -v python3 >/dev/null 2>&1; then
  echo "engram: running selftest…"
  python3 "$REPO_ROOT/scripts/engram.py" selftest >/dev/null 2>&1 \
    && echo "engram: selftest OK" \
    || echo "engram: WARNING — selftest did not pass; run it directly to see why" >&2
fi

cat <<EOF

Next steps:
  1. (optional) Pin state inside your workspace to avoid Codex sandbox prompts:
       export ENGRAM_HOME="\$HOME/.engram"     # add to your shell rc
  2. Install the skills (if not via 'codex plugin add'):
       npx skills add nagisanzenin/engram
  3. In Codex, invoke skills as \$learn / \$review / \$coach, and the graders
     explicitly, e.g. "\$engram-assessor, grade these: <stash JSON>".

See INSTALL-CODEX.md for the full story and caveats.
EOF
