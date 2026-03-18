# Watchlist Redesign — Pre-Trigger Setups Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the VCP near-breakout watchlist with stocks approaching a RES_BREAKOUT or PULLBACK trigger — one move away from a live scanner setup.

**Architecture:** Add two new scanner functions (`scan_res_breakout_near` in engine6, `scan_pullback_approaching` in engine3), wire them into the main.py scan pipeline replacing the old `scan_near_breakout` call, and update WatchlistPanel.jsx to display the new `watchlist_source` field instead of VCP-specific `pattern_type`.

**Tech Stack:** Python/FastAPI backend, React 18 frontend, SQLite via `setup_type="WATCHLIST"` (no schema change)

---

## Chunk 1: Backend — New Scanner Functions

### Task 1: `scan_res_breakout_near()` in engine6.py

**Files:**
- Modify: `swing-trading-dashboard/backend/engines/engine6.py`

Logic: same as `scan_resistance_breakout()` but instead of requiring a cross (pre_close ≤ resistance < brk_close), require close to be within 5% **below** resistance — approaching but not yet broken. Consolidation filter still applies. Volume should be contracting (below SMA50 avg) as a quality signal but not a hard gate.

- [ ] **Step 1: Add `scan_res_breakout_near()` to engine6.py**

Add after the existing `scan_resistance_breakout()` function:

```python
def scan_res_breakout_near(
    ticker: str,
    df: pd.DataFrame,
    zones: list,
    debug: bool = False,
    params=None,
) -> dict | None:
    """
    Watchlist: stock approaching a resistance breakout but not yet triggered.

    Conditions:
      - Trend: close > SMA50
      - Resistance identified (Donchian / pivot / KDE)
      - Close within NEAR_PCT below resistance (approaching zone)
      - Close has NOT crossed resistance yet
      - Consolidation: >= _min_consol bars within _CONSOL_TOLERANCE of resistance
      - Volume: contracting preferred (no hard gate)

    Returns a WATCHLIST setup dict or None.
    """
    NEAR_PCT = 0.05   # within 5% below resistance

    try:
        _vol_thresh  = getattr(params, "brk_vol_mult",          RES_BREAKOUT_VOL_MULT)
        _stop_atr    = getattr(params, "brk_stop_atr",          RES_STOP_ATR_FACTOR)
        _donchian_n  = int(getattr(params, "brk_donchian_n",    _DONCHIAN_N_DEFAULT))
        _pivot_str   = int(getattr(params, "brk_pivot_strength",_PIVOT_STRENGTH_DEFAULT))
        _min_consol  = int(getattr(params, "brk_min_consolidation", _MIN_CONSOL_DEFAULT))

        data = _prep(df)
        if data is None or len(data) < max(60, _donchian_n + 10):
            return None

        adj      = _adj_col(data)
        close_s  = data[adj]
        high_s   = data["High"]
        low_s    = data["Low"]
        volume_s = data["Volume"]

        if close_s.dropna().shape[0] < 55:
            return None

        # Trend filter
        sma50  = data["_SMA50"] if "_SMA50" in data.columns else close_s.rolling(50).mean()
        lc_val = close_s.iloc[-1]
        lc     = float(lc_val.item() if hasattr(lc_val, "item") else lc_val)
        l50_val = sma50.iloc[-1]
        l50    = float(l50_val.item() if hasattr(l50_val, "item") else l50_val) if pd.notna(l50_val) else 0.0
        if l50 > 0 and lc < l50:
            return None

        vol_sma50_s = data["_VOLSMA50"] if "_VOLSMA50" in data.columns else volume_s.rolling(50).mean()
        vsm50_val   = vol_sma50_s.iloc[-1]
        vol_sma50   = float(vsm50_val.item() if hasattr(vsm50_val, "item") else vsm50_val)
        if np.isnan(vol_sma50) or vol_sma50 <= 0:
            return None

        atr14    = data["_ATR14"] if "_ATR14" in data.columns else _atr(high_s, low_s, close_s, 14)
        latr_val = atr14.iloc[-1]
        latr     = float(latr_val.item() if hasattr(latr_val, "item") else latr_val)
        if np.isnan(latr) or latr <= 0:
            return None

        close_arr  = close_s.values.astype(float)
        high_arr   = high_s.values.astype(float)
        volume_arr = volume_s.values.astype(float)
        n          = len(close_arr)

        donchian_res = (
            pd.Series(high_arr)
            .rolling(_donchian_n)
            .max()
            .shift(1)
            .values
        )
        pivot_levels = _find_pivot_highs(high_arr[: n - 1], _pivot_str)

        brk_idx = n - 1
        if brk_idx < _donchian_n:
            return None

        candidates = _resistance_candidates(
            high_arr, lc,
            brk_idx, donchian_res,
            pivot_levels, zones,
        )
        if not candidates:
            return None

        for resistance, source in candidates:
            # Must be above current close
            if resistance <= lc:
                continue

            # Must NOT have crossed (close is still below resistance)
            if lc >= resistance:
                continue

            # Proximity: close within NEAR_PCT below resistance
            distance_pct = (resistance - lc) / resistance
            if distance_pct > NEAR_PCT:
                continue

            # Consolidation: >= _min_consol bars within _CONSOL_TOLERANCE of resistance
            if _min_consol > 0:
                consol_start = max(0, brk_idx - _min_consol - 10)
                consol_closes = close_arr[consol_start:brk_idx]
                near_res = consol_closes >= resistance * (1.0 - _CONSOL_TOLERANCE)
                if not np.any(near_res):
                    continue

            # Volume ratio (soft signal only)
            last_vol = volume_arr[brk_idx]
            vol_ratio = last_vol / vol_sma50 if vol_sma50 > 0 else 1.0

            entry     = round(resistance * 1.001, 2)
            stop_loss = round(resistance - _stop_atr * latr, 2)
            risk      = entry - stop_loss
            if risk <= 0 or risk > entry * 0.15:
                continue

            from zone_utils import nearest_resistance_target
            take_profit, actual_rr = nearest_resistance_target(entry, zones, risk)

            return {
                "ticker":           ticker,
                "setup_type":       "WATCHLIST",
                "watchlist_source": "RES_BREAKOUT",
                "entry":            entry,
                "stop_loss":        stop_loss,
                "take_profit":      take_profit,
                "rr":               actual_rr,
                "resistance_level": round(resistance, 2),
                "distance_pct":     round(distance_pct * 100, 2),
                "volume_ratio":     round(vol_ratio, 2),
                "zone_source":      source,
                "setup_date":       str(data.index[-1].date()),
            }

        return None

    except Exception as exc:
        print(f"[Engine6 near] {ticker}: {exc}")
        return None
```

- [ ] **Step 2: Quick sanity check — import works**

```bash
cd swing-trading-dashboard/backend
python -c "from engines.engine6 import scan_res_breakout_near; print('OK')"
```
Expected: `OK`

---

### Task 2: `scan_pullback_approaching()` in engine3.py

**Files:**
- Modify: `swing-trading-dashboard/backend/engines/engine3.py`

Logic: trend confirmed (EMA8 > EMA20, close > SMA50×0.97) + CCI declining (pullback in progress) + price within 2 ATR of a structural support found by the existing `_find_structural_support()`. Pin bar and CCI hook NOT required.

- [ ] **Step 1: Add `scan_pullback_approaching()` to engine3.py**

Add after `scan_relaxed_pullback()`:

```python
def scan_pullback_approaching(
    ticker: str,
    df: pd.DataFrame,
    sr_zones: list,
    trendline: dict | None = None,
    rs_score: float = 0.0,
    debug: bool = False,
) -> dict | None:
    """
    Watchlist: stock in uptrend pulling back toward a structural support.
    Fires before the pin bar / CCI hook — one move away from a PULLBACK setup.

    Conditions:
      - Trend: EMA8 > EMA20, close > SMA50 × 0.97
      - CCI declining: cci_today < cci_prev  (pullback actively in progress)
      - RS not a persistent underperformer (same gate as engine 3)
      - Structural support exists within 2 ATR of current low
        (KDE zone / consolidation low / demand zone / ascending TDL)
      - Pin bar and CCI hook NOT required
    """
    APPROACH_ATR = 2.0   # within 2 ATR of structural support

    try:
        ind = _prepare_indicators(ticker, df)
        if ind is None:
            return None

        data = ind.data
        lc, lh, ll   = ind.lc, ind.lh, ind.ll
        l8, l20, l50 = ind.l8, ind.l20, ind.l50
        latr         = ind.latr
        cci_today    = ind.cci_today
        cci_prev     = ind.cci_prev

        # RS gate (same as engine 3)
        if rs_score < RS_REJECT_THRESHOLD:
            return None

        # Trend (relaxed — same as scan_relaxed_pullback)
        if not (l8 > l20 and lc > l50 * 0.97):
            return None

        # CCI must be declining — pullback is actively in progress
        if cci_today >= cci_prev:
            return None

        # Structural support check
        vol_sma50   = ind.volume.rolling(50).mean()
        vsm_val     = vol_sma50.iloc[-1]
        avg_vol_sup = float(vsm_val.item() if hasattr(vsm_val, "item") else vsm_val)

        nearest_sup = _find_structural_support(
            ll, lc, sr_zones, trendline,
            ind.high, ind.low, ind.close, ind.volume, avg_vol_sup, latr,
        )
        if nearest_sup is None:
            return None

        # Price must be approaching (within APPROACH_ATR of support level)
        support_level = nearest_sup["level"]
        if latr > 0 and (lc - support_level) > APPROACH_ATR * latr:
            return None

        # Support must be below current price
        if support_level >= lc:
            return None

        entry     = round(lh * 1.001, 2)
        stop_base = min(ll, nearest_sup["lower"])
        stop_loss = round(stop_base - ATR_STOP_MULTIPLIER * latr, 2)
        risk      = entry - stop_loss
        if risk <= 0 or risk > entry * 0.15:
            return None

        from zone_utils import nearest_resistance_target
        take_profit, actual_rr = nearest_resistance_target(entry, sr_zones, risk)

        return {
            "ticker":           ticker,
            "setup_type":       "WATCHLIST",
            "watchlist_source": "PULLBACK",
            "entry":            entry,
            "stop_loss":        stop_loss,
            "take_profit":      take_profit,
            "rr":               actual_rr,
            "support_level":    support_level,
            "support_source":   nearest_sup["source"],
            "distance_pct":     round((lc - support_level) / lc * 100, 2),
            "ema8":             round(l8, 2),
            "ema20":            round(l20, 2),
            "cci_today":        round(cci_today, 2),
            "setup_date":       str(data.index[-1].date()),
        }

    except Exception as exc:
        print(f"[Engine3 approaching] {ticker}: {exc}")
        return None
```

- [ ] **Step 2: Quick sanity check — import works**

```bash
cd swing-trading-dashboard/backend
python -c "from engines.engine3 import scan_pullback_approaching; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add swing-trading-dashboard/backend/engines/engine6.py \
        swing-trading-dashboard/backend/engines/engine3.py
git commit -m "feat(watchlist): add scan_res_breakout_near and scan_pullback_approaching"
```

---

## Chunk 2: Backend — Wire into main.py

### Task 3: Replace VCP watchlist with new feeds in main.py

**Files:**
- Modify: `swing-trading-dashboard/backend/main.py`

Three changes:
1. Update imports to include new functions
2. Replace the `scan_near_breakout` call in `_process()` with calls to both new functions
3. Update `engine_stats` counters

- [ ] **Step 1: Update imports at top of main.py**

Find:
```python
from engines.engine2 import scan_vcp, detect_trendline, scan_near_breakout
from engines.engine3 import scan_pullback, scan_relaxed_pullback, scan_pullback_scored
```

Replace with:
```python
from engines.engine2 import scan_vcp, detect_trendline
from engines.engine3 import scan_pullback, scan_relaxed_pullback, scan_pullback_scored, scan_pullback_approaching
from engines.engine6 import scan_resistance_breakout, scan_res_breakout_near
```

- [ ] **Step 2: Update `_scan_state` engine_stats init**

Find both occurrences of:
```python
"e2": {"vcp": 0, "watchlist": 0},
```
Replace with:
```python
"e2": {"vcp": 0},
"watchlist": {"res_breakout_near": 0, "pullback_approaching": 0},
```

- [ ] **Step 3: Replace `scan_near_breakout` block in `_process()`**

Find and remove this entire block:
```python
                if not vcp:
                    try:
                        near = await loop.run_in_executor(
                            None, scan_near_breakout, ticker, df, zones, tl
                        )
                        if near:
                            # Sanitize near-breakout output: ensure numeric fields are proper floats
                            try:
                                near["entry"] = float(near.get("entry", 0.0))
                                near["distance_pct"] = float(near.get("distance_pct", 0.0))
                            except (ValueError, TypeError) as conv_err:
                                log.warning("Near-breakout conversion failed for %s: %s", ticker, conv_err)
                                return

                            near["sector"] = SECTORS.get(ticker, "Unknown")
                            near["rs_blue_dot"] = rs_blue_dot
                            collected_setups.append(near)
                            _scan_state["engine_stats"]["e2"]["watchlist"] += 1
                            log.info("  NEAR     %-6s  dist=%.1f%%", ticker, near["distance_pct"])
                    except Exception as near_exc:
                        log.warning("Near-breakout check failed for %s: %s", ticker, near_exc)
```

Replace with:
```python
                # ── Watchlist: RES_BREAKOUT approaching ──────────────────────────
                try:
                    wl_res = await loop.run_in_executor(
                        None, scan_res_breakout_near, ticker, df, zones
                    )
                    if wl_res:
                        wl_res["sector"] = SECTORS.get(ticker, "Unknown")
                        wl_res["rs_blue_dot"] = rs_blue_dot
                        collected_setups.append(wl_res)
                        _scan_state["engine_stats"]["watchlist"]["res_breakout_near"] += 1
                        log.info("  WL_BRK   %-6s  dist=%.1f%%", ticker, wl_res.get("distance_pct", 0))
                except Exception as wl_exc:
                    log.warning("WL res_breakout_near failed for %s: %s", ticker, wl_exc)

                # ── Watchlist: PULLBACK approaching ───────────────────────────────
                try:
                    wl_pb = await loop.run_in_executor(
                        None, scan_pullback_approaching, ticker, df, zones, tl, rs_score
                    )
                    if wl_pb:
                        wl_pb["sector"] = SECTORS.get(ticker, "Unknown")
                        wl_pb["rs_blue_dot"] = rs_blue_dot
                        collected_setups.append(wl_pb)
                        _scan_state["engine_stats"]["watchlist"]["pullback_approaching"] += 1
                        log.info("  WL_PB    %-6s  sup=%.2f  src=%s", ticker, wl_pb.get("support_level", 0), wl_pb.get("support_source", ""))
                except Exception as wl_exc:
                    log.warning("WL pullback_approaching failed for %s: %s", ticker, wl_exc)
```

- [ ] **Step 4: Verify backend starts cleanly**

```bash
cd swing-trading-dashboard/backend
python -c "import main; print('OK')"
```
Expected: `OK` with no import errors

- [ ] **Step 5: Commit**

```bash
git add swing-trading-dashboard/backend/main.py
git commit -m "feat(watchlist): wire new pre-trigger watchlist feeds into scan pipeline"
```

---

## Chunk 3: Frontend — WatchlistPanel.jsx

### Task 4: Update WatchlistPanel to display new watchlist_source

**Files:**
- Modify: `swing-trading-dashboard/frontend/src/components/WatchlistPanel.jsx`

The current panel filters by `pattern_type` (VCP-specific: KDE, TDL, KDE-BRK, TDL-BRK). Replace that logic with `watchlist_source` (RES_BREAKOUT or PULLBACK). Two sections: "Near Breakout" and "Pullback Setup".

- [ ] **Step 1: Replace the entire WatchlistPanel.jsx**

```jsx
import { useState } from 'react'

export default function WatchlistPanel({ items, selectedTicker, onSelectTicker, loading }) {
  const [showAllBrk, setShowAllBrk] = useState(false)
  const [showAllPb,  setShowAllPb]  = useState(false)

  const brkItems = items
    .filter(item => item.watchlist_source === 'RES_BREAKOUT')
    .sort((a, b) => (a.distance_pct ?? 99) - (b.distance_pct ?? 99))

  const pbItems = items
    .filter(item => item.watchlist_source === 'PULLBACK')
    .sort((a, b) => (a.distance_pct ?? 99) - (b.distance_pct ?? 99))

  const visibleBrk = showAllBrk ? brkItems : brkItems.slice(0, 15)
  const visiblePb  = showAllPb  ? pbItems  : pbItems.slice(0, 15)

  const SectionHeader = ({ label, count }) => (
    <div style={{
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      padding: '6px 12px',
      borderBottom: '1px solid var(--border)',
      background: 'rgba(255,255,255,0.02)',
    }}>
      <span style={{
        fontSize: 9, letterSpacing: '0.12em', textTransform: 'uppercase',
        color: 'var(--muted)', fontFamily: '"IBM Plex Mono", monospace', fontWeight: 700,
      }}>
        {label}
      </span>
      <span style={{
        fontSize: 9, padding: '1px 6px', borderRadius: 4,
        background: 'rgba(245,166,35,0.08)', border: '1px solid rgba(245,166,35,0.2)',
        color: 'var(--muted)', fontFamily: '"IBM Plex Mono", monospace', fontWeight: 700,
      }}>
        {count}
      </span>
    </div>
  )

  const ShowMoreBtn = ({ allItems, visible, onToggle }) => {
    if (allItems.length <= 15) return null
    return (
      <button
        onClick={() => onToggle(v => !v)}
        style={{
          width: '100%', padding: '6px',
          background: 'transparent', border: 'none',
          borderTop: '1px solid var(--border)',
          color: 'var(--muted)', cursor: 'pointer',
          fontSize: 9, letterSpacing: '0.1em',
          textTransform: 'uppercase',
          fontFamily: '"IBM Plex Mono", monospace',
        }}
      >
        {visible ? `▲ Show top 15` : `▼ Show all ${allItems.length}`}
      </button>
    )
  }

  const WatchRow = ({ item }) => {
    const isSelected = selectedTicker === item.ticker
    const isBrk      = item.watchlist_source === 'RES_BREAKOUT'
    const hasBlueDot = !!item.rs_blue_dot

    // Distance label
    const dist      = item.distance_pct ?? 0
    const distLabel = isBrk ? `${dist.toFixed(1)}% away` : `${dist.toFixed(1)}% to sup`
    const distColor = dist < 1.5 ? 'var(--go)' : dist < 3 ? 'var(--accent)' : 'var(--muted)'

    // Source badge (e.g. KDE, CONSOLIDATION_LOW, donchian, pivot)
    const sourceLabel = isBrk
      ? (item.zone_source ?? 'BRK').toUpperCase().slice(0, 6)
      : (item.support_source ?? 'SUP').replace('_', ' ').slice(0, 6)

    const badgeBg    = isBrk ? 'rgba(0,200,122,0.10)' : 'rgba(100,180,255,0.10)'
    const badgeBord  = isBrk ? 'rgba(0,200,122,0.30)' : 'rgba(100,180,255,0.30)'
    const badgeColor = isBrk ? 'var(--go)' : '#64b4ff'

    return (
      <div
        onClick={() => onSelectTicker(item.ticker)}
        style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '8px 12px',
          borderBottom: '1px solid var(--border)',
          borderLeft: isSelected
            ? '3px solid var(--accent)'
            : isBrk
            ? '3px solid rgba(0,200,122,0.4)'
            : '3px solid rgba(100,180,255,0.4)',
          background: isSelected ? 'rgba(245,166,35,0.06)' : 'transparent',
          cursor: 'pointer',
          transition: 'background 0.1s',
          gap: 8,
        }}
        onMouseEnter={e => {
          if (!isSelected) e.currentTarget.style.background = 'rgba(255,255,255,0.04)'
        }}
        onMouseLeave={e => {
          e.currentTarget.style.background = isSelected ? 'rgba(245,166,35,0.06)' : 'transparent'
        }}
      >
        {/* Left: ticker + blue dot */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginBottom: 2 }}>
            <span style={{
              fontSize: 12, fontWeight: 700, letterSpacing: '0.03em',
              color: isSelected ? 'var(--accent)' : 'var(--text)',
              fontFamily: '"IBM Plex Mono", monospace',
            }}>
              {item.ticker}
            </span>
            {hasBlueDot && (
              <span style={{ color: 'var(--blue)', fontSize: 9 }}>●</span>
            )}
          </div>
          <span style={{
            fontSize: 9, color: distColor,
            fontFamily: '"IBM Plex Mono", monospace',
          }}>
            {distLabel}
          </span>
        </div>

        {/* Right: source badge + TV link */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 }}>
          <span style={{
            fontSize: 8, padding: '2px 5px', borderRadius: 4,
            fontFamily: '"IBM Plex Mono", monospace', fontWeight: 700,
            letterSpacing: '0.04em',
            background: badgeBg, color: badgeColor, border: `1px solid ${badgeBord}`,
          }}>
            {sourceLabel}
          </span>
          <a
            href={`https://www.tradingview.com/chart/?symbol=${item.ticker}&interval=D`}
            target="_blank"
            rel="noopener noreferrer"
            onClick={e => e.stopPropagation()}
            style={{
              fontSize: 8, padding: '2px 4px', borderRadius: 3,
              border: '1px solid rgba(245,166,35,0.25)',
              color: 'rgba(245,166,35,0.5)',
              fontFamily: '"IBM Plex Mono", monospace', fontWeight: 700,
              textDecoration: 'none',
            }}
          >
            TV
          </a>
        </div>
      </div>
    )
  }

  const totalCount = brkItems.length + pbItems.length

  return (
    <div style={{
      display: 'flex', flexDirection: 'column',
      height: '100%', overflow: 'hidden',
      background: 'var(--panel)',
    }}>

      {/* Header */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '10px 12px',
        borderBottom: '1px solid var(--border)',
        flexShrink: 0,
      }}>
        <span style={{
          fontSize: 10, fontWeight: 700, letterSpacing: '0.12em',
          textTransform: 'uppercase', color: 'var(--muted)',
          fontFamily: '"IBM Plex Mono", monospace',
        }}>
          Watchlist
        </span>
        <span style={{
          fontSize: 9, padding: '1px 7px', borderRadius: 4,
          background: 'rgba(245,166,35,0.08)', border: '1px solid rgba(245,166,35,0.2)',
          color: 'var(--accent)', fontFamily: '"IBM Plex Mono", monospace', fontWeight: 700,
        }}>
          {totalCount}
        </span>
      </div>

      {/* Body */}
      <div style={{ flex: 1, overflowY: 'auto' }}>
        {loading ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, padding: 12 }}>
            {[...Array(4)].map((_, i) => (
              <div key={i} style={{
                height: 48, borderRadius: 6,
                background: 'rgba(255,255,255,0.04)',
                opacity: 1 - i * 0.2,
              }} />
            ))}
          </div>
        ) : totalCount === 0 ? (
          <div style={{
            padding: '32px 16px', textAlign: 'center',
            color: 'var(--muted)', fontSize: 10,
            fontFamily: '"IBM Plex Mono", monospace',
            letterSpacing: '0.1em', textTransform: 'uppercase',
          }}>
            No items — run a scan
          </div>
        ) : (
          <>
            {brkItems.length > 0 && (
              <>
                <SectionHeader label="Near Breakout" count={brkItems.length} />
                {visibleBrk.map(item => <WatchRow key={item.ticker} item={item} />)}
                <ShowMoreBtn allItems={brkItems} visible={showAllBrk} onToggle={setShowAllBrk} />
              </>
            )}
            {pbItems.length > 0 && (
              <>
                <SectionHeader label="Pullback Setup" count={pbItems.length} />
                {visiblePb.map(item => <WatchRow key={item.ticker} item={item} />)}
                <ShowMoreBtn allItems={pbItems} visible={showAllPb} onToggle={setShowAllPb} />
              </>
            )}
          </>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Verify frontend builds**

```bash
cd swing-trading-dashboard/frontend
npm run build
```
Expected: build succeeds with no errors

- [ ] **Step 3: Commit**

```bash
git add swing-trading-dashboard/frontend/src/components/WatchlistPanel.jsx
git commit -m "feat(watchlist): rewrite WatchlistPanel for RES_BREAKOUT/PULLBACK sources"
```

---

## Chunk 4: Deploy

- [ ] **Step 1: Push and deploy**

```bash
git push
cd swing-trading-dashboard
bash deploy.sh 89.167.25.25
```
Expected: `✓ Frontend rebuilt` and `✓ Backend restarted`

- [ ] **Step 2: Run a scan and verify watchlist**

After deploy, trigger a scan from the UI. Once complete, open the Watchlist tab and confirm:
- Items appear with "Near Breakout" and/or "Pullback Setup" sections
- Each row shows a source badge (DONCHI, PIVOT, KDE, CONSOL, DEMAND, ASCEND)
- Distance label shows "X.X% away" (breakout) or "X.X% to sup" (pullback)
- No VCP-specific `pattern_type` references remain
