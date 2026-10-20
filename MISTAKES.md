# Mistakes

Append-only. Every entry: what was wrong, what it cost, and what rule would have
prevented it. Written by the agent when a past decision turns out to be wrong, and by
the owner when the agent missed one. Lines are never removed.

_No mistakes recorded yet. The first live run has not happened._

## 2026-10-16 (dry run, replayed on 2026-10-18): the algorithm cannot run in dry-run mode

- **What was wrong:** the build session on 2026-10-18 declared the pipeline ready without
  running the daily session end to end in dry-run mode. `strategy/current.py` looks up the
  latest snapshot with `dry_run=False` hard-coded, so in a dry run it ignores the dry-run
  snapshot it was just given and exits with "no portfolio snapshot found". The first dry run
  therefore produced no signals and no proposed orders.
- **What it cost:** no money. One dry run that could not test the guardrails preview path,
  which was the point of the dry run, and one more owner-side fix before the first live day.
- **Rule that would have prevented it:** a test (or a step in the build checklist) that runs
  `bin/snapshot.py --dry-run` followed by `strategy/current.py` under `FINANCE_DRY_RUN=1` and
  asserts a JSON result. More generally: no component is "done" until the dry-run path has
  been exercised through the same entry points the session uses.

## 2026-10-19 (dry run): v001 sizes buys in fractional EUR amounts; the broker buys whole shares

- **What was wrong:** v001 and its backtest size every buy as a EUR amount (24% of NAV) and
  assume fractional units. The first real previews on 2026-10-19 showed that Scalable sizes an
  `--amount` market order in whole shares, rounded down at the ask: EUR 240 of the VanEck
  Semiconductor ETF became 2 shares, EUR 182.20, and EUR 240 of ASML failed outright
  ("below one share at current askPrice 1486"). 11 of the 42 ranked instruments are priced
  above the slot size and can never be bought; most other buys miss the guardrails' 1% amount
  tolerance. The question was raised in the 2026-10-15 rehearsal and parked in the research
  inbox instead of being checked with one read-only preview before the strategy was frozen.
- **What it cost:** no money. In a live run it would have cost the first trading day (one
  buy rejected, one aborted). Without the 1% amount check it would have silently bought 24%
  less than the strategy intended.
- **Rule that would have prevented it:** before a strategy version is frozen, run one real
  read-only preview for each order shape it can produce (a cheap ETF, an expensive stock)
  and check that the broker executes exactly what the backtest assumes. Fixture previews
  that accept any amount prove nothing about sizing.

## 2026-10-20: a rehearsal's intraday prices stayed in the live price cache

- **What was wrong:** the 2026-10-19 dry run ran at about 16:40 CEST, before the Xetra close.
  `strategy/data.py --refresh` stored that moment's prices as the 2026-10-19 bar in the price
  cache, which live and dry runs share. The session put the issue in the inbox and called it
  "harmless at 18:15", on the assumption that the next refresh would overwrite the bar. It did
  not: on 2026-10-20 all 42 ranked prices for 2026-10-19 were identical to the 16:40 values.
  For the semiconductor ETF the cached value is about 1% above the broker's own previous-close
  reference. I have not established why the refresh kept it (yfinance serving the same bar, or
  serving none so `combine_first` fell back to the cache).
- **What it cost:** no money. The 12-1 ranking does not use the last close, and the trend
  filter was 8% clear of its threshold. The share counts of both proposed orders were computed
  from the bad bar, and it was one of the three reasons today's first live session declined
  to trade.
- **Rule that would have prevented it:** a dry run must not write to the cache that live
  sessions read, or must not store a bar for a day whose close has not happened yet. And an
  item filed as "harmless" in the inbox needs the condition it depends on checked, not
  assumed.

## 2026-10-20: the site builder had never been run with a live snapshot

- **What was wrong:** `bin/build-site.py` was declared ready after being run only with
  rehearsal data, which it filters out. On the first live session it crashed
  (`TypeError: Object of type date is not JSON serializable`), probably on `state.as_of`,
  which is only filled in when a live snapshot exists.
- **What it cost:** no money. The first live session (a no-trade day) is committed to the
  repository but not shown on the public site until the owner fixes the builder.
- **Rule that would have prevented it:** the same rule as the 2026-10-16 entry, applied to
  the live path: every component must be exercised through the entry points the live
  session uses, with live-shaped data (here, one non-dry-run snapshot), before the first
  live day.

## 2026-10-20 (ops): operational failures move to OPERATIONS.md

This file is for decisions that turned out wrong: trades, refusals, market views,
strategy flaws, execution that cost more than the model. Failures of the machinery
(data, tooling, network, bugs) now go to `OPERATIONS.md`. The two entries above from
2026-10-20 are of that kind, so the site lists them under Operations:

- ops: 2026-10-20: a rehearsal's intraday prices stayed in the live price cache
- ops: 2026-10-20: the site builder had never been run with a live snapshot
