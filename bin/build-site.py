#!/usr/bin/env python3
"""Export the site data for the Astro site in web/.

    uv run python bin/build-site.py            # writes web/src/data/site.json

The Python side owns everything that needs the repo's data model: which entries are
live (dry-run rehearsals stay in the repo but are never published), the equity curve,
the trade and position tables, and the markdown → HTML rendering. The Astro project
in web/ only lays this JSON out; GitHub Actions builds it on every push to web/.

Dry-run entries, trade files and snapshots never reach the JSON. Mistakes entries
whose heading mentions a dry run are dropped from the published page.
"""
from __future__ import annotations

import json
import re
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

import markdown

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from finance import mandate as mandate_mod, paths, portfolio, trades  # noqa: E402

REPO_URL = "https://github.com/fconforti/bot-vs-market"
SITE_URL = "https://fconforti.github.io/bot-vs-market/"
MD = markdown.Markdown(extensions=["tables", "fenced_code", "sane_lists"])
MD_SECTIONS = markdown.Markdown(extensions=["tables", "fenced_code", "sane_lists", "toc"],
                                 extension_configs={"toc": {"anchorlink": False, "toc_depth": "2-2"}})
MD_ANCHORS = markdown.Markdown(extensions=["tables", "fenced_code", "sane_lists", "toc"],
                               extension_configs={"toc": {"anchorlink": False, "toc_depth": "3-3"}})


def scroll_tables(html: str) -> str:
    """Wrap tables so wide ones scroll sideways on phones instead of widening the page."""
    return html.replace("<table>", '<div class="table-scroll"><table>').replace("</table>", "</table></div>")


def md(text: str, anchors: bool = False) -> str:
    conv = MD_ANCHORS if anchors else MD
    conv.reset()
    return scroll_tables(conv.convert(text))


def strip_h1(text: str) -> str:
    """Pages render their own title; drop a leading '# Title' from markdown documents."""
    lines = text.lstrip().splitlines()
    if lines and lines[0].startswith("# "):
        return "\n".join(lines[1:]).lstrip("\n")
    return text


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
        title_m = re.match(r"#\s+(.+)", text.lstrip())
        out.append({"date": p.stem, "anchor": p.stem, "status": status,
                    "title": title_m.group(1).strip() if title_m else p.stem,
                    "html": md(text), "excerpt_html": excerpt(text)})
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


def strategy_doc(text: str) -> dict:
    """STRATEGY.md for the Strategy page: the plain-language summary paragraph, the
    full document with h2 anchors, and the list of h2 sections for a side index."""
    import re as _re
    body = strip_h1(text)
    m = _re.search(r"^## [^\n]*plain language[^\n]*\n+(.+?)\n\n", body, _re.M | _re.S)
    summary = " ".join(m.group(1).split()) if m else ""
    MD_SECTIONS.reset()
    html = scroll_tables(MD_SECTIONS.convert(body))
    sections = [{"title": t["name"], "slug": t["id"]} for t in MD_SECTIONS.toc_tokens if t["level"] == 2]
    return {"summary": summary, "html": html, "sections": sections}


def strategy_facts() -> dict:
    """Parameters and universe counts, so the page's key-decision cards always show the
    numbers the live algorithm actually uses."""
    import csv
    try:
        with (paths.STRATEGY / "params.toml").open("rb") as fh:
            params = tomllib.load(fh)
    except OSError:
        params = {}
    counts: dict[str, int] = {}
    try:
        with (paths.STRATEGY / "universe.csv").open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                counts[row.get("type", "?")] = counts.get(row.get("type", "?"), 0) + 1
    except OSError:
        pass
    return {"params": params, "universe": counts}


def sections_only(text: str) -> str:
    """Entries only ('## ...' sections); the page header already carries the intro."""
    i = text.find("\n## ")
    return text[i + 1:] if i >= 0 else ""


def glossary_body(text: str) -> str:
    """The terms only: the page header already carries the intro above the first term."""
    i = text.find("\n### ")
    return text[i + 1:] if i >= 0 else strip_h1(text)


def glossary_terms(text: str) -> list[dict]:
    """Term index for the glossary page: one entry per '### Heading', with the same slug
    python-markdown's toc extension generates for the heading id."""
    from markdown.extensions.toc import slugify
    terms = []
    for line in text.splitlines():
        if line.startswith("### "):
            title = line[4:].strip()
            terms.append({"title": title, "slug": slugify(title, "-")})
    return terms


def last_closes() -> dict[str, float]:
    try:
        from strategy import data as data_mod
        c = data_mod.closes_by_isin()
        if c.empty:
            return {}
        return {k: float(v) for k, v in c.ffill().iloc[-1].items() if v == v}
    except Exception:  # noqa: BLE001 - the site must build without a price cache
        return {}


def _float(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def build_data() -> dict:
    man = mandate_mod.load()
    built_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    journal = read_entries(paths.JOURNAL)
    research = read_entries(paths.RESEARCH)
    all_trades = [t for t in trades.load_all() if not t.get("dry_run")]   # rehearsals are not published
    live_snaps = portfolio.list_snapshots()
    state = portfolio.load_snapshot(live_snaps[-1]) if live_snaps else None
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
    if state:
        for p in state.positions:
            closes[p.isin] = p.price

    nav_now = state.nav if state else None
    cash_now = state.cash if state else None
    n_pos = len(state.positions) if state else 0
    start_nav = curve[0]["nav"] if curve else None
    ret_total = (nav_now / start_nav - 1) if (start_nav and nav_now) else None
    bench_now = curve[-1]["benchmark"] if curve and curve[-1]["benchmark"] else None
    ret_bench = (bench_now / man.benchmark_initial_eur - 1) if bench_now else None
    last_session = journal[0] if journal else None
    try:
        with (paths.STRATEGY / "params.toml").open("rb") as fh:
            version = tomllib.load(fh).get("version", "?")
    except OSError:
        version = "?"

    rows = []
    for t in sorted(all_trades, key=lambda d: d.get("id", ""), reverse=True):
        prev = (t.get("preview") or {}).get("result") or {}
        calc = prev.get("calculation") or {}
        est_price_f = _float(calc.get("sizing_price") or calc.get("estimate_price"))
        pnl = None
        if t.get("status") == "executed" and est_price_f and t.get("isin") in closes:
            now_px = closes[t["isin"]]
            pnl = (now_px / est_price_f - 1) if t.get("side") == "buy" else (est_price_f / now_px - 1)
        rows.append({
            "id": t.get("id"), "date": t.get("date"), "side": t.get("side"), "isin": t.get("isin"),
            "name": t.get("name"), "status": t.get("status"), "order_type": t.get("order_type"),
            "eur_amount": _float(t.get("eur_amount")), "quantity": _float(t.get("quantity")),
            "est_price": est_price_f, "pnl_pct": pnl, "venue": t.get("venue"),
            "reason": (t.get("reason") or "")[:300], "thesis": (t.get("thesis") or "")[:300],
            "rejection": (t.get("rejection") or t.get("error") or "")[:300] if isinstance(t.get("rejection") or t.get("error"), str) else "",
            "order_id": t.get("order_id"), "journal_anchor": t.get("date", ""),
        })

    positions = []
    if state:
        buys = {}
        for t in sorted(all_trades, key=lambda d: d.get("id", "")):
            if t.get("status") == "executed" and t.get("side") == "buy":
                buys[t["isin"]] = t
        for p in state.positions:
            b = buys.get(p.isin, {})
            positions.append({"isin": p.isin, "name": p.name, "quantity": p.quantity, "price": p.price, "value_eur": p.value_eur,
                              "weight": p.value_eur / state.nav if state.nav else 0, "fifo_price": p.fifo_price,
                              "unrealised": p.unrealised_pct, "thesis": (b.get("thesis") or "")[:300], "trade_id": b.get("id")})

    strategy_path = paths.ROOT / "STRATEGY.md"
    strategy_md = strategy_path.read_text(encoding="utf-8") if strategy_path.exists() else "# Strategy\n\n(not written yet)"
    backtests = []
    for p in sorted((paths.RESEARCH / "backtests").glob("v*.json")):
        try:
            b = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            continue
        backtests.append({
            "version": b.get("version"), "period": b.get("period"), "generated_at": b.get("generated_at"),
            "strategy": b.get("strategy"), "benchmark": b.get("benchmark"),
            "in_sample": b.get("in_sample"), "out_of_sample": b.get("out_of_sample"),
            "yearly": b.get("yearly"), "frictions": b.get("frictions"), "data": b.get("data"),
            "equity_curve": b.get("equity_curve") or [],
        })
    mistakes_md = paths.MISTAKES.read_text(encoding="utf-8") if paths.MISTAKES.exists() else "# Mistakes\n\nNone recorded yet."
    mistakes_md = drop_rehearsal_sections(mistakes_md)
    glossary_path = paths.DOCS / "glossary.md"
    glossary_md = glossary_path.read_text(encoding="utf-8") if glossary_path.exists() else "# Glossary\n\n(not written yet)"
    mandate_md = (paths.ROOT / "MANDATE.md").read_text(encoding="utf-8")

    return {
        "built_at": built_at,
        "repo_url": REPO_URL,
        "site_url": SITE_URL,
        "version": version,
        "initial_eur": man.benchmark_initial_eur,
        "live": bool(curve),
        "home": {
            "nav": nav_now, "cash": cash_now, "n_positions": n_pos,
            "live_days": len(curve), "start_date": curve[0]["date"] if curve else None,
            "ret_total": ret_total,
            "ret_vs_bench": (ret_total - ret_bench) if (ret_total is not None and ret_bench is not None) else None,
            "last_session": {"date": last_session["date"], "status": last_session["status"],
                             "excerpt_html": last_session["excerpt_html"]} if last_session else None,
        },
        "curve": curve,
        "journal": journal,
        "research": research,
        "trades": rows,
        "portfolio": {
            "state": {"as_of": state.as_of, "nav": state.nav, "cash": state.cash, "buying_power": state.buying_power} if state else None,
            "positions": positions,
            "benchmark": {"isin": man.benchmark_isin, "name": man.benchmark_name, "start_date": bench.get("start_date"),
                          "last": bench["series"][-1] if bench.get("series") else None},
        },
        "strategy": {**strategy_doc(strategy_md), **strategy_facts(), "backtests": backtests},
        "mistakes_html": md(sections_only(mistakes_md)),
        "glossary": {"html": md(glossary_body(glossary_md), anchors=True), "terms": glossary_terms(glossary_md)},
        "mandate_html": md(strip_h1(mandate_md)),
        "venue": man.venue if hasattr(man, "venue") else None,
    }


def build() -> Path:
    data = build_data()
    out = paths.SITE_DATA
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


if __name__ == "__main__":
    out = build()
    print(f"site data written to {out.relative_to(paths.ROOT)}")
