# finance

> **Disclaimer.** This is an experiment. An autonomous AI agent (Claude) manages a small
> real-money Scalable Capital Broker account (about EUR 1,000) with an explicit,
> versioned trading strategy written as code, and publishes every decision, trade,
> mistake and portfolio snapshot to a public site. The owner accepts the risk of losing
> the entire amount. Nothing here is investment advice or a recommendation to anyone.
> Do not copy these trades.

Site: <https://fconforti.github.io/finance/> · Strategy: [`STRATEGY.md`](STRATEGY.md) ·
Rules: [`MANDATE.md`](MANDATE.md) · First-run checklist: [`docs/handover.md`](docs/handover.md)

## Status

This section is kept current by whoever last worked on the repo (the build agent so far).

| Date | State |
|---|---|
| 2026-10-18 | Built and pushed. 48 tests pass. Two rehearsals (dry runs on fixture data, replayed as 2026-10-16 and 2026-10-15): the first aborted on a plumbing bug, now fixed; the second went end to end (two proposals, guardrails preview matched, no confirm). **Not yet live:** the Scalable CLI has never been logged in on the machine, so the real account's JSON shapes, the EIX venue code and the bitcoin ETP's appropriateness rules are unverified. Timers are not enabled. No real order has ever been placed. **Site not live yet:** the Pages deploy workflow fails until the owner sets Settings → Pages → Source to "GitHub Actions" (the repo token cannot do it); re-run the workflow after that. |

## What this is

An experiment in running a trading strategy with three properties that are usually
missing from "AI trades stocks" projects:

1. **The strategy is code, not vibes.** `strategy/current.py` is a pure function from
   (portfolio, prices, parameters) to a list of proposed orders. The daily agent may
   execute those orders or refuse to trade. It may not invent orders, resize them, or
   change the algorithm. Only the weekly research session can change the strategy, and
   only with a written argument and a backtest.
2. **The money is protected from the software, not from the market.** Every order passes
   through `bin/guardrails.py`, the only code path that can confirm a trade with the
   broker. It re-reads the limits in `mandate.toml`, checks the proposal against today's
   account snapshot, asks the broker for a preview, compares the preview with the
   proposal, and confirms exactly once or not at all. Losing the money to a bad strategy
   is accepted; losing it to a bug, a misread number or a drifting prompt is not.
3. **Everything is public and append-only.** The journal, the trade files, the
   snapshots and the research notes are committed to this repository and rendered on
   the site. They are never edited after the fact; a pre-commit hook rejects such
   commits. Mistakes get their own page.

## How a day works

Every weekday at 18:15 Europe/Rome (after the Xetra close, while EIX/gettex are still
open), `bin/run-session.sh` starts a headless Claude Code session with
[`prompts/daily.md`](prompts/daily.md) and a short allow-list of tools. The session:

1. takes a snapshot of the account (`bin/snapshot.py`),
2. re-reads the last ten journal entries, the strategy, the research inbox and the mistakes page,
3. refreshes prices and reads the news, recording its sources,
4. writes a market view *before* any decision,
5. reviews each position against the thesis recorded when it was bought,
6. runs the algorithm and pastes its output verbatim,
7. accepts the orders or refuses to trade with a written reason,
8. writes one JSON file per order and hands each to the guardrails,
9. re-snapshots, records fills,
10. appends to the mistakes page or the research inbox if warranted,
11. rebuilds the site. The runner commits and pushes.

Every Saturday, `bin/run-research.sh` runs [`prompts/research.md`](prompts/research.md):
review the week, address the inbox, form at most one testable hypothesis, backtest it
against the current version, and adopt it only with an argument that covers overfitting
and regime risk. The default outcome is "no change".

## The strategy in one paragraph

v001 is a slow, trend-filtered momentum rotation over 44 liquid EUR-listed instruments
(mostly ETFs, a few large caps, gold, one bitcoin ETP). New positions are opened only
while the MSCI World ETF trades above its 200-day average; everything is sold if it
falls 3% below it. Up to four positions, equal weight, chosen by 12-1 month momentum;
exits only in the first three trading days of a month, with a wide hysteresis band so
the book does not churn. Two orders a day at most, market orders only. The backtest
(2013 to 2026, with fees and spreads) and, more importantly, the reasons not to trust
it are in [`STRATEGY.md`](STRATEGY.md).

## Safety layers, from the outside in

| Layer | What it does |
|---|---|
| Broker | Order size cap and ISIN allow-list in the Scalable CLI's own `[trade_controls]` config (set by the owner, outside this repo). |
| `mandate.toml` | 25% of NAV per order, 40% per position, 2 orders a day, EUR 25 minimum, market orders only, one venue. Re-read on every call. |
| `bin/guardrails.py` | Validates, previews, compares, confirms once. Any mismatch, warning, questionnaire or error: no order. Never retries. Idempotent. |
| Claude Code permissions and hook | The agent cannot call the broker's trade commands, cannot write outside the journal/trades/inbox, cannot edit history, cannot push in a dry run. |
| Append-only history | Pre-commit hook rejects edits to past journal, trade, snapshot and research files. |
| Kill switch | `bin/kill-switch.sh` disables the timers and writes `HALTED`; every session checks for it first. |

## Layout

```
MANDATE.md / mandate.toml   rules and limits (human / machine)
STRATEGY.md                 current strategy, backtest, caveats, changelog
strategy/                   current.py, params.toml, universe.csv, data.py, backtest.py, versions/
bin/                        run-session.sh, run-research.sh, guardrails.py, snapshot.py,
                            session-info.py, build-site.py, check-append-only.py, kill-switch.sh
prompts/                    daily.md, research.md
journal/ trades/ portfolio/ research/    append-only history (dry runs are suffixed -dryrun)
site/                       generated static site (committed, deployed by GitHub Pages)
systemd/                    user units (not enabled)
tests/                      pytest, with a fake `sc` that serves fixtures
docs/                       cli-notes.md (what the Scalable CLI really does), handover.md
finance/                    shared library: sc wrapper, mandate, models, trade files, snapshots
```

## Running it yourself (owner)

```sh
cd ~/personal/finance
uv sync && uvx pre-commit install && uv run pytest -q
```

Scalable CLI: enable "Agentic Investing" in the Scalable profile, then

```sh
mkdir -p ~/.config/scalable-cli
printf '[auth]\nsession_backend = "file"\n\n[trade_controls]\nmax_order_notional = "250"\n' >> ~/.config/scalable-cli/config.toml
sc login                          # device-code flow, done by a human
sc whoami --json                  # must print ok:true
```

The keyring backend does not work on this machine (no Secret Service on D-Bus), hence
`session_backend = "file"`.

```sh
uv run python bin/snapshot.py                  # portfolio/YYYY-MM-DD.json from the account
uv run python strategy/data.py --refresh       # price cache (yfinance)
uv run python strategy/data.py --check-live    # cached closes vs broker quotes
uv run python strategy/current.py              # signals and proposed orders, read-only
uv run python strategy/backtest.py --version current
uv run python bin/build-site.py && python -m http.server -d site 8000

./bin/run-session.sh --dry-run                 # full session, preview only, never confirms
./bin/run-session.sh                           # live
./bin/run-research.sh --dry-run
```

`--dry-run` uses the real account when `sc` is logged in and falls back to a fake `sc`
with fixture data (clearly labelled in the journal) when it is not. Dry-run journals
and snapshots carry a `-dryrun` suffix and never feed the equity curve.
`FINANCE_TODAY=YYYY-MM-DD` replays a date for a rehearsal on a weekend; never set it live.

## Automation (not enabled)

```sh
mkdir -p ~/.config/systemd/user
cp systemd/finance.service systemd/finance.timer \
   systemd/finance-research.service systemd/finance-research.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now finance.timer finance-research.timer
systemctl --user list-timers
journalctl --user -u finance.service -f
```

User timers only fire while the owner is logged in, unless lingering is on:

```sh
loginctl enable-linger filippo     # currently off; needed for unattended runs
```

The services load `~/.secrets/finance.env` (`GH_TOKEN` for pushing). Logs go to
`~/.local/state/finance/`. `claude -p` uses this machine's Claude Code login.
GitHub Pages must be set to "GitHub Actions" once in the repo settings; the workflow
in `.github/workflows/pages.yml` deploys `site/` on every push that touches it.

## Kill switch

```sh
./bin/kill-switch.sh      # disables both timers and writes HALTED to the repo root
```

Remove the file and re-enable the timers to resume.
