# Scanner UI Improvements Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Improve scanner usability with score column, distance-to-entry display, active row highlighting, chart focus mode, watchlist RS enhancements, better panel contrast, and a full-fidelity regime banner showing the 3-level classification, score, and engine status.

**Architecture:** Mostly frontend (React). One backend DB migration needed for Task 5 (add columns to `market_regime` table so the full regime state is persisted and returned). Five frontend files touched: `SetupTable.jsx`, `App.jsx`, `WatchlistPanel.jsx`, `index.css`, `Header.jsx`. One backend file: `database.py`.

**Tech Stack:** React 18, Tailwind CSS, CSS variables (IBM Plex Mono font). No new dependencies.

---

## Key Data Facts

- `s.setup_score` — unified 0–100 score, already in API response for all setup types
- `s.setup_date` — ISO date string for age calculation (already used for `daysOld` in signal column)
- `s.rs_score` — in WatchlistPanel items, range −1 to +1 (−1=worst, +1=best)
- `s.rs_blue_dot` — boolean, RS at 52-week high
- `s.distance_pct` — in WatchlistPanel items only (% away from breakout level)
- Distance to entry in SetupTable: computed as `((livePrices[ticker] - entry) / entry) * 100` — already exists as `dist` variable in the live price cell render (line 142)
- CSS variables: `--bg #000`, `--panel #0c111a`, `--surface #080c12`, `--border #1a2535`, `--border-light #253347`, `--accent #F5A623`, `--go #00c87a`, `--halt #ff2d55`

---

## Task 1: Score Column + Distance Display + Active Row Glow + Age Subtext

**Files:**
- Modify: `frontend/src/components/SetupTable.jsx` (complete rewrite of the table section)

**What to do:**
1. Add a new `Score` column (narrow, after Ticker) that shows `s.setup_score` color-coded:
   - 80–100: green (`var(--go)`)
   - 60–79: amber (`var(--accent)`)
   - below 60: muted (`var(--muted)`)
   - null/missing: show `—`
2. Enhance the "Now $" cell to show distance below the price as a second line:
   - Format: `2.1%↓` (below entry) or `▲0.3%` (above entry, green)
   - Color matches current price color logic
3. Add active row glow when `dist > -3 && dist < 0` (within 3% below entry):
   - Add `box-shadow: inset 3px 0 0 rgba(245,166,35,0.7)` to the TR style
   - This is a distinct amber left-stripe glow (different from the vol-surge green)
4. Move age display from the Signal column into the Ticker cell as a subscript:
   - Remove the age badge from the Signal column (lines 394–409 in original)
   - Add it below the ticker name in the Ticker cell

**Step 1: Read the file**

Read `frontend/src/components/SetupTable.jsx` to understand current structure (499 lines).

**Step 2: Write the updated SetupTable.jsx**

Key changes from the original file:

**A. Add Score column header** — in the `<thead>` section after `<th style={{ textAlign: 'left' }}>Ticker</th>`:
```jsx
<th style={{ textAlign: 'right', width: 32 }}>Scr</th>
```

**B. Update `rowStyle`** — extend the existing `rowStyle` logic (around line 90) to add glow:
```jsx
// Compute distance for glow detection
const livePrice = livePrices[s.ticker]
const distForRow = (livePrice && s.entry > 0)
  ? ((livePrice - s.entry) / s.entry) * 100
  : null
const isNearEntry = distForRow !== null && distForRow > -3 && distForRow < 0

const rowStyle = isVolSurge
  ? { background: 'rgba(0, 200, 122, 0.06)', borderLeft: '2px solid rgba(0,200,122,0.45)' }
  : isNearEntry
  ? { borderLeft: '3px solid rgba(245,166,35,0.7)', background: 'rgba(245,166,35,0.04)' }
  : {}
```

**C. Update Ticker cell** — add age subtext below ticker:
```jsx
{/* Ticker */}
<td>
  <div className="flex flex-col gap-0">
    <div className="flex items-center gap-1">
      <span
        className="font-600 tracking-wide"
        style={{ color: isSelected ? 'var(--accent)' : color.dot }}
      >
        {s.ticker}
      </span>
      {s.hot_sector && (
        <span title={`Hot sector: ${s.sector ?? ''} (3+ setups)`} style={{ marginLeft: 3, fontSize: 10 }}>🔥</span>
      )}
      <a
        href={`https://www.tradingview.com/chart/?symbol=${s.ticker}&interval=D`}
        target="_blank"
        rel="noopener noreferrer"
        onClick={e => e.stopPropagation()}
        title="Open in TradingView"
        style={{
          marginLeft: 5, fontSize: 8, padding: '1px 4px',
          border: '1px solid rgba(245,166,35,0.3)', color: 'rgba(245,166,35,0.55)',
          borderRadius: 2, fontFamily: '"IBM Plex Mono", monospace',
          fontWeight: 700, letterSpacing: '0.05em',
          textDecoration: 'none', userSelect: 'none',
        }}
      >
        TV
      </a>
    </div>
    {daysOld != null && daysOld >= 1 && (
      <span
        style={{
          fontSize: 7,
          color: daysOld >= 5 ? 'rgba(255,45,85,0.6)' : 'var(--muted)',
          letterSpacing: '0.04em',
        }}
      >
        {daysOld}d ago
      </span>
    )}
  </div>
</td>
```

**D. Add Score cell** — immediately after the Ticker `</td>`:
```jsx
{/* Score */}
{(() => {
  const sc = typeof s.setup_score === 'number' ? Math.round(s.setup_score) : null
  const scColor = sc === null ? 'var(--muted)'
    : sc >= 80 ? 'var(--go)'
    : sc >= 60 ? 'var(--accent)'
    : 'var(--muted)'
  return (
    <td style={{ textAlign: 'right' }}>
      <span className="font-mono text-[9px] tabular-nums" style={{ color: scColor }}>
        {sc !== null ? sc : '—'}
      </span>
    </td>
  )
})()}
```

**E. Update "Now $" cell** — replace the existing live price cell (lines 138–154) with one that shows distance below:
```jsx
{/* Now $ + distance */}
{(() => {
  const price = livePrices[s.ticker]
  if (!price) return <td className="text-t-muted" style={{ fontSize: 9 }}>—</td>
  const dist = s.entry > 0 ? ((price - s.entry) / s.entry) * 100 : null
  const priceColor = dist === null ? 'var(--muted)'
    : price >= s.entry ? 'var(--go)'
    : dist > -3 ? 'var(--accent)'
    : 'var(--muted)'
  const distLabel = dist === null ? null
    : price >= s.entry
    ? `▲${Math.abs(dist).toFixed(1)}%`
    : `${Math.abs(dist).toFixed(1)}%↓`
  const distColor = dist === null ? 'var(--muted)'
    : price >= s.entry ? 'var(--go)'
    : dist > -3 ? 'var(--accent)'
    : 'var(--muted)'
  return (
    <td>
      <div className="flex flex-col items-end gap-0">
        <span className="font-mono text-[9px] tabular-nums" style={{ color: priceColor }}>
          {price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
        </span>
        {distLabel && (
          <span className="font-mono tabular-nums" style={{ fontSize: 7, color: distColor }}>
            {distLabel}
          </span>
        )}
      </div>
    </td>
  )
})()}
```

**F. Remove age badge from Signal column** — delete lines 394–409 (the `{daysOld != null && daysOld >= 1 && ...}` block inside the Signal column). Age is now in the Ticker cell.

**G. Update colSpan** in the narrative expansion row — was `devMode ? 8 : 7`, now `devMode ? 9 : 8` (one extra column for Score).

**Step 3: Verify the file compiles**

Run: `cd frontend && npm run build 2>&1 | tail -20`
Expected: no errors (warnings are OK)

**Step 4: Commit**
```bash
git add frontend/src/components/SetupTable.jsx
git commit -m "feat(ui): add score column, distance display, near-entry glow, age subtext"
```

---

## Task 2: Chart Focus Mode (F key)

**Files:**
- Modify: `frontend/src/App.jsx`

**What to do:**
1. Add `chartFocus` state
2. Add `F` key handler (alongside the existing `?` handler in the same `useEffect`)
3. When `chartFocus === true`: hide `<WatchlistPanel>` and the scanner `<aside>` using `display: none`
4. Show a subtle "F — exit focus" hint in the chart area when focus mode is active

**Step 1: Read App.jsx lines 260–290** (the keyboard handler and layout start)

**Step 2: Add state** — in App.jsx near the other `useState` calls (around line 50–100):
```jsx
const [chartFocus, setChartFocus] = useState(false)
```

**Step 3: Update the keyboard handler** — find the existing `useEffect` for the `?` key (around line 269):
```jsx
useEffect(() => {
  const handler = (e) => {
    if (document.activeElement.tagName === 'INPUT') return
    if (e.key === '?') setShowGuide((v) => !v)
    if (e.key === 'f' || e.key === 'F') setChartFocus((v) => !v)
  }
  window.addEventListener('keydown', handler)
  return () => window.removeEventListener('keydown', handler)
}, [])
```

**Step 4: Update layout** — in the scanner body section (around line 381–508), add `display: none` conditionally:

For `<WatchlistPanel>`:
```jsx
<WatchlistPanel
  items={watchlistItems}
  selectedTicker={selectedTicker}
  onSelectTicker={handleTickerClick}
  loading={loadingSetups}
  style={chartFocus ? { display: 'none' } : undefined}
/>
```

Wait — WatchlistPanel doesn't accept a `style` prop. Instead, wrap it:
```jsx
{!chartFocus && (
  <WatchlistPanel
    items={watchlistItems}
    selectedTicker={selectedTicker}
    onSelectTicker={handleTickerClick}
    loading={loadingSetups}
  />
)}
```

For the `<aside>` scanner panel:
```jsx
<aside
  className="flex flex-col overflow-y-auto flex-shrink-0"
  style={{
    width: 400,
    borderRight: '1px solid var(--border)',
    background: 'var(--panel)',
    display: chartFocus ? 'none' : undefined,
  }}
>
```

**Step 5: Add focus hint overlay** — inside the `<main>` chart panel, add a small hint when focus mode is active. Add this right before `<TradingChart .../>`:
```jsx
{chartFocus && (
  <div style={{
    position: 'absolute',
    top: 8,
    right: 12,
    zIndex: 10,
    fontSize: 8,
    color: 'rgba(245,166,35,0.5)',
    fontFamily: '"IBM Plex Mono", monospace',
    letterSpacing: '0.08em',
    pointerEvents: 'none',
  }}>
    F — EXIT FOCUS
  </div>
)}
```

The `<main>` needs `position: relative` for this to work:
```jsx
<main className="flex-1 min-w-0 overflow-hidden" style={{ background: 'var(--bg)', position: 'relative' }}>
```

**Step 6: Verify**

Run: `cd frontend && npm run build 2>&1 | tail -20`
Expected: no errors

**Step 7: Commit**
```bash
git add frontend/src/App.jsx
git commit -m "feat(ui): add chart focus mode (F key) — collapses scanner panels"
```

---

## Task 3: Watchlist RS Display + Status Labels

**Files:**
- Modify: `frontend/src/components/WatchlistPanel.jsx`

**What to do:**
1. In `WatchRow`, show RS score as a compact label: `rs_score * 100` rounded, prefixed by `RS` with + or − sign
   - e.g. `+15` → `RS+15`, `−5` → `RS−5`, value `0.00` → `RS±0`
   - Color: positive = `var(--go)`, negative = `var(--muted)`, near-zero (|val| < 5) = `var(--muted)`
2. Add a status label to the right side:
   - `LEAD` (cyan) if `rs_blue_dot === true`
   - `NEAR` (amber) if `distance_pct < 1.0` AND not a confirmed break
   - These replace/supplement the existing badge area

**Step 1: Read WatchlistPanel.jsx** (182 lines)

**Step 2: Update WatchRow** — replace the return JSX of `WatchRow`:

```jsx
const WatchRow = ({ item }) => {
  const isSelected = selectedTicker === item.ticker
  const isTdl = item.pattern_type === 'TDL'
  const isKdeBrk = item.pattern_type === 'KDE-BRK'
  const isTdlBrk = item.pattern_type === 'TDL-BRK'
  const isConfirmedBrk = isKdeBrk || isTdlBrk
  const hasRsBlueDot = !!item.rs_blue_dot

  // RS display
  const rsRaw = item.rs_score ?? 0
  const rsInt = Math.round(rsRaw * 100)
  const rsLabel = `RS${rsInt >= 0 ? '+' : ''}${rsInt}`
  const rsColor = rsInt >= 5 ? 'var(--go)'
    : rsInt <= -5 ? 'var(--muted)'
    : 'var(--muted)'

  // Status label
  const statusLabel = hasRsBlueDot ? 'LEAD'
    : (!isConfirmedBrk && (item.distance_pct ?? 99) < 1.0) ? 'NEAR'
    : null
  const statusColor = hasRsBlueDot
    ? { color: '#00C8FF', border: '1px solid rgba(0,200,255,0.3)', background: 'rgba(0,200,255,0.08)' }
    : { color: 'var(--accent)', border: '1px solid rgba(245,166,35,0.3)', background: 'rgba(245,166,35,0.08)' }

  const badgeStyle = isConfirmedBrk
    ? { background: 'rgba(0,200,122,0.18)', color: 'var(--go)', border: '1px solid rgba(0,200,122,0.4)', fontWeight: 700 }
    : isTdl
    ? { background: 'rgba(255,255,255,0.08)', color: '#FFF', border: '1px solid rgba(255,255,255,0.25)' }
    : { background: 'rgba(0,200,255,0.10)', color: '#00C8FF', border: '1px solid rgba(0,200,255,0.3)' }

  const distLabel = isConfirmedBrk
    ? `▲${item.distance_pct?.toFixed(1)}%`
    : `${item.distance_pct?.toFixed(1)}%`

  const distColor = isConfirmedBrk
    ? 'var(--go)'
    : (item.distance_pct ?? 99) < 0.8 ? 'var(--go)' : 'var(--accent)'

  return (
    <div
      onClick={() => onSelectTicker(item.ticker)}
      className="flex items-center justify-between px-2 py-2 cursor-pointer"
      style={{
        borderLeft: isSelected ? '2px solid var(--accent)' : isConfirmedBrk ? '2px solid rgba(0,200,122,0.5)' : '2px solid transparent',
        background: isSelected ? 'rgba(245,166,35,0.06)' : isConfirmedBrk ? 'rgba(0,200,122,0.04)' : 'transparent',
        borderBottom: '1px solid var(--border)',
        transition: 'background 0.1s',
      }}
      onMouseEnter={e => e.currentTarget.style.background = 'rgba(255,255,255,0.03)'}
      onMouseLeave={e => e.currentTarget.style.background = isSelected ? 'rgba(245,166,35,0.06)' : isConfirmedBrk ? 'rgba(0,200,122,0.04)' : 'transparent'}
    >
      {/* Left: ticker + RS */}
      <div className="flex flex-col gap-0">
        <div className="flex items-center gap-1">
          <span className="font-600 text-[10px] tracking-wide"
                style={{ color: isSelected ? 'var(--accent)' : isConfirmedBrk ? 'var(--go)' : 'var(--text)' }}>
            {item.ticker}
          </span>
          <a
            href={`https://www.tradingview.com/chart/?symbol=${item.ticker}&interval=D`}
            target="_blank"
            rel="noopener noreferrer"
            onClick={e => e.stopPropagation()}
            title="Open in TradingView"
            style={{
              fontSize: 7, padding: '1px 3px',
              border: '1px solid rgba(245,166,35,0.3)', color: 'rgba(245,166,35,0.55)',
              borderRadius: 2, fontFamily: '"IBM Plex Mono", monospace',
              fontWeight: 700, letterSpacing: '0.05em',
              textDecoration: 'none', userSelect: 'none', flexShrink: 0,
            }}
          >
            TV
          </a>
        </div>
        <span className="font-mono tabular-nums" style={{ fontSize: 7, color: rsColor }}>
          {rsLabel}
        </span>
      </div>

      {/* Right: status label + distance + type badge */}
      <div className="flex items-center gap-1">
        {statusLabel && (
          <span className="badge text-[7px]" style={{ ...statusColor, fontWeight: 700 }}>
            {statusLabel}
          </span>
        )}
        <span className="font-mono text-[9px] tabular-nums" style={{ color: distColor }}>
          {distLabel}
        </span>
        <span className="badge text-[7px]" style={badgeStyle}>
          {item.pattern_type}
        </span>
      </div>
    </div>
  )
}
```

**Step 3: Verify**

Run: `cd frontend && npm run build 2>&1 | tail -20`
Expected: no errors

**Step 4: Commit**
```bash
git add frontend/src/components/WatchlistPanel.jsx
git commit -m "feat(ui): enhance watchlist with RS score label and status badges"
```

---

## Task 4: Panel Contrast + CSS Polish

**Files:**
- Modify: `frontend/src/index.css`
- Modify: `frontend/src/App.jsx` (scanner aside background)

**What to do:**
1. **Scanner aside** (`App.jsx`): change background from `var(--panel)` to `var(--surface)` — slightly lighter, creates visual separation from chart
2. **WatchlistPanel**: already uses `var(--panel)` — keep as-is (it's the darkest panel)
3. **Borders**: increase contrast of the border between panels — change to `var(--border-light)` for main dividers
4. **Add CSS rule** for near-entry row glow animation (subtle pulse for rows with the glow)
5. **Active setup** CSS class: add `.row-near-entry` to index.css with a left-border pulse

**Step 1: Update index.css** — add after the `.terminal-table tr.selected` block (after line 109):
```css
/* ── Near-entry row glow ─────────────────────────────── */
.row-near-entry td {
  background: rgba(245, 166, 35, 0.035) !important;
}
.row-near-entry td:first-child {
  border-left: 3px solid rgba(245, 166, 35, 0.65) !important;
  padding-left: 5px;
}
```

**Step 2: Update App.jsx aside** — find:
```jsx
style={{
  width: 400,
  borderRight: '1px solid var(--border)',
  background: 'var(--panel)',
}}
```
Change to:
```jsx
style={{
  width: 400,
  borderRight: '2px solid var(--border-light)',
  background: 'var(--surface)',
}}
```

**Step 3: Update WatchlistPanel border** — find in `WatchlistPanel.jsx`:
```jsx
<div className="flex flex-col flex-shrink-0 overflow-y-auto border-r border-t-border"
```
Change `border-t-border` to use a slightly stronger border. In the `style` prop of this outer div (line 120):
```jsx
style={{ width: 190, background: 'var(--panel)', borderRight: '2px solid var(--border-light)' }}
```
Remove the Tailwind `border-r border-t-border` classes from the `className`.

**Step 4: Apply `.row-near-entry` class in SetupTable** — in Task 1 we added inline styles for `isNearEntry`. Additionally add `className` to the `<tr>`:
```jsx
<tr
  className={`${isSelected ? 'selected' : ''} ${isNearEntry ? 'row-near-entry' : ''}`}
  style={rowStyle}
  onClick={() => onSelectTicker(s.ticker)}
>
```
(This works in conjunction with the inline `rowStyle` — the CSS class gives the background, the inline style handles the border-left which CSS class also sets, but inline wins. Keep both for correctness — update `rowStyle` to only set the vol-surge case since `row-near-entry` handles the near-entry case via CSS.)

Updated `rowStyle`:
```jsx
const rowStyle = isVolSurge
  ? { background: 'rgba(0, 200, 122, 0.06)', borderLeft: '2px solid rgba(0,200,122,0.45)' }
  : {}
```
(The `isNearEntry` glow now comes from the CSS class `.row-near-entry`.)

**Step 5: Verify**

Run: `cd frontend && npm run build 2>&1 | tail -20`
Expected: no errors

**Step 6: Visual check** — open http://localhost:5174 and verify:
- Scanner panel (aside) is slightly lighter than chart area
- Borders between panels are more visible
- Near-entry rows show amber left border when live price is within 3% of entry

**Step 7: Commit**
```bash
git add frontend/src/index.css frontend/src/App.jsx frontend/src/components/SetupTable.jsx frontend/src/components/WatchlistPanel.jsx
git commit -m "feat(ui): improve panel contrast, border separation, and near-entry glow CSS"
```

---

## Final Verification

---

## Task 5: Full-Fidelity Regime Banner

**Files:**
- Modify: `backend/database.py` (add columns + update save/get)
- Modify: `frontend/src/components/Header.jsx`

### Background

**Engine 0** (`backend/engines/engine0.py`) computes a 7-factor regime score (0–100) and classifies it as:
- `AGGRESSIVE` (score ≥ 70) — all engines active
- `SELECTIVE` (score 54–69) — all engines active (`is_bullish = True`)
- `DEFENSIVE` (score < 54) — Engines 2 (VCP) + 3 (Pullback) disabled (`is_bullish = False`)

The thresholds are `REGIME_AGGRESSIVE_THRESHOLD = 70` and `REGIME_SELECTIVE_THRESHOLD = 54` (updated by Optuna v3).

**Current DB problem:** `market_regime` table only stores `spy_close`, `spy_20ema`, `is_bullish`, `regime` — missing `regime_score`, `spy_sma50`, `vix`, `breadth_pct`, `hl_ratio`, `factors_json`.

**Current header problem:** Header shows only `MARKET GO` or `MARKET HALT` based on `is_bullish`. SELECTIVE and AGGRESSIVE look identical (both "GO"). Traders can't see the actual score or which engines are active.

**Engine 0 return shape** (all fields available after a scan):
```python
{
    "is_bullish":   bool,
    "regime_score": int,        # 0–100
    "regime":       str,        # "AGGRESSIVE" | "SELECTIVE" | "DEFENSIVE"
    "spy_close":    float,
    "spy_20ema":    float,
    "spy_sma50":    float,
    "spy_sma200":   float,
    "vix":          float,
    "vix_sma20":    float,
    "breadth_pct":  float,      # 0.0–1.0
    "hl_ratio":     float,      # 0.0–1.0
    "factors": {
        "f1_ema20":    int,     # 20 or 0
        "f2_sma50":    int,     # 15 or 0
        "f3_ma_stack": int,     # 15 or 0
        "f4_slope":    int,     # 0–10
        "f5_breadth":  int,     # 0–20
        "f6_hl_ratio": int,     # 0–10
        "f7_vix":      int,     # 10 or 0
    },
}
```

**Engine status logic:**
- Engine 2 (VCP) + Engine 3 (Pullback) = active only when `is_bullish = True`
- All other engines (1 Watchlist, 5 Base, 6 ResBreakout, 7 Options, 8 HTF, 9 LCE) = always active

### Part A — Backend: Add columns to market_regime table

**Step 1: Read database.py** lines 28–37 (table schema) and lines 229–247 (save_regime) and lines 327–347 (get_latest_regime).

**Step 2: Add migration in `init_db()`**

Find the `init_db` function. After the existing `CREATE TABLE IF NOT EXISTS` calls, add a migration block that adds the new columns if they don't exist. In SQLite, `ALTER TABLE ADD COLUMN` fails silently when used in a try/except if the column already exists:

```python
# In init_db(), after existing table creation:
_REGIME_MIGRATIONS = [
    "ALTER TABLE market_regime ADD COLUMN regime_score INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE market_regime ADD COLUMN spy_sma50    REAL    NOT NULL DEFAULT 0.0",
    "ALTER TABLE market_regime ADD COLUMN vix          REAL    NOT NULL DEFAULT 0.0",
    "ALTER TABLE market_regime ADD COLUMN breadth_pct  REAL    NOT NULL DEFAULT 0.5",
    "ALTER TABLE market_regime ADD COLUMN hl_ratio     REAL    NOT NULL DEFAULT 0.5",
    "ALTER TABLE market_regime ADD COLUMN factors_json TEXT    DEFAULT '{}'",
]
```

Find the existing `init_db` function (it uses `aiosqlite`), and add at the end:
```python
for migration in _REGIME_MIGRATIONS:
    try:
        await db.execute(migration)
    except Exception:
        pass  # column already exists
await db.commit()
```

**Step 3: Update `save_regime()`**

Replace the existing `save_regime` function:
```python
async def save_regime(db_path: str, scan_timestamp: str, regime: Dict) -> None:
    import json as _json
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """INSERT INTO market_regime
               (scan_timestamp, spy_close, spy_20ema, is_bullish, regime,
                regime_score, spy_sma50, vix, breadth_pct, hl_ratio, factors_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                scan_timestamp,
                regime["spy_close"],
                regime["spy_20ema"],
                1 if regime["is_bullish"] else 0,
                regime["regime"],
                regime.get("regime_score", 0),
                regime.get("spy_sma50", 0.0),
                regime.get("vix", 0.0),
                regime.get("breadth_pct", 0.5),
                regime.get("hl_ratio", 0.5),
                _json.dumps(regime.get("factors", {})),
            ),
        )
        await db.commit()
```

**Step 4: Update `get_latest_regime()`**

Replace the existing `get_latest_regime` function:
```python
async def get_latest_regime(db_path: str) -> Optional[Dict]:
    import json as _json
    scan_ts = await get_latest_scan_timestamp(db_path)
    if not scan_ts:
        return None

    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            """SELECT spy_close, spy_20ema, is_bullish, regime,
                      regime_score, spy_sma50, vix, breadth_pct, hl_ratio, factors_json
               FROM market_regime WHERE scan_timestamp = ? LIMIT 1""",
            (scan_ts,),
        ) as cur:
            row = await cur.fetchone()
            if row:
                factors = {}
                try:
                    factors = _json.loads(row[9]) if row[9] else {}
                except Exception:
                    pass
                return {
                    "spy_close":    row[0],
                    "spy_20ema":    row[1],
                    "is_bullish":   bool(row[2]),
                    "regime":       row[3],
                    "regime_score": row[4] or 0,
                    "spy_sma50":    row[5] or 0.0,
                    "vix":          row[6] or 0.0,
                    "breadth_pct":  row[7] if row[7] is not None else 0.5,
                    "hl_ratio":     row[8] if row[8] is not None else 0.5,
                    "factors":      factors,
                    "scan_timestamp": scan_ts,
                }
    return None
```

**Step 5: Verify backend tests still pass**
```bash
cd backend && python3 -m pytest tests/ -q 2>&1 | tail -10
```
Expected: all tests pass (no tests touch save_regime columns, so no failures expected).

**Step 6: Commit backend**
```bash
git add backend/database.py
git commit -m "feat(db): add regime_score, vix, breadth, sma50, factors to market_regime table"
```

---

### Part B — Frontend: Update Header.jsx

**Step 1: Read Header.jsx** (full file, 559 lines) to understand current structure.

**Step 2: Replace the regime status block**

The current regime block starts at line 46 with:
```jsx
{/* REGIME STATUS — left block */}
<div className={`flex items-center gap-4 px-5 border-r border-t-border ${bgClass}`} style={{ minWidth: 340 }}>
```

**A. Update the 3-state color logic** — replace lines 11–27 (current 2-state logic):

```jsx
export default function Header({ regime, scanStatus, onRunScan, onSearchTicker, onOpenGuide, devMode, dryRun, onToggleDev, onToggleDryRun }) {
  const regimeType = regime?.regime  // "AGGRESSIVE" | "SELECTIVE" | "DEFENSIVE" | "NO_DATA" | undefined
  const isNoData   = !regime || regimeType === 'NO_DATA'
  const isError    = regimeType?.startsWith('ERROR')
  const isAggressive = regimeType === 'AGGRESSIVE'
  const isSelective  = regimeType === 'SELECTIVE'
  const isDefensive  = regimeType === 'DEFENSIVE' || (regime && !regime.is_bullish && !isNoData && !isError)

  // Stripe + background + text colors for 3 states
  let stripeClass = 'bg-t-muted'
  let bgClass     = 'bg-t-surface'
  let textClass   = 'text-t-muted'
  if (isAggressive) { stripeClass = 'bg-t-go';     bgClass = 'bg-t-goDim';     textClass = 'text-t-go'    }
  if (isSelective)  { stripeClass = 'bg-t-accent';  bgClass = 'bg-t-accentDim'; textClass = 'text-t-accent' }
  if (isDefensive)  { stripeClass = 'bg-t-halt';    bgClass = 'bg-t-haltDim';   textClass = 'text-t-halt'   }

  // Human-readable label
  const regimeLabel = isAggressive ? 'BULL'
    : isSelective ? 'NEUTRAL'
    : isDefensive ? 'HALT'
    : 'NO DATA'

  // Engine status: Engines 2+3 only active when is_bullish
  const isBullish = regime?.is_bullish
  const engines = [
    { id: 2, label: 'VCP',  active: !!isBullish },
    { id: 3, label: 'PB',   active: !!isBullish },
    { id: 5, label: 'BASE', active: true },
    { id: 6, label: 'BRK',  active: true },
  ]

  const fmtTime = (iso) => {
    if (!iso) return '—'
    const d = new Date(iso + 'Z')
    return d.toLocaleTimeString('en-US', { hour12: false })
  }
```

**B. Replace the regime status block JSX** (the `{/* REGIME STATUS — left block */}` div):

```jsx
{/* REGIME STATUS — left block */}
<div
  className={`flex flex-col justify-center px-4 border-r border-t-border ${bgClass}`}
  style={{ minWidth: 380, gap: 2 }}
>
  {isNoData ? (
    <span className="font-condensed text-[22px] font-700 tracking-tight text-t-muted">NO DATA</span>
  ) : isError ? (
    <span className="font-condensed text-[14px] font-600 text-t-muted truncate max-w-[340px]">{regimeType}</span>
  ) : (
    <>
      {/* Row 1: Regime label + score */}
      <div className="flex items-center gap-3">
        <span className={`font-condensed text-[10px] font-700 tracking-widest uppercase text-t-muted opacity-60`}>
          REGIME
        </span>
        <span
          className={`font-condensed text-[22px] font-700 tracking-tight leading-none ${textClass} ${isDefensive ? 'animate-pulse_halt' : ''}`}
          style={isAggressive ? { textShadow: '0 0 12px rgba(0,200,122,0.4)' } : isDefensive ? { textShadow: '0 0 12px rgba(255,45,85,0.4)' } : {}}
        >
          {regimeLabel}
        </span>
        {regime.regime_score != null && (
          <span
            className="font-mono tabular-nums"
            style={{
              fontSize: 10,
              padding: '1px 6px',
              background: 'rgba(255,255,255,0.05)',
              border: '1px solid var(--border-light)',
              color: isAggressive ? 'var(--go)' : isSelective ? 'var(--accent)' : 'var(--halt)',
              borderRadius: 2,
              letterSpacing: '0.04em',
            }}
          >
            {regime.regime_score}/100
          </span>
        )}
        {isDefensive && devMode && (
          <span className="text-[9px] font-600 tracking-widest text-t-accent uppercase animate-pulse">
            ⚠ FORCE-ON
          </span>
        )}
      </div>

      {/* Row 2: SPY metrics + VIX + Breadth */}
      <div className="flex items-center gap-3">
        <span className="font-mono tabular-nums text-[10px]" style={{ color: textClass ? 'inherit' : 'var(--text)' }}>
          <span className="text-t-muted text-[8px] mr-1">SPY</span>
          <span className={textClass}>${regime.spy_close?.toFixed(2)}</span>
        </span>
        {regime.spy_sma50 > 0 && (
          <span className="font-mono text-[9px] tabular-nums">
            <span className="text-t-muted text-[8px] mr-0.5">SMA50</span>
            <span style={{ color: regime.spy_close > regime.spy_sma50 ? 'var(--go)' : 'var(--halt)' }}>
              {regime.spy_close > regime.spy_sma50 ? '✔' : '✖'}
            </span>
          </span>
        )}
        {regime.vix > 0 && (
          <span className="font-mono text-[9px] tabular-nums">
            <span className="text-t-muted text-[8px] mr-0.5">VIX</span>
            <span style={{ color: regime.vix < (regime.vix_sma20 || 999) ? 'var(--go)' : 'var(--muted)' }}>
              {regime.vix.toFixed(1)}
            </span>
          </span>
        )}
        {regime.breadth_pct != null && (
          <span className="font-mono text-[9px] tabular-nums">
            <span className="text-t-muted text-[8px] mr-0.5">BRD</span>
            <span style={{ color: regime.breadth_pct > 0.6 ? 'var(--go)' : regime.breadth_pct > 0.4 ? 'var(--accent)' : 'var(--halt)' }}>
              {Math.round(regime.breadth_pct * 100)}%
            </span>
          </span>
        )}
      </div>

      {/* Row 3: Engine status */}
      <div className="flex items-center gap-2">
        <span className="text-[8px] tracking-widest uppercase text-t-muted">ENG</span>
        {engines.map(({ id, label, active }) => (
          <span
            key={id}
            className="font-mono text-[8px]"
            style={{ color: active ? 'var(--go)' : 'rgba(255,45,85,0.6)' }}
            title={`Engine ${id}: ${active ? 'active' : 'disabled (DEFENSIVE regime)'}`}
          >
            {label}{active ? '✔' : '✖'}
          </span>
        ))}
      </div>
    </>
  )}
</div>
```

**Step 3: Verify no TypeScript/lint errors**
```bash
cd frontend && npm run build 2>&1 | tail -20
```
Expected: no errors

**Step 4: Commit**
```bash
git add frontend/src/components/Header.jsx
git commit -m "feat(ui): replace regime banner with 3-level display (BULL/NEUTRAL/HALT), score, VIX, breadth, engine status"
```

---

## Final Verification

After all 5 tasks are committed, run a full build:

```bash
cd frontend && npm run build
```

Expected: exit code 0, no errors.

Visual checklist:
- [ ] Score column visible in all setup tables (green/amber/muted based on value)
- [ ] Live price cell shows distance below price (e.g. `1.8%↓`)
- [ ] Rows within 3% of entry have amber left-border glow
- [ ] Age shows as subtext under ticker name (`2d ago`)
- [ ] Pressing F hides scanner panels and shows chart full-width
- [ ] Pressing F again restores panels
- [ ] "F — EXIT FOCUS" hint visible in chart overlay during focus mode
- [ ] Watchlist shows RS score (e.g. `RS+12`) under each ticker
- [ ] Watchlist shows `LEAD` or `NEAR` status badges where applicable
- [ ] Scanner aside has lighter background than chart area
- [ ] Panel borders are clearly visible
- [ ] Regime banner shows BULL (green) / NEUTRAL (amber) / HALT (red)
- [ ] Regime score visible (e.g. `78/100`)
- [ ] SPY, SMA50 status, VIX, Breadth% shown in banner
- [ ] Engine status row shows VCP✔/✖, PB✔/✖, BASE✔, BRK✔
- [ ] After running a new scan: all regime fields update from DB correctly
