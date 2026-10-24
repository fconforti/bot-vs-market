#!/usr/bin/env bash
# Daily entrypoint. Wraps `claude -p` with prompts/daily.md under a restricted tool set.
#
#   bin/run-session.sh             live: may place orders through bin/guardrails.py
#   bin/run-session.sh --dry-run   preview only, never confirms, never pushes
#
# Exit 0 on a completed session (including a deliberate "no trade" or an abort that
# was journaled), 3 when sc is not logged in, 8 when the broker stayed unreachable,
# the agent's exit code when it failed, 4 when the push failed, 5 when the commit
# was refused (a pre-commit hook: secret scan or append-only), 7 when the network
# never came up. Any non-zero exit
# makes systemd run finance-alert@.service, which emails the owner.
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
SUFFIX_LOG=""; if [[ $DRY_RUN == 1 ]]; then SUFFIX_LOG="-dryrun"; fi
LOG="$STATE_DIR/session-$TODAY$SUFFIX_LOG.log"
exec > >(tee -a "$LOG") 2>&1
echo "=== finance session $TODAY dry_run=$DRY_RUN start $(date -Is)"

if [[ -f HALTED ]]; then
  echo "HALTED present in repo root; not running. Remove it to resume."
  exit 0
fi

# Live orders only in the evening window: after the Xetra close (the strategy reads
# closing prices) and while EIX is open (until 22:00). On 2026-10-20 a 09:01 run saw
# 1.5% spreads on a US-sector ETF. This also stops the timer's catch-up run after the
# machine was off at 18:15. FINANCE_ANY_TIME=1 overrides it for a deliberate run.
HHMM=$(TZ=Europe/Rome date +%H%M)
if [[ $DRY_RUN == 0 && -z "${FINANCE_ANY_TIME:-}" ]] && (( 10#$HHMM < 1745 || 10#$HHMM >= 2130 )); then
  echo "live sessions run between 17:45 and 21:30 Europe/Rome; it is $HHMM. Not running."
  exit 0
fi

export FINANCE_DRY_RUN="$DRY_RUN"
export FINANCE_AGENT=1
export FINANCE_ROOT="$ROOT"
export PATH="$HOME/.local/bin:$PATH"

# shellcheck source=bin/net.sh
source "$ROOT/bin/net.sh"
if ! wait_for_network 600; then
  echo "network unavailable for 10 minutes; not starting."
  exit 7
fi

# --- broker session ---------------------------------------------------------
# Retries network errors for about five minutes; tells "not logged in" (3) apart from
# "broker unreachable" (8). Before 2026-10-22 both were reported as an expired login.
BROKER_RC=0
BROKER_MSG="$(uv run python bin/broker-check.py)" || BROKER_RC=$?
echo "broker check: $BROKER_MSG"
if [[ $BROKER_RC == 0 ]]; then
  export FINANCE_SC_MODE=live
else
  if [[ $DRY_RUN == 1 ]]; then
    echo "sc is not logged in: dry run falls back to the fake sc with FIXTURE data"
    export FINANCE_SC_MODE=fixture
    export SC_BIN="$ROOT/tests/fake_sc.py"
    export FINANCE_SC_FIXTURES="$ROOT/tests/fixtures/sc"
    SHIM="$(mktemp -d)"; ln -s "$SC_BIN" "$SHIM/sc"; export PATH="$SHIM:$PATH"   # direct `sc` calls hit the fake too
  else
    export FINANCE_SC_MODE=none
    JOURNAL="journal/$TODAY.md"
    if [[ $BROKER_RC == 8 ]]; then
      WHY="the broker could not be reached for about five minutes (network errors); the login itself was not the problem"
      ACTION="nothing, unless it repeats; the next scheduled run tries again"
      SHORT="broker unreachable"
    else
      WHY="the Scalable CLI session is missing or expired"
      ACTION="run \`sc login\` on the machine, then \`sc whoami --json\`"
      SHORT="sc not logged in"
    fi
    if [[ ! -f "$JOURNAL" ]]; then
      {
        echo "# $TODAY — aborted before start"
        echo
        echo "- **Status:** aborted"
        echo "- **Reason:** $WHY. No orders were placed."
        echo "- **Action for the owner:** $ACTION."
        echo "- This note was added automatically by the scheduler; the agent never started."
      } > "$JOURNAL"
      uv run python bin/build-site.py >/dev/null || true
      git add -A && git commit -q -m "session: $TODAY (aborted: $SHORT)" || true
      push_with_retry || echo "push failed (GH_TOKEN missing or network)"
    fi
    echo "$SHORT; aborted and journaled."
    exit "$BROKER_RC"
  fi
fi

# --- the agent --------------------------------------------------------------
PROMPT="$(cat prompts/daily.md)"
ALLOWED=(
  "Read" "Glob" "Grep" "WebSearch" "WebFetch" "TodoWrite"
  "Edit(journal/**)" "Edit(trades/**)" "Edit(research/inbox.md)" "Edit(MISTAKES.md)" "Edit(OPERATIONS.md)"
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
SUFFIX=""; if [[ $DRY_RUN == 1 ]]; then SUFFIX=" (dry run)"; fi
PUSH_RC=0
if [[ -n "$(git status --porcelain)" ]]; then
  git add -A
  git commit -q -m "session: $TODAY$SUFFIX" || { PUSH_RC=5; echo "commit failed (pre-commit hook?)"; }
fi
if [[ $DRY_RUN == 0 && $PUSH_RC == 0 ]]; then
  push_with_retry || { PUSH_RC=4; echo "push failed (GH_TOKEN missing or network)"; }
else
  echo "not pushing (dry run or commit failed)"
fi
echo "=== done $(date -Is)"
# Whatever the agent wrote is still committed above; a failed agent or push fails the unit.
if [[ $AGENT_RC != 0 ]]; then exit "$AGENT_RC"; fi
exit "$PUSH_RC"
