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

## 2026-10-20: the first trading session could not commit its own output

The 18:16 session placed the first two real orders and wrote everything, but the
commit was refused by two pre-commit hooks, so the journal, the trades and the site
stayed on the machine until the owner's session committed them an hour later. First,
the secret scanner flagged the order's idempotency key in the two trade files: a
one-time UUID the broker returns on confirmation, not a credential, but it looks like
one and no rehearsal had ever reached the confirm step. It is now redacted like the
other secret-looking fields. Second, the append-only hook rejected the benchmark file,
which had been empty until the first live run and is rewritten daily as the series
grows. The hook now checks that file structurally instead: earlier points must survive
unchanged, and the fixed fields never change. Nothing about the orders themselves was
affected; the broker had both.

## 2026-10-21: no session, the broker login had expired

The CLI login made on 2026-10-19 at about 15:57 was gone by the 18:17 run two days
later (`no_session`). The session aborted at its first check, as designed, and no
order was proposed. Scalable does not document the login lifetime; the next login
will show whether two days is fixed. The owner logged in again on 2026-10-22 at 08:43.

## 2026-10-22: a valid login was reported as expired

The 18:16 run aborted as "not logged in", but the login was valid. The CLI could not
reach Scalable's sign-in server to verify it (`network_error`, `internal_error`): on
the same Wi-Fi, two calls out of three failed and the third succeeded. The runner
treated any failed check as an expired login and did not retry. Since then, broker
calls that cannot place an order are retried on network errors (an order confirmation
never is), the pre-session check retries for about five minutes, and a broker that
stays unreachable is reported as such instead of as a missing login. The session was
then started by hand the same evening.
