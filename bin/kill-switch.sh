#!/usr/bin/env bash
# Stop everything: disable both timers and write HALTED to the repo root.
# Every session checks for HALTED and exits immediately. Open orders are NOT cancelled
# (the strategy is market-only, so there normally are none); check with
#   sc broker transactions --status pending --json
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
systemctl --user disable --now finance.timer finance-research.timer 2>/dev/null || true
echo "halted by $(whoami) at $(date -Is)" > "$ROOT/HALTED"
echo "HALTED written to $ROOT/HALTED and timers disabled. Remove the file and re-enable the timers to resume."
