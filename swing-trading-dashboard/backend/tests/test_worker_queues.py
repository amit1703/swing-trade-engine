"""Tests for the bounded worker queue phases in main.py."""
import sys, os, asyncio
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import pandas as pd


def _make_df(n=252):
    dates = pd.bdate_range("2024-01-02", periods=n)
    prices = [100.0 + i * 0.1 for i in range(n)]
    return pd.DataFrame({
        "Open": prices, "High": prices, "Low": prices,
        "Close": prices, "Adj Close": prices,
        "Volume": [2_000_000] * n,
    }, index=dates)


def test_run_io_phase_processes_all_tickers():
    from main import _run_io_phase
    from cache_store import CacheStore
    import tempfile, asyncio

    with tempfile.TemporaryDirectory() as tmp:
        cs = CacheStore(cache_dir=tmp)
        for t in ["AAPL", "NVDA", "MSFT"]:
            cs.put(t, _make_df(252))  # already fresh

        async def run():
            sem = asyncio.Semaphore(10)
            await _run_io_phase(["AAPL", "NVDA", "MSFT"], cs, sem)

        asyncio.run(run())
        # All tickers should now be in memory
        for t in ["AAPL", "NVDA", "MSFT"]:
            assert cs.get(t) is not None


def test_run_io_phase_handles_empty_list():
    from main import _run_io_phase
    from cache_store import CacheStore
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        cs = CacheStore(cache_dir=tmp)
        asyncio.run(_run_io_phase([], cs, asyncio.Semaphore(5)))
        # No error — just a no-op


def test_run_compute_phase_processes_all_survivors():
    from main import _run_compute_phase
    import asyncio

    results = []

    async def fake_process(ticker, idx, **kwargs):
        results.append(ticker)

    survivors = ["AAPL", "NVDA", "MSFT", "GOOG"]
    asyncio.run(_run_compute_phase(
        survivors,
        process_fn=fake_process,
        workers=2,
    ))
    assert sorted(results) == sorted(survivors)


def test_run_compute_phase_handles_worker_exception_gracefully():
    from main import _run_compute_phase
    import asyncio

    call_count = [0]

    async def sometimes_fails(ticker, idx, **kwargs):
        call_count[0] += 1
        if ticker == "FAIL":
            raise ValueError("simulated crash")

    survivors = ["AAPL", "FAIL", "NVDA"]
    asyncio.run(_run_compute_phase(
        survivors,
        process_fn=sometimes_fails,
        workers=2,
    ))
    # All 3 attempted, including FAIL
    assert call_count[0] == 3


def test_worker_count_capped_at_cpu_count(monkeypatch):
    """Effective compute workers must not exceed os.cpu_count() × 2."""
    import os, main as m
    monkeypatch.setattr(os, "cpu_count", lambda: 2)
    assert m._effective_compute_workers() <= 4
