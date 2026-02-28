"""
TDD tests for the sr_zones `source` column migration.

Uses a temporary SQLite file (via tmp_path + monkeypatch) so the real
trading.db is never touched.  database.py accepts db_path as an explicit
parameter on every function, so we pass the temp path directly.
"""

import asyncio
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from database import init_db, save_sr_zones, get_sr_zones_for_ticker_from_db


@pytest.fixture
def db(tmp_path):
    """Return a path to a freshly-initialised temp database."""
    path = str(tmp_path / "test.db")
    asyncio.run(init_db(path))
    return path


def test_pivot_zone_source_persisted(db):
    """A zone with source='pivot' round-trips through save/load with source='pivot'."""
    zones = [
        {"level": 105.0, "upper": 106.0, "lower": 104.0, "type": "RESISTANCE", "source": "pivot"}
    ]
    asyncio.run(save_sr_zones(db, "2026-01-01T00:00:00", "AAPL", zones))

    # Simulate a completed scan_run so get_sr_zones_for_ticker_from_db finds the timestamp
    import aiosqlite

    async def _mark_complete():
        async with aiosqlite.connect(db) as conn:
            await conn.execute(
                "INSERT OR IGNORE INTO scan_runs (scan_timestamp, completed) VALUES (?, 1)",
                ("2026-01-01T00:00:00",),
            )
            await conn.commit()

    asyncio.run(_mark_complete())

    result = asyncio.run(get_sr_zones_for_ticker_from_db(db, "AAPL"))
    assert len(result) == 1
    assert result[0]["source"] == "pivot"


def test_kde_zone_defaults_to_kde_source(db):
    """A zone dict without a 'source' key is saved and retrieved as source='kde'."""
    zones = [{"level": 100.0, "upper": 101.0, "lower": 99.0, "type": "SUPPORT"}]
    asyncio.run(save_sr_zones(db, "2026-01-01T00:00:00", "MSFT", zones))

    import aiosqlite

    async def _mark_complete():
        async with aiosqlite.connect(db) as conn:
            await conn.execute(
                "INSERT OR IGNORE INTO scan_runs (scan_timestamp, completed) VALUES (?, 1)",
                ("2026-01-01T00:00:00",),
            )
            await conn.commit()

    asyncio.run(_mark_complete())

    result = asyncio.run(get_sr_zones_for_ticker_from_db(db, "MSFT"))
    assert len(result) == 1
    assert result[0]["source"] == "kde"


def test_init_db_idempotent(db):
    """Calling init_db() twice does not raise (ALTER TABLE migration is safe)."""
    asyncio.run(init_db(db))  # second call — must not raise
