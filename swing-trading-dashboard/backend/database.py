"""
SQLite persistence layer for pre-computed scan results.
All tables are keyed by scan_timestamp so historical scans are preserved.
The frontend always reads from the latest completed scan.
"""

import json
from typing import Dict, List, Optional

import aiosqlite


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_CREATE_SCAN_RUNS = """
CREATE TABLE IF NOT EXISTS scan_runs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_timestamp   TEXT    NOT NULL UNIQUE,
    tickers_scanned  INTEGER DEFAULT 0,
    completed        INTEGER DEFAULT 0,
    created_at       TEXT    DEFAULT CURRENT_TIMESTAMP
);
"""

_CREATE_MARKET_REGIME = """
CREATE TABLE IF NOT EXISTS market_regime (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_timestamp TEXT    NOT NULL,
    spy_close      REAL    NOT NULL,
    spy_20ema      REAL    NOT NULL,
    is_bullish     INTEGER NOT NULL,
    regime         TEXT    NOT NULL,
    FOREIGN KEY (scan_timestamp) REFERENCES scan_runs(scan_timestamp)
);
"""

_CREATE_SCAN_SETUPS = """
CREATE TABLE IF NOT EXISTS scan_setups (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_timestamp TEXT    NOT NULL,
    ticker         TEXT    NOT NULL,
    setup_type     TEXT    NOT NULL,
    entry          REAL    NOT NULL,
    stop_loss      REAL    NOT NULL,
    take_profit    REAL    NOT NULL,
    rr             REAL    NOT NULL,
    setup_date     TEXT    NOT NULL,
    metadata       TEXT,
    FOREIGN KEY (scan_timestamp) REFERENCES scan_runs(scan_timestamp)
);
"""

_CREATE_SR_ZONES = """
CREATE TABLE IF NOT EXISTS sr_zones (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_timestamp TEXT NOT NULL,
    ticker         TEXT NOT NULL,
    level          REAL NOT NULL,
    zone_upper     REAL NOT NULL,
    zone_lower     REAL NOT NULL,
    zone_type      TEXT NOT NULL,
    source         TEXT DEFAULT 'kde',
    FOREIGN KEY (scan_timestamp) REFERENCES scan_runs(scan_timestamp)
);
"""

_CREATE_TRADES = """
CREATE TABLE IF NOT EXISTS trades (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker      TEXT    NOT NULL,
    entry_price REAL    NOT NULL,
    quantity    REAL    NOT NULL,
    stop_loss   REAL    NOT NULL,
    target      REAL    NOT NULL,
    entry_date  TEXT    NOT NULL,
    notes       TEXT    DEFAULT '',
    status      TEXT    NOT NULL DEFAULT 'active',
    created_at  TEXT    DEFAULT CURRENT_TIMESTAMP
);
"""

_CREATE_BACKTEST_RESULTS = """
CREATE TABLE IF NOT EXISTS backtest_results (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id           TEXT    NOT NULL,
    ticker           TEXT    NOT NULL,
    setup_type       TEXT    NOT NULL,
    start_date       TEXT    NOT NULL,
    end_date         TEXT    NOT NULL,
    total_trades     INTEGER NOT NULL,
    win_count        INTEGER NOT NULL,
    loss_count       INTEGER NOT NULL,
    win_rate         REAL    NOT NULL,
    avg_rr           REAL    NOT NULL,
    profit_factor    REAL    NOT NULL,
    max_drawdown_pct REAL    NOT NULL,
    avg_holding_days REAL    NOT NULL,
    gross_profit     REAL    NOT NULL,
    gross_loss       REAL    NOT NULL,
    net_profit_pct   REAL    NOT NULL DEFAULT 0,
    trades_json      TEXT    NOT NULL,
    created_at       TEXT    DEFAULT CURRENT_TIMESTAMP
);
"""

_BACKTEST_INDEX = "CREATE INDEX IF NOT EXISTS idx_backtest_ticker ON backtest_results(ticker, setup_type);"

_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_setups_ts         ON scan_setups(scan_timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_setups_type       ON scan_setups(scan_timestamp, setup_type);",
    "CREATE INDEX IF NOT EXISTS idx_setups_ticker     ON scan_setups(ticker);",
    "CREATE INDEX IF NOT EXISTS idx_zones_ticker      ON sr_zones(ticker, scan_timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_zones_scan        ON sr_zones(scan_timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_regime_ts         ON market_regime(scan_timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_trades_status     ON trades(status);",
]


# ---------------------------------------------------------------------------
# Initialise
# ---------------------------------------------------------------------------

async def init_db(db_path: str) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(_CREATE_SCAN_RUNS)
        await db.execute(_CREATE_MARKET_REGIME)
        await db.execute(_CREATE_SCAN_SETUPS)
        await db.execute(_CREATE_SR_ZONES)
        await db.execute(_CREATE_TRADES)
        await db.execute(_CREATE_BACKTEST_RESULTS)
        await db.execute(_BACKTEST_INDEX)
        for idx_sql in _INDEXES:
            await db.execute(idx_sql)
        await db.commit()
        # Migration: add targets_json column if it does not yet exist
        try:
            await db.execute("ALTER TABLE trades ADD COLUMN targets_json TEXT")
            await db.commit()
        except Exception:
            pass  # column already exists — safe to ignore
        # Migration: add source column to sr_zones if it does not yet exist
        try:
            await db.execute("ALTER TABLE sr_zones ADD COLUMN source TEXT DEFAULT 'kde'")
            await db.commit()
        except Exception:
            pass  # column already exists — safe to ignore
        # Migration: add exit_price and exit_date to trades if they do not yet exist
        for col_sql in [
            "ALTER TABLE trades ADD COLUMN exit_price REAL",
            "ALTER TABLE trades ADD COLUMN exit_date  TEXT",
        ]:
            try:
                await db.execute(col_sql)
                await db.commit()
            except Exception:
                pass  # column already exists — safe to ignore
        # Migration: add net_profit_pct column to backtest_results if not exists
        try:
            await db.execute("ALTER TABLE backtest_results ADD COLUMN net_profit_pct REAL NOT NULL DEFAULT 0")
            await db.commit()
        except Exception:
            pass  # column already exists — safe to ignore


# ---------------------------------------------------------------------------
# Scan-run lifecycle
# ---------------------------------------------------------------------------

async def save_scan_run(db_path: str, scan_timestamp: str) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "INSERT OR IGNORE INTO scan_runs (scan_timestamp) VALUES (?)",
            (scan_timestamp,),
        )
        await db.commit()


async def complete_scan_run(db_path: str, scan_timestamp: str, tickers_scanned: int) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "UPDATE scan_runs SET completed = 1, tickers_scanned = ? WHERE scan_timestamp = ?",
            (tickers_scanned, scan_timestamp),
        )
        await db.commit()


async def get_latest_scan_timestamp(db_path: str) -> Optional[str]:
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT scan_timestamp FROM scan_runs WHERE completed = 1 ORDER BY created_at DESC LIMIT 1"
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else None


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------

async def save_regime(db_path: str, scan_timestamp: str, regime: Dict) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """INSERT INTO market_regime (scan_timestamp, spy_close, spy_20ema, is_bullish, regime)
               VALUES (?, ?, ?, ?, ?)""",
            (
                scan_timestamp,
                regime["spy_close"],
                regime["spy_20ema"],
                1 if regime["is_bullish"] else 0,
                regime["regime"],
            ),
        )
        await db.commit()


async def save_setup(db_path: str, scan_timestamp: str, setup: Dict) -> None:
    # Extra fields (cci, resistance_level, etc.) go into JSON metadata
    meta_keys = {"ticker", "setup_type", "entry", "stop_loss", "take_profit", "rr", "setup_date"}
    metadata = json.dumps({k: v for k, v in setup.items() if k not in meta_keys})

    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """INSERT INTO scan_setups
               (scan_timestamp, ticker, setup_type, entry, stop_loss, take_profit, rr, setup_date, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                scan_timestamp,
                setup["ticker"],
                setup["setup_type"],
                setup["entry"],
                setup["stop_loss"],
                setup["take_profit"],
                setup["rr"],
                setup["setup_date"],
                metadata,
            ),
        )
        await db.commit()


async def batch_save_setups(db_path: str, scan_timestamp: str, setups: List[Dict]) -> None:
    """Batch insert multiple setups in a single transaction (5-10x faster than individual saves)."""
    if not setups:
        return

    # Prepare all records with metadata
    meta_keys = {"ticker", "setup_type", "entry", "stop_loss", "take_profit", "rr", "setup_date"}
    insert_values = [
        (
            scan_timestamp,
            setup["ticker"],
            setup["setup_type"],
            setup["entry"],
            setup["stop_loss"],
            setup["take_profit"],
            setup["rr"],
            setup["setup_date"],
            json.dumps({k: v for k, v in setup.items() if k not in meta_keys}),
        )
        for setup in setups
    ]

    async with aiosqlite.connect(db_path) as db:
        await db.executemany(
            """INSERT INTO scan_setups
               (scan_timestamp, ticker, setup_type, entry, stop_loss, take_profit, rr, setup_date, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            insert_values,
        )
        await db.commit()


async def save_sr_zones(
    db_path: str, scan_timestamp: str, ticker: str, zones: List[Dict]
) -> None:
    if not zones:
        return
    async with aiosqlite.connect(db_path) as db:
        await db.executemany(
            """INSERT INTO sr_zones (scan_timestamp, ticker, level, zone_upper, zone_lower, zone_type, source)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [
                (scan_timestamp, ticker, z["level"], z["upper"], z["lower"], z["type"], z.get("source", "kde"))
                for z in zones
            ],
        )
        await db.commit()


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------

async def get_latest_regime(db_path: str) -> Optional[Dict]:
    scan_ts = await get_latest_scan_timestamp(db_path)
    if not scan_ts:
        return None

    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            """SELECT spy_close, spy_20ema, is_bullish, regime
               FROM market_regime WHERE scan_timestamp = ? LIMIT 1""",
            (scan_ts,),
        ) as cur:
            row = await cur.fetchone()
            if row:
                return {
                    "spy_close": row[0],
                    "spy_20ema": row[1],
                    "is_bullish": bool(row[2]),
                    "regime": row[3],
                    "scan_timestamp": scan_ts,
                }
    return None


async def get_latest_setups(
    db_path: str, setup_type: Optional[str] = None
) -> List[Dict]:
    scan_ts = await get_latest_scan_timestamp(db_path)
    if not scan_ts:
        return []

    async with aiosqlite.connect(db_path) as db:
        if setup_type:
            sql = """SELECT ticker, setup_type, entry, stop_loss, take_profit, rr, setup_date, metadata
                     FROM scan_setups WHERE scan_timestamp = ? AND setup_type = ?"""
            params = (scan_ts, setup_type)
        else:
            sql = """SELECT ticker, setup_type, entry, stop_loss, take_profit, rr, setup_date, metadata
                     FROM scan_setups WHERE scan_timestamp = ?"""
            params = (scan_ts,)

        async with db.execute(sql, params) as cur:
            rows = await cur.fetchall()

        results = []
        for row in rows:
            record = {
                "ticker": row[0],
                "setup_type": row[1],
                "entry": row[2],
                "stop_loss": row[3],
                "take_profit": row[4],
                "rr": row[5],
                "setup_date": row[6],
                "scan_timestamp": scan_ts,
            }
            if row[7]:
                try:
                    record.update(json.loads(row[7]))
                except Exception:
                    pass
            results.append(record)

        return results


# ---------------------------------------------------------------------------
# Trades CRUD
# ---------------------------------------------------------------------------

async def add_trade(db_path: str, trade: Dict) -> int:
    """Insert a new active trade; returns the new row id."""
    targets = trade.get("targets") or [trade["target"]]
    targets_json = json.dumps([float(t) for t in targets])
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            """INSERT INTO trades
               (ticker, entry_price, quantity, stop_loss, target, targets_json, entry_date, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                trade["ticker"].upper(),
                trade["entry_price"],
                trade["quantity"],
                trade["stop_loss"],
                float(targets[0]),
                targets_json,
                trade["entry_date"],
                trade.get("notes", ""),
            ),
        )
        await db.commit()
        return cur.lastrowid


async def get_trades(db_path: str, status: str = "active") -> List[Dict]:
    """Return all trades with the given status."""
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            """SELECT id, ticker, entry_price, quantity, stop_loss, target, targets_json,
                      entry_date, notes, status, created_at
               FROM trades WHERE status = ? ORDER BY created_at DESC""",
            (status,),
        ) as cur:
            rows = await cur.fetchall()
            result = []
            for r in rows:
                targets = json.loads(r[6]) if r[6] else [r[5]]
                result.append({
                    "id":          r[0],
                    "ticker":      r[1],
                    "entry_price": r[2],
                    "quantity":    r[3],
                    "stop_loss":   r[4],
                    "target":      r[5],
                    "targets":     targets,
                    "entry_date":  r[7],
                    "notes":       r[8],
                    "status":      r[9],
                    "created_at":  r[10],
                })
            return result


async def close_trade(
    db_path: str,
    trade_id: int,
    exit_price: Optional[float] = None,
    exit_date: Optional[str] = None,
) -> bool:
    """Mark a trade as closed, optionally recording the exit price and date.
    Returns True if a row was updated."""
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            """UPDATE trades
               SET status = 'closed', exit_price = ?, exit_date = ?
               WHERE id = ? AND status = 'active'""",
            (exit_price, exit_date, trade_id),
        )
        await db.commit()
        return cur.rowcount > 0


async def get_closed_trades(db_path: str, limit: int = 50) -> List[Dict]:
    """Return the most recent closed trades (up to limit)."""
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            """SELECT id, ticker, entry_price, quantity, stop_loss, target, targets_json,
                      entry_date, notes, exit_price, exit_date, created_at
               FROM trades WHERE status = 'closed'
               ORDER BY exit_date DESC, created_at DESC LIMIT ?""",
            (limit,),
        ) as cur:
            rows = await cur.fetchall()
            result = []
            for r in rows:
                targets = json.loads(r[6]) if r[6] else [r[5]]
                exit_price_val = r[9]
                entry_price_val = r[2]
                pl_dollar = None
                pl_pct = None
                if exit_price_val is not None and entry_price_val:
                    qty = r[3] or 0
                    pl_dollar = round((exit_price_val - entry_price_val) * qty, 2)
                    pl_pct = round((exit_price_val - entry_price_val) / entry_price_val * 100, 2)
                days_held = None
                if r[7] and r[10]:
                    try:
                        from datetime import date
                        d0 = date.fromisoformat(r[7])
                        d1 = date.fromisoformat(r[10])
                        days_held = (d1 - d0).days
                    except Exception:
                        pass
                result.append({
                    "id":          r[0],
                    "ticker":      r[1],
                    "entry_price": r[2],
                    "quantity":    r[3],
                    "stop_loss":   r[4],
                    "target":      r[5],
                    "targets":     targets,
                    "entry_date":  r[7],
                    "notes":       r[8],
                    "exit_price":  exit_price_val,
                    "exit_date":   r[10],
                    "pl_dollar":   pl_dollar,
                    "pl_pct":      pl_pct,
                    "days_held":   days_held,
                    "created_at":  r[11],
                })
            return result


async def get_sr_zones_for_ticker_from_db(db_path: str, ticker: str) -> List[Dict]:
    scan_ts = await get_latest_scan_timestamp(db_path)
    if not scan_ts:
        return []

    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            """SELECT level, zone_upper, zone_lower, zone_type, source
               FROM sr_zones WHERE scan_timestamp = ? AND ticker = ?
               ORDER BY level""",
            (scan_ts, ticker),
        ) as cur:
            rows = await cur.fetchall()
            return [
                {"level": r[0], "upper": r[1], "lower": r[2], "type": r[3], "source": r[4] or "kde"}
                for r in rows
            ]


# ---------------------------------------------------------------------------
# Backtest Results CRUD
# ---------------------------------------------------------------------------

async def save_backtest_result(db_path: str, result: Dict) -> int:
    """Insert one backtest result row. Returns new row id."""
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            """INSERT INTO backtest_results
               (run_id, ticker, setup_type, start_date, end_date,
                total_trades, win_count, loss_count, win_rate,
                avg_rr, profit_factor, max_drawdown_pct, avg_holding_days,
                gross_profit, gross_loss, net_profit_pct, trades_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                result["run_id"],
                result["ticker"].upper(),
                result["setup_type"],
                result["start_date"],
                result["end_date"],
                result["total_trades"],
                result["win_count"],
                result["loss_count"],
                result["win_rate"],
                result["avg_rr"],
                result["profit_factor"],
                result["max_drawdown_pct"],
                result["avg_holding_days"],
                result["gross_profit"],
                result["gross_loss"],
                result.get("net_profit_pct", 0.0),
                json.dumps(result.get("trades", [])),
            ),
        )
        await db.commit()
        return cur.lastrowid


async def get_backtest_results(db_path: str, ticker: str) -> List[Dict]:
    """Return all backtest results for a ticker, newest first."""
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            """SELECT run_id, ticker, setup_type, start_date, end_date,
                      total_trades, win_count, loss_count, win_rate,
                      avg_rr, profit_factor, max_drawdown_pct, avg_holding_days,
                      gross_profit, gross_loss, net_profit_pct, trades_json, created_at
               FROM backtest_results WHERE ticker = ?
               ORDER BY created_at DESC""",
            (ticker.upper(),),
        ) as cur:
            rows = await cur.fetchall()
            results = []
            for r in rows:
                results.append({
                    "run_id":           r[0],
                    "ticker":           r[1],
                    "setup_type":       r[2],
                    "start_date":       r[3],
                    "end_date":         r[4],
                    "total_trades":     r[5],
                    "win_count":        r[6],
                    "loss_count":       r[7],
                    "win_rate":         r[8],
                    "avg_rr":           r[9],
                    "profit_factor":    r[10],
                    "max_drawdown_pct": r[11],
                    "avg_holding_days": r[12],
                    "gross_profit":     r[13],
                    "gross_loss":       r[14],
                    "net_profit_pct":   r[15],
                    "trades":           json.loads(r[16]) if r[16] else [],
                    "created_at":       r[17],
                })
            return results
