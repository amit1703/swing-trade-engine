# IS/OOS Split Tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a third "IS / OOS Split" tab to DiagnosticsTab that runs two sequential portfolio backtests and shows a metric comparison table with a delta row.

**Architecture:** Backend adds three endpoints (`/api/diagnostics/isoos/*`) to `main.py` using the same lock + background-task + atomic-cache pattern as the existing backtest endpoints. Frontend adds a third source tab `'isoos'` to `DiagnosticsTab.jsx` with its own config state, polling, and results renderer.

**Tech Stack:** FastAPI (Python), React 18, existing `run_portfolio_backtest_universe`, `compute_live_diagnostics`, `compute_setup_breakdown` from `analytics.py`.

---

## File Map

| File | Change |
|------|--------|
| `backend/main.py` | Add `ISOOSRunRequest` model, `_isoos_running`/`_isoos_status` globals, `ISOOS_DIAG_CACHE_PATH`, and 3 new endpoints |
| `backend/tests/test_isoos_endpoint.py` | New test file — unit tests for IS/OOS state and endpoint logic |
| `frontend/src/components/DiagnosticsTab.jsx` | Add `'isoos'` source tab, config state, polling, comparison table renderer |

No other files need to change.

---

## Task 1: Backend — IS/OOS endpoints in main.py

**Files:**
- Modify: `swing-trading-dashboard/backend/main.py`
- Test: `swing-trading-dashboard/backend/tests/test_isoos_endpoint.py`

The backtest endpoints live at lines ~3311–3428. Add the IS/OOS block immediately after the existing `GET /api/diagnostics/backtest` endpoint and before the `DELETE /api/trades/{trade_id}` endpoint.

- [ ] **Step 1: Write the failing tests**

Create `swing-trading-dashboard/backend/tests/test_isoos_endpoint.py`:

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_isoos_run_request_defaults():
    """ISOOSRunRequest has correct default values."""
    import main as m
    req = m.ISOOSRunRequest()
    assert req.is_start_date == "2017-01-01"
    assert req.is_end_date == "2021-12-31"
    assert req.oos_start_date == "2022-01-01"
    assert req.oos_end_date == "2024-12-31"
    assert req.max_positions == 4
    assert req.ticker_count is None
    assert req.min_score == 0.0
    assert "PULLBACK" in req.setup_types
    assert "VCP" not in req.setup_types


def test_isoos_status_initial_state():
    """_isoos_status global starts idle."""
    import main as m
    # Reset to known state
    m._isoos_status.update({
        "status": "idle", "is_done": False,
        "current": 0, "total": 0, "phase": None, "error": None,
    })
    assert m._isoos_status["status"] == "idle"
    assert m._isoos_status["is_done"] is False
    assert m._isoos_status["phase"] is None
    assert m._isoos_status["error"] is None


def test_isoos_cache_path_is_in_cache_dir():
    """ISOOS_DIAG_CACHE_PATH resolves inside the cache/ directory."""
    import main as m
    assert "isoos_diagnostics.json" in m.ISOOS_DIAG_CACHE_PATH
    assert "cache" in m.ISOOS_DIAG_CACHE_PATH.replace("\\", "/")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd swing-trading-dashboard/backend
python -m pytest tests/test_isoos_endpoint.py -v
```

Expected: FAIL — `ImportError` or `AttributeError` (ISOOSRunRequest, _isoos_status, ISOOS_DIAG_CACHE_PATH not yet defined)

- [ ] **Step 3: Add ISOOSRunRequest model to main.py**

Locate the `BacktestRunRequest` class (around line 1904). Add the new model directly after it:

```python
class ISOOSRunRequest(BaseModel):
    is_start_date:  str           = "2017-01-01"
    is_end_date:    str           = "2021-12-31"
    oos_start_date: str           = "2022-01-01"
    oos_end_date:   str           = "2024-12-31"
    max_positions:  int           = 4
    ticker_count:   Optional[int] = None
    min_score:      float         = 0.0
    setup_types:    List[str]     = Field(default_factory=lambda: [
        "PULLBACK", "BASE", "RES_BREAKOUT", "HTF", "LCE"
    ])
```

- [ ] **Step 4: Add IS/OOS globals and cache path**

Locate the block starting with `# ── Backtest diagnostics state` (around line 435). Add the IS/OOS state block immediately after the existing `_backtest_diag_status` block and `_backtest_trade_to_analytics` function:

```python
# ── IS/OOS diagnostics state ──────────────────────────────────────────────────
ISOOS_DIAG_CACHE_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "cache", "isoos_diagnostics.json")
)

_isoos_running: bool = False
_isoos_status: dict = {
    "status":  "idle",   # "idle" | "running_is" | "running_oos" | "completed" | "failed"
    "is_done": False,
    "current": 0,
    "total":   0,
    "phase":   None,     # "is" | "oos" | "done" | None
    "error":   None,
}
```

- [ ] **Step 5: Run tests — should now pass**

```bash
cd swing-trading-dashboard/backend
python -m pytest tests/test_isoos_endpoint.py -v
```

Expected: PASS (all 3 tests green)

- [ ] **Step 6: Add the three IS/OOS endpoints to main.py**

Add these three endpoints after the existing `GET /api/diagnostics/backtest` endpoint (around line 3428), before the `DELETE /api/trades/{trade_id}` endpoint:

```python
# ── IS / OOS Split endpoints ──────────────────────────────────────────────────

@app.post("/api/diagnostics/isoos/run", status_code=202)
async def run_isoos_diagnostics(
    background_tasks: BackgroundTasks,
    req: ISOOSRunRequest = Body(default=ISOOSRunRequest()),
):
    """
    Trigger IS/OOS split backtest. Runs two sequential portfolio backtests
    (IS period then OOS period) and caches combined results.
    Returns 409 if already running.
    """
    global _isoos_running, _isoos_status
    if _isoos_running:
        raise HTTPException(status_code=409, detail="IS/OOS backtest already running")

    all_tickers = list(ACTIVE_UNIVERSE) if ACTIVE_UNIVERSE else list(SCAN_UNIVERSE)
    tickers     = all_tickers[:req.ticker_count] if req.ticker_count else all_tickers

    _isoos_running = True
    _isoos_status.update({
        "status":  "running_is",
        "is_done": False,
        "current": 0,
        "total":   len(tickers),
        "phase":   "is",
        "error":   None,
    })

    async def _do_isoos():
        global _isoos_running, _isoos_status
        try:
            # ── Phase IS ──────────────────────────────────────────────────
            async def _progress_is(done: int, total: int):
                _isoos_status["current"] = done
                _isoos_status["total"]   = total

            is_config = BacktestConfig(
                start_date    = req.is_start_date,
                end_date      = req.is_end_date,
                max_positions = req.max_positions,
                ticker_count  = req.ticker_count,
                min_score     = req.min_score,
                setup_types   = req.setup_types,
            )
            is_raw = await run_portfolio_backtest_universe(
                tickers, is_config, params=BacktestParams(), progress_cb=_progress_is
            )
            is_adapted = [_backtest_trade_to_analytics(t) for t in is_raw]

            # ── Phase OOS ─────────────────────────────────────────────────
            _isoos_status.update({
                "status":  "running_oos",
                "phase":   "oos",
                "current": 0,
                "total":   len(tickers),
            })

            async def _progress_oos(done: int, total: int):
                _isoos_status["current"] = done
                _isoos_status["total"]   = total

            oos_config = BacktestConfig(
                start_date    = req.oos_start_date,
                end_date      = req.oos_end_date,
                max_positions = req.max_positions,
                ticker_count  = req.ticker_count,
                min_score     = req.min_score,
                setup_types   = req.setup_types,
            )
            oos_raw = await run_portfolio_backtest_universe(
                tickers, oos_config, params=BacktestParams(), progress_cb=_progress_oos
            )
            oos_adapted = [_backtest_trade_to_analytics(t) for t in oos_raw]

            # ── Analytics & cache ─────────────────────────────────────────
            report = {
                "generated_at":   datetime.now(timezone.utc).isoformat(),
                "config": {
                    "is_start_date":  req.is_start_date,
                    "is_end_date":    req.is_end_date,
                    "oos_start_date": req.oos_start_date,
                    "oos_end_date":   req.oos_end_date,
                    "max_positions":  req.max_positions,
                    "setup_types":    req.setup_types,
                    "min_score":      req.min_score,
                },
                "is": {
                    "summary":         compute_live_diagnostics(is_adapted),
                    "setup_breakdown": compute_setup_breakdown(is_adapted),
                },
                "oos": {
                    "summary":         compute_live_diagnostics(oos_adapted),
                    "setup_breakdown": compute_setup_breakdown(oos_adapted),
                },
            }

            os.makedirs(os.path.dirname(ISOOS_DIAG_CACHE_PATH), exist_ok=True)
            tmp_fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(ISOOS_DIAG_CACHE_PATH))
            try:
                with os.fdopen(tmp_fd, "w") as f:
                    json.dump(report, f, cls=_NumpyEncoder)
                os.replace(tmp_path, ISOOS_DIAG_CACHE_PATH)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise

            _isoos_status.update({
                "status":  "completed",
                "is_done": True,
                "phase":   "done",
            })
            log.info("IS/OOS backtest complete: IS=%d trades, OOS=%d trades",
                     len(is_adapted), len(oos_adapted))

        except Exception as exc:
            _isoos_status.update({
                "status": "failed",
                "error":  str(exc),
            })
            log.error("IS/OOS backtest failed: %s", exc)
        finally:
            _isoos_running = False

    background_tasks.add_task(_do_isoos)
    return {"status": "started", "tickers": len(tickers)}


@app.get("/api/diagnostics/isoos/status")
async def isoos_diagnostics_status():
    """Poll progress of the IS/OOS background backtest run."""
    return {
        "status":  _isoos_status["status"],
        "is_done": _isoos_status["is_done"],
        "current": _isoos_status["current"],
        "total":   _isoos_status["total"],
        "phase":   _isoos_status["phase"],
        "error":   _isoos_status["error"],
    }


@app.get("/api/diagnostics/isoos")
async def isoos_diagnostics_report():
    """
    Return the cached IS/OOS split diagnostics report.
    Returns 404 if no run has been completed yet.
    """
    if not os.path.exists(ISOOS_DIAG_CACHE_PATH):
        raise HTTPException(
            status_code=404,
            detail="No IS/OOS cache found. POST /api/diagnostics/isoos/run to generate.",
        )
    try:
        with open(ISOOS_DIAG_CACHE_PATH, "r") as f:
            return json.load(f)
    except Exception as exc:
        log.error("Failed to read IS/OOS diagnostics cache: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to read IS/OOS cache")
```

- [ ] **Step 7: Verify server starts without errors**

```bash
cd swing-trading-dashboard/backend
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Expected: starts cleanly, no import errors. Hit Ctrl+C to stop.

- [ ] **Step 8: Commit**

```bash
cd swing-trading-dashboard
git add backend/main.py backend/tests/test_isoos_endpoint.py
git commit -m "feat: add IS/OOS split backtest endpoints"
```

---

## Task 2: Frontend — IS/OOS tab in DiagnosticsTab.jsx

**Files:**
- Modify: `swing-trading-dashboard/frontend/src/components/DiagnosticsTab.jsx`

DiagnosticsTab currently has `source` state with values `'live'` and `'backtest'`. We add `'isoos'` as a third option. It gets its own config state, polling, and results section. We do NOT touch the `'live'` or `'backtest'` sections.

Read the full file first before editing: there are multiple conditional blocks keyed on `source === 'backtest'` — the new `'isoos'` sections are added in parallel, not interleaved.

- [ ] **Step 1: Add isoos state variables**

After the existing state declarations (around line 234), add:

```jsx
const [ioConfig, setIoConfig] = useState({
  isStartYear:  2017,
  isEndYear:    2021,
  oosStartYear: 2022,
  oosEndYear:   2024,
  maxPositions: 4,
  minScore:     0,
  setupTypes:   ['PULLBACK', 'BASE', 'RES_BREAKOUT', 'HTF', 'LCE'],
})
const [ioRunning, setIoRunning]               = useState(false)
const [ioStatus, setIoStatus]                 = useState(null)
const [ioData, setIoData]                     = useState(null)
const [ioError, setIoError]                   = useState(null)
const ioPollRef                               = useRef(null)
const [showIsBreakdown, setShowIsBreakdown]   = useState(false)
const [showOosBreakdown, setShowOosBreakdown] = useState(false)
```

- [ ] **Step 2: Add fetchData branch for isoos**

In the `fetchData` function inside the `useEffect` (around line 250), update the URL selection line:

```jsx
const url = source === 'live'
  ? '/api/diagnostics/report'
  : source === 'backtest'
  ? '/api/diagnostics/backtest'
  : '/api/diagnostics/isoos'
```

Then replace the block from `if (res.status === 404 && source === 'backtest')` through `setData(await res.json())` (the last line of the try body) with:

```jsx
if (res.status === 404 && source === 'backtest') {
  setData(null)
  setLoading(false)
  return
}
if (res.status === 404 && source === 'isoos') {
  setIoData(null)
  setLoading(false)
  return
}
if (!res.ok) throw new Error(`HTTP ${res.status}`)
const json = await res.json()
if (source === 'isoos') {
  setIoData(json)
} else {
  setData(json)
}
```

This replaces the original `setData(await res.json())` call — make sure that old line is removed and only the new if/else remains.

- [ ] **Step 3: Add IS/OOS polling logic**

After the existing `useEffect` for `btRunning` polling (around line 276), add a parallel polling effect for IS/OOS:

```jsx
useEffect(() => {
  if (!ioRunning) return
  ioPollRef.current = setInterval(async () => {
    try {
      const s = await fetch('/api/diagnostics/isoos/status').then(r => r.json())
      setIoStatus(s)
      if (s.status === 'completed' || s.status === 'failed') {
        clearInterval(ioPollRef.current)
        setIoRunning(false)
        if (s.status === 'completed') {
          const result = await fetch('/api/diagnostics/isoos').then(r => r.json())
          setIoData(result)
          setIoError(null)
        } else {
          setIoError(s.error || 'IS/OOS backtest failed')
        }
      }
    } catch (err) {
      clearInterval(ioPollRef.current)
      setIoRunning(false)
      setIoError(err.message)
    }
  }, 3000)
  return () => clearInterval(ioPollRef.current)
}, [ioRunning])
```

- [ ] **Step 4: Add handleRunIsOos function**

After the existing `handleRunBacktest` function (around line 295), add:

```jsx
async function handleRunIsOos() {
  if (ioRunning) return
  setIoRunning(true)
  setIoError(null)
  try {
    await fetch('/api/diagnostics/isoos/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        is_start_date:  `${ioConfig.isStartYear}-01-01`,
        is_end_date:    `${ioConfig.isEndYear}-12-31`,
        oos_start_date: `${ioConfig.oosStartYear}-01-01`,
        oos_end_date:   `${ioConfig.oosEndYear}-12-31`,
        max_positions:  ioConfig.maxPositions,
        min_score:      ioConfig.minScore,
        setup_types:    ioConfig.setupTypes,
      }),
    })
    const s = await fetch('/api/diagnostics/isoos/status').then(r => r.json())
    setIoStatus(s)
  } catch (err) {
    setIoRunning(false)
    setIoError(err.message)
  }
}
```

- [ ] **Step 5: Add "IS / OOS Split" to the source toggle**

Find the source toggle section (around line 356). It currently maps `['live', 'backtest']`. Change to include `'isoos'`:

```jsx
{['live', 'backtest', 'isoos'].map(src => (
  <button
    key={src}
    onClick={() => { setSource(src); setData(null); if (src !== 'isoos') setIoData(null) }}
    style={{
      padding: '5px 14px', borderRadius: 6, fontSize: 11, fontWeight: 700,
      fontFamily: '"IBM Plex Mono", monospace', letterSpacing: '0.05em',
      border: source === src ? '1px solid var(--accent)' : '1px solid var(--border)',
      background: source === src ? 'rgba(245,166,35,0.12)' : 'transparent',
      color: source === src ? 'var(--accent)' : 'var(--muted)',
      cursor: 'pointer',
    }}
  >
    {src === 'live' ? 'Live Trades' : src === 'backtest' ? 'Full System Backtest' : 'IS / OOS Split'}
  </button>
))}
```

- [ ] **Step 6: Add IS/OOS config panel**

After the existing backtest config panel block (`{source === 'backtest' && (...)}`), add the IS/OOS config panel:

```jsx
{/* IS/OOS config panel */}
{source === 'isoos' && (
  <div style={{
    padding: '12px 20px', borderBottom: '1px solid var(--border)',
    background: 'rgba(255,255,255,0.02)',
  }}>
    <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
      <span style={{ fontSize: 10, color: 'var(--muted)', fontFamily: '"IBM Plex Mono", monospace' }}>IS</span>
      <input type="number" min={2010} max={2030} value={ioConfig.isStartYear}
        onChange={e => setIoConfig(c => ({ ...c, isStartYear: +e.target.value }))}
        style={{ width: 60, background: 'var(--card)', border: '1px solid var(--border)',
          color: 'var(--text)', borderRadius: 4, padding: '3px 6px', fontSize: 11,
          fontFamily: '"IBM Plex Mono", monospace' }} />
      <span style={{ fontSize: 10, color: 'var(--muted)' }}>→</span>
      <input type="number" min={2010} max={2030} value={ioConfig.isEndYear}
        onChange={e => setIoConfig(c => ({ ...c, isEndYear: +e.target.value }))}
        style={{ width: 60, background: 'var(--card)', border: '1px solid var(--border)',
          color: 'var(--text)', borderRadius: 4, padding: '3px 6px', fontSize: 11,
          fontFamily: '"IBM Plex Mono", monospace' }} />
      <span style={{ fontSize: 10, color: 'var(--muted)', marginLeft: 8 }}>OOS</span>
      <input type="number" min={2010} max={2030} value={ioConfig.oosStartYear}
        onChange={e => setIoConfig(c => ({ ...c, oosStartYear: +e.target.value }))}
        style={{ width: 60, background: 'var(--card)', border: '1px solid var(--border)',
          color: 'var(--text)', borderRadius: 4, padding: '3px 6px', fontSize: 11,
          fontFamily: '"IBM Plex Mono", monospace' }} />
      <span style={{ fontSize: 10, color: 'var(--muted)' }}>→</span>
      <input type="number" min={2010} max={2030} value={ioConfig.oosEndYear}
        onChange={e => setIoConfig(c => ({ ...c, oosEndYear: +e.target.value }))}
        style={{ width: 60, background: 'var(--card)', border: '1px solid var(--border)',
          color: 'var(--text)', borderRadius: 4, padding: '3px 6px', fontSize: 11,
          fontFamily: '"IBM Plex Mono", monospace' }} />
      <span style={{ fontSize: 10, color: 'var(--muted)', marginLeft: 8 }}>Pos</span>
      <input type="number" min={1} max={20} value={ioConfig.maxPositions}
        onChange={e => setIoConfig(c => ({ ...c, maxPositions: +e.target.value }))}
        style={{ width: 44, background: 'var(--card)', border: '1px solid var(--border)',
          color: 'var(--text)', borderRadius: 4, padding: '3px 6px', fontSize: 11,
          fontFamily: '"IBM Plex Mono", monospace' }} />
      <span style={{ fontSize: 10, color: 'var(--muted)' }}>MinScore</span>
      <input type="number" min={0} max={100} step={0.5} value={ioConfig.minScore}
        onChange={e => setIoConfig(c => ({ ...c, minScore: +e.target.value }))}
        style={{ width: 44, background: 'var(--card)', border: '1px solid var(--border)',
          color: 'var(--text)', borderRadius: 4, padding: '3px 6px', fontSize: 11,
          fontFamily: '"IBM Plex Mono", monospace' }} />
      <div style={{ display: 'flex', gap: 4, marginLeft: 4 }}>
        {['PULLBACK', 'BASE', 'RES_BREAKOUT', 'HTF', 'LCE'].map(st => (
          <label key={st} style={{ display: 'flex', alignItems: 'center', gap: 3,
            fontSize: 10, color: 'var(--muted)', fontFamily: '"IBM Plex Mono", monospace',
            cursor: 'pointer' }}>
            <input type="checkbox"
              checked={ioConfig.setupTypes.includes(st)}
              onChange={e => setIoConfig(c => ({
                ...c,
                setupTypes: e.target.checked
                  ? [...c.setupTypes, st]
                  : c.setupTypes.filter(x => x !== st),
              }))} />
            {st}
          </label>
        ))}
      </div>
      <button onClick={handleRunIsOos} disabled={ioRunning}
        style={{
          marginLeft: 'auto', padding: '4px 14px', borderRadius: 5, fontSize: 11,
          fontFamily: '"IBM Plex Mono", monospace', fontWeight: 700, letterSpacing: '0.05em',
          background: 'rgba(245,166,35,0.15)', color: ioRunning ? 'var(--muted)' : 'var(--accent)',
          border: `1px solid ${ioRunning ? 'var(--border)' : 'rgba(245,166,35,0.35)'}`,
          cursor: ioRunning ? 'not-allowed' : 'pointer',
        }}>
        {ioRunning ? 'Running…' : 'RUN IS/OOS'}
      </button>
    </div>
  </div>
)}
```

- [ ] **Step 7: Add IS/OOS loading, empty, and error states**

After the backtest first-run loading block (`{source === 'backtest' && !data && btRunning && (...)}`), add:

```jsx
{/* IS/OOS running progress */}
{source === 'isoos' && ioRunning && (
  <div style={{ padding: '24px 20px' }}>
    <div style={{ fontSize: 10, color: 'var(--accent)', fontFamily: '"IBM Plex Mono", monospace', marginBottom: 6 }}>
      {ioStatus?.phase === 'oos' ? 'Running OOS period' : 'Running IS period'} — {ioStatus?.current ?? 0} / {ioStatus?.total ?? '…'}…
    </div>
    <div style={{ height: 3, background: 'var(--border)', borderRadius: 2, width: '100%' }}>
      <div style={{
        height: '100%', borderRadius: 2, background: 'var(--accent)',
        width: ioStatus?.total > 0 ? `${(ioStatus.current / ioStatus.total * 100)}%` : '0%',
        transition: 'width 0.5s ease',
      }} />
    </div>
  </div>
)}

{/* IS/OOS empty state */}
{source === 'isoos' && !ioData && !ioRunning && !ioError && (
  <div style={{ padding: 40, textAlign: 'center', color: 'var(--muted)', fontSize: 12 }}>
    Configure IS and OOS date ranges above, then click RUN IS/OOS.
  </div>
)}

{/* IS/OOS error state */}
{source === 'isoos' && ioError && (
  <div style={{ padding: '16px 20px', color: 'var(--halt)', fontSize: 12,
    fontFamily: '"IBM Plex Mono", monospace' }}>
    Error: {ioError}
    <button onClick={handleRunIsOos} style={{ marginLeft: 12, fontSize: 11, color: 'var(--accent)',
      background: 'none', border: 'none', cursor: 'pointer', textDecoration: 'underline' }}>
      Retry
    </button>
  </div>
)}
```

- [ ] **Step 8: Add the IS/OOS comparison table and setup breakdown**

After the error state block, add the results section. This renders when `source === 'isoos' && ioData`:

```jsx
{/* IS/OOS results */}
{source === 'isoos' && ioData && !ioRunning && (() => {
  const is  = ioData.is?.summary  ?? {}
  const oos = ioData.oos?.summary ?? {}

  const metrics = [
    {
      key: 'win_rate',
      label: 'WIN RATE',
      fmt: v => v != null ? `${(v * 100).toFixed(1)}%` : '—',
      delta: v => v != null ? `${v >= 0 ? '+' : ''}${(v * 100).toFixed(1)}%` : '—',
    },
    {
      key: 'profit_factor',
      label: 'PROFIT F.',
      fmt: v => v != null ? v.toFixed(2) : '—',
      delta: v => v != null ? `${v >= 0 ? '+' : ''}${v.toFixed(2)}` : '—',
    },
    {
      key: 'avg_R',
      label: 'AVG R',
      fmt: v => v != null ? `${v >= 0 ? '+' : ''}${v.toFixed(2)}R` : '—',
      delta: v => v != null ? `${v >= 0 ? '+' : ''}${v.toFixed(2)}R` : '—',
    },
    {
      key: 'max_drawdown',
      label: 'MAX DD',
      fmt: v => v != null ? `${v.toFixed(2)}R` : '—',
      delta: v => v != null ? `${v >= 0 ? '+' : ''}${v.toFixed(2)}R` : '—',
    },
    {
      key: 'total_trades',
      label: 'TRADES',
      fmt: v => v ?? '—',
      delta: () => '—',
      noColor: true,
    },
  ]

  const colStyle = { padding: '6px 12px', textAlign: 'right', fontSize: 12,
    fontFamily: '"IBM Plex Mono", monospace' }
  const hStyle   = { ...colStyle, fontSize: 9, color: 'var(--muted)',
    letterSpacing: '0.08em', fontWeight: 700 }

  const [showIsBreakdown, setShowIsBreakdown]   = useState(false)
  const [showOosBreakdown, setShowOosBreakdown] = useState(false)

  return (
    <div style={{ padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* Run metadata */}
      {ioData.config && (
        <div style={{ fontSize: 10, color: 'var(--muted)', fontFamily: '"IBM Plex Mono", monospace' }}>
          IS: {ioData.config.is_start_date} → {ioData.config.is_end_date}
          {' · '}OOS: {ioData.config.oos_start_date} → {ioData.config.oos_end_date}
          {' · '}max {ioData.config.max_positions} pos
          {' · '}generated {ioData.generated_at
            ? new Date(ioData.generated_at).toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'short' })
            : '—'}
        </div>
      )}

      {/* Comparison table */}
      <div style={{ background: 'var(--card)', border: '1px solid var(--card-border)',
        borderRadius: 10, overflow: 'hidden' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ borderBottom: '1px solid var(--card-border)' }}>
              <th style={{ ...hStyle, textAlign: 'left' }}></th>
              {metrics.map(m => (
                <th key={m.key} style={hStyle}>{m.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {/* IN-SAMPLE row */}
            <tr style={{ borderBottom: '1px solid var(--card-border)' }}>
              <td style={{ ...colStyle, textAlign: 'left', fontSize: 10,
                color: '#50d8f0', fontWeight: 700, letterSpacing: '0.06em' }}>
                IN-SAMPLE
              </td>
              {metrics.map(m => (
                <td key={m.key} style={{ ...colStyle, color: 'var(--text)' }}>
                  {m.fmt(is[m.key])}
                </td>
              ))}
            </tr>
            {/* OUT-OF-SAMPLE row */}
            <tr style={{ borderBottom: '1px solid var(--card-border)' }}>
              <td style={{ ...colStyle, textAlign: 'left', fontSize: 10,
                color: '#f5a623', fontWeight: 700, letterSpacing: '0.06em' }}>
                OUT-OF-SAMPLE
              </td>
              {metrics.map(m => (
                <td key={m.key} style={{ ...colStyle, color: 'var(--text)' }}>
                  {m.fmt(oos[m.key])}
                </td>
              ))}
            </tr>
            {/* DELTA row */}
            <tr>
              <td style={{ ...colStyle, textAlign: 'left', fontSize: 10,
                color: 'var(--muted)', letterSpacing: '0.06em' }}>
                DELTA
              </td>
              {metrics.map(m => {
                const d = (oos[m.key] != null && is[m.key] != null)
                  ? oos[m.key] - is[m.key]
                  : null
                const color = m.noColor || d == null
                  ? 'var(--muted)'
                  : d < 0 ? 'var(--halt)' : d > 0 ? 'var(--go)' : 'var(--muted)'
                return (
                  <td key={m.key} style={{ ...colStyle, color, fontWeight: 700 }}>
                    {m.delta(d)}
                  </td>
                )
              })}
            </tr>
          </tbody>
        </table>
      </div>

      {/* IS breakdown (collapsible) */}
      <div style={{ background: 'var(--card)', border: '1px solid var(--card-border)', borderRadius: 10 }}>
        <button onClick={() => setShowIsBreakdown(v => !v)}
          style={{ width: '100%', padding: '10px 16px', background: 'none', border: 'none',
            cursor: 'pointer', display: 'flex', justifyContent: 'space-between', alignItems: 'center',
            color: 'var(--muted)', fontSize: 10, fontFamily: '"IBM Plex Mono", monospace',
            letterSpacing: '0.08em', fontWeight: 700 }}>
          <span style={{ color: '#50d8f0' }}>IN-SAMPLE BREAKDOWN</span>
          <span>{showIsBreakdown ? '▲' : '▼'}</span>
        </button>
        {showIsBreakdown && (
          <div style={{ padding: '0 16px 16px' }}>
            <SetupBreakdownTable breakdown={ioData.is?.setup_breakdown} />
          </div>
        )}
      </div>

      {/* OOS breakdown (collapsible) */}
      <div style={{ background: 'var(--card)', border: '1px solid var(--card-border)', borderRadius: 10 }}>
        <button onClick={() => setShowOosBreakdown(v => !v)}
          style={{ width: '100%', padding: '10px 16px', background: 'none', border: 'none',
            cursor: 'pointer', display: 'flex', justifyContent: 'space-between', alignItems: 'center',
            color: 'var(--muted)', fontSize: 10, fontFamily: '"IBM Plex Mono", monospace',
            letterSpacing: '0.08em', fontWeight: 700 }}>
          <span style={{ color: '#f5a623' }}>OUT-OF-SAMPLE BREAKDOWN</span>
          <span>{showOosBreakdown ? '▲' : '▼'}</span>
        </button>
        {showOosBreakdown && (
          <div style={{ padding: '0 16px 16px' }}>
            <SetupBreakdownTable breakdown={ioData.oos?.setup_breakdown} />
          </div>
        )}
      </div>
    </div>
  )
})()}
```

- [ ] **Step 9: Verify in browser**

Start the dev server:
```bash
cd swing-trading-dashboard/frontend
npm run dev
```

Navigate to Diagnostics. Confirm:
- Three tabs visible: Live Trades | Full System Backtest | IS / OOS Split
- Clicking "IS / OOS Split" shows config panel with IS/OOS date inputs and RUN IS/OOS button
- Other tabs still work as before
- No console errors

- [ ] **Step 10: Commit**

```bash
cd swing-trading-dashboard
git add frontend/src/components/DiagnosticsTab.jsx
git commit -m "feat: add IS/OOS split tab to DiagnosticsTab"
```

---

## Task 3: Deploy to VPS

- [ ] **Step 1: Push to remote**

```bash
cd swing-trading-dashboard
git push origin main
```

- [ ] **Step 2: Pull, rebuild, restart on VPS**

```bash
ssh root@89.167.25.25 "cd /opt/dashboard && git pull && cd swing-trading-dashboard/frontend && npm run build && systemctl restart dashboard && echo DONE"
```

Expected: `DONE` printed, no errors.

- [ ] **Step 3: Smoke test**

```bash
curl -s http://89.167.25.25/api/diagnostics/isoos/status | python3 -m json.tool
```

Expected: `{"status": "idle", "is_done": false, "current": 0, "total": 0, "phase": null, "error": null}`
