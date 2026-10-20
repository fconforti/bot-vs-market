"""The site exporter publishes live data only and keeps glossary anchors stable."""
from __future__ import annotations

import importlib.util
import json
import re
import shutil

from finance import paths, trades
from tests.conftest import REPO


def _exporter():
    spec = importlib.util.spec_from_file_location("build_site", REPO / "bin" / "build-site.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _seed(root):
    shutil.copy(REPO / "MANDATE.md", root / "MANDATE.md")
    shutil.copy(REPO / "docs" / "glossary.md", root / "docs" / "glossary.md")
    (root / "journal" / "2026-10-19.md").write_text("# 2026-10-19 — daily session\n\n- **Status:** completed\n\nLive entry.\n")
    (root / "journal" / "2026-10-20-dryrun.md").write_text("# 2026-10-20 — daily session\n\n- **Status:** completed\n\nREHEARSAL TEXT\n")
    (root / "MISTAKES.md").write_text("# Mistakes\n\nIntro.\n\n## 2026-10-19: live slip\n\nReal.\n\n"
                                      "## 2026-10-20 (dry run): rehearsal slip\n\nREHEARSAL TEXT\n"
                                      "## 2026-10-20: the cache broke\n\nPLUMBING\n\n"
                                      "## 2026-10-21 (ops): split\n\n- ops: 2026-10-20: the cache broke\n")
    (root / "OPERATIONS.md").write_text("# Operations log\n\nIntro.\n\n## 2026-10-19: wifi\n\nDROPPED\n")


def test_export_skips_dry_runs(repo):
    _seed(repo)
    from datetime import date
    live = trades.new_proposal(day=date(2026, 10, 19), isin="IE00B5BMR087", side="buy", eur_amount=100)
    dry = trades.new_proposal(day=date(2026, 10, 20), isin="IE00B5BMR087", side="buy", eur_amount=100)
    t = trades.load(dry)
    t["dry_run"] = True
    t["status"] = "dry_run"
    trades.write(dry, t)

    mod = _exporter()
    out = mod.build()
    assert out == paths.SITE_DATA
    data = json.loads(out.read_text())
    blob = json.dumps(data)
    assert "REHEARSAL TEXT" not in blob
    assert "dryrun" not in blob
    assert [e["date"] for e in data["journal"]] == ["2026-10-19"]
    assert [t["id"] for t in data["trades"]] == [trades.load(live)["id"]]
    assert "live slip" in data["mistakes_html"] and "rehearsal slip" not in data["mistakes_html"]
    # machinery entries leave the Mistakes page for the Operations page, append-only
    assert "PLUMBING" not in data["mistakes_html"] and "(ops)" not in data["mistakes_html"]
    assert "PLUMBING" in data["operations"]["from_mistakes_html"]
    assert "DROPPED" in data["operations"]["html"] and "Intro." not in data["operations"]["html"]
    assert data["live"] is False and data["home"]["nav"] is None


def test_glossary_terms_match_heading_ids(repo):
    _seed(repo)
    data = _exporter().build_data()
    ids = set(re.findall(r'<h3 id="([^"]+)"', data["glossary"]["html"]))
    slugs = [t["slug"] for t in data["glossary"]["terms"]]
    assert slugs and set(slugs) == ids


def test_site_term_links_resolve():
    """Every <Term id="..."> and glossary/#... link in the Astro sources exists in the glossary."""
    from markdown.extensions.toc import slugify
    gloss = (REPO / "docs" / "glossary.md").read_text()
    ids = {slugify(l[4:].strip(), "-") for l in gloss.splitlines() if l.startswith("### ")}
    used = set()
    for f in (REPO / "web" / "src").rglob("*.astro"):
        s = f.read_text()
        used |= set(re.findall(r'<Term id="([^"]+)"', s))
        used |= set(re.findall(r'glossary/#([a-z0-9-]+)', s))
    used |= {"cagr", "drawdown", "sharpe-ratio", "volatility", "turnover", "nav"}   # strategy.astro termFor map
    assert used and not (used - ids), sorted(used - ids)


def test_export_with_a_live_snapshot(repo):
    """The first real snapshot (2026-10-20) crashed the exporter: nothing had ever
    built the site from live data."""
    _seed(repo)
    from datetime import date
    from finance import portfolio
    from finance.models import PortfolioState
    state = PortfolioState(as_of=date(2026, 10, 19), nav=1000.0, cash=1000.0, buying_power=1000.0, positions=())
    portfolio.write_snapshot(state, {"overview": {}})
    data = json.loads(_exporter().build().read_text())
    assert data["live"] is True and data["home"]["nav"] == 1000.0
    assert data["portfolio"]["state"]["as_of"] == "2026-10-19"


JOURNAL_NEW = """# 2026-10-21 — daily session
- **Status:** completed
- **Mode:** live
- **Strategy:** v002
- **Orders:** 2 proposed, 2 executed, 0 rejected (both filled)

## The day
Bought two ETFs. NAV EUR 998.

## Market view
Quiet.

## Decision
Accepted both orders.

## Technical log
### 0. Session facts
```
{"date": "2026-10-21"}
```
### 8. Execution
guardrails said ok
"""

JOURNAL_LEGACY = """# 2026-10-20 — daily session
- **Status:** no-trade
- **Strategy:** v002

## 0. Session facts
JSON DUMP

## 1. State
NAV table

## 4. Market view
Bounce.

## 7. Decision
Refused.

## 11. Publish
build failed
"""


def test_journal_entries_split_reader_part_from_technical_log(repo):
    _seed(repo)
    (repo / "journal" / "2026-10-21.md").write_text(JOURNAL_NEW)
    (repo / "journal" / "2026-10-20.md").write_text(JOURNAL_LEGACY)
    data = json.loads(_exporter().build().read_text())
    new, legacy = data["journal"][0], data["journal"][1]
    assert new["status"] == "completed" and new["meta"] == {"mode": "live", "strategy": "v002", "orders": "2 proposed, 2 executed, 0 rejected (both filled)"}
    assert "Bought two ETFs" in new["html"] and "guardrails" not in new["html"] and "<li>" not in new["html"]
    assert "guardrails said ok" in new["tech_html"] and "Session facts" in new["tech_html"]
    assert new["excerpt_html"].strip() == "<p>Bought two ETFs. NAV EUR 998.</p>"
    # before the split existed: market view, positions and decision stay open, the rest folds
    assert "JSON DUMP" not in legacy["html"] and "build failed" not in legacy["html"]
    assert "Bounce." in legacy["html"] and "<h2>Market view</h2>" in legacy["html"] and "NAV table" not in legacy["html"]
    assert "JSON DUMP" in legacy["tech_html"] and "build failed" in legacy["tech_html"] and "NAV table" in legacy["tech_html"]
    assert legacy["excerpt_html"].strip() == "<p>Refused.</p>"


def test_second_session_the_same_day_keeps_both_parts():
    mod = _exporter()
    text = JOURNAL_NEW + "\n---\n\n# Second session, 18:20\n- **Status:** completed\n- **Orders:** 3 proposed, 3 executed, 0 rejected\n\n## The day\nThird buy.\n\n## Technical log\n### 8. Execution\nlater ok\n"
    reader, tech, meta = mod.split_entry(text)
    assert "Second session, 18:20" in reader and "Third buy." in reader and "later ok" not in reader
    assert "later ok" in tech and "guardrails said ok" in tech
    assert meta["orders"].startswith("3 proposed")


def test_site_shows_the_post_trade_snapshot(repo):
    """2026-10-20: the first trading day's site still said "all cash" because the
    exporter read the pre-trade snapshot only. The portfolio page and the equity
    curve must use the last snapshot of each day."""
    _seed(repo)
    from datetime import date
    from finance import portfolio
    from finance.models import PortfolioState, Position
    pre = PortfolioState(as_of=date(2026, 10, 20), nav=1000.0, cash=1000.0, buying_power=1000.0, positions=())
    pos = Position(isin="IE00BMC38736", name="VanEck Semiconductor", quantity=2, price=90.2, value_eur=180.4)
    post = PortfolioState(as_of=date(2026, 10, 20), nav=997.2, cash=816.8, buying_power=816.8, positions=(pos,))
    portfolio.write_snapshot(pre, {})
    portfolio.write_snapshot(post, {}, post_trade=True)
    data = json.loads(_exporter().build().read_text())
    assert data["portfolio"]["state"]["cash"] == 816.8
    assert [p["isin"] for p in data["portfolio"]["positions"]] == ["IE00BMC38736"]
    assert [r["nav"] for r in portfolio.equity_curve()] == [997.2]
