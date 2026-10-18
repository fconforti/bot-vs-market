#!/usr/bin/env python3
"""Generate site/ from journal/, trades/, portfolio/, research/, STRATEGY.md, MANDATE.md.

    uv run python bin/build-site.py

Static HTML, no build step at deploy time. Chart.js is loaded from a CDN with the
equity data inlined as JSON. Dry-run entries and snapshots are shown and labelled, but
never feed the equity curve or the headline numbers.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

import markdown
from jinja2 import Environment, FileSystemLoader, select_autoescape

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from finance import mandate as mandate_mod, paths, portfolio, trades  # noqa: E402

REPO_URL = "https://github.com/fconforti/finance"
MENU = [("index.html", "Home"), ("journal.html", "Journal"), ("trades.html", "Trades"), ("portfolio.html", "Portfolio"),
        ("strategy.html", "Strategy"), ("research.html", "Research"), ("mistakes.html", "Mistakes"),
        ("glossary.html", "Glossary"), ("about.html", "About")]
MD = markdown.Markdown(extensions=["tables", "fenced_code", "sane_lists"])
MD_ANCHORS = markdown.Markdown(extensions=["tables", "fenced_code", "sane_lists", "toc"],
                               extension_configs={"toc": {"anchorlink": True}})


def md(text: str, anchors: bool = False) -> str:
    conv = MD_ANCHORS if anchors else MD
    conv.reset()
    return conv.convert(text)


def eur(v) -> str:
    try:
        return f"EUR {float(v):,.2f}"
    except (TypeError, ValueError):
        return "—"


def pct(v) -> str:
    try:
        return f"{float(v) * 100:+.2f}%"
    except (TypeError, ValueError):
        return "—"


def fmt(v, key: str) -> str:
    if v is None:
        return "—"
    if key in ("cagr", "max_drawdown", "volatility", "total_return"):
        return f"{float(v) * 100:.1f}%"
    if key in ("fees_eur", "end_nav"):
        return f"{float(v):,.2f}"
    return str(v)


def read_entries(directory: Path) -> list[dict]:
    """Live entries only. Dry-run rehearsals (*-dryrun*.md) stay in the repo but are
    not published."""
    out = []
    for p in sorted(directory.glob("????-??-??*.md"), reverse=True):
        if "dryrun" in p.stem:
            continue
        text = p.read_text(encoding="utf-8")
        m = re.search(r"\*\*Status:\*\*\s*([^\n(]+)", text)
        status = m.group(1).strip() if m else None
        out.append({"date": p.stem, "anchor": p.stem, "dry_run": "dryrun" in p.stem,
                    "status": status, "html": md(text), "text": text})
    return out


def drop_rehearsal_sections(text: str) -> str:
    """Remove '## ...' sections whose heading mentions a dry run. The file itself is
    append-only and keeps them; the site does not publish rehearsals."""
    out, skipping = [], False
    for line in text.splitlines():
        if line.startswith("## "):
            skipping = "dry run" in line.lower() or "dry-run" in line.lower() or "rehearsal" in line.lower()
        if not skipping:
            out.append(line)
    return "\n".join(out) + "\n"


def excerpt(text: str, max_lines: int = 30) -> str:
    lines = text.splitlines()
    return md("\n".join(lines[:max_lines]) + ("\n\n…" if len(lines) > max_lines else ""))


def last_closes() -> dict[str, float]:
    try:
        from strategy import data as data_mod
        c = data_mod.closes_by_isin()
        if c.empty:
            return {}
        return {k: float(v) for k, v in c.ffill().iloc[-1].items() if v == v}
    except Exception:  # noqa: BLE001 - the site must build without a price cache
        return {}


def build() -> Path:
    env = Environment(loader=FileSystemLoader(str(paths.ROOT / "templates")), autoescape=select_autoescape(["html"]))
    env.filters["eur"] = eur
    env.filters["pct"] = pct
    env.filters["fmt"] = fmt
    man = mandate_mod.load()
    site = paths.SITE
    (site / "assets").mkdir(parents=True, exist_ok=True)
    built_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    common = {"menu": MENU, "repo_url": REPO_URL, "built_at": built_at, "initial": man.benchmark_initial_eur}

    journal = read_entries(paths.JOURNAL)
    research = read_entries(paths.RESEARCH)
    all_trades = [t for t in trades.load_all() if not t.get("dry_run")]   # rehearsals are not published
    live_snaps = portfolio.list_snapshots()
    state = portfolio.load_snapshot(live_snaps[-1]) if live_snaps else None
    display_state = state
    bench = portfolio.load_benchmark()
    bench_by_date = {r["date"]: r["value"] for r in bench.get("series", [])}
    curve = [{"date": r["date"], "nav": r["nav"], "benchmark": bench_by_date.get(r["date"])} for r in portfolio.equity_curve()]
    last_b = None
    for r in curve:
        if r["benchmark"] is None:
            r["benchmark"] = last_b
        else:
            last_b = r["benchmark"]
    closes = last_closes()
    if display_state:
        for p in display_state.positions:
            closes[p.isin] = p.price

    nav_now = state.nav if state else (display_state.nav if display_state else 0.0)
    cash_now = state.cash if state else (display_state.cash if display_state else 0.0)
    n_pos = len(state.positions) if state else (len(display_state.positions) if display_state else 0)
    start_nav = curve[0]["nav"] if curve else None
    ret_total = (nav_now / start_nav - 1) if start_nav else 0.0
    bench_now = curve[-1]["benchmark"] if curve and curve[-1]["benchmark"] else None
    ret_bench = (bench_now / man.benchmark_initial_eur - 1) if bench_now else 0.0
    last_session = journal[0] if journal else None
    try:
        with (paths.STRATEGY / "params.toml").open("rb") as fh:
            version = tomllib.load(fh).get("version", "?")
    except OSError:
        version = "?"

    pages = {}
    pages["index.html"] = env.get_template("index.html").render(
        title="Home", current="index.html", version=version, last_session=last_session, nav_now=nav_now,
        live_days=len(curve), start_date=curve[0]["date"] if curve else None,
        ret_total=ret_total, ret_vs_bench=ret_total - ret_bench, cash=cash_now, n_positions=n_pos,
        curve=curve, latest_excerpt=excerpt(last_session["text"]) if last_session else None, **common)
    pages["journal.html"] = env.get_template("journal.html").render(title="Journal", current="journal.html", entries=journal, **common)
    pages["research.html"] = env.get_template("research.html").render(title="Research", current="research.html", entries=research, **common)

    rows = []
    for t in sorted(all_trades, key=lambda d: d.get("id", ""), reverse=True):
        prev = (t.get("preview") or {}).get("result") or {}
        calc = prev.get("calculation") or {}
        est_price = calc.get("sizing_price") or calc.get("estimate_price")
        try:
            est_price_f = float(est_price) if est_price else None
        except (TypeError, ValueError):
            est_price_f = None
        pnl = None
        if t.get("status") == "executed" and est_price_f and t.get("isin") in closes:
            now_px = closes[t["isin"]]
            pnl = (now_px / est_price_f - 1) if t.get("side") == "buy" else (est_price_f / now_px - 1)
        if t.get("eur_amount") is not None:
            size = f"EUR {float(t['eur_amount']):.2f}"
        elif t.get("quantity") is not None:
            size = f"{t['quantity']} sh"
        else:
            size = "—"
        rows.append({**t, "size": size, "est_price": f"{est_price_f:.2f}" if est_price_f else None, "pnl_pct": pnl,
                     "reason": (t.get("reason") or "")[:220], "thesis": (t.get("thesis") or "")[:220],
                     "journal_anchor": t.get("date", "") + ("-dryrun" if t.get("dry_run") else "")})
    pages["trades.html"] = env.get_template("trades.html").render(title="Trades", current="trades.html", trades=rows, **common)

    positions = []
    if display_state:
        buys = {}
        for t in sorted(all_trades, key=lambda d: d.get("id", "")):
            if t.get("status") == "executed" and t.get("side") == "buy":
                buys[t["isin"]] = t
        for p in display_state.positions:
            b = buys.get(p.isin, {})
            positions.append({"isin": p.isin, "name": p.name, "quantity": p.quantity, "price": p.price, "value_eur": p.value_eur,
                              "weight": p.value_eur / display_state.nav if display_state.nav else 0, "fifo_price": p.fifo_price,
                              "unrealised": p.unrealised_pct, "thesis": (b.get("thesis") or "")[:300], "trade_id": b.get("id")})
    pages["portfolio.html"] = env.get_template("portfolio.html").render(
        title="Portfolio", current="portfolio.html", state=display_state, positions=positions,
        benchmark={"isin": man.benchmark_isin, "name": man.benchmark_name, "start_date": bench.get("start_date"),
                   "last": bench["series"][-1] if bench.get("series") else None}, **common)

    strategy_path = paths.ROOT / "STRATEGY.md"
    strategy_md = strategy_path.read_text(encoding="utf-8") if strategy_path.exists() else "# Strategy\n\n(not written yet)"
    backtests = []
    for p in sorted((paths.RESEARCH / "backtests").glob("v*.json")):
        try:
            b = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            continue
        png = p.with_suffix(".png")
        b["chart"] = None
        if png.exists():
            shutil.copy(png, site / "assets" / png.name)
            b["chart"] = f"assets/{png.name}"
        backtests.append(b)
    pages["strategy.html"] = env.get_template("strategy.html").render(title="Strategy", current="strategy.html",
                                                                       strategy_html=md(strategy_md), backtests=backtests, **common)
    mistakes_md = paths.MISTAKES.read_text(encoding="utf-8") if paths.MISTAKES.exists() else "# Mistakes\n\nNone recorded yet."
    mistakes_md = drop_rehearsal_sections(mistakes_md)
    pages["mistakes.html"] = env.get_template("mistakes.html").render(title="Mistakes", current="mistakes.html", html=md(mistakes_md), **common)
    glossary_path = paths.DOCS / "glossary.md"
    glossary_md = glossary_path.read_text(encoding="utf-8") if glossary_path.exists() else "# Glossary\n\n(not written yet)"
    pages["glossary.html"] = env.get_template("glossary.html").render(title="Glossary", current="glossary.html", html=md(glossary_md, anchors=True), **common)
    mandate_md = (paths.ROOT / "MANDATE.md").read_text(encoding="utf-8")
    pages["about.html"] = env.get_template("about.html").render(title="About", current="about.html", mandate_html=md(mandate_md), **common)

    for name, html in pages.items():
        (site / name).write_text(html, encoding="utf-8")
    (site / "data").mkdir(exist_ok=True)
    (site / "data" / "equity.json").write_text(json.dumps({"curve": curve, "built_at": built_at}, indent=1) + "\n", encoding="utf-8")
    (site / ".nojekyll").touch()
    return site


if __name__ == "__main__":
    out = build()
    print(f"site built in {out}")
