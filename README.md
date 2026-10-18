# finance

> **Disclaimer.** This is an experiment. An autonomous AI agent (Claude) manages a small
> real-money Scalable Capital Broker account (about EUR 1,000) with an explicit,
> versioned trading strategy written as code, and publishes every decision, trade,
> mistake and portfolio snapshot to a public site. The owner accepts the risk of losing
> the entire amount. Nothing here is investment advice or a recommendation to anyone.
> Do not copy these trades.

Site: <https://fconforti.github.io/finance/>

## What this is

- A daily session (`bin/run-session.sh`, 18:15 Europe/Rome, Mon–Fri) in which the
  agent snapshots the account, refreshes data, writes a market view, runs the strategy
  in `strategy/current.py`, and either executes its orders through `bin/guardrails.py`
  or refuses to trade with a written reason. Everything is written to
  `journal/YYYY-MM-DD.md`, committed and pushed.
- A weekly research session (`bin/run-research.sh`, Saturday 10:00) that reviews the
  week, tests at most one hypothesis with `strategy/backtest.py`, and may adopt a new
  strategy version with a written argument.
- Guardrails in code (`bin/guardrails.py`), the only path to an order confirmation:
  limits from `mandate.toml`, a preview that must match the proposal, no retries.
- A static site (`bin/build-site.py` → `site/`) deployed by GitHub Pages.

See `MANDATE.md` for the rules, `STRATEGY.md` for the current strategy,
`docs/cli-notes.md` for what the Scalable CLI really does, and `docs/handover.md` for
the owner's first-run checklist.

## Layout

```
MANDATE.md / mandate.toml   rules and limits (human / machine)
STRATEGY.md                 current strategy and changelog
strategy/                   current.py (live algorithm), params.toml, universe.csv,
                            data.py, backtest.py, versions/ (frozen copies)
bin/                        run-session.sh, run-research.sh, guardrails.py,
                            snapshot.py, build-site.py, kill-switch.sh
prompts/                    daily.md, research.md (the agent's session prompts)
journal/ research/ trades/ portfolio/   append-only history
site/                       generated static site (committed)
systemd/                    user units (not enabled)
tests/                      pytest, with a fake `sc`
docs/                       CLI notes, capabilities dump, handover
```

## Setup (owner)

```sh
cd ~/personal/finance
uv sync                                  # Python 3.12 venv with dependencies
uvx pre-commit install                   # gitleaks + append-only hook
uv run pytest                            # all green before anything else
```

Scalable CLI: enable "Agentic Investing" in the Scalable profile, then

```sh
mkdir -p ~/.config/scalable-cli
printf '[auth]\nsession_backend = "file"\n\n[trade_controls]\nmax_order_notional = "250"\n' >> ~/.config/scalable-cli/config.toml
sc login                                 # device-code flow, do it yourself
sc whoami --json                         # must print ok:true
```

The keyring backend does not work on this machine (no Secret Service on DBus), hence
`session_backend = "file"`. `max_order_notional` is a second, CLI-level cap that this
repo's code cannot bypass. Add `allowed_isins` from `strategy/universe.csv` as well if
you want the CLI to refuse anything outside the universe.

## Running

```sh
uv run python bin/snapshot.py                  # portfolio/YYYY-MM-DD.json from the account
uv run python strategy/data.py --refresh       # price cache
uv run python strategy/current.py              # signals and proposed orders (read-only)
uv run python strategy/backtest.py --version current
uv run python bin/build-site.py && python -m http.server -d site 8000

./bin/run-session.sh --dry-run                 # full session, preview only, no confirm
./bin/run-session.sh                           # live session (places orders)
./bin/run-research.sh --dry-run
```

`--dry-run` uses the real account when `sc` is logged in and falls back to the fake
`sc` with fixture data (clearly marked in the journal) when it is not.

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

User timers only fire while you are logged in, unless lingering is on:

```sh
loginctl enable-linger filippo     # currently off; needed for unattended runs
```

The services load `~/.secrets/finance.env` (`GH_TOKEN` for pushing). Logs go to
`~/.local/state/finance/`. `claude -p` uses this machine's Claude Code login.

## Kill switch

```sh
./bin/kill-switch.sh      # disables both timers and writes HALTED to the repo root
```

Every session checks for `HALTED` and exits immediately if it exists. Remove the file
and re-enable the timers to resume.
