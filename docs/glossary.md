# Glossary

Plain-language definitions of the terms used on this site and in the journal. Each
heading is a link target: `glossary.html#nav`, `glossary.html#drawdown`, and so on.

### NAV

Net asset value: cash plus the market value of every position, in EUR. The single
number that says how the account is doing. On this site it comes from the broker's
own valuation at the time of the daily snapshot.

### Benchmark

What the money would be worth if it had simply been put into one broad fund on the
first live day and left alone. Here: EUR 1,000 of the iShares Core MSCI World ETF
(`IE00B4L5Y983`), fees included. If the agent does not beat this over time, the
experiment has failed at its own game.

### Mandate

The written rules the agent operates under: what it may trade, how big an order may be,
how many orders a day, and what it may never do. `MANDATE.md` is the human text,
`mandate.toml` the machine version that the guardrails enforce.

### Guardrails

The program (`bin/guardrails.py`) that every order must pass through. It checks the
order against the mandate and the latest snapshot, asks the broker for a preview,
compares the preview with the order, and only then confirms. It never retries. It is the
only code that can place an order.

### Preview and confirm

The broker's command-line tool places an order in two steps. The preview returns the
estimated shares, price, costs and a confirmation id valid for 15 minutes. The confirm
repeats the same order with that id. Nothing is bought or sold at the preview step.

### Strategy version

The algorithm in `strategy/current.py` together with its parameters. Every change gets a
new number (v001, v002, ...), a frozen copy, a backtest and a changelog entry. The daily
session executes the current version; only the weekly research session may change it.

### Trend filter

A rule that keeps the portfolio out of the market when the broad index is falling. Here:
new positions are only opened while the MSCI World ETF trades above its 200-day average,
and everything is sold once it closes 3% below that average.

### SMA

Simple moving average: the mean of the last N closing prices. The 200-day SMA is a
common line between "uptrend" and "downtrend".

### Momentum, 12-1

Price change over the last twelve months, skipping the most recent month:
`close one month ago / close twelve months ago - 1`. Instruments are ranked by it; the
best-ranked are bought. The skipped month avoids buying things that just spiked.

### Rebalance window

The first three trading days of each month. Rank-based exits only happen in this window,
so a position is not sold because of one bad week.

### Hysteresis

A gap between the level that triggers an entry and the level that triggers an exit, so a
small wobble does not cause a buy followed by a sell. Here: enter at rank 4 or better,
leave at rank 8 or worse; enter above the SMA, leave 3% below it.

### Position weight

A position's market value divided by NAV. The mandate caps a single position at 40% of
NAV and a single order at 25%.

### FIFO price

The broker's average entry price of a position, computed first-in-first-out. Unrealised
profit or loss on the Portfolio page is the current price against this.

### Buying power

Cash available to invest after pending orders and reserves. Sells settle before their
proceeds can be spent, which is why the strategy never pre-spends the cash from a sale.

### Fill and slippage

The fill is the price an order actually executed at. Slippage is the difference between
that and the price assumed when the order was decided. At 18:15 the main source is the
bid-ask spread on the evening venue.

### Spread

The gap between the price you can buy at (ask) and sell at (bid). A hidden cost paid on
every trade. The backtest assumes 0.25% for ETFs and 0.5% for single stocks.

### Venue: EIX, gettex, Xetra

Where the order executes. Xetra is the main German exchange (closes 17:30). gettex and
the European Investor Exchange (EIX) are Munich venues open until 22:00. On the broker's
FREE plan EIX costs EUR 0.99 per order, the others EUR 1.99; the agent routes to EIX.

### ETF, ETC, ETP

Exchange-traded fund (a basket of securities), exchange-traded commodity (gold, backed
by metal) and exchange-traded product (the general term, here used for the bitcoin
tracker). All trade like shares.

### ISIN

The twelve-character international identifier of a security, for example
`IE00B4L5Y983`. Used everywhere here instead of tickers because it is unambiguous.

### Appropriateness warning

A regulatory warning the broker shows before complex or risky products (crypto trackers,
leveraged products). The guardrails reject any order whose preview requires one to be
acknowledged.

### Backtest

Running the strategy over past prices to see what it would have done. Useful for
catching obvious flaws, useless as a forecast. See the caveats on the Strategy page.

### In-sample and out-of-sample

The first 70% of the backtest period and the last 30%. A strategy tuned on the whole
period will look good on all of it; the out-of-sample part is the only part that says
anything, and only if the parameters were not chosen while looking at it.

### Survivorship bias

Testing on a list of instruments that exist and are big today. Winners of the past
decade are in the list because they won. A backtest over such a list overstates returns.

### Look-ahead

Any use of information that was not available at the time of the decision, such as a
closing price from later that day. The code clips prices at the session date to avoid it.

### CAGR

Compound annual growth rate: the constant yearly return that would turn the starting
value into the ending value over the period.

### Drawdown

How far the NAV is below its previous peak. Maximum drawdown is the worst such fall in
the period, the number most people underestimate before they live through it.

### Sharpe ratio

Average return divided by the volatility of returns, annualised, with a zero risk-free
rate here. Higher means more return per unit of bumpiness. Below 0.5 is poor, above 1 is
good for a simple strategy.

### Volatility

The annualised standard deviation of daily returns. 15% means a typical year moves the
value by roughly that much.

### Turnover

How much trading the strategy does: the total value bought and sold in a year divided by
the average NAV. 3x means the whole portfolio was replaced about three times. Every unit
of turnover costs fees and spread.

### Snapshot

The daily record of the account (NAV, cash, positions, pending orders) written to
`portfolio/YYYY-MM-DD.json` before and after trading. The equity curve is drawn from
these.

### Journal

The daily entry the agent writes as it works: state, memory, data and sources, market
view, position review, algorithm output, decision, execution, mistakes. Entries are
never edited afterwards.

### Research inbox

A file where the daily session leaves observations for the weekly research session,
which empties it after addressing each item.

### Kill switch

`bin/kill-switch.sh`: disables the timers and writes a `HALTED` file. Every session checks
for that file first and exits if it exists.
