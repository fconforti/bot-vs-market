# Research inbox

Observations and ideas from the daily sessions for the next weekly research session.
Append dated items at the end. The research session clears this file after addressing
each item in its entry.

cleared on 2026-11-07 by the research session

## 2026-11-12: single-company event risk in sector funds between monthly windows

- Nvidia announced on 12 Nov that Jensen Huang is stepping down as CEO (CFO Colette Kress
  interim), with Q3 results reportedly still on 17 Nov. NVD.DE closed -5.2% on Xetra;
  the semiconductor fund (VVSM, ~18% of NAV, Nvidia its largest holding) closed only
  -0.3% because other chipmakers (AMD) rose.
- v002 has no position-level exit between monthly windows; the only mid-month exit is
  the MSCI World trend filter. That was right by design today (the fund barely moved),
  but the question is open: should a sector fund whose top holding faces a governance
  shock plus earnings inside the next 5 days be treated differently? The daily session
  cannot act on it (no orders proposed, no freestyling). Worth checking: does any
  backtestable rule (e.g. a per-position drawdown stop, or skipping entries that fall
  in the 5 days before the top holding reports) improve the risk/return in the backtest,
  or is it just reacting to a headline?

## 2026-11-13: follow-up to the 12 Nov event-risk item

- The day after Nvidia's CEO exit, the semiconductor fund (VVSM) closed -5.05% on Xetra
  (NVD.DE -3.0%, ASML -2.8%); US chips sold off broadly (AMD about -10%, Broadcom -6%
  intraday per Yahoo Finance). The fund is now -9.8% vs FIFO cost and still ranks 1st by
  momentum (+79.0%), so v002 holds it until the 1-3 Dec window. NAV impact: -EUR 7.67
  of a -EUR 8.81 day. Nvidia reports on 17 Nov. Data point for the per-position-stop
  question: what would a backtested drawdown stop (e.g. -10% from entry) have done here,
  and how often does such a stop fire on noise in the backtest?
