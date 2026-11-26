# Research inbox

Observations and ideas from the daily sessions for the next weekly research session.
Append dated items at the end. The research session clears this file after addressing
each item in its entry.

cleared on 2026-11-21 by the research session

## 2026-11-25: first close below the 200-day average in the live period

EUNL.DE closed at 122.24, 0.45% below its SMA200 (122.79); `trend_on` is false, `trend_exit`
false, exit level 119.11 (2.6% below the close). Nothing changed today (all four slots
full, not a window). Observation, not a proposal: if the index stays inside the band
through 1–3 December, any holding sold at the window cannot be replaced, so the book
would drift towards cash without the exit ever triggering. How often did the backtest
sit in the band at a window, and how did those months turn out versus the exit case?

## 2026-11-26: back above the 200-day average after one day

EUNL.DE closed at 125.825 (+2.93%), 2.41% above its SMA200 (122.86); `trend_on` true
again, exit level 119.17 (5.3% below). The filter flipped off and on in two sessions with
no order either time. Observation for the research session: how often does the backtest
flip `trend_on` within a few days, and would a window falling on an "off" day of such a
flicker have blocked a refill that the next day would have allowed?
