#!/usr/bin/env bash
# Weekly research entrypoint (Saturdays). Same wrapper as run-session.sh with write
# access to strategy/, STRATEGY.md and research/. Never places orders.
#
#   bin/run-research.sh [--dry-run]     --dry-run: no push
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/finance"
mkdir -p "$STATE_DIR"
# FINANCE_TODAY=YYYY-MM-DD replays a past date (dry runs on weekends). Never set it for live runs.
TODAY="${FINANCE_TODAY:-$(TZ=Europe/Rome date +%F)}"
LOG="$STATE_DIR/research-$TODAY.log"
exec > >(tee -a "$LOG") 2>&1
echo "=== finance research $TODAY dry_run=$DRY_RUN start $(date -Is)"

if [[ -f HALTED ]]; then
  echo "HALTED present; not running."
  exit 0
fi

export FINANCE_DRY_RUN="$DRY_RUN"
export FINANCE_AGENT=1
export FINANCE_ROOT="$ROOT"
export FINANCE_SESSION=research
export PATH="$HOME/.local/bin:$PATH"
if sc whoami --json >/dev/null 2>&1; then export FINANCE_SC_MODE=live; else export FINANCE_SC_MODE=none; fi

PROMPT="$(cat prompts/research.md)"
ALLOWED=(
  "Read" "Glob" "Grep" "WebSearch" "WebFetch" "TodoWrite"
  "Write(research/**)" "Write(strategy/**)" "Write(STRATEGY.md)" "Write(site/mistakes.md)"
  "Edit(research/**)" "Edit(strategy/**)" "Edit(STRATEGY.md)" "Edit(site/mistakes.md)"
  "Bash(uv run python bin/session-info.py:*)"
  "Bash(uv run python bin/build-site.py:*)"
  "Bash(uv run python strategy/data.py:*)"
  "Bash(uv run python strategy/current.py:*)"
  "Bash(uv run python strategy/backtest.py:*)"
  "Bash(uv run pytest:*)"
  "Bash(cp strategy/current.py strategy/versions/:*)" "Bash(cp strategy/params.toml strategy/versions/:*)"
  "Bash(sc whoami:*)" "Bash(sc broker overview:*)" "Bash(sc broker holdings:*)"
  "Bash(sc broker cash-breakdown:*)" "Bash(sc broker quote:*)" "Bash(sc broker search:*)"
  "Bash(sc broker transactions:*)" "Bash(sc broker chart:*)" "Bash(sc broker security-news:*)"
  "Bash(git status:*)" "Bash(git log:*)" "Bash(git diff:*)" "Bash(ls:*)" "Bash(cat:*)" "Bash(date:*)"
)
CLAUDE_ARGS=(-p "$PROMPT" --allowedTools "${ALLOWED[@]}" --permission-mode default --permission-prompts none
             --settings "$ROOT/.claude/agent-settings.json" --output-format text)
if [[ -n "${FINANCE_CLAUDE_MODEL:-}" ]]; then CLAUDE_ARGS+=(--model "$FINANCE_CLAUDE_MODEL"); fi

set +e
claude "${CLAUDE_ARGS[@]}"
AGENT_RC=$?
set -e
echo "=== agent exited with $AGENT_RC at $(date -Is)"

uv run pytest -q || echo "TESTS FAILED after research session; review before the next daily run"
uv run python bin/build-site.py || echo "build-site failed"
if [[ -n "$(git status --porcelain)" ]]; then
  git add -A
  git commit -q -m "research: $TODAY" || echo "commit failed (pre-commit hook?)"
fi
if [[ $DRY_RUN == 0 ]]; then git push -q || echo "push failed"; else echo "dry run: not pushing"; fi
echo "=== done $(date -Is)"
exit 0
