# System Guide & Legend Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a full-screen System Guide modal to the dashboard so new users can understand every signal, badge, and setup type the scanner produces.

**Architecture:** Three files touched — create `SystemGuideModal.jsx` (self-contained), add `onOpenGuide` prop + GUIDE button to `Header.jsx`, add `showGuide` state + modal render to `App.jsx`. No backend changes, no new CSS classes, no router changes.

**Tech Stack:** React 18, inline styles matching the existing CSS variable design system, existing `.badge` and `.section-label` CSS classes.

---

### Task 1: Create SystemGuideModal.jsx

**Files:**
- Create: `frontend/src/components/SystemGuideModal.jsx`

No unit test needed — this is a pure render component. Verify visually in Task 3.

**Step 1: Create the file with this exact content**

```jsx
/**
 * SystemGuideModal — System Guide & Legend overlay
 *
 * Props:
 *   isOpen  {bool}  — controls visibility
 *   onClose {func}  — called on Escape, × button, or backdrop click
 *
 * Keyboard shortcuts (wired in App.jsx):
 *   Escape → close
 *   ?      → open (when no input is focused)
 */
import { useEffect } from 'react'

export default function SystemGuideModal({ isOpen, onClose }) {
  // Close on Escape
  useEffect(() => {
    if (!isOpen) return
    const handler = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [isOpen, onClose])

  if (!isOpen) return null

  return (
    /* Backdrop — click outside to close */
    <div
      onClick={onClose}
      style={{
        position: 'fixed', inset: 0, zIndex: 50,
        background: 'rgba(0,0,0,0.88)',
        backdropFilter: 'blur(2px)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        padding: 20,
      }}
    >
      {/* Panel — stop clicks propagating to backdrop */}
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: '100%', maxWidth: 820,
          maxHeight: '85vh',
          background: 'var(--surface)',
          border: '1px solid var(--border-light)',
          display: 'flex', flexDirection: 'column',
        }}
      >
        {/* Amber accent bar */}
        <div style={{ height: 3, background: 'var(--accent)', flexShrink: 0 }} />

        {/* Title row */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '12px 16px 10px',
          borderBottom: '1px solid var(--border)',
          flexShrink: 0,
        }}>
          <span style={{
            fontFamily: 'Barlow Condensed, sans-serif',
            fontSize: 14, fontWeight: 700, letterSpacing: '0.2em',
            textTransform: 'uppercase', color: 'var(--text)',
          }}>
            System Guide &amp; Legend
          </span>
          <button
            onClick={onClose}
            title="Close (Esc)"
            style={{
              background: 'transparent', border: 'none',
              color: 'var(--muted)', cursor: 'pointer',
              fontFamily: 'IBM Plex Mono, monospace',
              fontSize: 18, padding: '0 4px', lineHeight: 1,
            }}
          >
            ×
          </button>
        </div>

        {/* Scrollable body */}
        <div style={{ overflowY: 'auto', paddingBottom: 16 }}>
          <MetricsSection />
          <IndicatorsSection />
          <SetupTypesSection />
        </div>
      </div>
    </div>
  )
}

/* ── Section 1: Core Metrics ──────────────────────────────────────────────── */

function MetricsSection() {
  const metrics = [
    {
      label: 'Entry $',
      value: '$182.40',
      color: 'var(--text)',
      desc: 'Exact trigger price to enter the trade.',
    },
    {
      label: 'Stop $',
      value: '$174.20',
      color: 'var(--halt)',
      desc: 'Invalidation level — hard stop-loss. Exit immediately if price closes below this.',
    },
    {
      label: 'Target $',
      value: '$198.80',
      color: 'var(--go)',
      desc: 'Initial take-profit based on ATR or the next KDE resistance zone.',
    },
    {
      label: 'R:R',
      value: '2.0×',
      color: 'var(--accent)',
      desc: 'Risk-to-Reward ratio. 2.0 means you stand to make twice what you risk.',
    },
  ]

  return (
    <div>
      <SectionLabel color="var(--accent)">Core Metrics</SectionLabel>
      <div style={{
        display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)',
        gap: 8, padding: '12px 12px 4px',
      }}>
        {metrics.map((m) => (
          <div
            key={m.label}
            style={{
              background: 'var(--panel)',
              border: '1px solid var(--border)',
              padding: '12px 14px',
              display: 'flex', flexDirection: 'column', gap: 6,
            }}
          >
            <span style={{
              fontFamily: 'Barlow Condensed, sans-serif',
              fontSize: 9, fontWeight: 700, letterSpacing: '0.18em',
              textTransform: 'uppercase', color: 'var(--muted)',
            }}>
              {m.label}
            </span>
            <span style={{
              fontFamily: 'IBM Plex Mono, monospace',
              fontSize: 20, fontWeight: 700, color: m.color, lineHeight: 1,
            }}>
              {m.value}
            </span>
            <span style={{ fontSize: 10, color: 'var(--muted)', lineHeight: 1.5 }}>
              {m.desc}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

/* ── Section 2: Alpha Indicators ──────────────────────────────────────────── */

function IndicatorsSection() {
  const rows = [
    {
      badge: <span style={{ fontSize: 14, lineHeight: 1 }}>🔥</span>,
      name: 'Hot Sector',
      desc: "Sector Clustering — appears when ≥3 setups fire in the same sector during a single scan. Signals institutional order flow and sector rotation in progress.",
    },
    {
      badge: <GBadge style={{ background: 'rgba(0,200,255,0.10)', color: '#00C8FF', border: '1px solid rgba(0,200,255,0.3)', fontWeight: 700 }}>LEAD</GBadge>,
      name: 'RS Lead',
      desc: "Highest-conviction breakout: stock's 3-month return beats SPY AND the RS Line is at a 52-week high (blue dot). Institutional accumulation at peak relative strength.",
    },
    {
      badge: <GBadge style={{ background: 'rgba(0,200,122,0.18)', color: 'var(--go)', border: '1px solid rgba(0,200,122,0.4)', fontWeight: 700 }}>BRK</GBadge>,
      name: 'Confirmed Breakout',
      desc: "Price closed above a KDE resistance zone with ≥150% average volume and positive composite RS score (O'Neil formula). Demand is overwhelming supply.",
    },
    {
      badge: <GBadge style={{ background: 'rgba(245,166,35,0.12)', color: 'var(--accent)', border: '1px solid rgba(245,166,35,0.3)' }}>DRY</GBadge>,
      name: 'Volume Dry-Up',
      desc: "Volume contracted to <50% of the 50-day average during consolidation. Sellers are exhausted — the stock is coiling for the next explosive move.",
    },
    {
      badge: <GBadge style={{ background: 'rgba(255,255,255,0.08)', color: '#FFFFFF', border: '1px solid rgba(255,255,255,0.25)' }}>TDL</GBadge>,
      name: 'Trendline',
      desc: "Setup is respecting or breaking a strictly validated geometric trendline. Enforced with no-slice rule (no candle body may cross the line) and macro anchor (global high/low).",
    },
    {
      badge: <GBadge style={{ background: 'rgba(0,200,255,0.10)', color: '#00C8FF', border: '1px solid rgba(0,200,255,0.3)', fontWeight: 700 }}>KDE</GBadge>,
      name: 'KDE Breakout',
      desc: "Horizontal breakout above a Gaussian KDE density peak — a statistically significant price cluster where heavy institutional volume was traded historically.",
    },
    {
      badge: <GBadge style={{ background: 'rgba(0,200,255,0.10)', color: '#00C8FF', border: '1px solid rgba(0,200,255,0.2)', fontSize: 8 }}>RS+</GBadge>,
      name: 'RS Positive',
      desc: "Stock's O'Neil composite RS score is positive: weighted 63-day (40%) + 126-day (20%) + 189-day (20%) + 252-day (20%) return vs. SPY. Outperforming the market.",
    },
    {
      badge: <GBadge style={{ background: 'rgba(245,166,35,0.12)', color: 'var(--accent)', border: '1px solid rgba(245,166,35,0.3)', fontSize: 7 }}>RLX</GBadge>,
      name: 'CCI Relaxation',
      desc: "CCI reset below −30 (oversold) while the primary trend (8 EMA > 20 EMA, close > 50 SMA) remains intact. Relaxed pullback entry for strong ongoing trends.",
    },
    {
      badge: <GBadge style={{ background: '#FF6B35', color: 'white', border: 'none', fontSize: 7, fontWeight: 700, letterSpacing: '0.5px', padding: '2px 4px' }}>ASC-TDL</GBadge>,
      name: 'Ascending TDL',
      desc: "3rd-touch bounce off a validated ascending trendline (higher-lows sequence). Geometric no-slice rule enforced — no bar has ever closed below the line.",
    },
    {
      badge: <GBadge style={{ fontFamily: 'monospace', fontSize: 9, background: 'rgba(255,255,255,0.04)', color: 'var(--muted)', border: '1px solid var(--border)' }}>Q72</GBadge>,
      name: 'Quality Score (0–100)',
      desc: "O'Neil composite for Base patterns: RS vs SPY (25pts) + base tightness/depth (25pts) + volume dry-up (25pts) + RS blue dot at 52-week high (25pts).",
    },
  ]

  return (
    <div>
      <SectionLabel color="#00C8FF">Alpha Indicators</SectionLabel>
      <div style={{ padding: '4px 12px 4px' }}>
        {rows.map((row, i) => (
          <div
            key={i}
            style={{
              display: 'grid',
              gridTemplateColumns: '148px 1fr',
              alignItems: 'center',
              gap: 12,
              padding: '8px 8px',
              borderBottom: i < rows.length - 1 ? '1px solid rgba(26,37,53,0.6)' : 'none',
            }}
          >
            {/* Left: badge + name */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <div style={{ minWidth: 40, display: 'flex', justifyContent: 'flex-start' }}>
                {row.badge}
              </div>
              <span style={{
                fontFamily: 'Barlow Condensed, sans-serif',
                fontSize: 10, fontWeight: 700, letterSpacing: '0.1em',
                textTransform: 'uppercase', color: 'var(--text)',
                whiteSpace: 'nowrap',
              }}>
                {row.name}
              </span>
            </div>
            {/* Right: description */}
            <span style={{ fontSize: 10, color: 'var(--muted)', lineHeight: 1.55 }}>
              {row.desc}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

/* ── Section 3: Setup Types ───────────────────────────────────────────────── */

function SetupTypesSection() {
  const setups = [
    {
      name: 'VCP Breakouts',
      accent: 'var(--blue)',
      desc: "Minervini's Volatility Contraction Pattern. The stock is in a Stage 2 uptrend, contracting from left to right with decreasing volume, ready to explode out of a tight pivot.",
    },
    {
      name: 'Tactical Pullbacks',
      accent: 'var(--accent)',
      desc: 'A strong stock pulling back to a key moving average (20 EMA or 50 SMA) to shake out weak hands before resuming the uptrend. CCI resets to oversold then hooks up.',
    },
    {
      name: 'Base Patterns',
      accent: 'var(--go)',
      desc: "Flat or deep consolidations (Cup & Handle, Flat Base) where the stock catches its breath and builds a foundation for the next leg up. Quality-scored 0–100.",
    },
    {
      name: 'Resistance Breakouts',
      accent: 'var(--go)',
      desc: 'Stock built a tight 3-bar launchpad just below a heavy resistance level and is now breaking through with decisive close (top 30% of range) and >150% average volume.',
    },
  ]

  return (
    <div>
      <SectionLabel color="var(--go)">Setup Types</SectionLabel>
      <div style={{
        display: 'grid', gridTemplateColumns: '1fr 1fr',
        gap: 8, padding: '12px',
      }}>
        {setups.map((s) => (
          <div
            key={s.name}
            style={{
              background: 'var(--panel)',
              border: '1px solid var(--border)',
              borderLeft: `3px solid ${s.accent}`,
              padding: '12px 14px',
              display: 'flex', flexDirection: 'column', gap: 6,
            }}
          >
            <span style={{
              fontFamily: 'Barlow Condensed, sans-serif',
              fontSize: 12, fontWeight: 700, letterSpacing: '0.12em',
              textTransform: 'uppercase', color: 'var(--text)',
            }}>
              {s.name}
            </span>
            <span style={{ fontSize: 10, color: 'var(--muted)', lineHeight: 1.55 }}>
              {s.desc}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

/* ── Shared primitives ────────────────────────────────────────────────────── */

function SectionLabel({ children, color }) {
  return (
    <div
      className="section-label"
      style={{ borderTop: '1px solid var(--border)' }}
    >
      <span style={{
        display: 'inline-block', width: 6, height: 6,
        borderRadius: '50%', background: color, flexShrink: 0,
      }} />
      {children}
    </div>
  )
}

function GBadge({ children, style }) {
  return (
    <span className="badge" style={style}>
      {children}
    </span>
  )
}
```

**Step 2: Verify file exists**

```bash
ls frontend/src/components/SystemGuideModal.jsx
```

Expected: file listed with non-zero size.

**Step 3: Commit**

```bash
git add frontend/src/components/SystemGuideModal.jsx
git commit -m "feat(guide): add SystemGuideModal component"
```

---

### Task 2: Add GUIDE Button to Header.jsx

**Files:**
- Modify: `frontend/src/components/Header.jsx`

**Step 1: Add `onOpenGuide` to the props destructure**

In `Header.jsx` line 10, find:
```jsx
export default function Header({ regime, scanStatus, onRunScan, onSearchTicker }) {
```

Change to:
```jsx
export default function Header({ regime, scanStatus, onRunScan, onSearchTicker, onOpenGuide }) {
```

**Step 2: Add the GUIDE button in the right block**

In the right block section (the `div` containing scan metadata and RUN SCAN button), find:
```jsx
          {/* Run scan button */}
          <button
            className="btn-scan"
```

Insert immediately **before** that comment:
```jsx
          {/* Guide button */}
          <button
            onClick={onOpenGuide}
            style={{
              fontFamily: 'IBM Plex Mono, monospace',
              fontSize: 11,
              fontWeight: 600,
              letterSpacing: '0.08em',
              padding: '5px 12px',
              background: 'transparent',
              border: '1px solid var(--border-light)',
              color: 'var(--muted)',
              cursor: 'pointer',
              textTransform: 'uppercase',
              transition: 'border-color 0.15s, color 0.15s',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.borderColor = 'var(--accent)'
              e.currentTarget.style.color = 'var(--accent)'
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.borderColor = 'var(--border-light)'
              e.currentTarget.style.color = 'var(--muted)'
            }}
            title="System Guide & Legend (?)"
          >
            ? GUIDE
          </button>
```

**Step 3: Verify the right block now has both buttons**

The right block should read:
```
[ Last Scan / SCANNING... ]  [ ? GUIDE ]  [ RUN SCAN ]
```

**Step 4: Commit**

```bash
git add frontend/src/components/Header.jsx
git commit -m "feat(guide): add GUIDE button to Header"
```

---

### Task 3: Wire State and Modal in App.jsx

**Files:**
- Modify: `frontend/src/App.jsx`

**Step 1: Import SystemGuideModal**

At the top of `App.jsx`, after the existing imports, add:
```jsx
import SystemGuideModal from './components/SystemGuideModal.jsx'
```

**Step 2: Add showGuide state**

Inside the `App()` function, after the existing `useState` declarations (around line 58), add:
```jsx
  const [showGuide, setShowGuide] = useState(false)
```

**Step 3: Add `?` keyboard shortcut**

After the existing `useEffect` hooks, add a new one:
```jsx
  // '?' key opens the guide (when no input element is focused)
  useEffect(() => {
    const handler = (e) => {
      if (e.key === '?' && document.activeElement.tagName !== 'INPUT') {
        setShowGuide((v) => !v)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])
```

**Step 4: Pass `onOpenGuide` to Header**

Find the `<Header` render call:
```jsx
      <Header
        regime={regime}
        scanStatus={scanStatus}
        onRunScan={handleRunScan}
        onSearchTicker={handleTickerClick}
      />
```

Change to:
```jsx
      <Header
        regime={regime}
        scanStatus={scanStatus}
        onRunScan={handleRunScan}
        onSearchTicker={handleTickerClick}
        onOpenGuide={() => setShowGuide(true)}
      />
```

**Step 5: Render the modal at the bottom of the App JSX**

Find the closing `</div>` of the root App div (the very last line before the closing `}`):
```jsx
    </div>
  )
}
```

Change to:
```jsx
      {/* System Guide modal */}
      <SystemGuideModal isOpen={showGuide} onClose={() => setShowGuide(false)} />
    </div>
  )
}
```

**Step 6: Commit**

```bash
git add frontend/src/App.jsx
git commit -m "feat(guide): wire SystemGuideModal into App — state + ? shortcut"
```

---

### Task 4: Visual Verification

**Step 1: Start the frontend dev server**

```bash
cd swing-trading-dashboard/frontend
npm run dev
```

**Step 2: Open browser at http://localhost:5173**

**Step 3: Verify these 6 things**

1. Header right block shows `? GUIDE` button to the left of RUN SCAN
2. Button is muted/dim by default, glows amber on hover
3. Clicking `? GUIDE` opens the modal overlay
4. Modal shows amber top bar + all 3 sections (Core Metrics, Alpha Indicators, Setup Types)
5. Clicking the backdrop or pressing `Escape` closes the modal
6. Pressing `?` on the keyboard (when not typing in the search box) toggles the modal

**Step 4: Final commit**

```bash
git add -A
git commit -m "feat(guide): complete System Guide & Legend modal"
```

---

## Testing Summary

This is a pure UI feature — no backend, no data logic, no new algorithmic behaviour. All 111 existing backend tests remain unaffected. Verification is visual per Task 4.

The `?` keyboard shortcut skips firing when `document.activeElement.tagName === 'INPUT'` so it won't interfere with the Chart Lookup search box in the header.
