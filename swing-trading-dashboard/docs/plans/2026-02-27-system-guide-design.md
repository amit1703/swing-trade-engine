# System Guide & Legend — Design Document
**Date:** 2026-02-27
**Status:** Approved

---

## Problem

New users have no reference for what the scanner signals mean. Badge labels (DRY, BRK, TDL, RLX, LEAD, KDE, ASC-TDL), the R:R column, the 🔥 icon, and Q-scores are all opaque without prior O'Neil/Minervini context.

---

## Solution

A full-screen modal overlay accessible via a `GUIDE` button in the header. Organises all signal documentation into 3 logical sections with live badge rendering and setup-type cards. Matches the existing dark quant aesthetic exactly.

---

## Architecture

### New files
| File | Purpose |
|------|---------|
| `frontend/src/components/SystemGuideModal.jsx` | Self-contained modal component. Accepts `isOpen` + `onClose` props. Owns no external state. |

### Modified files
| File | Change |
|------|--------|
| `frontend/src/components/Header.jsx` | Add `onOpenGuide` prop; render `GUIDE` button in right block between scan metadata and RUN SCAN button. |
| `frontend/src/App.jsx` | Add `showGuide` / `setShowGuide` useState; pass `onOpenGuide` to Header; render `<SystemGuideModal>` at root JSX level. |

---

## Header Button

**Placement:** Right block, between scan metadata and the RUN SCAN button.

**Visual spec:**
- Label: `? GUIDE`
- Default state: `border: 1px solid var(--border-light)`, `color: var(--muted)`
- Hover state: `border-color: var(--accent)`, `color: var(--accent)`
- Same font/padding as `.btn-scan` (IBM Plex Mono, 11px, letter-spacing 0.08em)
- Does NOT use `btn-scan` class directly (different default colour) — inline styles

---

## Modal Structure

```
┌─ amber top-bar (3px) ─────────────────────────────────────────┐
│  SYSTEM GUIDE & LEGEND                               [ × ]     │
├───────────────────────────────────────────────────────────────┤
│  ● CORE METRICS                                               │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐        │
│  │ ENTRY $  │ │  STOP $  │ │ TARGET $ │ │   R:R    │        │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘        │
├───────────────────────────────────────────────────────────────┤
│  ● ALPHA INDICATORS                                           │
│  [badge] label          description …                         │
│  [badge] label          description …                         │
│  … (10 rows)                                                  │
├───────────────────────────────────────────────────────────────┤
│  ● SETUP TYPES                                                │
│  ┌──────────────────────┐  ┌──────────────────────┐         │
│  │ VCP Breakouts        │  │ Tactical Pullbacks    │         │
│  └──────────────────────┘  └──────────────────────┘         │
│  ┌──────────────────────┐  ┌──────────────────────┐         │
│  │ Base Patterns        │  │ Resistance Breakouts  │         │
│  └──────────────────────┘  └──────────────────────┘         │
└───────────────────────────────────────────────────────────────┘
```

**Overlay:** `position: fixed; inset: 0; z-index: 50; background: rgba(0,0,0,0.88); backdrop-filter: blur(2px)`

**Panel:** `max-width: 820px; max-height: 85vh; overflow-y: auto; background: var(--surface); border: 1px solid var(--border-light)` — centered via flexbox on overlay.

**Top accent bar:** `height: 3px; background: var(--accent)` — amber stripe at very top of panel.

**Close:** `×` button top-right, and `Escape` key listener. `?` key anywhere on page toggles open.

---

## Section 1 — Core Metrics

4-column CSS grid of metric cards. Each card:
- Label: Barlow Condensed, 9px, tracking-widest, `var(--muted)`
- Example value: IBM Plex Mono, 18px, bold, colour-coded
- Description: 1 line, 10px, `var(--muted)`

| Metric | Example colour | Example value | Description |
|--------|---------------|---------------|-------------|
| ENTRY $ | `var(--text)` | `$182.40` | Exact trigger price to enter the trade |
| STOP $ | `var(--halt)` | `$174.20` | Invalidation level — hard stop-loss |
| TARGET $ | `var(--go)` | `$198.80` | Initial take-profit based on ATR or next resistance |
| R:R | `var(--accent)` | `2.0×` | Risk-to-Reward. 2.0 = stand to make twice what you risk |

---

## Section 2 — Alpha Indicators

2-column definition list (`display: grid; grid-template-columns: 140px 1fr`). Left col: live badge JSX (exact same markup as SetupTable). Right col: bold name + description.

| Badge | Name | Description |
|-------|------|-------------|
| 🔥 | Hot Sector | ≥3 setups in the same sector during this scan — institutional order flow / sector rotation signal |
| `LEAD` (cyan) | RS Lead | Highest-conviction BRK: stock's 3m return > SPY AND RS Line at 52-week high (blue dot) |
| `BRK` (green) | Confirmed Breakout | Price closed above resistance zone with ≥150% average volume and positive composite RS score |
| `DRY` (amber) | Volume Dry-Up | Volume contracted to <50% of 50-day average during consolidation — sellers exhausted |
| `TDL` (white) | Trendline Break | Setup is breaking or respecting a strictly validated geometric trendline (no-slice rule enforced) |
| `KDE` (cyan) | KDE Breakout | Horizontal breakout above a Gaussian KDE density peak (high-probability resistance cluster) |
| `RS+` (cyan) | RS Positive | Stock's 3-month return is currently outperforming SPY |
| `RLX` (amber) | CCI Relaxation | Momentum oscillator reset to oversold (CCI < −30) while primary trend intact — relaxed pullback entry |
| `ASC-TDL` (orange) | Ascending TDL | 3rd touch bounce off a validated ascending trendline — structural higher-low sequence |
| `Q{n}` (dim) | Quality Score | O'Neil composite score 0–100: RS vs SPY (25pts) + base tightness (25pts) + vol dry-up (25pts) + blue dot (25pts) |

---

## Section 3 — Setup Types

2×2 CSS grid of cards. Each card:
- Coloured `border-left: 3px solid <accent>` (blue=VCP, amber=Pullback, green=Base & ResBreakout)
- Name: Barlow Condensed, 12px, 700, tracking-wide, `var(--text)`
- Description: 10px, `var(--muted)`, 3 lines max

| Setup | Accent | Description |
|-------|--------|-------------|
| VCP Breakouts | `var(--blue)` | Minervini's Volatility Contraction Pattern. Stage 2 uptrend contracting left-to-right with decreasing volume, ready to explode from a tight pivot. |
| Tactical Pullbacks | `var(--accent)` | Strong stock pulling back to a key moving average (20 EMA or 50 SMA) to shake out weak hands before resuming the uptrend. |
| Base Patterns | `var(--go)` | Flat or deep consolidations where the stock is catching its breath and building a foundation for the next leg up (Cup & Handle, Flat Base). |
| Resistance Breakouts | `var(--go)` | Tight launchpad just below a heavy resistance level, now breaking through with decisive price action and >150% average volume (Minervini rules). |

---

## Interaction

- `GUIDE` button in header → sets `showGuide = true`
- Clicking overlay backdrop → `onClose()`
- `×` button → `onClose()`
- `Escape` key → `onClose()` (useEffect with keydown listener)
- `?` key (when modal closed, no input focused) → `setShowGuide(true)`

---

## Styling Constraints

- No new CSS classes in `index.css` — all styles inline or via existing Tailwind utilities + existing classes (`.section-label`, `.badge`)
- Modal uses `font-family: 'IBM Plex Mono', monospace` for body, `'Barlow Condensed', sans-serif` for section headers — matching root CSS
- Scanline overlay (`body::after`, z-index 9999) sits above the modal — this is intentional (preserves the CRT aesthetic over the guide too)
