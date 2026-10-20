# Operations log

Failures of the machinery: data, tooling, network, bugs, the machine the agent runs
on. They are not investment mistakes (those are in `MISTAKES.md`), but they can stop a
session or delay a trade, so they are logged here, append-only, with what was done
about them. Every journal entry also carries its own technical log.

## 2026-10-19: the first scheduled live session exited before doing anything

The 18:16 run ended after zero seconds with exit code 1. A line in the runner computed
the log file name with a command substitution whose status was 1 in live mode, and
`set -e` ended the script there. Every earlier run had been a dry run, where the same
line succeeds. No broker call was made. Fixed the same evening; the retry at 18:19 ran.

## 2026-10-19: the retried session and the push failed on the network

The 18:19 run lost its connection to the Claude API (`ECONNRESET`) a quarter of the way
through the pipeline, and the push to GitHub failed on a TLS error. The afternoon's dry
run had already stopped once on a DNS failure. The machine is on Wi-Fi that dropped
about twenty times that day. No order was proposed. Since 2026-10-20 the sessions wait
up to ten minutes for the network before starting and retry the push; nothing that
talks to the broker is retried.

## 2026-10-20: a session started at 09:01 instead of 18:15

The owner started the session by hand in the morning to recover the previous day. The
agent declined to trade, correctly: the strategy is defined on closing prices and the
spreads at the open were six times the cost model. Live sessions now refuse to start
outside 17:45 to 21:30 Europe/Rome, which also stops the timer from catching up a
missed run the next morning.
