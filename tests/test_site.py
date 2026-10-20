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
                                      "## 2026-10-20 (dry run): rehearsal slip\n\nREHEARSAL TEXT\n")


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
