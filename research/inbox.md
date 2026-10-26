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
