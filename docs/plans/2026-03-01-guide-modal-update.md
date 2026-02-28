# Guide Modal Update Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Update SystemGuideModal.jsx to document all features added since the last guide update — new chart elements, new signal badges, and a new Chart Controls section.

**Architecture:** Single-file frontend change. All updates are in `SystemGuideModal.jsx`. No backend changes, no API changes, no new files. Four existing sections are updated in-place; one new section is inserted between Chart Legend and Portfolio Health.

**Tech Stack:** React 18, inline styles, IBM Plex Mono / Barlow Condensed fonts, existing `GBadge` and `SectionLabel` primitives.

---

### Task 1: Update Alpha Indicators — add 4 missing badge entries

**Files:**
- Modify: `swing-trading-dashboard/frontend/src/components/SystemGuideModal.jsx`

The `rows` array in `IndicatorsSection()` is missing these 4 entries. Add them after the existing `RLX` entry (index 7) and before `ASC-TDL`:

**Step 1: Add Age badge entry**

In the `rows` array inside `IndicatorsSection`, add after the `RLX` entry:

```jsx
{
  badge: <GBadge style={{ fontSize: 7, background: 'transparent', color: 'var(--muted)', border: '1px solid var(--border)', padding: '2px 5px' }}>5d</GBadge>,
  name: 'Setup Age',
  desc: 'Days since the setup was first detected. Turns red-bordered at ≥5 days — older setups have had more time for the thesis to play out or fail. Fresh setups (no badge) were detected in the current scan.',
},
```

**Step 2: Add C&H badge entry**

Add after the age entry:

```jsx
{
  badge: <GBadge style={{ background: 'rgba(38,166,154,0.12)', color: '#26a69a', border: '1px solid rgba(38,166,154,0.35)', fontWeight: 700 }}>C&amp;H</GBadge>,
  name: 'Cup & Handle',
  desc: 'Base pattern type: U-shaped cup with a shallow handle. Cup depth 12–35%, right rim within 15% of left peak, handle 5–25 days and 3–15% deep. One of the highest-probability continuation setups.',
},
```

**Step 3: Add FLAT badge entry**

Add after C&H:

```jsx
{
  badge: <GBadge style={{ background: 'rgba(66,165,245,0.12)', color: '#42a5f5', border: '1px solid rgba(66,165,245,0.35)', fontWeight: 700 }}>FLAT</GBadge>,
  name: 'Flat Base',
  desc: 'Base pattern type: tight horizontal consolidation ≥25 days, depth ≤12%, close in upper 75% of range, volume drying to ≤90% of 50-day average. Indicates controlled selling — institutions holding.',
},
```

**Step 4: Add Days Since Breakout entry**

Add after FLAT (this applies to Resistance Breakout rows):

```jsx
{
  badge: <GBadge style={{ fontFamily: 'monospace', fontSize: 9, background: 'transparent', color: 'var(--muted)', border: '1px solid var(--border)' }}>2d ago</GBadge>,
  name: 'Breakout Freshness',
  desc: "Days since the resistance breakout bar. Shows 'today' for same-day breaks, '1d ago'–'3d ago' for recent ones. Fresher breakouts carry less risk of being overextended or fading.",
},
```

**Step 5: Verify in browser**

Open the guide (press `?`) → Alpha Indicators section should now show Setup Age, C&H, FLAT, and Breakout Freshness rows.

---

### Task 2: Update existing Alpha Indicator descriptions

**Files:**
- Modify: `swing-trading-dashboard/frontend/src/components/SystemGuideModal.jsx`

**Step 1: Update BRK description**

Find the BRK row `desc` field and replace with:

```
"Price closed above a KDE resistance zone with ≥150% average volume AND a positive O'Neil composite RS score (stock outperforming SPY over 3–12 months). All three conditions required — volume, price location, and relative strength."
```

**Step 2: Update DRY description**

Find the DRY row `desc` field and replace with:

```
"Stock is in an uptrend and within 3% of resistance, with volume contracted to <50% of 50-day average (at least one bar in the last 10). A U-shape curve fit confirms the contraction pattern. The coil is tightening before the next breakout attempt."
```

**Step 3: Verify in browser**

Open guide → Alpha Indicators → BRK and DRY descriptions should reflect the updated text.

---

### Task 3: Update Chart Legend — add 7 missing entries

**Files:**
- Modify: `swing-trading-dashboard/frontend/src/components/SystemGuideModal.jsx`

Add the following entries to the `items` array in `ChartLegendSection()`, after the existing Pivot Resistance Line entry:

**Step 1: Add SMA 200 entry**

```jsx
{
  visual: (
    <svg width="48" height="20" style={{ display: 'block' }}>
      <line x1="0" y1="10.5" x2="48" y2="10.5" stroke="#FF5C8A" strokeWidth="2" />
    </svg>
  ),
  name: 'SMA 200',
  desc: 'The 200-day simple moving average — the long-term trend divider. Stocks above this line are in a Stage 2 uptrend. Rendered as a thick red-pink line. All scanner setups require price above SMA 200.',
},
```

**Step 2: Add Descending Trendline entry**

```jsx
{
  visual: (
    <svg width="48" height="20" style={{ display: 'block' }}>
      <line x1="0" y1="4" x2="48" y2="16" stroke="rgba(255,255,255,0.75)" strokeWidth="1.5" />
    </svg>
  ),
  name: 'Descending TDL',
  desc: "Resistance trendline drawn from the stock's macro high through validated lower highs. White solid line labelled TDL-R. A close above this line — confirmed by the engine — produces a Trendline Breakout (TDL) signal.",
},
```

**Step 3: Add Ascending Trendline entry**

```jsx
{
  visual: (
    <svg width="48" height="20" style={{ display: 'block' }}>
      <line x1="0" y1="16" x2="48" y2="4" stroke="rgba(255,255,255,0.75)" strokeWidth="1.5" />
    </svg>
  ),
  name: 'Ascending TDL',
  desc: 'Support trendline drawn through a sequence of validated higher lows. White solid line labelled TDL-S. A third confirmed touch generates an ASC-TDL pullback signal — price bouncing off rising support.',
},
```

**Step 4: Add Volume Bars entry**

```jsx
{
  visual: (
    <svg width="48" height="20" style={{ display: 'block' }}>
      <rect x="4"  y="8"  width="6" height="12" fill="rgba(0,200,122,0.35)" />
      <rect x="13" y="4"  width="6" height="16" fill="rgba(0,200,122,0.35)" />
      <rect x="22" y="10" width="6" height="10" fill="rgba(255,45,85,0.28)" />
      <rect x="31" y="6"  width="6" height="14" fill="rgba(255,45,85,0.28)" />
      <rect x="40" y="9"  width="6" height="11" fill="rgba(0,200,122,0.35)" />
      <line x1="0" y1="9" x2="48" y2="11" stroke="rgba(245,166,35,0.55)" strokeWidth="1" strokeDasharray="3,3" />
    </svg>
  ),
  name: 'Volume Bars',
  desc: 'Per-bar volume histogram in the lower 25% of the chart. Green = up bar, red = down bar. The amber dashed line is the 50-bar volume SMA — bars above it indicate above-average participation.',
},
```

**Step 5: Add RS Line entry**

```jsx
{
  visual: (
    <svg width="48" height="20" style={{ display: 'block' }}>
      <polyline points="0,14 12,12 24,8 36,10 48,5" fill="none" stroke="#F5A623" strokeWidth="1.5" />
    </svg>
  ),
  name: 'RS Line',
  desc: "Sub-chart below the main price panel. Plots ticker close ÷ SPY close daily — rising line means the stock is outperforming the market. A new 52-week high on the RS Line (green dashed reference) is the strongest leading indicator.",
},
```

**Step 6: Add Blue Dot entry**

```jsx
{
  visual: (
    <svg width="48" height="20" style={{ display: 'block' }}>
      <polyline points="0,14 12,12 24,8 36,10 48,5" fill="none" stroke="#F5A623" strokeWidth="1.5" />
      <circle cx="48" cy="5" r="4" fill="#00c87a" />
    </svg>
  ),
  name: 'RS Blue Dot',
  desc: "Green dot marker on the RS Line when the current RS ratio is within 0.5% of its 52-week high. Signals peak relative strength — the stock is leading the market right now. Highest conviction entry signal.",
},
```

**Step 7: Add Earnings Warning entry**

```jsx
{
  visual: (
    <span style={{
      fontSize: 8, padding: '2px 5px',
      background: 'rgba(255,165,0,0.15)',
      color: '#FFA500',
      border: '1px solid rgba(255,165,0,0.4)',
      fontWeight: 700,
      fontFamily: 'IBM Plex Mono, monospace',
      whiteSpace: 'nowrap',
    }}>⚠ EARNINGS 7d</span>
  ),
  name: 'Earnings Warning',
  desc: "Appears in the chart legend when earnings are ≤14 days away. Shows 'TODAY' on the report date. Holding a breakout trade through earnings introduces binary gap risk — consider reducing size or waiting for the print.",
},
```

**Step 8: Verify in browser**

Open guide → Chart Legend section should now list all 10 entries including the 7 new ones.

---

### Task 4: Add Chart Visibility Toggles section

**Files:**
- Modify: `swing-trading-dashboard/frontend/src/components/SystemGuideModal.jsx`

**Step 1: Add new `ChartControlsSection` component**

Add this new function after `ChartLegendSection` and before `PortfolioHealthSection`:

```jsx
function ChartControlsSection() {
  const toggles = [
    { label: 'EMA',  color: '#9B6EFF', desc: 'Show/hide EMA 8 (purple) and EMA 20 (yellow) overlays.' },
    { label: 'SMA',  color: '#4CAF50', desc: 'Show/hide SMA 50 (green) and SMA 200 (red-pink) overlays.' },
    { label: 'TDL',  color: 'rgba(255,255,255,0.8)', desc: 'Show/hide descending resistance trendline and ascending support trendline.' },
    { label: 'S/R',  color: 'rgba(255,255,255,0.6)', desc: 'Show/hide all KDE support and resistance bands.' },
    { label: 'RS',   color: '#F5A623', desc: 'Show/hide the RS Line sub-panel (only appears when RS data is available).' },
    { label: 'VOL',  color: 'rgba(0,200,122,0.8)', desc: 'Show/hide the volume histogram and 50-bar volume SMA.' },
  ]

  return (
    <div>
      <SectionLabel color="var(--muted)">Chart Visibility Toggles</SectionLabel>
      <div style={{ padding: '4px 12px 4px' }}>
        {toggles.map((t, i) => (
          <div
            key={i}
            style={{
              display: 'grid',
              gridTemplateColumns: '148px 1fr',
              alignItems: 'center',
              gap: 12,
              padding: '8px 8px',
              borderBottom: i < toggles.length - 1 ? '1px solid rgba(26,37,53,0.6)' : 'none',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <div style={{ minWidth: 40, display: 'flex', justifyContent: 'flex-start' }}>
                <span style={{
                  fontFamily: 'IBM Plex Mono, monospace',
                  fontSize: 9, fontWeight: 700, letterSpacing: '0.08em',
                  padding: '2px 7px',
                  background: 'rgba(0,0,0,0.75)',
                  border: `1px solid ${t.color}`,
                  color: t.color,
                  userSelect: 'none',
                }}>
                  {t.label}
                </span>
              </div>
              <span style={{
                fontFamily: 'Barlow Condensed, sans-serif',
                fontSize: 10, fontWeight: 700, letterSpacing: '0.1em',
                textTransform: 'uppercase', color: 'var(--text)',
                whiteSpace: 'nowrap',
              }}>
                {t.label}
              </span>
            </div>
            <span style={{ fontSize: 10, color: 'var(--muted)', lineHeight: 1.55 }}>
              {t.desc}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}
```

**Step 2: Wire it into the scrollable body**

In the `SystemGuideModal` return, the scrollable body currently renders:

```jsx
<MetricsSection />
<IndicatorsSection />
<SetupTypesSection />
<ChartLegendSection />
<PortfolioHealthSection />
<KeyboardSection />
```

Add `<ChartControlsSection />` after `<ChartLegendSection />`:

```jsx
<MetricsSection />
<IndicatorsSection />
<SetupTypesSection />
<ChartLegendSection />
<ChartControlsSection />
<PortfolioHealthSection />
<KeyboardSection />
```

**Step 3: Verify in browser**

Open guide → scroll past Chart Legend → new "Chart Visibility Toggles" section should appear with 6 toggle rows.

---

### Task 5: Commit

```bash
cd swing-trading-dashboard
git add frontend/src/components/SystemGuideModal.jsx
git commit -m "docs(guide): update guide modal with new chart elements, badges, and controls section"
```
