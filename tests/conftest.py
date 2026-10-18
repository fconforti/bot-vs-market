"""Test harness: a temporary repo root, the fake `sc`, and a fixed "today"."""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from finance import paths  # noqa: E402

FIXTURES = REPO / "tests" / "fixtures" / "sc"
TODAY = "2026-10-20"   # a Tuesday, not a holiday


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """Isolated repo layout under tmp_path with the real mandate and holidays."""
    root = tmp_path / "repo"
    for d in ("journal", "trades", "portfolio", "research", "data", "data/prices", "docs"):
        (root / d).mkdir(parents=True)
    shutil.copy(REPO / "mandate.toml", root / "mandate.toml")
    shutil.copy(REPO / "data" / "holidays.toml", root / "data" / "holidays.toml")
    monkeypatch.setattr(paths, "ROOT", root)
    monkeypatch.setattr(paths, "JOURNAL", root / "journal")
    monkeypatch.setattr(paths, "TRADES", root / "trades")
    monkeypatch.setattr(paths, "PORTFOLIO", root / "portfolio")
    monkeypatch.setattr(paths, "RESEARCH", root / "research")
    monkeypatch.setattr(paths, "SITE_DATA", root / "web" / "src" / "data" / "site.json")
    monkeypatch.setattr(paths, "DATA", root / "data")
    monkeypatch.setattr(paths, "PRICE_CACHE", root / "data" / "prices")
    monkeypatch.setattr(paths, "MANDATE_TOML", root / "mandate.toml")
    monkeypatch.setattr(paths, "HALTED", root / "HALTED")
    monkeypatch.setattr(paths, "INBOX", root / "research" / "inbox.md")
    monkeypatch.setattr(paths, "MISTAKES", root / "MISTAKES.md")
    monkeypatch.setattr(paths, "BENCHMARK", root / "portfolio" / "benchmark.json")
    monkeypatch.setenv("FINANCE_TODAY", TODAY)
    monkeypatch.delenv("FINANCE_DRY_RUN", raising=False)
    return root


@pytest.fixture
def fake_sc(tmp_path, monkeypatch):
    """Point finance.sc at tests/fake_sc.py with a private copy of the fixtures."""
    fx = tmp_path / "fixtures"
    shutil.copytree(FIXTURES, fx)
    log = tmp_path / "calls.jsonl"
    monkeypatch.setenv("SC_BIN", str(REPO / "tests" / "fake_sc.py"))
    monkeypatch.setenv("FINANCE_SC_FIXTURES", str(fx))
    monkeypatch.setenv("FINANCE_SC_CALLLOG", str(log))

    class Fake:
        dir = fx
        calllog = log

        def calls(self) -> list[list[str]]:
            if not log.exists():
                return []
            return [json.loads(l)["argv"] for l in log.read_text().splitlines() if l.strip()]

        def trade_calls(self, confirm: bool | None = None) -> list[list[str]]:
            out = [c for c in self.calls() if c[:2] == ["broker", "trade"]]
            if confirm is None:
                return out
            return [c for c in out if ("--confirm" in c) == confirm]

        def patch(self, name: str, **changes) -> None:
            """Set top-level keys (e.g. _exit=30, _override={...}) on a fixture."""
            p = fx / name
            d = json.loads(p.read_text())
            d.update(changes)
            p.write_text(json.dumps(d))

    return Fake()


@pytest.fixture
def snapshot(repo, fake_sc):
    """Today's pre-trade snapshot from the fixture account (NAV 1000, cash 775.32,
    2 x EUNL)."""
    from finance import portfolio
    from finance.clock import today
    state, raw = portfolio.fetch_state(today())
    portfolio.write_snapshot(state, raw)
    return state
