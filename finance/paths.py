"""Repository paths. Everything is relative to the repo root so bin/ scripts can be
run from anywhere."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(os.environ.get("FINANCE_ROOT", Path(__file__).resolve().parent.parent))
JOURNAL = ROOT / "journal"
TRADES = ROOT / "trades"
PORTFOLIO = ROOT / "portfolio"
RESEARCH = ROOT / "research"
WEB = ROOT / "web"
SITE_DATA = WEB / "src" / "data" / "site.json"
STRATEGY = ROOT / "strategy"
DATA = ROOT / "data"
DOCS = ROOT / "docs"
MANDATE_TOML = ROOT / "mandate.toml"
HALTED = ROOT / "HALTED"
INBOX = RESEARCH / "inbox.md"
MISTAKES = ROOT / "MISTAKES.md"
BENCHMARK = PORTFOLIO / "benchmark.json"
PRICE_CACHE = DATA / "prices"


def ensure_dirs() -> None:
    for d in (JOURNAL, TRADES, PORTFOLIO, RESEARCH, DATA, PRICE_CACHE):
        d.mkdir(parents=True, exist_ok=True)
