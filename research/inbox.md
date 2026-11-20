# Research inbox

Observations and ideas from the daily sessions for the next weekly research session.
Append dated items at the end. The research session clears this file after addressing
each item in its entry.

cleared on 2026-11-14 by the research session

- 2026-11-18 (daily): the two energy funds (IE00B42NKQ00, IE00BM67HM91) moved -2.61% and
  -2.68% on a day the benchmark moved +0.02%: together 44% of NAV, they behave as one
  position (EUR -11.75 of the day's EUR -11.11 NAV change). v002 ranks instruments
  independently and can fill two of four slots with near-duplicates. Question for
  research: does a correlation or same-sector cap (e.g. skip a candidate whose 60-day
  return correlation with a holding is above 0.9) improve backtested drawdown without
  overfitting? Observation only; one day is not evidence.

- 2026-11-19 (daily): the daily NAV uses broker mid quotes at ~18:15 Rome, while the
  benchmark value uses the Xetra close at 17:30. On 2026-11-19 US stocks fell after
  Frankfurt closed: the benchmark ETF's broker mid was 1.29% below its Xetra close, so
  the published gap (6.41 points) was about 1.3 points worse for the portfolio than a
  like-for-like comparison (5.15). Question for research: value the benchmark at the
  broker mid taken in the same snapshot (or value both at Xetra closes), so the daily
  comparison is not biased by after-close moves. Measurement only, not strategy.

- 2026-11-20 (daily): VanEck Semiconductor (IE00BMC38736) fell 11.60% at the Xetra close
  and is 23% below its purchase price, yet it is still ranked 1st (+72.7%), because 12-1
  momentum ignores the last 21 trading days. Between monthly windows, only the
  index-wide trend exit can sell it, and that exit is 3.1% away (MSCI World +0.08% above
  its SMA200). The 2026-10-31 crash-exit candidate already tested a per-position
  stop. This is a live data point for revisiting it, not a new mechanism. Question: in the
  backtest, how often did a held instrument lose more than 20% from entry inside one
  month while still ranked 7th or better, and what did holding it to the window cost on
  average versus selling it? Observation only.
