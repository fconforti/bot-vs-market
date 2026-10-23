# Scalable CLI (`sc`) notes

What the tool actually exposes, learned from `sc capabilities --json` (saved as
`docs/sc-capabilities.json`), `sc <cmd> --help`, the README and the public Rust source
of `ScalableCapital/scalable-cli` (v1.1.0; running 1.2.0 since 2026-10-23). Everything in this repo is built against
this, not against assumptions. Items marked **VERIFY** need a logged-in account; the read-only ones were verified on 2026-10-19.

## Envelope and exit codes

Every command with `--json` prints one JSON object:

```json
{"ok": true,  "command": "broker.holdings", "data": {...}}
{"ok": false, "command": "broker.holdings", "error": {"code": "...", "message": "..."}}
```

Exit codes: `0` ok, `1` generic error, `10` validation error, `20` auth/config error,
`30` network/backend error. `finance/sc.py` maps all of them to `ScError.exit_code`.

## Auth and session

- `sc login` is an OAuth device-code flow, marked `human_only`. There is no
  non-interactive mode. The owner logs in; the agent never does.
- Session storage defaults to the OS keyring. On this machine the keyring is not
  reachable (`DBus error: The name is not activatable`), so even `sc whoami` fails
  until `~/.config/scalable-cli/config.toml` says:

  ```toml
  [auth]
  session_backend = "file"
  ```

  This is required for headless systemd runs too. Verified 2026-10-19: with it set,
  `sc login` and every read command work.
- Access tokens refresh automatically using a refresh token. Session lifetime is not
  documented. Expect to re-run `sc login` occasionally; the daily run detects exit
  code 20 and aborts with a "needs re-login" journal entry.
  Observed: the login of 2026-10-19 ~15:57 was gone by 2026-10-21 18:17
  (`no_session`), i.e. it lasted at most about 50 hours, despite daily use. Watch
  the next one to see whether that is a fixed lifetime.
  **Documented since (vendor automation guide, "Session lifetimes and refresh"):**
  access token 20 minutes (refreshed by the CLI), idle timeout 24 hours without an
  authenticated request (read-only requests count), maximum 7 days from `sc login`.
  The short lifetimes we saw were not these limits but upstream bug #38: in 1.1.0 a
  transient failure while verifying a refreshed token (one dropped DNS packet is
  enough) deleted the session (`refresh_relogin_required`). Fixed in 1.2.0, which
  saves the rotated refresh token first and returns `refresh_retryable` (exit 30);
  `finance.sc` retries that like a network error.
- `SC_CONFIG_DIR` overrides the config directory.
- `sc login --local-read-only` blocks write commands locally. Useful for a first week
  of paper trading: the guardrails preview still works, the confirm is refused by
  the CLI itself.

## Local trade controls (second guardrail layer, outside this repo)

```toml
[trade_controls]
allowed_isins = ["IE00B4L5Y983", "..."]   # the universe
max_order_notional = "250"
```

Enforced by the CLI on phase 1 and phase 2 of buy/sell. Independent of our
`guardrails.py`, so a bug in our code cannot exceed them. The handover tells the
owner to add them.

## Read-only commands and their JSON shapes (`data`)

Verified against the real account on 2026-10-19. Account-scoped commands (`overview`,
`holdings`, `cash-breakdown`, `quote`, `transactions`) wrap their payload:
`data = {account_id, portfolio_id, resolution: {...}, result: {...}}`, and the fields
below live in `data.result`. `chart` and `security-news` are not wrapped, and `whoami`
returns `data.result.personOverview`. `finance/sc.py` unwraps this in one place
(`_payload`). Decimals arrive as JSON numbers, not strings (`sc.num` accepts both).

**Rate limit.** About 45 quotes in a quick burst returned `rate_limited` on every
call for several minutes afterwards. The daily `--check-live` therefore quotes only
holdings, the benchmark and a rotating slice of 8 instruments, one per second, and
stops at the first `rate_limited`.

- `whoami` → `{person_id, env, ...}`; only `ok` is relied on.
- `broker overview` → `{account_id, portfolio_id, valuation: {total, securities, crypto}, timestamps: {...}, performance: [{timeframe, simpleAbsoluteReturn}]}`.
  `valuation.total` is NAV (securities + cash). Decimals arrive as strings.
- `broker holdings` → `{count, items: [{isin, name, security_type, quantity, pending_quantity, blocked_quantity, fifo_price, valuation, valuation_currency, quote_mid_price, quote_currency, quote_timestamp_utc, quote_is_outdated}]}`.
  `quantity` can be fractional. `fifo_price` is the average entry price.
- `broker cash-breakdown` → `{cash_balance, buying_power, buying_power_without_credit, available_credit_line, loaned, pending_buy_orders_amount, possible_taxes, ...}`.
- `broker quote --isin X` → `{isin, name, security_type, quote_mid_price, quote_bid_price, quote_ask_price, quote_currency, quote_timestamp_utc, quote_is_outdated, quote_performances}`.
  Errors if the returned ISIN differs from the requested one, so it doubles as an
  "instrument exists" check.
- `broker search "<query>"` → `{query, count, items: [{isin, name, security_type, quote_*}]}`.
- `broker chart --isin X --timeframe 1d|7d|1m|3m|6m|ytd|1y|max` → `{isin, timeframe, currency, data_points: [{mid_price, timestamp_utc}]}`.
- `broker transactions [--status ...] [--type-filter ...] [--isin X] [--page-size N]` → `{cursor, total, count, items: [{id, summary_type, type, status, isin, side, quantity, amount, limit_price, stop_price, last_event_datetime, ...}]}`.
  **There is no open-orders command.** `--status CREATED --status REQUESTED --status PENDING --status PARTIAL_FILLED`
  is the only way to see unfilled orders. `id` is the `order_id` for `trade cancel`.
- `broker security-news --isin X --locale en_DE`.

## Order flow (two-phase, 15-minute confirmation window)

Phase 1 (preview): same arguments without `--confirm`.

```
sc broker trade buy  --isin <ISIN> --amount <EUR>     --order-type market [--venue SEIX] --json
sc broker trade buy  --isin <ISIN> --shares <WHOLE>   --order-type market [--venue SEIX] --json
sc broker trade sell --isin <ISIN> --shares <DECIMAL> --order-type market [--venue SEIX] --json
```

- Buys take `--amount` (EUR, fractional shares result) or `--shares` (whole number).
- Sells take `--shares` only, decimal allowed. There is no sell-by-amount.
- `--order-type limit` needs `--limit-price`, `stop` needs `--stop-price`.
- Venue codes in the source: `SEIX` = European Investor Exchange (EIX), `GETTEX`
  (the help text shows `MUNC`) = gettex, `XETR` = Xetra. Without `--venue` the
  backend's primary venue is used; the sample payloads in the source show `SEIX` as
  primary. **VERIFY** which code the preview accepts and returns as `selected_venue`.

Phase 1 `data`:

```
account_id, portfolio_id,
result: {
  intent: {side, isin, amount, shares, order_type, limit_price, stop_price, venue_override, locale},
  market_quote: {mid_price, ask_price, bid_price, currency, is_outdated, timestamp_utc},
  calculation: {sizing_price, estimate_price, shares, estimated_order_volume_raw, estimated_order_volume, is_whole_position_sold},
  tradability: {status, selected_venue, selected_venue_label, selected_venue_status, requires_appropriateness, tradable, selected_venue_sellable},
  warning: null | {kind, title, version, body, acknowledgement_text},
  price_warnings: {items: [...]},
  ex_ante_costs: {...},
  suitability: {status, questionnaire_required, requires_appropriateness_warning_acknowledgement, ...},
  order_submission: {submitted: false, reason: "phase_1_preview_only"},
  regulatory_disclosures: {...}, document_links: {...}
},
confirmation: {id, intent_checksum, expires_at_epoch, requires_appropriateness_warning_acknowledgement, command_template, ...},
compliance: {...}
```

Phase 2 (submit): identical arguments plus `--confirm <id>`. The CLI re-prepares the
trade, re-checks it against the stored phase-1 snapshot, then submits with an
idempotency key. `data.result.order_submission` becomes
`{submitted: true, idempotency_key, idempotency_reused, order_id, is_marketable}`.

- The confirmation id expires 15 minutes after phase 1 and is single-use.
- If the same intent is re-submitted shortly after a successful submit, the CLI
  returns the existing `order_id` with `idempotency_reused: true` instead of placing
  a second order. Our guardrails never retry anyway.
- A phase-1 preview that requires an appropriateness warning acknowledgement or a
  questionnaire is rejected by `guardrails.py` (mandate `reject_on_appropriateness`).
  The CLI would need `--acknowledge-appropriateness-warning` on phase 2; we never
  pass it.
- The execution instruction says orders are "valid for up to 360 days", i.e. an
  unfilled order (venue closed) stays open. At 18:15 EIX and gettex are open (until
  22:00), so market orders normally fill immediately.

## Fees (Scalable FREE Broker, schedule effective 2026-09-01)

| Venue | Fee |
|---|---|
| EIX (`SEIX`) | EUR 0.99 per order; EUR 0 for PRIME ETF buys (iShares, Xtrackers, Amundi, Vanguard) of EUR 250 or more |
| gettex, Xetra | EUR 1.99 per order |
| Crypto ETPs | 0.99% spread surcharge on top |

## Things the brief assumed that are not so

- "preview → confirmation ID → confirm": correct, but the CLI documents the confirm as
  a human step. The owner chose to automate it anyway.
- Sells cannot be expressed in EUR. Quantities come from the holdings snapshot.
- No open-orders listing; `transactions --status` is the workaround.
- `sc capabilities` works logged out; everything else needs a session.
