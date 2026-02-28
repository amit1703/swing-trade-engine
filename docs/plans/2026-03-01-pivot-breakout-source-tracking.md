# Pivot Breakout Source Tracking Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Propagate `zone_source` ("kde" or "pivot") from Engine 1 zone dicts through Engine 6's output so pivot resistance breakouts are traceable in the database and frontend.

**Architecture:** Engine 1 already produces both KDE zones (no `source` key) and pivot zones (`source: "pivot"`) in the same list passed to Engine 6. Engine 6 already scans against both — the only gap is that the candidate output dict doesn't carry which zone type triggered the breakout. Adding one field to the candidate dict is sufficient: `database.py` automatically serialises all non-core fields into the `metadata` JSON column, and `get_latest_setups` merges them back into the returned record, so the frontend already receives any extra field placed on the setup dict.

**Tech Stack:** Python, engine6.py only. No DB schema changes, no frontend changes.

---

### Task 1: Add `zone_source` to Engine 6 candidate output

**Files:**
- Modify: `swing-trading-dashboard/backend/engines/engine6.py:221-235`

**Context:** The `candidate` dict is built at line 221 inside the `for zone in resistance_zones` loop. `zone` is the dict from Engine 1 — KDE zones have no `source` key, pivot zones have `source: "pivot"`. We default to `"kde"` when the key is absent.

**Step 1: Open the file and locate the candidate dict**

The candidate dict (around line 221) currently looks like:

```python
candidate = {
    "ticker":              ticker,
    "setup_type":          "RES_BREAKOUT",
    "signal":              "BRK",
    "entry":               entry,
    "stop_loss":           stop_loss,
    "take_profit":         take_profit,
    "rr":                  actual_rr,
    "resistance_level":    round(zone_level, 2),
    "zone_upper":          round(zone_upper, 2),
    "breakout_pct":        breakout_pct,
    "volume_ratio":        round(vol_ratio, 2),
    "days_since_breakout": days_back,
    "setup_date":          str(data.index[-1].date()),
}
```

**Step 2: Add `zone_source` field**

Add one line after `"days_since_breakout"`:

```python
candidate = {
    "ticker":              ticker,
    "setup_type":          "RES_BREAKOUT",
    "signal":              "BRK",
    "entry":               entry,
    "stop_loss":           stop_loss,
    "take_profit":         take_profit,
    "rr":                  actual_rr,
    "resistance_level":    round(zone_level, 2),
    "zone_upper":          round(zone_upper, 2),
    "breakout_pct":        breakout_pct,
    "volume_ratio":        round(vol_ratio, 2),
    "days_since_breakout": days_back,
    "zone_source":         zone.get("source", "kde"),
    "setup_date":          str(data.index[-1].date()),
}
```

**Step 3: Verify the change looks correct**

Re-read the file around line 221–236 and confirm `zone_source` is present and in the right position (inside the candidate dict, not outside it).

**Step 4: Commit**

```bash
cd swing-trading-dashboard
git add backend/engines/engine6.py
git commit -m "feat(engine6): propagate zone_source (kde/pivot) in resistance breakout output"
```

---

### Task 2: Smoke-test via the debug endpoint

**Context:** The app exposes `GET /api/debug/{ticker}` which runs all engines live on a single ticker and returns per-engine results. This lets us verify the field appears without running a full scan.

**Step 1: Start the backend if not running**

```bash
cd swing-trading-dashboard/backend
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

**Step 2: Pick a ticker known to be near resistance and call the debug endpoint**

```bash
curl -s http://localhost:8000/api/debug/AAPL | python -m json.tool | grep -A2 "zone_source\|res_breakout\|engine6"
```

Expected: if Engine 6 fires for AAPL, the `engine6` block in the response will contain `"zone_source": "kde"` or `"zone_source": "pivot"`.

If Engine 6 doesn't fire for AAPL (no breakout found), the field won't appear — that's fine. Try a few tickers or confirm via a dry-run scan.

**Step 3: (Optional) Dry-run scan to verify field in batch output**

In the frontend, enable Dev Mode → Dry Run → Run Scan. After it completes, open the browser DevTools Network tab, find the `/api/scan-status` response, and inspect `dry_run_setups.res_breakout` — each setup there should now include `"zone_source"`.
