# Expanded Universe + ATR Pre-Filter Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the hardcoded ~700-ticker list with a SEC EDGAR-sourced 3000+ ticker universe filtered by price ≥ $10, avg volume 50d ≥ 500K, and ATR%(14) ≥ 2.0% — rebuilt on every scan run.

**Architecture:** The existing `filter_price_volume()` in `universe_builder.py` already handles price and volume gates using `yf.download` in batches. We add an ATR% gate to that same function (free — uses already-downloaded data), increase batch size from 100→250 to reduce total sleep time, and wire `build_universe()` to run at the start of every `_run_scan()` call in `main.py` via an executor thread. The `?tickers=` debug override bypasses universe rebuild.

**Tech Stack:** Python 3.11, yfinance, pandas, FastAPI, pytest, asyncio

---

### Task 1: Add MIN_ATR_PCT constant and tune batch settings

**Files:**
- Modify: `swing-trading-dashboard/backend/constants.py` (end of file)
- Modify: `swing-trading-dashboard/backend/universe_builder.py:29-30`

**Step 1: Add constant to constants.py**

At the end of `constants.py`, after `VITALITY_MIN_RANGE_PCT`, add:

```python
# ──────────────────────────────────────────────────────────────────────────
# Universe Pre-Filter
# ──────────────────────────────────────────────────────────────────────────

MIN_ATR_PCT = 2.0           # ATR(14)/Close×100 minimum — filters low-vol stocks
```

**Step 2: Increase batch size and reduce delay in universe_builder.py**

Find lines 29-30 in `universe_builder.py`:
```python
BATCH_SIZE = 100
BATCH_DELAY = 2.0
```

Replace with:
```python
BATCH_SIZE = 250        # larger batches → fewer sleeps → ~2min vs ~8min for 5000 tickers
BATCH_DELAY = 1.0       # reduced from 2.0s
```

(Leave `SECTOR_BATCH_SIZE = 50` and `SECTOR_BATCH_DELAY = 3.0` untouched — sector fetching hits individual ticker endpoints which are more rate-sensitive.)

**Step 3: Verify no import errors**

```bash
cd swing-trading-dashboard/backend && python -c "from constants import MIN_ATR_PCT; print(MIN_ATR_PCT)"
```
Expected: `2.0`

```bash
python -c "from universe_builder import BATCH_SIZE, BATCH_DELAY; print(BATCH_SIZE, BATCH_DELAY)"
```
Expected: `250 1.0`

**Step 4: Commit**

```bash
git add swing-trading-dashboard/backend/constants.py swing-trading-dashboard/backend/universe_builder.py
git commit -m "feat(universe): add MIN_ATR_PCT constant, increase filter batch size to 250"
```

---

### Task 2: Add ATR% filter to filter_price_volume()

**Files:**
- Modify: `swing-trading-dashboard/backend/universe_builder.py` — `filter_price_volume()` function and `build_universe()`
- Modify: `swing-trading-dashboard/backend/tests/test_universe_builder.py` — add ATR% tests

**Step 1: Write failing tests first**

In `tests/test_universe_builder.py`, add these test cases to the `TestFilterPriceVolume` class. The existing import at the top already imports `filter_price_volume`. No import changes needed.

Add a new helper function after the existing `_make_single_ticker_df`:

```python
def _make_volatile_df(
    close: float = 150.0,
    volume: int = 2_000_000,
    atr_pct: float = 3.0,
    rows: int = 60,
) -> pd.DataFrame:
    """Return a DataFrame with controlled High/Low spread to produce a target ATR%."""
    idx = pd.date_range("2025-01-01", periods=rows, freq="B")
    half_range = close * (atr_pct / 100) / 2
    return pd.DataFrame(
        {
            "Open": close * 0.995,
            "High": close + half_range,
            "Low": close - half_range,
            "Close": close,
            "Adj Close": close,
            "Volume": volume,
        },
        index=idx,
    )
```

Then add these two test methods to `TestFilterPriceVolume`:

```python
@patch("universe_builder.time.sleep")
@patch("universe_builder.yf.download")
def test_filters_below_min_atr_pct(self, mock_download, _mock_sleep):
    """Ticker with ATR% = 0.5% should be excluded when min_atr_pct=2.0."""
    mock_download.return_value = _make_volatile_df(
        close=150.0, volume=2_000_000, atr_pct=0.5
    )
    result = filter_price_volume(["FLAT"], min_price=10.0, min_avg_volume=500_000, min_atr_pct=2.0)
    assert "FLAT" not in result
    assert result == []

@patch("universe_builder.time.sleep")
@patch("universe_builder.yf.download")
def test_passes_sufficient_atr_pct(self, mock_download, _mock_sleep):
    """Ticker with ATR% = 4.0% should pass when min_atr_pct=2.0."""
    mock_download.return_value = _make_volatile_df(
        close=150.0, volume=2_000_000, atr_pct=4.0
    )
    result = filter_price_volume(["VOLATILE"], min_price=10.0, min_avg_volume=500_000, min_atr_pct=2.0)
    assert result == ["VOLATILE"]

@patch("universe_builder.time.sleep")
@patch("universe_builder.yf.download")
def test_atr_filter_disabled_when_zero(self, mock_download, _mock_sleep):
    """min_atr_pct=0.0 (default) should not filter out low-volatility tickers."""
    mock_download.return_value = _make_volatile_df(
        close=150.0, volume=2_000_000, atr_pct=0.1
    )
    result = filter_price_volume(["CALM"], min_price=10.0, min_avg_volume=500_000, min_atr_pct=0.0)
    assert result == ["CALM"]
```

**Step 2: Run tests to confirm they fail**

```bash
cd swing-trading-dashboard/backend && python -m pytest tests/test_universe_builder.py::TestFilterPriceVolume::test_filters_below_min_atr_pct tests/test_universe_builder.py::TestFilterPriceVolume::test_passes_sufficient_atr_pct tests/test_universe_builder.py::TestFilterPriceVolume::test_atr_filter_disabled_when_zero -v
```

Expected: 3 FAILs — `filter_price_volume` does not accept `min_atr_pct` yet (TypeError).

**Step 3: Implement the ATR% filter in filter_price_volume()**

In `universe_builder.py`, find the `filter_price_volume` function signature (around line 170):

```python
def filter_price_volume(
    tickers: List[str],
    min_price: float = DEFAULT_MIN_PRICE,
    min_avg_volume: int = DEFAULT_MIN_AVG_VOLUME,
) -> List[str]:
```

Change it to:

```python
def filter_price_volume(
    tickers: List[str],
    min_price: float = DEFAULT_MIN_PRICE,
    min_avg_volume: int = DEFAULT_MIN_AVG_VOLUME,
    min_atr_pct: float = 0.0,
) -> List[str]:
```

Also update the docstring first line to:
```
"""Filter tickers by minimum price, average daily volume, and optional ATR%.
```

Now find the block inside the per-ticker loop that currently ends at the `passed.append(ticker)` line (after the avg_volume check). Insert the ATR% gate **before** `passed.append(ticker)`:

```python
                # --- ATR% filter (optional — skipped when min_atr_pct == 0) ---
                if min_atr_pct > 0:
                    if "High" not in ticker_df.columns or "Low" not in ticker_df.columns:
                        continue
                    high = ticker_df["High"].dropna()
                    low  = ticker_df["Low"].dropna()
                    close_s = ticker_df["Close"].dropna() if "Close" in ticker_df.columns \
                              else ticker_df["Adj Close"].dropna()
                    prev_close = close_s.shift(1)
                    tr = pd.concat([
                        high - low,
                        (high - prev_close).abs(),
                        (low  - prev_close).abs(),
                    ], axis=1).max(axis=1)
                    atr14 = tr.rolling(14).mean()
                    if atr14.empty or pd.isna(atr14.iloc[-1]):
                        continue
                    atr_pct = float(atr14.iloc[-1]) / last_close * 100.0
                    if atr_pct < min_atr_pct:
                        continue
```

This block sits between the `if avg_volume < min_avg_volume: continue` check and the `passed.append(ticker)` line. The full corrected tail of the per-ticker block becomes:

```python
                if avg_volume < min_avg_volume:
                    continue

                # --- ATR% filter (optional — skipped when min_atr_pct == 0) ---
                if min_atr_pct > 0:
                    if "High" not in ticker_df.columns or "Low" not in ticker_df.columns:
                        continue
                    high = ticker_df["High"].dropna()
                    low  = ticker_df["Low"].dropna()
                    close_s = ticker_df["Close"].dropna() if "Close" in ticker_df.columns \
                              else ticker_df["Adj Close"].dropna()
                    prev_close = close_s.shift(1)
                    tr = pd.concat([
                        high - low,
                        (high - prev_close).abs(),
                        (low  - prev_close).abs(),
                    ], axis=1).max(axis=1)
                    atr14 = tr.rolling(14).mean()
                    if atr14.empty or pd.isna(atr14.iloc[-1]):
                        continue
                    atr_pct = float(atr14.iloc[-1]) / last_close * 100.0
                    if atr_pct < min_atr_pct:
                        continue

                passed.append(ticker)
```

**Step 4: Update build_universe() to pass min_atr_pct**

In `universe_builder.py`, find `build_universe()` signature:

```python
def build_universe(
    min_price: float = DEFAULT_MIN_PRICE,
    min_avg_volume: int = DEFAULT_MIN_AVG_VOLUME,
) -> dict:
```

Change to:

```python
def build_universe(
    min_price: float = DEFAULT_MIN_PRICE,
    min_avg_volume: int = DEFAULT_MIN_AVG_VOLUME,
    min_atr_pct: float = 0.0,
) -> dict:
```

Find the call to `filter_price_volume` inside `build_universe()`:

```python
    filtered = filter_price_volume(candidates, min_price, min_avg_volume)
```

Change to:

```python
    filtered = filter_price_volume(candidates, min_price, min_avg_volume, min_atr_pct)
```

Also update the `filters` dict in the metadata to record it:

```python
            "filters": {
                "min_price": min_price,
                "min_avg_volume_50d": min_avg_volume,
                "min_atr_pct": min_atr_pct,
                "exchanges": ["NYSE", "Nasdaq"],
            },
```

Also update the CLI argparse block at the bottom:

```python
    parser.add_argument("--min-atr-pct", type=float, default=0.0)
```

And pass it to `build_universe`:

```python
    universe = build_universe(
        min_price=args.min_price,
        min_avg_volume=args.min_volume,
        min_atr_pct=args.min_atr_pct,
    )
```

**Step 5: Run the new tests — should pass**

```bash
cd swing-trading-dashboard/backend && python -m pytest tests/test_universe_builder.py::TestFilterPriceVolume -v
```

Expected: ALL PASS (including the 3 new ATR tests and all 7 existing tests).

**Step 6: Run the full universe_builder test suite**

```bash
cd swing-trading-dashboard/backend && python -m pytest tests/test_universe_builder.py -v
```

Expected: ALL PASS.

**Step 7: Commit**

```bash
git add swing-trading-dashboard/backend/universe_builder.py swing-trading-dashboard/backend/tests/test_universe_builder.py
git commit -m "feat(universe): add ATR%(14) >= 2% pre-filter to filter_price_volume"
```

---

### Task 3: Wire build_universe() into _run_scan() in main.py

**Files:**
- Modify: `swing-trading-dashboard/backend/main.py` — imports and `_run_scan()` function

**Step 1: Update the import from universe_builder**

Find the current import line (around line 93):

```python
from universe_builder import load_universe, UNIVERSE_FILE
```

Replace with:

```python
from universe_builder import build_universe, load_universe, save_universe, UNIVERSE_FILE
```

**Step 2: Add MIN_ATR_PCT to the constants import**

Find the `from constants import (` block. Add `MIN_ATR_PCT` to it:

```python
from constants import (
    CACHE_TTL_FAILURE,
    CACHE_TTL_SUCCESS,
    CONCURRENCY_LIMIT,
    DATA_FETCH_PERIOD,
    DB_PATH,
    DAYS_3_MONTHS,
    FETCH_BACKOFF_BASE,
    FETCH_MAX_RETRIES,
    MAX_TICKERS_PER_SCAN,
    MIN_ATR_PCT,
    MIN_CANDLES_FOR_ANALYSIS,
    MIN_CANDLES_FOR_RS,
    RS_BLUE_DOT_TOLERANCE_PCT,
    TRADING_DAYS_IN_YEAR,
)
```

**Step 3: Locate the start of _run_scan()**

Find `async def _run_scan(scan_ts: str, tickers: List[str], force: bool = False, dry_run: bool = False) -> None:` (around line 294).

The function starts with something like:
```python
    global _scan_state
    _scan_state["in_progress"] = True
    _scan_state["started_at"] = ...
```

**Step 4: Insert universe rebuild at the start of _run_scan()**

Right after the `_scan_state` setup block (but before the per-ticker loop), add:

```python
    # ── Rebuild universe (SEC EDGAR → filter → save) ───────────────────────
    # Skip if specific tickers were requested via ?tickers= debug override.
    # "specific tickers" means the passed list != ACTIVE_UNIVERSE, i.e. it was
    # explicitly provided by the caller.  We detect this by checking if the
    # list is the same object as ACTIVE_UNIVERSE.
    global ACTIVE_UNIVERSE, SECTORS
    if tickers is ACTIVE_UNIVERSE:
        log.info("Rebuilding universe via SEC EDGAR + yfinance pre-filters…")
        loop = asyncio.get_event_loop()
        try:
            universe_dict = await loop.run_in_executor(
                None,
                lambda: build_universe(
                    min_atr_pct=MIN_ATR_PCT,
                ),
            )
            if universe_dict["tickers"]:
                save_universe(universe_dict, UNIVERSE_FILE)
                ACTIVE_UNIVERSE = universe_dict["tickers"]
                SECTORS = universe_dict["sectors"]
                tickers = ACTIVE_UNIVERSE
                log.info(
                    "Universe rebuilt: %d tickers (price≥$10, vol≥500K, ATR%%≥%.1f%%)",
                    len(tickers),
                    MIN_ATR_PCT,
                )
            else:
                log.warning("Universe rebuild returned 0 tickers — keeping existing universe")
        except Exception:
            log.exception("Universe rebuild failed — proceeding with existing universe")
```

**Step 5: Update the scan endpoint to pass `ACTIVE_UNIVERSE` by reference**

Find the `/api/run-scan` endpoint body (around line 837):

```python
    if tickers:
        ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    else:
        ticker_list = ACTIVE_UNIVERSE
```

This already passes `ACTIVE_UNIVERSE` (the global object itself, not a copy) when no debug tickers are supplied. The `tickers is ACTIVE_UNIVERSE` check in `_run_scan` will correctly identify this as the non-debug path. **No change needed here.**

**Step 6: Verify the backend starts without errors**

```bash
cd swing-trading-dashboard/backend && python -c "
from main import app
print('Import OK')
"
```

Expected: `Import OK` with no exceptions.

**Step 7: Smoke test — confirm build_universe is reachable**

```bash
cd swing-trading-dashboard/backend && python -c "
from constants import MIN_ATR_PCT
from universe_builder import build_universe
print('MIN_ATR_PCT =', MIN_ATR_PCT)
print('build_universe signature OK')
import inspect
sig = inspect.signature(build_universe)
print('params:', list(sig.parameters.keys()))
"
```

Expected:
```
MIN_ATR_PCT = 2.0
build_universe signature OK
params: ['min_price', 'min_avg_volume', 'min_atr_pct']
```

**Step 8: Run full test suite to confirm nothing broke**

```bash
cd swing-trading-dashboard/backend && python -m pytest tests/ -v --tb=short 2>&1 | tail -30
```

Expected: all existing tests pass, no new failures.

**Step 9: Commit**

```bash
git add swing-trading-dashboard/backend/main.py
git commit -m "feat(scan): rebuild universe on every scan run with ATR% pre-filter"
```

---

## Final verification checklist

- [ ] `constants.py` has `MIN_ATR_PCT = 2.0`
- [ ] `universe_builder.py` `BATCH_SIZE = 250`, `BATCH_DELAY = 1.0`
- [ ] `filter_price_volume()` accepts `min_atr_pct` param, ATR%(14) gate applied when `> 0`
- [ ] `build_universe()` passes `min_atr_pct` through to `filter_price_volume()`
- [ ] CLI `--min-atr-pct` flag works
- [ ] All 3 new ATR% tests pass, all existing universe tests pass
- [ ] `main.py` imports `build_universe`, `save_universe`, `MIN_ATR_PCT`
- [ ] `_run_scan()` calls `build_universe(min_atr_pct=MIN_ATR_PCT)` in executor at start
- [ ] Debug `?tickers=` override bypasses universe rebuild
- [ ] Full test suite passes
