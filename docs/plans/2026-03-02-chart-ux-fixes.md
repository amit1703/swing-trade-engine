# Chart UX Fixes Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix four chart UX pain-points in `TradingChart.jsx`: scroll-to-pan (Ctrl=zoom), auto-scale reset button, kinetic scroll removal, and right margin.

**Architecture:** All changes are isolated to `TradingChart.jsx`. A new `chartsRef` stores the three live chart instances so the AUTO button (rendered in JSX) can reach them. Wheel behavior is managed by toggling `handleScale`/`handleScroll` options on the same chart instances in response to DOM `wheel` events. No new files are created.

**Tech Stack:** React 18, lightweight-charts v4, Vite

---

### Task 1: Add right margin and disable kinetic scroll in SHARED_CHART_OPTS

**Files:**
- Modify: `swing-trading-dashboard/frontend/src/components/TradingChart.jsx:69-76`

**Step 1: Apply the two new `timeScale` options**

In `SHARED_CHART_OPTS`, replace the existing `timeScale` block (lines 69-73):

```js
timeScale: {
  borderColor: COLORS.border,
  timeVisible: true,
  secondsVisible: false,
  rightOffset: 8,
  kineticScrollEnabled: false,
},
```

`rightOffset: 8` keeps 8 empty bars to the right of the last candle.
`kineticScrollEnabled: false` stops the "slides away" momentum effect.

**Step 2: Verify the dev server still compiles**

The Vite dev server is already running on http://localhost:5173. Check the terminal — no red errors. Reload the page, click a ticker, confirm the chart loads and the last candle no longer touches the right axis wall.

**Step 3: Commit**

```bash
git add swing-trading-dashboard/frontend/src/components/TradingChart.jsx
git commit -m "fix(chart): add rightOffset=8 and disable kinetic scroll"
```

---

### Task 2: Enable autoScale on the price scale

**Files:**
- Modify: `swing-trading-dashboard/frontend/src/components/TradingChart.jsx:64-68`

**Step 1: Add `autoScale: true` to `rightPriceScale` in `SHARED_CHART_OPTS`**

```js
rightPriceScale: {
  borderColor: COLORS.border,
  textColor: COLORS.muted,
  scaleMargins: { top: 0.08, bottom: 0.05 },
  autoScale: true,
},
```

This ensures the price scale starts in auto-fit mode on every fresh chart load.

**Step 2: Verify**

Reload, click a ticker. The price scale should fit the visible candles without any manual adjustment needed.

**Step 3: Commit**

```bash
git add swing-trading-dashboard/frontend/src/components/TradingChart.jsx
git commit -m "fix(chart): enable autoScale on rightPriceScale"
```

---

### Task 3: Add chartsRef to expose live chart instances outside the effect

**Files:**
- Modify: `swing-trading-dashboard/frontend/src/components/TradingChart.jsx:80-95`

**Step 1: Declare the ref after the existing `seriesRef`**

After the line `const seriesRef  = useRef({})`, add:

```js
const chartsRef  = useRef({})   // holds mainChart / cciChart / rsChart for AUTO button
```

**Step 2: Populate the ref inside the chart-creation `useEffect`, just before the cleanup return**

After the line `seriesRef.current = { ... }` block (around line 541), add:

```js
// ── Store chart instance refs for AUTO button ──────────────────────────
chartsRef.current = { mainChart, cciChart, rsChart }
```

Also clear it in the cleanup:

```js
return () => {
  chartsRef.current = {}        // ← add this line first
  seriesRef.current = {}
  observer.disconnect()
  ...
}
```

**Step 3: Verify compilation**

No runtime errors in console after reload.

**Step 4: Commit**

```bash
git add swing-trading-dashboard/frontend/src/components/TradingChart.jsx
git commit -m "refactor(chart): expose chart instances via chartsRef for AUTO button"
```

---

### Task 4: Scroll-to-pan with Ctrl/Cmd+scroll-to-zoom

**Files:**
- Modify: `swing-trading-dashboard/frontend/src/components/TradingChart.jsx` — inside chart-creation `useEffect`, after chart creation

**Step 1: Set initial handleScale/handleScroll options on all three charts**

In `SHARED_CHART_OPTS`, replace:

```js
handleScale: true,
handleScroll: true,
```

with:

```js
handleScale: {
  mouseWheel: false,          // wheel zooms only when Ctrl/Cmd held (see wheel listener)
  pinch: true,
  axisPressedMouseMove: { time: true, price: true },
  axisDoubleClickReset: { time: true, price: true },
},
handleScroll: {
  mouseWheel: true,           // default: wheel pans
  pressedMouseMove: true,
  horzTouchDrag: true,
  vertTouchDrag: false,
},
```

**Step 2: Add wheel event listeners after all three charts are created**

Inside the `useEffect`, after `rsChart` is created and before the candlestick series block, add:

```js
// ── Ctrl/Cmd+scroll = zoom, plain scroll = pan ─────────────────────────
const makeWheelHandler = (chart) => (e) => {
  const wantZoom = e.ctrlKey || e.metaKey
  chart.applyOptions({
    handleScale: { mouseWheel: wantZoom },
    handleScroll: { mouseWheel: !wantZoom },
  })
}

const mainWheelHandler = makeWheelHandler(mainChart)
const cciWheelHandler  = makeWheelHandler(cciChart)
const rsWheelHandler   = makeWheelHandler(rsChart)

mainEl.addEventListener('wheel', mainWheelHandler, { passive: true })
cciEl.addEventListener('wheel', cciWheelHandler,   { passive: true })
rsEl.addEventListener('wheel', rsWheelHandler,     { passive: true })
```

**Step 3: Clean up listeners in the cleanup return**

```js
return () => {
  mainEl.removeEventListener('wheel', mainWheelHandler)
  cciEl.removeEventListener('wheel', cciWheelHandler)
  rsEl.removeEventListener('wheel', rsWheelHandler)
  chartsRef.current = {}
  seriesRef.current = {}
  observer.disconnect()
  ...
}
```

**Step 4: Verify behavior**

- Plain mouse wheel: chart pans left/right
- Ctrl+scroll (or Cmd+scroll on Mac): chart zooms in/out
- No console errors

**Step 5: Commit**

```bash
git add swing-trading-dashboard/frontend/src/components/TradingChart.jsx
git commit -m "feat(chart): scroll pans by default, Ctrl/Cmd+scroll zooms"
```

---

### Task 5: Add "AUTO" reset button overlay

**Files:**
- Modify: `swing-trading-dashboard/frontend/src/components/TradingChart.jsx` — JSX section inside the main chart `<div className="flex-1 min-h-0 relative">`

**Step 1: Write the reset handler function (inside the component, above the return)**

After all the `useEffect` blocks and before the early-return loading state, add:

```js
const handleAutoReset = () => {
  const { mainChart, cciChart, rsChart } = chartsRef.current
  if (!mainChart) return
  mainChart.timeScale().fitContent()
  mainChart.priceScale('right').applyOptions({ autoScale: true })
  cciChart?.timeScale().fitContent()
  cciChart?.priceScale('right').applyOptions({ autoScale: true })
  rsChart?.timeScale().fitContent()
  rsChart?.priceScale('right').applyOptions({ autoScale: true })
}
```

**Step 2: Add the AUTO button to the JSX**

Inside the `<div className="flex-1 min-h-0 relative">` block, right after the closing `</div>` of the visibility toggle bar (around line 790), add:

```jsx
{/* AUTO reset button — bottom-right of main chart */}
{chartData && (
  <button
    onClick={handleAutoReset}
    style={{
      position: 'absolute', bottom: 8, right: 10, zIndex: 10,
      fontFamily: '"IBM Plex Mono", monospace',
      fontSize: 9,
      fontWeight: 700,
      letterSpacing: '0.08em',
      padding: '3px 8px',
      background: 'rgba(0,0,0,0.75)',
      border: '1px solid rgba(245,166,35,0.45)',
      color: 'rgba(245,166,35,0.85)',
      cursor: 'pointer',
      backdropFilter: 'blur(4px)',
      userSelect: 'none',
    }}
  >
    AUTO
  </button>
)}
```

This matches the existing `VisToggle` button visual style (same font, blur, border pattern) using the accent colour to make it findable.

**Step 3: Verify behavior**

1. Load a chart
2. Drag the Y-axis price scale to distort the view
3. Click AUTO — chart should snap back to full content fit with price scale auto-scaling re-enabled
4. Scroll to a historical area, click AUTO — should jump to fit all content

**Step 4: Commit**

```bash
git add swing-trading-dashboard/frontend/src/components/TradingChart.jsx
git commit -m "feat(chart): add AUTO button to reset fitContent and re-enable autoScale"
```

---

## Final verification checklist

- [ ] Right margin: last candle has ~8 bars of breathing room before the right axis
- [ ] Kinetic scroll: chart stops immediately when mouse is released, no slide-away
- [ ] Scroll = pan: plain wheel moves the chart horizontally
- [ ] Ctrl+scroll = zoom: holding Ctrl (or Cmd) while scrolling zooms in/out
- [ ] AUTO button visible: amber/orange "AUTO" chip at bottom-right of main chart
- [ ] AUTO resets: clicking it calls fitContent + re-enables autoScale on all panels
- [ ] No console errors on load, chart switch, or resize
