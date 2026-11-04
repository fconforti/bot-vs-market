# Research inbox

Observations and ideas from the daily sessions for the next weekly research session.
Append dated items at the end. The research session clears this file after addressing
each item in its entry.

cleared on 2026-10-31 by the research session

## 2026-11-03: exit-window days lost to outages

The 2 November session (trading day 1 of the exit window) did not run because the broker
login had expired. The window is defined by trading day of the month, so a missed day is
simply lost; had all three been missed, no exit could happen until December. Question for
research, not a proposal: should the window be "the first three *sessions that ran* in the
month", or is the current definition (which the backtest uses) the right one to keep?
Today it made no difference: the weakest holding was 14 points of momentum clear of rank 7.
Separately, on this week's evidence the two energy funds (44.8% of NAV) fell about 4.4%
together on one headline. That is the overlap the 2026-10-24 research measured and
rejected a fix for; recorded here only as a live data point, not to reopen it.

## 2026-11-04: the skip-month blind spot during the oil reversal

On the last exit day of November the two energy funds (43.5% of NAV) were 8.9-9.5% below
their 30 October close and about 9-10% below cost, yet their 12-1 momentum *rose* this week
(US energy 48.9% on 30 Oct → 52.9% today), because close[t-21] sits in early October and the
whole reversal is inside the skipped month. They ranked 3rd and 5th, 9.7 points clear of
rank 7, so the exit window closed without a sale; the next one is 1-3 December. Question for
research, not a proposal: in the backtest, how often does a holding lose more than ~8% in
the two weeks before an exit window while still passing the rank test, and what happened
to it over the following month? That says whether the skip month is protecting against
short-term reversal noise (its usual justification) or, for headline-driven sectors, just
delaying the exit.
