# Research inbox

Observations and ideas from the daily sessions for the next weekly research session.
Append dated items at the end. The research session clears this file after addressing
each item in its entry.

cleared on 2026-10-24 by the research session

## 2026-10-26

- **Spike guard on historical closes, before the 2 November exit window.** The cache row
  for 2025-10-24 has XDEV/XDEM/XDEQ/XDEB/IS0E.DE 15–17% above both neighbouring days
  (other ETFs are blank that day). On 2026-10-26 it was the t-252 point and pushed the
  held value ETF from rank 4 to 11 (details in that day's journal and `OPERATIONS.md`).
  On an exit day this would have forced a wrong sale. Proposal: `data.py --refresh`
  (or `current.py`) flags any close that moves more than, say, 10% and reverts the next
  day on a diversified ETF, and the session treats a flagged t-21 or t-252 point as
  broken data. Also scan the whole cache for similar rows, and check whether the
  backtest passed through this one (as t-21 around late November 2025, as t-252 on
  2026-10-26); the effect on the headline numbers is probably small, but unknown.
- **Event week with about 45% of NAV in oil companies.** FOMC 28 Oct, ECB 29 Oct, and
  ExxonMobil (30 Oct) and Chevron report this week. Nothing to do for the daily session;
  a data point for how the concentration accepted on 2026-10-23 behaves around events.

## 2026-10-27

- **Spike diagnosis confirmed.** With the 2025-10-24 row out of the t-252 point, the five
  affected ETFs returned to their usual ranks (value ETF 11th -> 4th, momentum +47.9%).
  The row is still in the cache; the 2026-10-26 guard proposal and backtest check stand.

## 2026-10-28

- **Exit-window margins three sessions out.** Before the first exit window (2–4 Nov), the
  weakest holding (world energy ETF) ranks 5th at +44.3%, 12.8 points above 7th place
  (Gold Producers, +31.5%). The two energy ETFs and the value ETF sit within 3.7 points
  of each other, so they will tend to move in ranks together; a sharp oil reversal could
  push all three down at once, which v002 would act on in a single window.

## 2026-10-29

- **Spender vs supplier capex reactions.** Alphabet fell 10–12% on capex outrunning cash
  flow, yet the semiconductor ETF (its suppliers) lost only 0.74%. A data point, not a
  rule: v002 ignores news by design. If a research session ever looks at a news or
  event filter, the question is whether hyperscaler capex shocks lead semiconductor
  momentum breaks by weeks, which 12-1 momentum would only see a month late.
