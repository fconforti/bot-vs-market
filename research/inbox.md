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
