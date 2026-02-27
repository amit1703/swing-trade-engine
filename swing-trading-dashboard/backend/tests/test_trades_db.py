"""Tests for multi-target trades DB layer."""
import asyncio
import json
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from database import init_db, add_trade, get_trades


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def tmp_db(tmp_path):
    db = str(tmp_path / "test.db")
    run(init_db(db))
    return db


def test_add_trade_single_target_returns_targets_list(tmp_db):
    """add_trade with targets=[150.0] → get_trades returns targets=[150.0]."""
    run(add_trade(tmp_db, {
        "ticker": "AAPL",
        "entry_price": 140.0,
        "quantity": 10,
        "stop_loss": 135.0,
        "targets": [150.0],
        "entry_date": "2026-01-01",
    }))
    trades = run(get_trades(tmp_db))
    assert len(trades) == 1
    assert trades[0]["targets"] == [150.0]


def test_add_trade_two_targets(tmp_db):
    """add_trade with targets=[150, 160] → get_trades returns both."""
    run(add_trade(tmp_db, {
        "ticker": "NVDA",
        "entry_price": 140.0,
        "quantity": 5,
        "stop_loss": 134.0,
        "targets": [150.0, 160.0],
        "entry_date": "2026-01-01",
    }))
    trades = run(get_trades(tmp_db))
    assert trades[0]["targets"] == [150.0, 160.0]


def test_add_trade_three_targets(tmp_db):
    """add_trade with three targets → all three returned."""
    run(add_trade(tmp_db, {
        "ticker": "TSLA",
        "entry_price": 200.0,
        "quantity": 3,
        "stop_loss": 192.0,
        "targets": [210.0, 220.0, 230.0],
        "entry_date": "2026-01-01",
    }))
    trades = run(get_trades(tmp_db))
    assert trades[0]["targets"] == [210.0, 220.0, 230.0]


def test_legacy_row_fallback(tmp_db):
    """Rows with targets_json=NULL fall back to [target] — backward compat."""
    import aiosqlite

    async def _insert_legacy(db_path):
        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                """INSERT INTO trades
                   (ticker, entry_price, quantity, stop_loss, target, entry_date)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                ("MSFT", 300.0, 2, 290.0, 315.0, "2025-12-01"),
            )
            await db.commit()

    run(_insert_legacy(tmp_db))
    trades = run(get_trades(tmp_db))
    assert trades[0]["targets"] == [315.0]


def test_legacy_target_col_written_as_t1(tmp_db):
    """add_trade sets target column = targets[0] for backward compat."""
    import aiosqlite

    run(add_trade(tmp_db, {
        "ticker": "GOOG",
        "entry_price": 180.0,
        "quantity": 4,
        "stop_loss": 174.0,
        "targets": [190.0, 200.0],
        "entry_date": "2026-01-02",
    }))

    async def _raw_target(db_path):
        async with aiosqlite.connect(db_path) as db:
            async with db.execute("SELECT target FROM trades WHERE ticker='GOOG'") as cur:
                row = await cur.fetchone()
                return row[0]

    raw_target = run(_raw_target(tmp_db))
    assert raw_target == 190.0


def test_trade_in_model_rejects_empty_targets():
    """TradeIn must reject an empty targets list."""
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from main import TradeIn
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        TradeIn(
            ticker="AAPL", entry_price=140, quantity=10,
            stop_loss=135, targets=[], entry_date="2026-01-01"
        )


def test_trade_in_model_rejects_four_targets():
    """TradeIn must reject more than 3 targets."""
    from main import TradeIn
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        TradeIn(
            ticker="AAPL", entry_price=140, quantity=10,
            stop_loss=135, targets=[150, 160, 170, 180], entry_date="2026-01-01"
        )


def test_trade_in_model_accepts_one_to_three():
    """TradeIn accepts 1, 2, or 3 targets."""
    from main import TradeIn
    m1 = TradeIn(ticker="A", entry_price=100, quantity=1, stop_loss=95, targets=[110], entry_date="2026-01-01")
    assert m1.targets == [110]
    m3 = TradeIn(ticker="B", entry_price=100, quantity=1, stop_loss=95, targets=[110, 120, 130], entry_date="2026-01-01")
    assert len(m3.targets) == 3
