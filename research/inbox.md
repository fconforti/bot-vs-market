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
