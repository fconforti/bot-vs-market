# Handover

Written by the build session on 2026-10-18. Read this before the first live run.

## What was built

- **Mandate**: `MANDATE.md` (human) and `mandate.toml` (enforced). Limits as in the brief,
  plus: market orders only (`allow_limit_orders = false`), venue `SEIX` (EIX), reject on
  any price warning or appropriateness requirement, 1% preview tolerance for buys.
- **Strategy v001**: `strategy/current.py` (pure `generate()`), `params.toml`,
  `universe.csv` (44 instruments), `data.py` (yfinance cache + live quote cross-check),
  `backtest.py` (same-day-close execution, EUR 0.99/order, spreads). Frozen copy in
  `strategy/versions/v001_2026-10-18.*`, results in `research/backtests/v001.*`,
  reasoning and caveats in `STRATEGY.md`.
- **Guardrails**: `bin/guardrails.py`, the only path to `--confirm`. Validates against
  the mandate and today's snapshot, previews, compares, confirms once, writes everything
  into the trade file. 47 tests in `tests/`, with a fake `sc` serving fixtures.
- **Sessions**: `bin/run-session.sh` (daily) and `bin/run-research.sh` (weekly) wrap
  `claude -p` with `prompts/daily.md` / `prompts/research.md`, a tool allow-list, deny
  rules in `.claude/agent-settings.json` and a PreToolUse hook (`.claude/hooks/guard.py`)
  that blocks direct trade calls, `--confirm`, history edits, pushes in dry runs. The
  hook is inert outside agent sessions (`FINANCE_AGENT=1`).
- **History**: `journal/`, `trades/`, `portfolio/`, `research/` are append-only; the
  pre-commit hook `bin/check-append-only.py` rejects edits, `gitleaks` scans secrets.
- **Site**: `bin/build-site.py` + `templates/` → `site/` (8 pages, dark-mode aware,
  Chart.js equity curve). `.github/workflows/pages.yml` deploys `site/` on push.
- **Automation**: `systemd/finance.{service,timer}` and `finance-research.*`. Not
  installed, not enabled. `bin/kill-switch.sh` disables them and writes `HALTED`.
- **Docs**: `docs/cli-notes.md` (what `sc` really does, from its source), `docs/sc-capabilities.json`.

## Rehearsals (dry runs on fixture data)

Both ran on 2026-10-18, a Saturday, with `FINANCE_TODAY` replaying a weekday.

- **2026-10-16 replay**: aborted at the algorithm step. `strategy/current.py`'s CLI entry
  used the machine clock and the live snapshot, so it never saw the dry-run snapshot.
  Fixed, with a regression test. The nested agent also hit the real `sc` binary on PATH
  (D-Bus error); fixture mode now shadows it. Journal: `journal/2026-10-16-dryrun.md`.
- **2026-10-15 replay**: complete. Two buys proposed (semiconductor ETF, ASML, EUR 240
  each), both previewed through the guardrails with all checks passing, no confirm,
  post-trade snapshot, site rebuilt, commit made. Journal: `journal/2026-10-15-dryrun.md`.
  It raised three things worth knowing:
  - the replay could see the next day's close; the algorithm now clips prices at the
    session date;
  - fractional **stock** buys (EUR 240 of ASML is about 0.16 shares) are accepted by the
    fixture but unverified with the real broker. If the first live preview of a stock
    is rejected, that is why; ETFs are the safer first trades;
  - the two proposals overlap (ASML is a top holding of the semiconductor ETF). v001 has
    no overlap rule; it is in the research inbox.

## What I could not verify (no `sc` login on this machine)

1. **The real JSON shapes.** `holdings`, `overview`, `cash-breakdown`, `quote` and the
   trade payloads were taken from the CLI's Rust source (v1.1.0), not from a live
   call. `finance/portfolio.py` and `bin/guardrails.py` fail loudly on a shape they do
   not understand, but the first `bin/snapshot.py` against the real account is the
   actual test.
2. **The venue code.** `SEIX` is the constant in the source and the label says
   "European Investor Exchange (EIX)". If the first preview is rejected with
   `preview_venue`, look at `selected_venue` in the trade file and set
   `[venue].code` in `mandate.toml` accordingly (or `MUNC` for gettex at EUR 1.99).
3. **Appropriateness for the bitcoin ETP** (`DE000A27Z304`). If the preview requires an
   acknowledgement, the guardrails reject it every time. Either acknowledge once in the
   app or drop it from `strategy/universe.csv` (that is a strategy change: new version).
4. **Session lifetime.** Not documented. The daily run detects an expired session and
   journals an abort; you will need to `sc login` again at some point.
5. **Ticker mapping.** All 44 yfinance tickers downloaded, but a wrong mapping would
   only show up as a large close-vs-quote gap. `strategy/data.py --check-live` prints
   those once logged in; run it before the first live session.

## Before the first live run (in this order)

```sh
cd ~/personal/finance
uv sync && uv run pytest -q                      # must pass

# Scalable CLI: file-backed session (keyring is unavailable here) + CLI-level caps
mkdir -p ~/.config/scalable-cli
cat >> ~/.config/scalable-cli/config.toml <<'TOML'
[auth]
session_backend = "file"

[trade_controls]
max_order_notional = "250"
TOML
sc login                                           # device flow, done by you
sc whoami --json && sc broker overview --json      # real shapes: compare with docs/cli-notes.md

uv run python bin/snapshot.py                      # first real snapshot
uv run python strategy/data.py --refresh
uv run python strategy/data.py --check-live        # no gap above 3%
uv run python strategy/current.py                  # what it would do today

./bin/run-session.sh --dry-run                     # full session, real data, preview only
```

Read the dry-run journal and the `trades/*.json` files it produced. In particular check
`preview.result.tradability.selected_venue`, `ex_ante_costs` and that
`estimated_order_volume` matches. If you want a week of paper trading with the real
account first: `sc login --local-read-only` makes the CLI itself refuse phase 2, so
even a live session can only preview.

Optional but recommended: add `allowed_isins = [...]` with the universe ISINs under
`[trade_controls]` so the CLI refuses anything outside the universe.

## First live run

```sh
./bin/run-session.sh            # on a weekday after 17:30, ideally at 18:15
git log -1 && cat journal/$(date +%F).md
```

Then enable the timers:

```sh
mkdir -p ~/.config/systemd/user
cp systemd/finance.service systemd/finance.timer systemd/finance-research.service systemd/finance-research.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now finance.timer finance-research.timer
systemctl --user list-timers
loginctl enable-linger filippo   # otherwise the timers only fire while you are logged in
```

`GH_TOKEN` comes from `~/.secrets/finance.env` via `EnvironmentFile`. `claude -p` uses
this machine's Claude Code login. Logs: `~/.local/state/finance/session-YYYY-MM-DD.log`.
Stop everything: `./bin/kill-switch.sh`.

GitHub Pages: in the repo settings, set Pages source to "GitHub Actions" once; the
workflow deploys `site/` on every push to `main` that touches it.

## Design decisions you made or should know about

- **Autonomous confirm.** The `sc` capabilities and README say phase 2 must follow an
  explicit human confirmation in a separate step. You chose to automate it. The
  guardrails record the full phase-1 payload (the disclosure the CLI wants shown) in
  every trade file. `max_order_notional` in the CLI config is your independent cap.
- **FREE plan, EIX.** Since 2026-09-01 gettex/Xetra cost EUR 1.99; EIX EUR 0.99 and
  EUR 0 for PRIME ETF buys of EUR 250 or more. With a 25% order cap on EUR 1,000 most
  orders sit below that threshold, so PRIME+ would not pay for itself.
- **18:15 Europe/Rome.** Xetra is closed, EIX/gettex open until 22:00. Market orders fill
  immediately at evening spreads; the backtest models same-day close plus half spread.
- **v001 deliberately simple**, with the churn-reducing fixes documented in `STRATEGY.md`.
  Expect live performance far below the backtest (survivorship bias in the universe).
- **Dry runs** write `journal/YYYY-MM-DD-dryrun.md` and `portfolio/YYYY-MM-DD-dryrun.json`
  so they never collide with live files; the site labels them and excludes them from
  the equity curve. `FINANCE_TODAY=YYYY-MM-DD` replays a date (used for the build's
  dry run, which ran on a Saturday); never set it for live runs.
- **CLAUDE_BRIEF.md is not committed** (it had owner-only permissions). Add it if you
  want the spec in the public repo.

## The three things to watch in the first week

1. **Preview versus proposal mismatches.** A `rejected` trade with reason
   `preview_amount_match` or `preview_venue` means the broker computes something
   differently from what I assumed. Fix the assumption, not the tolerance.
2. **Fills versus the backtest's cost model.** Compare `preview.result.calculation`
   and the actual fill from `sc broker transactions` with the close in the price cache.
   If evening spreads on single stocks are above 0.5%, the research session should
   raise the spread model or drop stocks from the universe.
3. **The trend filter state.** The strategy sells everything when the MSCI World ETF
   closes 3% below its 200-day average. If that happens in week one it is working as
   designed, not a bug; the journal should say how far the index is from that level
   every day.
