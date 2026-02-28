# DRY RUN Setups Display Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make DRY RUN mode a true safe mode — engines run, EngineHealthPanel shows counts, and SetupTables show tickers, all without any DB writes.

**Architecture:** During a dry_run scan, `collected_setups` is organized by type and stored in `_scan_state["dry_run_setups"]` after hot-sector injection. The `scan-status` endpoint returns this field. The frontend poll loop detects `dry_run=true` on scan completion and populates the SetupTables from this in-memory response instead of calling `loadAllData()` (which reads from DB).

**Tech Stack:** Python / FastAPI (`main.py`), React (`App.jsx`), pytest (`test_dev_mode.py`)

---

### Task 1: Backend — `dry_run_setups` in `_scan_state` and `scan_status`

**Files:**
- Modify: `swing-trading-dashboard/backend/main.py:148` (initializer), `main.py:293` (reset), `main.py:638` (populate), `main.py:786` (response)
- Test: `swing-trading-dashboard/backend/tests/test_dev_mode.py`

---

**Step 1: Write three failing tests in `test_dev_mode.py`**

Add these three tests at the bottom of the file:

```python
def test_scan_status_includes_dry_run_setups_key():
    """GET /api/scan-status must always return a dry_run_setups field."""
    resp = client.get("/api/scan-status")
    assert resp.status_code == 200
    assert "dry_run_setups" in resp.json()


def test_dry_run_setups_is_none_by_default():
    """dry_run_setups must be None when no dry run has completed."""
    m._scan_state["dry_run_setups"] = None   # explicit reset
    resp = client.get("/api/scan-status")
    assert resp.json()["dry_run_setups"] is None


def test_dry_run_setups_returned_when_populated():
    """When _scan_state has dry_run_setups, scan_status returns them verbatim."""
    m._scan_state["dry_run_setups"] = {
        "vcp": [{"ticker": "TEST", "setup_type": "VCP"}],
        "pullback": [],
        "base": [],
        "res_breakout": [],
        "watchlist": [],
    }
    resp = client.get("/api/scan-status")
    data = resp.json()
    assert data["dry_run_setups"]["vcp"][0]["ticker"] == "TEST"
```

**Step 2: Run to confirm all three fail**

```bash
cd swing-trading-dashboard/backend
pytest tests/test_dev_mode.py::test_scan_status_includes_dry_run_setups_key tests/test_dev_mode.py::test_dry_run_setups_is_none_by_default tests/test_dev_mode.py::test_dry_run_setups_returned_when_populated -v
```

Expected: all 3 FAIL — `KeyError: 'dry_run_setups'` or `AssertionError`

---

**Step 3: Add `"dry_run_setups": None` to the module-level `_scan_state` initializer**

File: `main.py`, around line 147–148. The initializer currently ends with:

```python
        "dry_run": False,
    },
}
```

Change to:

```python
        "dry_run": False,
    },
    "dry_run_setups": None,
}
```

**Step 4: Add `dry_run_setups=None` to the per-scan reset inside `_run_scan()`**

File: `main.py`, around line 276–294. The `_scan_state.update(...)` call currently ends with:

```python
        },
    )
```

Change the closing to include the reset:

```python
        },
        dry_run_setups=None,
    )
```

**Step 5: Populate `dry_run_setups` after hot-sector injection**

File: `main.py`, around line 638–642. Currently:

```python
        # ── Batch Save All Setups (5-10x faster than individual saves) ──────
        if collected_setups and not dry_run:
            db_save_start = time.time()
            await batch_save_setups(DB_PATH, scan_ts, collected_setups)
            db_save_time = time.time() - db_save_start
            log.info("Batch saved %d setups to database  [%.1fs]", len(collected_setups), db_save_time)
```

Change to:

```python
        # ── Batch Save All Setups (5-10x faster than individual saves) ──────
        if collected_setups and not dry_run:
            db_save_start = time.time()
            await batch_save_setups(DB_PATH, scan_ts, collected_setups)
            db_save_time = time.time() - db_save_start
            log.info("Batch saved %d setups to database  [%.1fs]", len(collected_setups), db_save_time)

        if collected_setups and dry_run:
            _scan_state["dry_run_setups"] = {
                "vcp":          [s for s in collected_setups if s.get("setup_type") == "VCP"],
                "pullback":     [s for s in collected_setups if s.get("setup_type") == "PULLBACK"],
                "base":         [s for s in collected_setups if s.get("setup_type") == "BASE"],
                "res_breakout": [s for s in collected_setups if s.get("setup_type") == "RES_BREAKOUT"],
                "watchlist":    [s for s in collected_setups if s.get("setup_type") == "WATCHLIST"],
            }
            log.info("DRY RUN: stored %d setups in memory (no DB write)", len(collected_setups))
```

**Step 6: Add `dry_run_setups` to the `scan_status` response**

File: `main.py`, around line 778–787. Currently:

```python
    return {
        "in_progress": _scan_state["in_progress"],
        "progress": _scan_state["progress"],
        "total": _scan_state["total"],
        "progress_pct": round(_scan_state["progress"] / total * 100, 1),
        "started_at": _scan_state["started_at"],
        "last_completed": _scan_state["last_completed"],
        "last_error": _scan_state["last_error"],
        "engine_stats": _scan_state["engine_stats"],
    }
```

Change to:

```python
    return {
        "in_progress": _scan_state["in_progress"],
        "progress": _scan_state["progress"],
        "total": _scan_state["total"],
        "progress_pct": round(_scan_state["progress"] / total * 100, 1),
        "started_at": _scan_state["started_at"],
        "last_completed": _scan_state["last_completed"],
        "last_error": _scan_state["last_error"],
        "engine_stats": _scan_state["engine_stats"],
        "dry_run_setups": _scan_state.get("dry_run_setups"),
    }
```

**Step 7: Run all tests to confirm the 3 new tests pass and nothing regresses**

```bash
cd swing-trading-dashboard/backend
pytest tests/test_dev_mode.py -v
```

Expected: all 9 existing tests + 3 new tests = **12 tests PASS**

Also run the full suite:

```bash
pytest --tb=short -q
```

Expected: all tests pass (currently 139).

**Step 8: Commit**

```bash
git add swing-trading-dashboard/backend/main.py swing-trading-dashboard/backend/tests/test_dev_mode.py
git commit -m "feat(dev): store dry_run_setups in _scan_state and expose via scan-status"
```

---

### Task 2: Frontend — use `dry_run_setups` in App.jsx poll loop

**Files:**
- Modify: `swing-trading-dashboard/frontend/src/App.jsx:148-151`

No automated test — verify manually by running the app with DEV + DRY RUN on and confirming SetupTables populate after scan.

---

**Step 1: Update the poll loop in App.jsx**

File: `App.jsx`, lines 148–151. Currently:

```js
        if (!status.in_progress) {
          clearInterval(pollTimerRef.current)
          loadAllData()
        }
```

Change to:

```js
        if (!status.in_progress) {
          clearInterval(pollTimerRef.current)
          if (status.engine_stats?.dry_run && status.dry_run_setups) {
            const dr = status.dry_run_setups
            setVcpSetups(dr.vcp ?? [])
            setPullbackSetups(dr.pullback ?? [])
            setBaseSetups(dr.base ?? [])
            setResBreakoutSetups(dr.res_breakout ?? [])
            setWatchlistItems(dr.watchlist ?? [])
          } else {
            loadAllData()
          }
        }
```

**Step 2: Verify the frontend still builds**

```bash
cd swing-trading-dashboard/frontend
npm run build 2>&1 | tail -20
```

Expected: no errors, build succeeds.

**Step 3: Commit**

```bash
git add swing-trading-dashboard/frontend/src/App.jsx
git commit -m "feat(dev): populate SetupTables from in-memory dry_run_setups after DRY RUN scan"
```

---

## Manual Verification Checklist

After both tasks are complete:

1. Start the backend: `uvicorn main:app --reload --host 0.0.0.0 --port 8000`
2. Start the frontend: `npm run dev`
3. Enable **DEV** toggle → enable **DRY RUN** toggle
4. Click **Run Scan**
5. Wait for scan to complete
6. Confirm:
   - EngineHealthPanel shows counts ✅
   - VCP / Pullback / Base / ResBreakout tables show tickers ✅
   - `trading.db` is NOT modified (check `last_completed` in scan-status stays at old value) ✅
