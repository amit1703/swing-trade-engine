# Dev Mode Design

**Goal:** Add a developer overlay to the dashboard that bypasses the market-halt engine gate, exposes engine health metrics, supports dry-run scanning, and provides a per-ticker debug drill-down — all behind a single toggleable `[DEV]` button.

**Architecture:** Stateless per-request flag (`?force=true`, `?dry_run=true`) passed from the frontend. `devMode` boolean lives in App.jsx React state only — no server-side global toggle. Backend extends `_scan_state` with per-engine counters. A new `GET /api/debug/{ticker}` endpoint re-runs the sniper debug logic and returns structured JSON.

**Tech Stack:** FastAPI/Python backend, React 18 frontend.

---

## Feature 1: Dev Mode Toggle & Visual Indicator

**Toggle:** A `[DEV]` button in Header's right block (between `? GUIDE` and `RUN SCAN`). Clicking toggles `devMode` boolean in App.jsx.

**Visual feedback when active:**
- An amber pulsing `⚠ DEV` badge appears next to the regime label in the header.
- When the regime is HALT, an additional line reads: `ENGINES FORCE-ENABLED` (in amber) below the "SPY < 20 EMA — ENGINES 2 & 3 DISABLED" line.
- The `[DEV]` button itself glows amber with a border when active.
- When dry-run is also active: `⚠ DEV · DRY RUN` badge.

**State:** `devMode: bool` and `dryRun: bool` in App.jsx. `dryRun` is only usable when `devMode` is active. Both reset on page refresh.

---

## Feature 2: Halt Bypass (Backend)

**`POST /api/run-scan?force=true`** — skips the bearish early-return in `_run_scan()` at the `if not regime["is_bullish"]: return` gate. The full ticker pipeline fires: Engine 1 (KDE zones), Engine 2 (VCP), Engine 3 (Pullback), Engine 4 (RS), Engine 5 (Base), Engine 6 (ResBreakout).

Results are saved to DB as normal. The frontend displays all result types (VCP table, Pullback table, Base table, ResBreakout table) regardless of regime.

**Implementation:** `_run_scan(scan_ts, universe, force=False)` receives `force` parameter. The bearish gate becomes `if not regime["is_bullish"] and not force: return`. The trigger endpoint reads `force: bool = Query(False)` and passes it through.

**Frontend:** When `devMode` is active, `handleRunScan()` in App.jsx appends `?force=true` (and optionally `&dry_run=true`) to the scan trigger URL.

---

## Feature 3: Engine Health Panel

**Location:** Bottom of the left sidebar, below the scan footer. Only rendered when `devMode` is active. Collapsed by default, expandable.

**Data source:** `GET /api/scan-status` — extend the existing response payload with `engine_stats`:

```json
{
  "engine_stats": {
    "e0": { "spy": 512.34, "ema": 498.21, "duration_s": 0.4 },
    "e1": { "zones_saved": 643, "duration_s": 2.1 },
    "e2": { "vcp": 14, "watchlist": 8, "duration_s": 8.3 },
    "e3": { "pullback": 6, "relaxed": 3, "duration_s": 7.1 },
    "e5": { "base": 3, "cup_handle": 2, "flat_base": 1, "duration_s": 5.2 },
    "e6": { "res_breakout": 2, "duration_s": 4.8 },
    "total_tickers": 643,
    "total_duration_s": 28.1,
    "forced": false,
    "dry_run": false
  }
}
```

**Backend:** `_scan_state` dict (already global in `main.py`) gets an `engine_stats` key. Each engine phase in `_run_scan()` updates it with counts and timing as it runs. Counts are reset to zero at scan start.

**Frontend component:** `EngineHealthPanel` in a new file `EngineHealthPanel.jsx`. Renders a compact monospace table. Shown in App.jsx's left sidebar below `ScanFooter`, gated on `devMode`.

---

## Feature 4: Dry-Run Mode

**`POST /api/run-scan?force=true&dry_run=true`** — runs the full pipeline but skips all DB write calls:
- `batch_save_setups()` skipped
- `save_sr_zones()` skipped
- `save_regime()` skipped
- `complete_scan_run()` still called (so scan appears in status)

Results still flow through `_scan_state` and `engine_stats`, so the health panel shows what would have been saved.

**Implementation:** `_run_scan(scan_ts, universe, force=False, dry_run=False)`. Gate all DB writes with `if not dry_run`.

**Frontend:** Second toggle in dev panel: a `DRY RUN` checkbox that appears when `devMode` is active. Appends `&dry_run=true` to the scan trigger URL.

---

## Feature 5: Per-Ticker Debug Drill-Down

**Trigger:** When `devMode` is active, each row in `SetupTable` renders a small `[?]` icon (9px, muted, amber on hover). Clicking it calls `GET /api/debug/{ticker}` and opens a `DebugDrawer` component.

**`GET /api/debug/{ticker}` endpoint:** Fetches yfinance data for the ticker, fetches latest regime + zones from DB, runs all engines in debug mode, returns structured JSON:

```json
{
  "ticker": "NVDA",
  "regime": { "is_bullish": true, "spy_close": 512.34, "spy_20ema": 498.21 },
  "zones": [{ "level": 140.5, "type": "RESISTANCE", "upper": 141.2, "lower": 139.8 }],
  "rs": { "ratio": 0.08, "blue_dot": true, "rs_score": 84 },
  "engine2": { "result": "VCP", "path": "B", "rejection": null, "vol_surge": true },
  "engine3": { "result": "SKIP", "rejection": "close < EMA20" },
  "engine5": { "result": "FLAT_BASE", "quality_score": 72, "rejection": null },
  "engine6": { "result": "SKIP", "rejection": "volume < 150% of SMA50" }
}
```

The endpoint reuses existing engine functions with their current return values. The `rejection` field is derived from the return value being `None` vs a dict (and using the debug message from existing `debug_ticker.py` logic).

**`DebugDrawer` component:** Slides in from the right over the chart (not replacing it — overlaid at z-index). Sections for each engine: a green ✓ or red ✗ badge, result label, key numeric values. Close with `×` or `Escape`.

---

## What Does NOT Change

- The live `regime` display — always shows the real market state.
- The `trading.db` schema — no new tables.
- The `scan_setups` table structure — engine results in dev/force mode are saved identically.
- The Portfolio tab — unaffected.
- The `debug_ticker.py` CLI script — kept as-is; the API endpoint reuses the same logic.
