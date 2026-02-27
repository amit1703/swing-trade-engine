# Engine Improvements Design — 2026-02-26

## Problem Summary

Five issues reported after recent scans:

1. **VCP engine** — too few trades (RS filter too strict, TDL breakouts routed to wrong table)
2. **Tactical Pullback** — too many RLX signals (relaxed engine triggers too easily)
3. **Base Patterns** — barely finds any trades (3 compounding bottlenecks)
4. **Resistance Breakout** — finds nothing (Stage 2 filter + 150% volume too strict)
5. **Watchlist TDL-BREAK label** — trendline breakouts should appear in VCP table, not watchlist

---

## Design

### 1. Engine 2 (VCP) — Loosen RS filter + fix TDL routing

**File:** `backend/engines/engine2.py`

**Change A — Path B (BRK):**
- Current: `rs_vs_spy > 0` (stock must beat SPY over 3 months)
- New: `rs_vs_spy > -0.05` (stock can lag SPY by up to 5% and still qualify)

**Change B — Path C (TDL Breakout):**
- Lower volume gate: `lvol >= 1.2 * avg_vol` → `lvol >= 1.0 * avg_vol` (100%)
- Extend price range: `0 < pct_above_tl <= 0.02` → `0 < pct_above_tl <= 0.03`

**Change C — `scan_near_breakout`:**
- Remove the TDL-BRK detection block (lines ~364–376 that check for close 0.1–3% above descending trendline)
- TDL breakouts now fully handled by Path C in `scan_vcp`

---

### 2. Engine 3 (Pullback) — Tighten relaxed engine

**File:** `backend/engines/engine3.py`

**`scan_relaxed_pullback` changes:**
- Raise CCI floor: `cci_prev < 0` → `cci_prev < -30`
- Add mandatory KDE support zone touch (same logic as strict engine):
  - Low must penetrate EMA8 or EMA20 (already present)
  - `nearest_sup` must not be None (require a support zone match)
  - Re-use the same zone-checking loop from `scan_pullback`

---

### 3. Engine 5 (Base Patterns) — Loosen three bottlenecks

**File:** `backend/engines/engine5.py`

**Both `scan_cup_handle` and `scan_flat_base`:**
- Remove the rising 200 SMA check:
  ```python
  # REMOVE:
  if l200_prev > 0 and l200 <= l200_prev:
      return None
  ```
  Keep: `close > 200 SMA` still required.

**`scan_cup_handle` only:**
- Loosen right rim recovery: `> 0.10` → `> 0.15`
  ```python
  if (left_peak - right_rim) / left_peak > 0.15:  # was 0.10
  ```

**`scan_flat_base` only:**
- Loosen volume dry-up: `vol_ratio_10_50 > 0.75` → `vol_ratio_10_50 > 0.90`

---

### 4. Engine 6 (Resistance Breakout) — Simplify Stage 2 + lower volume

**File:** `backend/engines/engine6.py`

**Remove full Stage 2 filter.** Replace with simple uptrend check:
- Keep: `close > 50 SMA`
- Remove: `close > 200 SMA` requirement
- Remove: `lc < yr_low * 1.30` check
- Remove: rising 200 SMA check (20-bar slope)

**Lower volume threshold:**
- `_VOL_SURGE_THRESHOLD = 1.50` → `_VOL_SURGE_THRESHOLD = 1.00`

---

### 5. No frontend changes required

The badge system in `SetupTable.jsx` already handles all existing signal types. Removing TDL-BRK from the watchlist means it disappears there; it will now appear in the VCP table under the existing TDL badge (from Path C).

---

## Files Changed

| File | Change |
|------|--------|
| `backend/engines/engine2.py` | RS threshold, TDL vol gate, remove TDL-BRK from near_breakout |
| `backend/engines/engine3.py` | Tighten relaxed pullback CCI floor + add support zone requirement |
| `backend/engines/engine5.py` | Remove rising SMA check, loosen rim + vol thresholds |
| `backend/engines/engine6.py` | Simplify Stage 2, lower volume threshold |

No database schema changes. No frontend changes.
