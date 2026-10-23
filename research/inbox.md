# Research inbox

Observations and ideas from the daily sessions for the next weekly research session.
Append dated items at the end. The research session clears this file after addressing
each item in its entry.

- 2026-10-18 (setup): the universe contains one crypto ETP (`DE000A27Z304`, BTCE). The
  first live preview will show whether the broker requires an appropriateness
  acknowledgement for it; if it does, the guardrails reject it every time and the
  research session should decide whether to drop it from the universe or ask the owner
  to acknowledge the warning in the app.
- 2026-10-18 (setup): `--venue SEIX` is unverified against the live account. If the
  first preview is rejected for `preview_venue`, check `selected_venue` in the trade
  file and tell the owner which code the CLI actually uses.
- 2026-10-16 (dry run, replayed on 2026-10-18): **`strategy/current.py` cannot run in a dry
  run.** `main()` calls `portfolio.latest_state(date.today())` with the default
  `dry_run=False`, so it never sees `portfolio/*-dryrun.json` and exits 2 with "no
  portfolio snapshot found". It should pass `dry_run=os.environ.get("FINANCE_DRY_RUN") == "1"`
  and use `clock.today()` instead of `date.today()` so replays with `FINANCE_TODAY` find the
  right file. Plumbing fix, not a strategy change, but it touches the algorithm file, so the
  owner or the research session should make it and re-run the dry run. A test that runs
  `current.main()` end to end in dry-run mode would have caught it.
- 2026-10-16 (dry run): the real `sc` binary, called directly in this non-graphical session,
  returned `internal_error: Platform failure: DBus error: The name is not activatable` on a
  read-only command. The likely cause is that `sc` stores its login in the secret-service
  keyring, which has no D-Bus activation under a headless or systemd session. Before the
  first live run the owner should run `sc whoami --json` from a terminal without a desktop
  session (or via `systemd-run --user`) and see whether it needs a different credential
  store or a `SC_CONFIG_DIR` setting. Otherwise the first live session will abort at
  `session-info.py` with `sc_logged_in: false`.
- 2026-10-16 (dry run): observation for the research loop, not a proposal. The Nasdaq fell
  4.5% in the week to 16 Oct led by semiconductors (AP/TheStreet). If the live book ends up
  holding the semiconductor ETF, the Nasdaq 100 ETF and the IT sector ETFs at the same time,
  four "equal weight" slots are really one bet. Worth measuring the pairwise correlation of
  the top-4 selections in the backtest before considering any sector cap.
- 2026-10-15 (dry run, replayed on 2026-10-18): **replays look one day ahead.** With
  `FINANCE_TODAY=2026-10-15` the price cache was refreshed to 2026-10-16 and
  `strategy/current.py` reported `signals.as_of = 2026-10-16` against a snapshot and session
  dated 2026-10-15. Harmless live (the newest close is never after today), but it makes a
  rehearsal dishonest: the algorithm "knows" tomorrow's close. `data.py` or the signal
  computation should clip the close series at `clock.today()`. Plumbing, not a strategy change.
- 2026-10-15 (dry run): the first two proposals of v001 were the VanEck Semiconductor ETF
  (`IE00BMC38736`) and ASML (`NL0010273215`), the same day, both at 24% of NAV. ASML is a top
  holding of that ETF. This is the concentration observation of 2026-10-16 made concrete:
  two of four slots, one bet. Same request as before: measure the overlap/correlation of the
  top-4 selections through the backtest before proposing any cap. Do not act on one day.
- 2026-10-15 (dry run): **fractional stock orders.** The EUR 240.00 buy of ASML at a close of
  EUR 1,475.60 is about 0.16 shares. The fixture preview accepts anything; the live broker may
  not accept fractional one-off market orders in single stocks. If the first live preview of a
  stock priced above the order size is rejected, the research session has to decide between
  dropping high-priced stocks from the universe and switching stock orders to whole shares
  (which breaks equal weighting on EUR 1,000).
- 2026-10-15 (dry run): `MANDATE.md` says the daily limit is "2 attempted (previewed) orders";
  `finance/trades.py` `attempted_today` counts only orders that reached the confirm step
  (executed, unknown, aborted after preview), and dry runs never count. Consequence live: two
  post-preview rejections would not stop a third preview. Either the text or the code should
  change so that they agree; the mandate file says the code wins and the disagreement gets fixed.
- 2026-10-19 (dry run, live data): **blocker for live: the broker buys whole shares only.**
  `sc broker trade buy --amount 240.00 --order-type market` on the VanEck Semiconductor ETF
  previewed as `shares: 2`, `estimated_order_volume: 182.2` (rounded down at the ask of 91.10),
  so the guardrails rejected it on `preview_amount_match` (24% short). On ASML the preview
  failed: `EX_ANTE_COST_UNAVAILABLE: amount 240 EUR is below one share at current askPrice 1486`.
  This answers the 2026-10-15 fractional-orders item: no fractional one-off orders. Consequences
  for v001 with EUR 1,000 and four slots: 11 of 42 ranked instruments are priced above EUR 240
  and can never be bought (ASML, NASDAQ 100 ETF, Rheinmetall, Core S&P 500 ETF, Microsoft,
  Allianz, LVMH, Tesla, Alphabet, Apple, Siemens, on 2026-10-19 prices); every other buy is
  rejected unless the whole-share leftover is under 1% (EUR 2.40). Options for the owner or the
  research session: size buys in whole shares via `quantity` (floor of target / ask) and widen or
  redefine the amount check accordingly; drop instruments priced above the slot size; or find out
  whether Scalable offers fractional execution another way (unverified). In every case re-run the
  backtest with whole-share sizing; at this NAV the rounding is several percent per position.
- 2026-10-19 (dry run, live data): answers to earlier items. `--venue SEIX` is correct: the live
  preview returned `selected_venue=SEIX`. The VanEck Semiconductor ETF previewed as
  `TRADABLE_WITHOUT_APPROPRIATENESS` with no price warnings. The bitcoin ETP appropriateness
  question is still untested (it ranks 40th). Costs in the preview: EUR 0.99 entry, EUR 0.99 exit,
  0.35% a year product costs for the ETF, matching the cost model.
- 2026-10-19 (dry run, live data): cosmetic. `bin/guardrails.py` line 87 labels every dry-run
  snapshot `DRY-RUN FIXTURE` in the `snapshot_today` check, even when the dry run reads the live
  account. It should say FIXTURE only when `FINANCE_SC_MODE` is `fixture`.
- 2026-10-19 (dry run, live data): timing. This rehearsal ran at about 16:40 CEST, before the
  Xetra close, so `data.py --refresh` stored an intraday price as the 2026-10-19 "close" and the
  algorithm ranked on it. Harmless at 18:15. If sessions can be started by hand at other times,
  `data.py` or `current.py` could refuse (or flag) a same-day bar fetched before 17:35 CET.
- 2026-10-20 (live): **the first live session started at 09:01 CEST, not 18:15**, one minute
  after commit `6f4b7f3` (runner network fix). I do not know whether it was started by hand,
  or by the timer catching up (`Persistent=true` fires a missed run when the timer is
  restarted; the 2026-10-19 18:15 run had failed on the network). The session declined to
  trade. Nothing in code enforces the mandate's "Session 18:15": `session-info.py` only reports
  the time and `guardrails.py` does not check it. Suggestion for the owner: have
  `run-session.sh` (live only) or `session-info.py` refuse outside a window such as
  17:45–21:00 Europe/Rome. Also decide whether a missed weekday run should be caught up at
  all; with `Persistent=true` the catch-up can land at any hour.
- 2026-10-20 (live): **the 2026-10-19 bar in the price cache is the 16:40 rehearsal's intraday
  snapshot**, and today's refresh did not replace it (see `MISTAKES.md`). Two fixes: find out
  why `refresh()` kept the cached value (does yfinance return the bar, or nothing?), and repair
  the bar. More generally, `refresh()` should always re-fetch and overwrite the last few cached
  bars, and should flag a bar that is identical across all instruments to the previous fetch.
- 2026-10-20 (live): cost-model data point, at 09:00–09:04 CEST on EIX. VanEck Semiconductor
  ETF bid/ask 88.76 / 90.12 (1.52%, against 0.02% at 16:41 the day before). S&P 500 Energy ETF
  12.884 / 12.946 (0.48%). MSCI World 130.18 / 130.23 (0.04%). ETFs that hold US stocks are
  quoted wide before New York opens. This supports the 18:15 session time, and suggests the
  first live fills should be compared with the 0.25% model.
- 2026-10-20 (live): **a second session on the same day cannot publish.** The runner commits
  `journal/<date>.md` and `portfolio/<date>.json`, and `bin/check-append-only.py` then rejects
  any later change to them. So after an off-schedule run, that day's 18:15 run fails at commit
  (exit 5). Either the runner should skip a live run when today's journal is already
  committed, or second sessions need their own file names (e.g. `<date>-2.md`).
- 2026-10-20 (live): **`bin/build-site.py` crashes once a live snapshot exists**:
  `TypeError: Object of type date is not JSON serializable` at `json.dumps` (line 294). The
  likely source is line 273, `"as_of": state.as_of` (a `datetime.date`). It never ran before,
  because there was no live snapshot. Fix: `.isoformat()`, or `json.dumps(..., default=str)`.
  Also check `equity_curve()` dates and the benchmark series. Then add a test that builds the
  site with one live snapshot present. Until it is fixed the public site does not show any
  live session. Plumbing for the owner, not a strategy change.
- 2026-10-20 (live, 18:16): **first live fills.** VanEck Semiconductor ETF: 2 shares at 90.46,
  the ask; Xetra close 89.92, mid at preview 90.195, spread 0.59%. Slippage vs close +0.60%
  (above the 0.5% watch threshold), vs mid +0.29%. Xtrackers MSCI World Value: 3 shares at
  72.88, the ask; close 72.77, mid 72.77, spread 0.30%; slippage vs close +0.15%. Two data
  points are not a sample, but the cost model's "close plus half the spread, 0.25% spread" was
  roughly right for the Value ETF and about twice too optimistic for the semiconductor ETF at
  18:19. Keep collecting before changing anything.
- 2026-10-20 (live): rank 3 vs rank 4 was decided by 0.0023 of momentum (Value ETF 0.5200 vs
  S&P 500 Energy ETF 0.5177), and the morning run, on a stale bar, had them the other way round.
  Not a flaw, just a reminder that adjacent ranks are near-ties and the daily entry order is
  partly noise. No action proposed.
- 2026-10-20 (live): doc/code mismatch. `STRATEGY.md` (v002 changelog) says share-count buys
  must have a preview value "within 2% of quantity x quote"; `bin/guardrails.py` uses
  `SELL_VOLUME_TOLERANCE = 0.03` for that check (lines 183/190, reported as "tolerance 3%"
  in today's trade files). One of the two should change so they agree.
- 2026-10-22 (live): **login lifetime is not fixed.** The 2026-10-22 08:43 login failed at about
  19:05 (`refresh_relogin_required`: refresh succeeded, verification of the new token failed),
  about 10 hours; the first lasted about 50. A login made in the morning may not survive to
  18:15. For the owner: is there any CLI or account setting that controls this? If not, the
  runner's pre-session check is the only defence, and a failure *during* the session (as today)
  costs the day. Worth logging the login time and the failure time each time to find a pattern.
- 2026-10-22 (live): **`data.py --refresh` drops instruments silently on partial yfinance
  failures.** First run: 11 tickers with no data; second run two minutes later: 6 different
  ones. A single refresh therefore leaves the held ETFs on stale closes, and `--check-live`
  then flags a false 4.4% gap on the semiconductor ETF. Suggestion: retry the failed tickers
  within `refresh()` (two or three passes) and report which remain missing. Allianz still has no
  21/22 Oct bar. Plumbing, not strategy.
- 2026-10-22 (live): the snapshot runs before the price refresh, so `portfolio/benchmark.json`'s
  last point in the snapshot was 2026-10-20 although the 2026-10-22 benchmark close was
  available minutes later. Check whether the benchmark series is filled in later (site build)
  or whether the session order should be refresh first, snapshot second.
- 2026-10-22 (live): concentration, concrete case. With slots 1 and 3 held (semiconductors,
  world value), v002 proposed slots 2 and 4 as the S&P 500 Energy ETF and the MSCI World Energy
  ETF: two funds dominated by the same US oil majors, 44% of NAV in one sector, and the value
  ETF itself is "heavy in financials and energy". The orders were not placed (login failure),
  but they will likely be proposed again. Same request as 2026-10-15/16: measure in the
  backtest how often the top-4 contains two funds of the same sector, and what a
  one-per-sector rule would have done, before proposing anything.
- 2026-10-22 (live): the semiconductor ETF fell 4.9% on the day after Lam Research's results
  (the event the 2026-10-20 session accepted at entry), and is down 5.0% from its fill. Data
  point for the research loop on whether known single-holding earnings within a few days of
  entry are worth a rule; one case proves nothing.
- 2026-10-22 (live, third session): Allianz's 12-1 momentum went from +32.0% (rank 10, last
  close 2026-10-20) to +23.4% (rank 17) once its 21–22 October closes arrived. The window
  seems to be anchored on each instrument's own last date, so a stale instrument is ranked on
  a window shifted against the others. Check in `strategy/` whether this is the case, and
  whether a stale instrument should be excluded from ranking instead (it did not affect any
  order here: Allianz does not fit a slot).
- 2026-10-22 (live, third session): rule interpretation used today: after an auth failure,
  "stop trading for today" was applied to the calendar day, so a later session that day with
  a restored login also refused. If the owner meant "this session", say so in the prompt or
  MANDATE.md.
- 2026-10-23 (live, 21:17): **fills 3 and 4.** S&P 500 Energy ETF, 17 at 13.232 (the ask);
  MSCI World Energy ETF, 3 at 74.76 (the ask). Both spreads were about 0.75% (13.132/13.232,
  74.20/74.76), three times the model's 0.25% for ETFs; cost vs mid +0.38% each. Vs the Xetra
  close almost nothing (+0.05%, -0.04%), because the funds kept moving after 17:30. Four fills
  so far: spreads 0.30%, 0.59%, 0.75%, 0.75%. Two of them were at 21:17, after the Xetra close,
  so this sample is not the 18:15 one; keep separating fills by time of day before changing the
  model.
- 2026-10-23 (live): the MSCI World Energy preview at 19:17:55Z carried a quote timestamped
  19:10:09Z (almost 8 minutes old) with `is_outdated: false`. The fill came at that same ask, so
  it cost nothing today. Worth a guardrail check: reject or flag a preview whose quote is older
  than, say, 2 minutes. Plumbing, for the owner.
- 2026-10-23 (live): **the concentration is now in the portfolio.** After today's buys about
  45% of NAV is in the two energy ETFs (the same US majors dominate both) and another 22% in the
  value ETF, which is itself heavy in energy and financials. Bought on a day both rose 4%+ on
  US-Iran headlines. Same request as 2026-10-15/16 and 2026-10-22: measure in the backtest how
  often the top-4 holds two funds of the same sector and what a one-per-sector rule would do.
- 2026-10-23 (live): this session started at 21:13, three hours after the scheduled 18:15,
  because the 18:16 run aborted on the login. Orders filled at 21:17, while US markets were
  still open and well after the Xetra close used for sizing. The strategy's prices were final,
  but the fills reflect three more hours of trading. If late manual reruns become common, the
  research session should check whether the cost model and the "close plus half spread"
  assumption still hold for them.
