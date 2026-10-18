#!/usr/bin/env bash
# Daily entrypoint. Wraps `claude -p` with prompts/daily.md under a restricted tool set.
#
#   bin/run-session.sh             live: may place orders through bin/guardrails.py
#   bin/run-session.sh --dry-run   preview only, never confirms, never pushes
#
# Exit 0 on a completed session (including a deliberate "no trade" or an abort that
# was journaled), 3 when the session could not even start.
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
LOG="$STATE_DIR/session-$TODAY$( [[ $DRY_RUN == 1 ]] && echo -dryrun ).log"
exec > >(tee -a "$LOG") 2>&1
echo "=== finance session $TODAY dry_run=$DRY_RUN start $(date -Is)"

if [[ -f HALTED ]]; then
  echo "HALTED present in repo root; not running. Remove it to resume."
  exit 0
fi

export FINANCE_DRY_RUN="$DRY_RUN"
export FINANCE_AGENT=1
export FINANCE_ROOT="$ROOT"
export PATH="$HOME/.local/bin:$PATH"

# --- broker session ---------------------------------------------------------
if sc whoami --json >/dev/null 2>&1; then
  export FINANCE_SC_MODE=live
else
  if [[ $DRY_RUN == 1 ]]; then
    echo "sc is not logged in: dry run falls back to the fake sc with FIXTURE data"
    export FINANCE_SC_MODE=fixture
    export SC_BIN="$ROOT/tests/fake_sc.py"
    export FINANCE_SC_FIXTURES="$ROOT/tests/fixtures/sc"
  else
    export FINANCE_SC_MODE=none
    JOURNAL="journal/$TODAY.md"
    if [[ ! -f "$JOURNAL" ]]; then
      {
        echo "# $TODAY — aborted before start"
        echo
        echo "- **Status:** aborted"
        echo "- **Reason:** \`sc whoami\` failed: the Scalable CLI session is missing or expired. No orders were placed."
        echo "- **Action for the owner:** run \`sc login\` on the machine, then \`sc whoami --json\`."
        echo "- Written by \`bin/run-session.sh\`, not by the agent."
      } > "$JOURNAL"
      uv run python bin/build-site.py >/dev/null || true
      git add -A && git commit -q -m "session: $TODAY (aborted: sc not logged in)" || true
      git push -q || echo "push failed (GH_TOKEN missing or network)"
    fi
    echo "sc not logged in; aborted and journaled."
    exit 3
  fi
fi

# --- the agent --------------------------------------------------------------
PROMPT="$(cat prompts/daily.md)"
ALLOWED=(
  "Read" "Glob" "Grep" "WebSearch" "WebFetch" "TodoWrite"
  "Write(journal/**)" "Write(trades/**)" "Write(research/inbox.md)" "Write(site/mistakes.md)"
  "Edit(journal/**)" "Edit(research/inbox.md)" "Edit(site/mistakes.md)"
  "Bash(uv run python bin/session-info.py:*)"
  "Bash(uv run python bin/snapshot.py:*)"
  "Bash(uv run python bin/guardrails.py:*)"
  "Bash(uv run python bin/build-site.py:*)"
  "Bash(uv run python strategy/data.py:*)"
  "Bash(uv run python strategy/current.py:*)"
  "Bash(sc whoami:*)" "Bash(sc broker overview:*)" "Bash(sc broker holdings:*)"
  "Bash(sc broker cash-breakdown:*)" "Bash(sc broker quote:*)" "Bash(sc broker search:*)"
  "Bash(sc broker transactions:*)" "Bash(sc broker chart:*)" "Bash(sc broker security-news:*)"
  "Bash(git status:*)" "Bash(git log:*)" "Bash(git diff:*)" "Bash(ls:*)" "Bash(cat:*)" "Bash(date:*)"
)
CLAUDE_ARGS=(
  -p "$PROMPT"
  --allowedTools "${ALLOWED[@]}"
  --permission-mode default
  --permission-prompts none
  --settings "$ROOT/.claude/agent-settings.json"
  --output-format text
)
if [[ -n "${FINANCE_CLAUDE_MODEL:-}" ]]; then
  CLAUDE_ARGS+=(--model "$FINANCE_CLAUDE_MODEL")
fi

set +e
claude "${CLAUDE_ARGS[@]}"
AGENT_RC=$?
set -e
echo "=== agent exited with $AGENT_RC at $(date -Is)"

# --- publish (deterministic, even if the agent stopped early) --------------
uv run python bin/build-site.py || echo "build-site failed"
SUFFIX=""; [[ $DRY_RUN == 1 ]] && SUFFIX=" (dry run)"
if [[ -n "$(git status --porcelain)" ]]; then
  git add -A
  git commit -q -m "session: $TODAY$SUFFIX" || echo "commit failed (pre-commit hook?)"
fi
if [[ $DRY_RUN == 0 ]]; then
  git push -q || echo "push failed (GH_TOKEN missing or network)"
else
  echo "dry run: not pushing"
fi
echo "=== done $(date -Is)"
exit 0
