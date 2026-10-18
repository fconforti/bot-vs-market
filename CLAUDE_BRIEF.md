# CLAUDE_BRIEF.md — Build framework-trader

You are working in `~/framework-trader`, an empty git repo on a Framework Desktop running Arch Linux. Your job is to build a system in which an autonomous Claude agent manages a real €1,000 Scalable Capital Broker portfolio, develops and refines an explicit trading strategy as code, and publishes every decision to a public GitHub Pages site.

The owner has read `TUTORIAL.md`, has a funded Scalable account, is allowlisted for the Scalable CLI (`sc`), and has cloned this repo through a per-repo SSH deploy key (host alias `github-framework-trader`). The machine has several `gh` accounts; never rely on the active `gh` login. Push over the deploy-key remote only, and if the GitHub API is needed read `GH_TOKEN` from the env file. Read `TUTORIAL.md` first. Then build everything below. **Do not enable the systemd timer and do not place any real order.** Stop when the dry run works and hand back to the owner.

The owner accepts the risk of losing the entire €1,000. Your job is not to protect the capital from the strategy; it is to protect it from bugs, misreads and prompt-level drift. Guardrails are enforced in code.

---

## 1. Discover the real CLI surface first

Run `sc capabilities --json` and `sc --help` and read the official README at `github.com/ScalableCapital/scalable-cli`. Save the capabilities output to `docs/sc-capabilities.json`. Build every CLI call in this repo against what the tool actually exposes, not against what you assume. In particular, learn the exact order flow (preview → confirmation ID → confirm), the JSON shapes of `holdings`, `overview`, `transactions`, `quote`, `search`, and how limit/stop orders are expressed. Write what you learn in `docs/cli-notes.md`.

## 2. Repository layout

```
framework-trader/
├── README.md                 # what this is, link to site, disclaimer
├── MANDATE.md                # rules, limits, objective — human-readable, agent reads every run
├── mandate.toml              # the same limits, machine-readable, enforced by the runner
├── STRATEGY.md               # current strategy in plain language, versioned
├── strategy/
│   ├── __init__.py
│   ├── current.py            # the live algorithm: signals -> proposed orders
│   ├── backtest.py           # backtest harness (yfinance data)
│   ├── data.py               # data fetching: sc quotes, yfinance, macro
│   └── versions/             # frozen copies: v001_<date>.py, v002_...
├── bin/
│   ├── run-session.sh        # daily entrypoint, wraps `claude -p` with the session prompt
│   ├── run-research.sh       # weekly strategy-research entrypoint
│   ├── guardrails.py         # validates proposed orders against mandate.toml; the ONLY path to `sc ... confirm`
│   ├── snapshot.py           # writes portfolio/YYYY-MM-DD.json from sc
│   └── build-site.py         # generates site/ from journal/, trades/, portfolio/
├── prompts/
│   ├── daily.md              # the session prompt for the daily agent run
│   └── research.md           # the session prompt for the weekly research run
├── journal/                  # one markdown file per daily run
├── research/                 # one markdown file per research run
├── trades/                   # one JSON per order (proposed, executed, rejected)
├── portfolio/                # daily snapshots + benchmark.json
├── site/                     # generated static site (committed)
├── systemd/
│   ├── framework-trader.service / .timer
│   └── framework-trader-research.service / .timer
├── .github/workflows/pages.yml
├── .pre-commit-config.yaml   # secret scanning
└── pyproject.toml
```

Python 3.12, `uv` for dependencies: `yfinance`, `pandas`, `numpy`, `tomli`/`tomllib`, `jinja2`, `matplotlib` (static charts) or Chart.js via CDN in the site. No heavy frameworks.

## 3. MANDATE.md and mandate.toml

Write both from this spec. The owner may edit them later; the runner must re-read `mandate.toml` every run.

- **Capital**: whatever is in the account. Never request more. Never transfer out.
- **Objective**: maximize total return of the portfolio. Total loss is an accepted outcome.
- **Instruments**: anything tradable through the Scalable Broker (stocks, ETFs, ETPs including crypto ETPs). Derivatives/margin/securities lending are out of scope because the CLI does not expose them.
- **Limits (enforced in code)**:
  - `max_order_pct_of_nav = 0.25`
  - `max_orders_per_day = 2`
  - `max_position_pct_of_nav = 0.40`
  - `min_order_eur = 25` (fees make smaller orders irrational)
  - `allow_market_orders = true`, `allow_limit_orders = true`
  - `trading_days = Mon–Fri`, `session_time = 18:15 Europe/Rome` (after Xetra close; orders execute next session or immediately on gettex if still open — the agent must know which)
- **Benchmark**: a hypothetical €1,000 buy-and-hold of an MSCI World UCITS ETF (pick a specific ISIN, record it) from the date of the first live run. Stored in `portfolio/benchmark.json`, updated daily with the ETF's close.
- **Hard stops**: any CLI error, auth failure, malformed JSON, or preview that does not match the proposed order → abort the run, write the journal explaining the abort, place no orders. Never retry an order confirm.
- **Honesty rules**: the agent may never edit past journal entries, trade files or snapshots. Corrections go in a new entry. The site must show the full history including rejected orders and aborted runs.

## 4. Strategy as code — the heart of the project

The agent does not freestyle. It runs an explicit algorithm it has written and may revise only through the research process.

### 4.1 `strategy/current.py`
Exposes:
```python
def generate(state: PortfolioState, market: MarketData, params: dict) -> list[ProposedOrder]
```
Pure function. Deterministic given inputs. Returns zero or more proposed orders, each with `isin`, `side`, `eur_amount` or `quantity`, `order_type`, optional `limit_price`, and a `rationale` string. Parameters live in `strategy/params.toml`.

### 4.2 Initial strategy (v001)
Write a defensible first version yourself, documented in `STRATEGY.md`. Suggested starting point — a mixed momentum/mean-reversion rotation over a liquid universe:
- Universe: ~30–60 liquid instruments on Scalable spanning broad equity ETFs, sector ETFs, major single stocks (EU + US ADRs/listings available on gettex), gold and a crypto ETP. Store as `strategy/universe.csv` with ISIN, ticker for yfinance, type.
- Signal: 12-1 month momentum ranking combined with a short-term mean-reversion filter; a volatility-targeting position sizer; a trend filter on a broad index that moves to cash/short-duration bond ETF when the trend is down.
- Keep it simple enough to backtest honestly. The point is a baseline the research loop can improve, not a clever v001.

### 4.3 `strategy/backtest.py`
Walk-forward backtest on yfinance daily data with realistic frictions: €0.99 per order, 0.1% spread, next-open execution. Reports CAGR, max drawdown, Sharpe, turnover, number of trades, and the same metrics for the benchmark. Output to `research/backtests/<version>.json` and a chart. Must run in under a few minutes on CPU.

### 4.4 Versioning discipline
- Every change to `current.py` or `params.toml` gets a new frozen copy in `strategy/versions/`, a bump in `STRATEGY.md` (changelog with the reasoning), and a backtest result.
- A new version goes live only if the research session argues for it in writing in `research/YYYY-MM-DD.md`, including: hypothesis, what the backtest shows, what could be overfit, and what the agent will watch for to decide it was a mistake.
- Daily sessions may **not** change the strategy. They execute it, and may only override it in one direction: refusing to trade (and explaining why). They may append observations to `research/inbox.md` for the next research session.

## 5. The daily session (`prompts/daily.md`)

`bin/run-session.sh` runs `claude -p "$(cat prompts/daily.md)"` with the repo as working directory and `--allowedTools` restricted to: Read, Write (only into `journal/`, `trades/`, `research/inbox.md`), Bash restricted to `python bin/*.py`, `sc broker <read-only subcommands>`, `uv run`, and web search/fetch. The agent must **not** be able to call `sc` order commands directly; it calls `python bin/guardrails.py execute trades/<proposal>.json`, which is the only code path that runs preview + confirm.

Pipeline the prompt must enforce, in this order, each step producing a section of `journal/YYYY-MM-DD.md`:

1. **State** — run `bin/snapshot.py`; summarize NAV, cash, positions, P&L vs yesterday and vs benchmark.
2. **Memory** — read the last 10 journal entries, `STRATEGY.md`, `research/inbox.md`, `site/mistakes.md`. Note any thesis whose conditions have changed.
3. **Data** — run `strategy/data.py` to refresh prices for the universe; web-search today's market wrap, macro calendar for the next 5 days, and news for each current holding. Record sources (URLs) in the journal.
4. **Market view** — 5–10 sentences. Written before any order decision.
5. **Position review** — for each holding: original thesis (from the trade file), is it intact, hold/trim/exit per the algorithm.
6. **Algorithm output** — run `strategy/current.py`, paste the proposed orders and rationale verbatim.
7. **Decision** — accept the algorithm's orders, or refuse to trade with a written reason (e.g. data looks broken, major event tomorrow). No other overrides.
8. **Execution** — write each accepted order to `trades/YYYY-MM-DD-NN.json` with `status: proposed`, then call `guardrails.py execute`. It validates against `mandate.toml`, runs the `sc` preview, checks the preview matches (ISIN, side, amount within 1%), confirms, and rewrites the trade file with `status: executed|rejected`, the confirmation data and the reason.
9. **Post-trade** — re-snapshot, record fills.
10. **Mistakes** — if any past decision now looks wrong, append to `site/mistakes.md` (append-only) with what was wrong and what rule would have prevented it. Put strategy ideas into `research/inbox.md`.
11. **Publish** — `bin/build-site.py`, `git add -A`, commit `session: YYYY-MM-DD`, push.

The prompt should also include: the owner's acceptance of total loss, the honesty rules, "you are being watched publicly — write for a smart reader who will check your numbers", and an explicit instruction to prefer doing nothing over doing something unjustified.

## 6. The weekly research session (`prompts/research.md`)

Runs Saturdays. Same tooling, plus Write access to `strategy/`, `STRATEGY.md`, `research/`. Pipeline:

1. Review the week: realized vs backtest expectations, slippage, costs, each trade's outcome versus its thesis.
2. Read `research/inbox.md` and `site/mistakes.md`.
3. Form at most **one** hypothesis for improving the strategy. Specific, testable.
4. Implement it as a candidate version, run `backtest.py` on candidate vs current on the same data, including an out-of-sample split.
5. Decide: adopt, reject, or run both as paper for another week (write a `paper` flag the daily session reports on). Adoption requires a written argument addressing overfitting and regime risk.
6. Update `STRATEGY.md`, freeze the version, write `research/YYYY-MM-DD.md`, clear the inbox, rebuild site, commit `research: YYYY-MM-DD`, push.

The research prompt must warn the agent explicitly about the standard traps: overfitting to the last few weeks, survivorship bias in the universe, look-ahead in yfinance data, and changing strategy because of noise. It should be biased toward *not* changing things.

## 7. Guardrails (`bin/guardrails.py`)

This is the most important file. Requirements:
- Reads `mandate.toml` fresh. Reads today's `trades/` to count orders already attempted today.
- Validates: instrument exists (`sc broker search`/`quote` resolves the ISIN), amount ≥ min, amount ≤ max pct of NAV, resulting position ≤ max pct, orders today < max, side/amount consistent with cash or holdings, market is one the CLI can trade.
- Runs the `sc` preview, parses the confirmation payload, compares to the proposal, confirms only on exact match of ISIN and side and amount within 1%.
- Writes everything (including the raw CLI output) into the trade file. Never prints secrets.
- Exits non-zero and never confirms on any exception. No retries of confirm. Idempotent: running it twice on an executed proposal does nothing.
- Has a `--dry-run` flag that runs preview and stops, used by `run-session.sh --dry-run`.
- Unit tests in `tests/` with mocked `sc` output.

## 8. Site (`bin/build-site.py` → `site/`)

Static HTML, no build step at deploy time, GitHub Pages via Actions workflow (or branch `/site`). Pages:
- **Home**: NAV equity curve vs benchmark (Chart.js, data inlined as JSON), today's headline numbers, latest journal excerpt, current strategy version, disclaimer.
- **Journal**: every daily entry, newest first, rendered from markdown.
- **Trades**: table of every order with status, thesis link, fill, P&L since.
- **Portfolio**: current positions with entry thesis and performance.
- **Strategy**: `STRATEGY.md` rendered, with changelog and backtest charts per version.
- **Research**: weekly research entries.
- **Mistakes**: `site/mistakes.md` rendered.
- **About**: the mandate, the setup, link to repo, and a clear "not investment advice; real money; owner accepts total loss" disclaimer.

Design: clean, readable, mobile-friendly, dark-mode aware. Numbers in EUR, dates ISO. The equity curve should make it immediately obvious whether the agent is beating the benchmark.

## 9. Automation

- `systemd/framework-trader.timer`: `OnCalendar=Mon..Fri 18:15 Europe/Rome`, `Persistent=true`. Service runs `bin/run-session.sh`, logs to `~/.local/state/framework-trader/`.
- `systemd/framework-trader-research.timer`: `OnCalendar=Sat 10:00 Europe/Rome`.
- Both services load `~/.config/framework-trader/env` for `ANTHROPIC_API_KEY` (if used) and `GH_TOKEN` (if needed). Git pushes go over the SSH deploy-key remote; set `GIT_SSH_COMMAND` in the service if the systemd user session doesn't pick up `~/.ssh/config`.
- Document install/enable commands in README but **do not enable them**.
- Market holiday handling: a `data/holidays.toml` for Xetra holidays; the session should still run and write a short "market closed" journal entry.

## 10. Safety and hygiene

- `.gitignore` for env files, `sc` config, caches.
- Pre-commit hook with secret scanning (`gitleaks` or `detect-secrets`).
- `README.md` disclaimer at the top: experimental, real money, not advice, owner accepts total loss, nothing here is a recommendation to anyone.
- A `bin/kill-switch.sh` that disables both timers and writes `HALTED` to the repo root; the daily prompt must check for that file and exit if present.

## 11. Definition of done (for you, this session)

1. All files above exist; `uv run pytest` passes.
2. `python strategy/backtest.py --version current` produces a result and a chart for v001 and the benchmark.
3. `./bin/run-session.sh --dry-run` completes end to end: snapshot from the real `sc` account, data refresh, a full journal entry, proposals written, guardrails preview run, **no confirm**, site rebuilt, commit made (do not push unless the owner says so).
4. `bin/build-site.py` output opens correctly locally.
5. You write `docs/handover.md`: what you built, what you were unsure about, the exact commands for the owner's first live run and for enabling the timers, and the three things you'd watch most closely in the first week.

Then stop and tell the owner it is ready for their review.
