# Signal Panel — Any-Ticker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make StockIntelPanel render the full signals view for any selected ticker — watchlist items, favorites, and search — not just tickers in the current scan results.

**Architecture:** Two changes. (1) `StockIntelPanel.jsx` synthesizes a display object from the `analysis` prop when `setup` is null, replacing the empty placeholder. (2) `App.jsx` adds a stale-analysis guard on the prop passed to `StockIntelPanel`, and changes search to always navigate to the scanner page.

**Tech Stack:** React 18, inline styles, IBM Plex Mono (project convention).

---

## Codebase facts

| File | What to know |
|------|-------------|
| `frontend/src/components/StockIntelPanel.jsx` | Props: `{ setup, livePrices, analysis, analysisLoading }`. `setup` is the scan-result setup object (null when ticker not in allSetups). `analysis` is always fetched from `/api/analyze/{ticker}` regardless. Currently shows placeholder when `setup` is null. |
| `frontend/src/App.jsx` | `selectedSetup = allSetups.find(s => s.ticker === selectedTicker) ?? null` — null for WL/search tickers. StockIntelPanel is at lines 374–379. TopBar search is at line 318. |

**analysis object fields used in synthesis:**
- `analysis.ticker` — ticker symbol
- `analysis.score` — setup score (0–100)
- `analysis.setup_type`, `analysis.detected_setup` — setup type string or null
- `analysis.entry`, `analysis.stop_loss`, `analysis.take_profit`, `analysis.rr` — trade plan (may be null)
- `analysis.signals.rs_score` — decimal RS score, same unit as `setup.rs_score` (multiply ×100 for display)
- `analysis.signals.vol_ratio` — volume ratio float

---

## File Map

| File | Action |
|------|--------|
| `frontend/src/components/StockIntelPanel.jsx` | Modify — synthesis block + rename + amber fixes |
| `frontend/src/App.jsx` | Modify — 2 small changes |

---

## Task 1: Update StockIntelPanel.jsx

**Files:**
- Modify: `frontend/src/components/StockIntelPanel.jsx`

- [ ] **Step 1: Read the file**

Read `frontend/src/components/StockIntelPanel.jsx` in full before editing.

- [ ] **Step 2: Replace the `StockIntelPanel` function body**

The helper sub-components (`SignalRow`, `ScoreBadge`, `RankBadge`, `AlignmentChip`, `V5AnalysisSection`) at the top of the file are **unchanged**. Only replace the `export default function StockIntelPanel(...)` block (from line 138 to end of file) with:

```jsx
export default function StockIntelPanel({ setup, livePrices, analysis, analysisLoading }) {
  // Synthesize a display object from analysis when setup (scan result) is not available.
  // The `setup` prop parameter is NOT renamed — it stays as-is so the ?? expression can read it.
  const displaySetup = setup ?? (analysis ? {
    ticker:       analysis.ticker,
    setup_score:  analysis.score,
    setup_type:   analysis.setup_type ?? analysis.detected_setup ?? null,
    entry:        analysis.entry        ?? 0,
    stop_loss:    analysis.stop_loss    ?? 0,
    take_profit:  analysis.take_profit  ?? 0,
    rr:           analysis.rr           ?? 0,
    rs_score:     analysis.signals?.rs_score  ?? null,
    vol_ratio:    analysis.signals?.vol_ratio ?? null,
    is_vol_surge: (analysis.signals?.vol_ratio ?? 0) > 1.5,
    rs_blue_dot:  false,
  } : null)

  // Replace the old `if (!setup)` block entirely with this:
  if (!displaySetup) {
    if (analysisLoading) {
      return (
        <div className="w-[320px] flex-shrink-0 bg-t-card border border-t-cardBorder rounded-xl flex flex-col p-4 gap-3">
          <div className="shimmer-row" style={{ height: 64 }} />
          <div className="shimmer-row" style={{ height: 40 }} />
          <div className="shimmer-row" style={{ height: 80 }} />
        </div>
      )
    }
    return (
      <div className="w-[320px] flex-shrink-0 bg-t-card border border-t-cardBorder rounded-xl flex flex-col items-center justify-center gap-2 text-t-muted p-5">
        <Target size={28} strokeWidth={1} color="var(--border-light)" />
        <span style={{ fontSize: 11, textAlign: 'center', lineHeight: 1.5 }}>
          Select a stock to view signals
        </span>
      </div>
    )
  }

  // All references below use `displaySetup` (not `setup`)
  const livePrice    = livePrices?.[displaySetup.ticker]
  const dist         = (livePrice && displaySetup.entry > 0)
    ? ((livePrice - displaySetup.entry) / displaySetup.entry) * 100
    : null
  const isAboveEntry = dist !== null && dist >= 0

  const risk = displaySetup.entry > 0 && displaySetup.stop_loss > 0
    ? ((displaySetup.entry - displaySetup.stop_loss) / displaySetup.entry * 100).toFixed(1)
    : null

  const rr = displaySetup.rr ? Number(displaySetup.rr).toFixed(2) : null

  return (
    <div className="w-[320px] flex-shrink-0 bg-t-card border border-t-cardBorder rounded-xl flex flex-col overflow-y-auto overflow-x-hidden">
      {/* Header */}
      <div style={{
        padding: '14px 16px',
        borderBottom: '1px solid var(--card-border)',
        background: 'rgba(255,255,255,0.02)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
          <div>
            <div style={{
              fontFamily: '"Barlow Condensed", sans-serif',
              fontSize: 24, fontWeight: 700, lineHeight: 1,
              color: 'var(--text)', letterSpacing: '-0.01em',
            }}>
              {displaySetup.ticker}
            </div>
            <div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 3, fontFamily: '"IBM Plex Mono", monospace' }}>
              {displaySetup.setup_type ?? '—'}
            </div>
          </div>
          <ScoreBadge score={displaySetup.setup_score} />
        </div>

        {livePrice && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{
              fontFamily: '"IBM Plex Mono", monospace', fontSize: 16, fontWeight: 700,
              color: isAboveEntry ? 'var(--go)' : dist !== null && dist > -3 ? 'var(--accent)' : 'var(--text)',
            }}>
              ${livePrice.toFixed(2)}
            </span>
            {dist !== null && (
              <span style={{
                fontSize: 10, fontFamily: '"IBM Plex Mono", monospace', fontWeight: 700,
                color: isAboveEntry ? 'var(--go)' : 'var(--muted)',
              }}>
                {isAboveEntry ? `▲${Math.abs(dist).toFixed(1)}%` : `${Math.abs(dist).toFixed(1)}%↓`}
              </span>
            )}
          </div>
        )}
      </div>

      {/* Signals */}
      <div style={{ padding: '10px 16px', borderBottom: '1px solid var(--card-border)' }}>
        <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.1em', color: 'var(--muted)', marginBottom: 6 }}>SIGNALS</div>
        <SignalRow
          label="Relative Strength"
          value={displaySetup.rs_score != null ? `RS${displaySetup.rs_score >= 0 ? '+' : ''}${Math.round(displaySetup.rs_score * 100)}` : '—'}
          color={displaySetup.rs_score > 0.05 ? 'var(--go)' : 'var(--muted)'}
        />
        <SignalRow
          label="Volume Surge"
          value={displaySetup.is_vol_surge ? 'YES' : displaySetup.vol_ratio ? `×${Number(displaySetup.vol_ratio).toFixed(1)}` : '—'}
          color={displaySetup.is_vol_surge ? 'var(--go)' : undefined}
        />
        <SignalRow
          label="RS Blue Dot"
          value={displaySetup.rs_blue_dot ? 'YES — 52W HIGH' : 'NO'}
          color={displaySetup.rs_blue_dot ? 'var(--blue)' : 'var(--muted)'}
        />
        <SignalRow
          label="Distance to Entry"
          value={dist !== null ? `${Math.abs(dist).toFixed(1)}%${isAboveEntry ? ' above' : ' below'}` : '—'}
          color={dist !== null && dist > -3 && !isAboveEntry ? 'var(--accent)' : undefined}
        />
      </div>

      {/* Trade Plan */}
      <div style={{ padding: '10px 16px', borderBottom: '1px solid var(--card-border)' }}>
        <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.1em', color: 'var(--muted)', marginBottom: 6 }}>TRADE PLAN</div>
        {[
          { label: 'Entry',  value: displaySetup.entry       ? `$${displaySetup.entry.toFixed(2)}`       : '—', color: 'var(--text)'   },
          { label: 'Stop',   value: displaySetup.stop_loss   ? `$${displaySetup.stop_loss.toFixed(2)}`   : '—', color: 'var(--halt)'   },
          { label: 'Target', value: displaySetup.take_profit ? `$${displaySetup.take_profit.toFixed(2)}` : '—', color: 'var(--go)'     },
          { label: 'Risk',   value: risk ? `${risk}%` : '—',                                                     color: 'var(--accent)' },
          { label: 'R:R',    value: rr ?? '—',
            color: rr && Number(rr) >= 2 ? 'var(--go)' : 'var(--text)' },
        ].map(({ label, value, color }) => (
          <div key={label} style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            padding: '5px 0', borderBottom: '1px solid rgba(26,37,53,0.4)',
          }}>
            <span style={{ fontSize: 11, color: 'var(--muted)' }}>{label}</span>
            <span style={{ fontSize: 11, fontFamily: '"IBM Plex Mono", monospace', fontWeight: 700, color }}>
              {value}
            </span>
          </div>
        ))}
      </div>

      {/* AI Verdict — amber values updated to cyan */}
      {analysis && (
        <div style={{ padding: '10px 16px', borderTop: '1px solid var(--card-border)' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
            <span style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.1em', color: 'var(--muted)' }}>AI VERDICT</span>
            <span style={{
              padding: '3px 8px', borderRadius: 5,
              fontSize: 9, fontWeight: 700, letterSpacing: '0.06em',
              fontFamily: '"IBM Plex Mono", monospace',
              background: analysis.verdict_color === 'go'     ? 'rgba(0,200,122,0.15)'
                        : analysis.verdict_color === 'accent' ? 'rgba(80,216,240,0.15)'
                        : 'rgba(255,45,85,0.12)',
              color: analysis.verdict_color === 'go'     ? 'var(--go)'
                   : analysis.verdict_color === 'accent' ? 'var(--accent)'
                   : 'var(--halt)',
              border: `1px solid ${
                analysis.verdict_color === 'go'     ? 'rgba(0,200,122,0.35)'
              : analysis.verdict_color === 'accent' ? 'rgba(80,216,240,0.35)'
              : 'rgba(255,45,85,0.3)'}`,
            }}>
              {analysis.verdict}
            </span>
          </div>
          <p style={{ fontSize: 10, lineHeight: 1.6, color: 'var(--muted)', fontFamily: '"Inter", sans-serif', margin: 0 }}>
            {analysis.narrative}
          </p>
          <div style={{ marginTop: 6, fontSize: 9, color: 'var(--muted)', fontFamily: '"IBM Plex Mono", monospace' }}>
            Setup Quality: <span style={{ color: 'var(--text)' }}>{analysis.quality}</span>
          </div>
        </div>
      )}

      {analysisLoading && (
        <div style={{ padding: '10px 16px', borderTop: '1px solid var(--card-border)' }}>
          <div className="shimmer-row" style={{ height: 50 }} />
        </div>
      )}

      {/* V5 Analysis section — hidden while loading to prevent stale-data bleed */}
      {!analysisLoading && analysis && <V5AnalysisSection analysis={analysis} />}

      {/* TradingView link — amber values updated to cyan */}
      <div style={{ padding: '10px 16px', borderTop: '1px solid var(--card-border)' }}>
        <a
          href={`https://www.tradingview.com/chart/?symbol=${displaySetup.ticker}&interval=D`}
          target="_blank"
          rel="noopener noreferrer"
          style={{
            display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6,
            padding: '7px', borderRadius: 8,
            background: 'rgba(80,216,240,0.08)', border: '1px solid rgba(80,216,240,0.2)',
            color: 'var(--accent)', fontSize: 10, fontWeight: 700,
            fontFamily: '"IBM Plex Mono", monospace', textDecoration: 'none',
            letterSpacing: '0.06em',
          }}
        >
          OPEN IN TRADINGVIEW <ChevronRight size={10} />
        </a>
      </div>
    </div>
  )
}
```

- [ ] **Step 3: Verify no amber values remain**

```bash
grep -n "245,166,35" /c/Users/1/OneDrive/Desktop/claudeSkillsTest/swing-trading-dashboard/frontend/src/components/StockIntelPanel.jsx
```

Expected: no output.

- [ ] **Step 4: Build check**

```bash
cd /c/Users/1/OneDrive/Desktop/claudeSkillsTest/swing-trading-dashboard/frontend && npx vite build 2>&1 | tail -5
```

Expected: `✓ built in` with no errors.

- [ ] **Step 5: Commit**

```bash
cd /c/Users/1/OneDrive/Desktop/claudeSkillsTest/swing-trading-dashboard
git add frontend/src/components/StockIntelPanel.jsx
git commit -m "feat: signal panel renders from analysis when ticker not in scan results"
```

---

## Task 2: Update App.jsx

**Files:**
- Modify: `frontend/src/App.jsx`

Two independent edits to this file.

- [ ] **Step 1: Read the file**

Read `frontend/src/App.jsx` around lines 314–382 to confirm the exact current text before editing.

- [ ] **Step 2: Fix stale-analysis guard**

Find (around line 374–379):

```jsx
                <StockIntelPanel
                    setup={selectedSetup}
                    livePrices={livePrices}
                    analysis={analysis}
                    analysisLoading={analysisLoading}
                  />
```

Replace with:

```jsx
                <StockIntelPanel
                    setup={selectedSetup}
                    livePrices={livePrices}
                    analysis={analysis?.ticker === selectedTicker ? analysis : null}
                    analysisLoading={analysisLoading}
                  />
```

This prevents a slow fetch from a previously clicked ticker from populating the panel with stale data after the user has moved on.

- [ ] **Step 3: Fix search switchTab**

Find (around line 318):

```jsx
          onSearchTicker={(t) => handleTickerClick(t, false)}
```

Replace with:

```jsx
          onSearchTicker={(t) => handleTickerClick(t, true)}
```

This ensures searching any ticker always navigates to the scanner page where StockIntelPanel lives.

- [ ] **Step 4: Build check**

```bash
cd /c/Users/1/OneDrive/Desktop/claudeSkillsTest/swing-trading-dashboard/frontend && npx vite build 2>&1 | tail -5
```

Expected: `✓ built in` with no errors.

- [ ] **Step 5: Commit**

```bash
cd /c/Users/1/OneDrive/Desktop/claudeSkillsTest/swing-trading-dashboard
git add frontend/src/App.jsx
git commit -m "feat: signal panel — stale-analysis guard + search navigates to scanner"
```

---

## Post-implementation deploy

```bash
git push origin main

# On VPS:
ssh root@89.167.25.25
cd /opt/dashboard && git pull origin main
cd swing-trading-dashboard/frontend && npm run build
systemctl restart dashboard.service
```

## Visual verification checklist

- [ ] Click a WL item → navigates to scanner → signal panel shows full data (not placeholder)
- [ ] Search a ticker → navigates to scanner → signal panel shows full data
- [ ] Click scanner row (ticker in scan) → signal panel still works as before
- [ ] No ticker selected → placeholder shows "Select a stock to view signals"
- [ ] Click a ticker, immediately click another → panel shows correct (second) ticker's data
- [ ] No amber/yellow in TV button or verdict badge — all cyan
