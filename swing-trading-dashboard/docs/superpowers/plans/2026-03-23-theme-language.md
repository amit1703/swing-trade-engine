# Theme & Language Settings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Dark/Light mode toggle and Hebrew/English language toggle to the app, accessible from the Settings page.

**Architecture:** New `AppSettingsContext` exposes `theme`, `lang`, `setTheme`, `setLang`, and `tr(key)` to all components via React context; dark/light toggling via `.light` CSS class on `<html>`; translations in a single `translations.js` file with ~250 keys across 10 namespaces.

**Tech Stack:** React 18 context + localStorage, Tailwind CSS variable references, shadcn Switch component, CSS `.light` override block.

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `src/i18n/translations.js` | Create | All UI strings in English + Hebrew |
| `src/contexts/AppSettingsContext.jsx` | Create | React context: theme/lang state + `tr()` |
| `src/main.jsx` | Modify | Wrap `<App>` with `<AppSettingsProvider>` |
| `tailwind.config.js` | Modify | Convert `t-*` tokens from static hex to `var(--x)` |
| `src/index.css` | Modify | Add `.light` CSS variable override block |
| `src/components/Settings.jsx` | Create | Settings page (theme + language cards) |
| `src/App.jsx` | Modify | Import Settings.jsx; replace settings stub; translate "more" menu labels |
| `src/components/Sidebar.jsx` | Modify | Translate nav labels |
| `src/components/TopBar.jsx` | Modify | Translate page titles, scan button, search placeholder |
| `src/components/BottomTabBar.jsx` | Modify | Translate mobile tab labels |
| `src/components/Header.jsx` | Modify | Translate regime banner labels |
| `src/components/ScannerTable.jsx` | Modify | Translate column headers, empty state |
| `src/components/SetupTable.jsx` | Modify | Translate column headers, empty state |
| `src/components/StockIntelPanel.jsx` | Modify | Translate section labels, verdict badges, buttons |
| `src/components/PortfolioTab.jsx` | Modify | Translate column headers, status labels |
| `src/components/WatchlistPanel.jsx` | Modify | Translate labels, empty state |
| `src/components/DiagnosticsTab.jsx` | Modify | Translate section + stat card labels |
| `src/components/StatCards.jsx` | Modify | Translate card labels |
| `src/components/MarketOverview.jsx` | Modify | Translate labels |
| `src/components/ScannerFilters.jsx` | Modify | Translate filter labels |
| `src/components/MobileSignalSheet.jsx` | Modify | Translate mobile sheet strings |

---

## Task 1: Create `src/i18n/translations.js`

**Files:**
- Create: `src/i18n/translations.js`

- [ ] **Step 1: Create the translations file**

```js
// src/i18n/translations.js
// Single source of truth for all UI strings.
// Named 'tr' throughout the app (never 't') to avoid collision with loop variable t.

export const translations = {
  en: {
    // ── Navigation ─────────────────────────────────────
    'nav.scanner':     'Scanner',
    'nav.watchlist':   'Watchlist',
    'nav.favorites':   'Favorites',
    'nav.portfolio':   'Portfolio',
    'nav.analytics':   'Analytics',
    'nav.diagnostics': 'Diagnostics',
    'nav.settings':    'Settings',
    'nav.more':        'More',
    // Mobile tab bar (abbreviated)
    'nav.tab.scanner':   'Scanner',
    'nav.tab.watchlist': 'WL',
    'nav.tab.favorites': 'Favs',
    'nav.tab.portfolio': 'Port',
    'nav.tab.more':      'More',

    // ── Regime / Status ────────────────────────────────
    'status.aggressive': 'AGGRESSIVE',
    'status.selective':  'SELECTIVE',
    'status.defensive':  'DEFENSIVE',
    'regime.score':      'Regime Score',
    'regime.market':     'Market',
    'regime.bullish':    'Bullish',
    'regime.bearish':    'Bearish',
    'regime.neutral':    'Neutral',
    'regime.spyClose':   'SPY Close',
    'regime.ema20':      'EMA20',
    'regime.sma50':      'SMA50',
    'regime.sma200':     'SMA200',
    'regime.breadth':    'Breadth',
    'regime.vix':        'VIX',

    // ── Table column headers ───────────────────────────
    'table.ticker':   'Ticker',
    'table.setup':    'Setup',
    'table.score':    'Score',
    'table.entry':    'Entry',
    'table.stop':     'Stop',
    'table.target':   'Target',
    'table.rr':       'R:R',
    'table.rs':       'RS',
    'table.sector':   'Sector',
    'table.vol':      'Volume',
    'table.date':     'Date',
    'table.pnl':      'P&L',
    'table.status':   'Status',
    'table.shares':   'Shares',
    'table.cost':     'Cost',
    'table.value':    'Value',
    'table.return':   'Return',
    'table.signal':   'Signal',
    'table.risk':     'Risk',
    'table.days':     'Days',

    // ── Setup type names ───────────────────────────────
    'setup.vcp':         'VCP',
    'setup.pullback':    'Pullback',
    'setup.watchlist':   'Watchlist',
    'setup.base':        'Base',
    'setup.resBreakout': 'Res. Breakout',
    'setup.htf':         'HTF',
    'setup.lce':         'LCE',
    'setup.options':     'Options',

    // ── Buttons ────────────────────────────────────────
    'btn.runScan':      'Run Scan',
    'btn.scanning':     'Scanning...',
    'btn.save':         'Save',
    'btn.cancel':       'Cancel',
    'btn.close':        'Close',
    'btn.add':          'Add',
    'btn.remove':       'Remove',
    'btn.refresh':      'Refresh',
    'btn.export':       'Export',
    'btn.runBacktest':  'Run Backtest',
    'btn.viewChart':    'View Chart',
    'btn.analyze':      'Analyze',
    'btn.loadMore':     'Load More',

    // ── Settings page ──────────────────────────────────
    'settings.title':    'Settings',
    'settings.theme':    'Theme',
    'settings.themeDesc':'Choose between dark and light mode',
    'settings.dark':     'Dark',
    'settings.light':    'Light',
    'settings.language': 'Language',
    'settings.langDesc': 'Choose display language',
    'settings.english':  'EN',
    'settings.hebrew':   'עברית',

    // ── Verdict labels ─────────────────────────────────
    'verdict.strong':   'STRONG',
    'verdict.caution':  'CAUTION',
    'verdict.avoid':    'AVOID',
    'verdict.neutral':  'NEUTRAL',
    'verdict.bullish':  'BULLISH',
    'verdict.bearish':  'BEARISH',
    'verdict.watch':    'WATCH',

    // ── Filter bar ─────────────────────────────────────
    'filter.all':        'All',
    'filter.vcp':        'VCP',
    'filter.pullback':   'Pullback',
    'filter.base':       'Base',
    'filter.resBreakout':'Res. BRK',
    'filter.htf':        'HTF',
    'filter.lce':        'LCE',
    'filter.options':    'Options',
    'filter.minScore':   'Min Score',
    'filter.sector':     'Sector',
    'filter.regime':     'Regime',
    'filter.sortBy':     'Sort By',
    'filter.rsRank':     'RS Rank',
    'filter.hotSector':  'Hot Sector',

    // ── Empty states & messages ────────────────────────
    'msg.noResults':        'No setups found',
    'msg.noResultsHint':    'Try running a new scan',
    'msg.loading':          'Loading...',
    'msg.noTrades':         'No trades yet',
    'msg.noWatchlist':      'Watchlist is empty',
    'msg.noWatchlistHint':  'Add tickers from the scanner',
    'msg.noFavorites':      'No favorites yet',
    'msg.selectTicker':     'Select a ticker to view analysis',
    'msg.analyzing':        'Analyzing...',
    'msg.scanComplete':     'Scan complete',
    'msg.scanRunning':      'Scan running...',
    'msg.error':            'Something went wrong',
    'msg.noBacktest':       'No backtest data. Run a backtest first.',
    'msg.backtestRunning':  'Backtest running...',

    // ── Scan status ────────────────────────────────────
    'scan.idle':        'Ready',
    'scan.running':     'Scanning...',
    'scan.complete':    'Done',
    'scan.progress':    'tickers processed',
    'scan.lastRun':     'Last scan',

    // ── Portfolio ──────────────────────────────────────
    'portfolio.hold':        'HOLD',
    'portfolio.caution':     'CAUTION',
    'portfolio.exit':        'EXIT',
    'portfolio.openTrades':  'Open Trades',
    'portfolio.closedTrades':'Closed Trades',
    'portfolio.totalPnl':    'Total P&L',
    'portfolio.winRate':     'Win Rate',
    'portfolio.addTrade':    'Add Trade',
    'portfolio.trailStop':   'Trail Stop',
    'portfolio.entryPrice':  'Entry',
    'portfolio.exitPrice':   'Exit',
    'portfolio.notes':       'Notes',

    // ── Diagnostics ────────────────────────────────────
    'diag.title':         'Diagnostics',
    'diag.liveSource':    'Live Trades',
    'diag.backtestSource':'Backtest',
    'diag.winRate':       'Win Rate',
    'diag.avgR':          'Avg R',
    'diag.profitFactor':  'Profit Factor',
    'diag.maxDrawdown':   'Max Drawdown',
    'diag.totalTrades':   'Total Trades',
    'diag.setupBreakdown':'Setup Breakdown',
    'diag.regimePerf':    'Regime Performance',
    'diag.tickerDist':    'Ticker Distribution',

    // ── Market overview / Stat cards ───────────────────
    'market.overview':  'Market Overview',
    'market.spy':       'SPY',
    'market.spyTrend':  'SPY Trend',
    'market.breadth':   'Market Breadth',
    'market.topSectors':'Top Sectors',
    'market.regime':    'Regime',

    // ── Stock Intel Panel ──────────────────────────────
    'intel.tradePlan':   'Trade Plan',
    'intel.analysis':    'Analysis',
    'intel.signals':     'Signals',
    'intel.entryZone':   'Entry Zone',
    'intel.stopLoss':    'Stop Loss',
    'intel.target':      'Target',
    'intel.risk':        'Risk',
    'intel.rr':          'R:R',
    'intel.srZones':     'S/R Zones',
    'intel.support':     'Support',
    'intel.resistance':  'Resistance',
    'intel.rsLine':      'RS Line',
    'intel.blueDot':     'Blue Dot',
    'intel.volume':      'Volume',
    'intel.atr':         'ATR',

    // ── Search ─────────────────────────────────────────
    'search.placeholder': 'Search ticker...',
    'search.noResults':   'No results for',
  },

  he: {
    // ── Navigation ─────────────────────────────────────
    'nav.scanner':     'סורק',
    'nav.watchlist':   'רשימת מעקב',
    'nav.favorites':   'מועדפים',
    'nav.portfolio':   'תיק השקעות',
    'nav.analytics':   'ניתוח',
    'nav.diagnostics': 'אבחון',
    'nav.settings':    'הגדרות',
    'nav.more':        'עוד',
    // Mobile tab bar (abbreviated)
    'nav.tab.scanner':   'סורק',
    'nav.tab.watchlist': 'רש"מ',
    'nav.tab.favorites': 'מועד\'',
    'nav.tab.portfolio': 'תיק',
    'nav.tab.more':      'עוד',

    // ── Regime / Status ────────────────────────────────
    'status.aggressive': 'אגרסיבי',
    'status.selective':  'סלקטיבי',
    'status.defensive':  'דפנסיבי',
    'regime.score':      'ציון שוק',
    'regime.market':     'שוק',
    'regime.bullish':    'שורי',
    'regime.bearish':    'דובי',
    'regime.neutral':    'ניטרלי',
    'regime.spyClose':   'SPY סגירה',
    'regime.ema20':      'EMA20',
    'regime.sma50':      'SMA50',
    'regime.sma200':     'SMA200',
    'regime.breadth':    'רוחב שוק',
    'regime.vix':        'VIX',

    // ── Table column headers ───────────────────────────
    'table.ticker':   'סימול',
    'table.setup':    'סטאפ',
    'table.score':    'ציון',
    'table.entry':    'כניסה',
    'table.stop':     'סטופ',
    'table.target':   'יעד',
    'table.rr':       'R:R',
    'table.rs':       'RS',
    'table.sector':   'סקטור',
    'table.vol':      'נפח',
    'table.date':     'תאריך',
    'table.pnl':      'רווח/הפסד',
    'table.status':   'סטטוס',
    'table.shares':   'מניות',
    'table.cost':     'עלות',
    'table.value':    'שווי',
    'table.return':   'תשואה',
    'table.signal':   'איתות',
    'table.risk':     'סיכון',
    'table.days':     'ימים',

    // ── Setup type names ───────────────────────────────
    'setup.vcp':         'VCP',
    'setup.pullback':    'פולבק',
    'setup.watchlist':   'מעקב',
    'setup.base':        'בסיס',
    'setup.resBreakout': 'פריצת התנגדות',
    'setup.htf':         'HTF',
    'setup.lce':         'LCE',
    'setup.options':     'אופציות',

    // ── Buttons ────────────────────────────────────────
    'btn.runScan':      'הרץ סריקה',
    'btn.scanning':     'סורק...',
    'btn.save':         'שמור',
    'btn.cancel':       'ביטול',
    'btn.close':        'סגור',
    'btn.add':          'הוסף',
    'btn.remove':       'הסר',
    'btn.refresh':      'רענן',
    'btn.export':       'ייצא',
    'btn.runBacktest':  'הרץ בקטסט',
    'btn.viewChart':    'הצג גרף',
    'btn.analyze':      'נתח',
    'btn.loadMore':     'טען עוד',

    // ── Settings page ──────────────────────────────────
    'settings.title':    'הגדרות',
    'settings.theme':    'ערכת נושא',
    'settings.themeDesc':'בחר בין מצב כהה ובהיר',
    'settings.dark':     'כהה',
    'settings.light':    'בהיר',
    'settings.language': 'שפה',
    'settings.langDesc': 'בחר שפת תצוגה',
    'settings.english':  'EN',
    'settings.hebrew':   'עברית',

    // ── Verdict labels ─────────────────────────────────
    'verdict.strong':   'חזק',
    'verdict.caution':  'זהירות',
    'verdict.avoid':    'הימנע',
    'verdict.neutral':  'ניטרלי',
    'verdict.bullish':  'שורי',
    'verdict.bearish':  'דובי',
    'verdict.watch':    'עקוב',

    // ── Filter bar ─────────────────────────────────────
    'filter.all':        'הכל',
    'filter.vcp':        'VCP',
    'filter.pullback':   'פולבק',
    'filter.base':       'בסיס',
    'filter.resBreakout':'פריצה',
    'filter.htf':        'HTF',
    'filter.lce':        'LCE',
    'filter.options':    'אופציות',
    'filter.minScore':   'ציון מינימום',
    'filter.sector':     'סקטור',
    'filter.regime':     'רג׳ים',
    'filter.sortBy':     'מיין לפי',
    'filter.rsRank':     'דירוג RS',
    'filter.hotSector':  'סקטור חם',

    // ── Empty states & messages ────────────────────────
    'msg.noResults':        'לא נמצאו סטאפים',
    'msg.noResultsHint':    'נסה להריץ סריקה חדשה',
    'msg.loading':          'טוען...',
    'msg.noTrades':         'אין עסקאות עדיין',
    'msg.noWatchlist':      'רשימת המעקב ריקה',
    'msg.noWatchlistHint':  'הוסף מניות מהסורק',
    'msg.noFavorites':      'אין מועדפים עדיין',
    'msg.selectTicker':     'בחר מנייה לניתוח',
    'msg.analyzing':        'מנתח...',
    'msg.scanComplete':     'הסריקה הושלמה',
    'msg.scanRunning':      'סריקה בריצה...',
    'msg.error':            'משהו השתבש',
    'msg.noBacktest':       'אין נתוני בקטסט. הרץ בקטסט תחילה.',
    'msg.backtestRunning':  'בקטסט בריצה...',

    // ── Scan status ────────────────────────────────────
    'scan.idle':        'מוכן',
    'scan.running':     'סורק...',
    'scan.complete':    'הושלם',
    'scan.progress':    'מניות עובדו',
    'scan.lastRun':     'סריקה אחרונה',

    // ── Portfolio ──────────────────────────────────────
    'portfolio.hold':        'החזק',
    'portfolio.caution':     'זהירות',
    'portfolio.exit':        'צא',
    'portfolio.openTrades':  'עסקאות פתוחות',
    'portfolio.closedTrades':'עסקאות סגורות',
    'portfolio.totalPnl':    'רווח/הפסד כולל',
    'portfolio.winRate':     'אחוז הצלחה',
    'portfolio.addTrade':    'הוסף עסקה',
    'portfolio.trailStop':   'סטופ נגרר',
    'portfolio.entryPrice':  'כניסה',
    'portfolio.exitPrice':   'יציאה',
    'portfolio.notes':       'הערות',

    // ── Diagnostics ────────────────────────────────────
    'diag.title':         'אבחון',
    'diag.liveSource':    'עסקאות חיות',
    'diag.backtestSource':'בקטסט',
    'diag.winRate':       'אחוז הצלחה',
    'diag.avgR':          'R ממוצע',
    'diag.profitFactor':  'פקטור רווח',
    'diag.maxDrawdown':   'ירידה מקסימלית',
    'diag.totalTrades':   'סה"כ עסקאות',
    'diag.setupBreakdown':'פירוט סטאפים',
    'diag.regimePerf':    'ביצועי רג׳ים',
    'diag.tickerDist':    'פיזור מניות',

    // ── Market overview / Stat cards ───────────────────
    'market.overview':  'סקירת שוק',
    'market.spy':       'SPY',
    'market.spyTrend':  'מגמת SPY',
    'market.breadth':   'רוחב שוק',
    'market.topSectors':'סקטורים מובילים',
    'market.regime':    'רג׳ים',

    // ── Stock Intel Panel ──────────────────────────────
    'intel.tradePlan':   'תוכנית עסקה',
    'intel.analysis':    'ניתוח',
    'intel.signals':     'איתותים',
    'intel.entryZone':   'אזור כניסה',
    'intel.stopLoss':    'סטופ לוס',
    'intel.target':      'יעד',
    'intel.risk':        'סיכון',
    'intel.rr':          'R:R',
    'intel.srZones':     'אזורי S/R',
    'intel.support':     'תמיכה',
    'intel.resistance':  'התנגדות',
    'intel.rsLine':      'קו RS',
    'intel.blueDot':     'נקודה כחולה',
    'intel.volume':      'נפח',
    'intel.atr':         'ATR',

    // ── Search ─────────────────────────────────────────
    'search.placeholder': 'חפש מנייה...',
    'search.noResults':   'לא נמצאו תוצאות עבור',
  },
}

/**
 * tr(lang, key) — standalone helper (used outside React context).
 * Named 'tr' to avoid collision with common loop variable 't'.
 */
export function tr(lang, key) {
  return translations[lang]?.[key] ?? translations['en'][key] ?? key
}
```

- [ ] **Step 2: Verify build passes**

```bash
cd swing-trading-dashboard/frontend && npm run build 2>&1 | tail -5
```
Expected: build succeeds (or only existing errors, not new ones from this file).

- [ ] **Step 3: Commit**

```bash
git add swing-trading-dashboard/frontend/src/i18n/translations.js
git commit -m "feat: add i18n translations file (en + he, ~250 keys)"
```

---

## Task 2: Create `src/contexts/AppSettingsContext.jsx`

**Files:**
- Create: `src/contexts/AppSettingsContext.jsx`

- [ ] **Step 1: Create the context file**

```jsx
// src/contexts/AppSettingsContext.jsx
import { createContext, useContext, useState, useEffect } from 'react'
import { translations } from '../i18n/translations'

export const AppSettingsContext = createContext(null)

export function AppSettingsProvider({ children }) {
  const [theme, setThemeState] = useState(
    () => localStorage.getItem('theme') || 'dark'
  )
  const [lang, setLangState] = useState(
    () => localStorage.getItem('lang') || 'en'
  )

  const setTheme = (val) => {
    setThemeState(val)
    localStorage.setItem('theme', val)
  }

  const setLang = (val) => {
    setLangState(val)
    localStorage.setItem('lang', val)
  }

  // Apply theme class and lang attribute to <html>
  useEffect(() => {
    const html = document.documentElement
    html.classList.toggle('dark', theme === 'dark')
    html.classList.toggle('light', theme === 'light')
    html.setAttribute('lang', lang)
  }, [theme, lang])

  // tr() — named 'tr' (not 't') to avoid collision with common loop variable t
  const tr = (key) =>
    translations[lang]?.[key] ?? translations['en'][key] ?? key

  return (
    <AppSettingsContext.Provider value={{ theme, lang, setTheme, setLang, tr }}>
      {children}
    </AppSettingsContext.Provider>
  )
}

export const useAppSettings = () => useContext(AppSettingsContext)
```

- [ ] **Step 2: Verify build passes**

```bash
cd swing-trading-dashboard/frontend && npm run build 2>&1 | tail -5
```

- [ ] **Step 3: Commit**

```bash
git add swing-trading-dashboard/frontend/src/contexts/AppSettingsContext.jsx
git commit -m "feat: add AppSettingsContext (theme + lang state, tr() helper)"
```

---

## Task 3: Update `tailwind.config.js` — convert `t-*` tokens to CSS vars

**Files:**
- Modify: `tailwind.config.js`

**Why:** The current `t-*` tokens are static hex values resolved at build time. They ignore `.light` CSS variable overrides entirely. Converting them to `var(--x)` references makes them respond dynamically to the `.light` class.

**Scope:** Only tokens that have a matching CSS variable in `:root` / `.light`. Tokens without CSS var equivalents (`accentDim`, `goDim`, `haltDim`, `blueDim`, `pink`) stay as static hex.

- [ ] **Step 1: Replace the `t` color object in `tailwind.config.js`**

Replace this block:
```js
        t: {
          bg:          '#000000',
          surface:     '#0d0d0d',
          panel:       '#111111',
          card:        '#131313',
          cardBorder:  '#222222',
          border:      '#1e1e1e',
          borderLight: '#2a2a2a',
          text:        '#e0e0e0',
          muted:       '#555555',
          accent:      '#50d8f0',
          accentDim:   '#0d4050',
          go:          '#00c87a',
          goDim:       '#003d25',
          halt:        '#ff2d55',
          haltDim:     '#4a0015',
          blue:        '#4a9eff',
          blueDim:     '#0a1f3a',
          purple:      '#9B6EFF',
          pink:        '#FF6EC7',
        },
```

With this block:
```js
        t: {
          bg:          'var(--bg)',
          surface:     'var(--surface)',
          panel:       'var(--panel)',
          card:        'var(--card)',
          cardBorder:  'var(--card-border)',
          border:      'var(--border)',
          borderLight: 'var(--border-light)',
          text:        'var(--text)',
          muted:       'var(--muted)',
          accent:      'var(--accent)',
          accentDim:   '#0d4050',   // no CSS var equivalent — stays static
          go:          'var(--go)',
          goDim:       '#003d25',   // no CSS var equivalent — stays static
          halt:        'var(--halt)',
          haltDim:     '#4a0015',   // no CSS var equivalent — stays static
          blue:        'var(--blue)',
          blueDim:     '#0a1f3a',   // no CSS var equivalent — stays static
          purple:      'var(--purple)',
          pink:        '#FF6EC7',   // no CSS var equivalent — stays static
        },
```

- [ ] **Step 2: Verify build passes**

```bash
cd swing-trading-dashboard/frontend && npm run build 2>&1 | tail -5
```

- [ ] **Step 3: Commit**

```bash
git add swing-trading-dashboard/frontend/tailwind.config.js
git commit -m "feat: convert t-* tailwind tokens to CSS var() references for light mode support"
```

---

## Task 4: Add `.light` CSS block to `src/index.css`

**Files:**
- Modify: `src/index.css`

- [ ] **Step 1: Insert `.light` block after the closing `}` of `:root` (after line 44)**

Add this block immediately after the `:root { ... }` closing brace:

```css
/* ── Light mode overrides ─────────────────────────── */
.light {
  --bg:           #ffffff;
  --surface:      #f8fafc;
  --panel:        #f1f5f9;
  --card:         #ffffff;
  --card-border:  #e2e8f0;
  --border:       #e2e8f0;
  --border-light: #f0f4f8;
  --text:         #0f172a;
  --muted:        #64748b;
  --accent:       #0ea5e9;
  --go:           #16a34a;
  --halt:         #dc2626;
  --blue:         #0ea5e9;
  --purple:       #8b5cf6;
  --radius-card:  12px;
  --shadow-card:  0 1px 3px rgba(0,0,0,0.08);

  /* shadcn/ui token overrides for light mode */
  --background:          #ffffff;
  --foreground:          #0f172a;
  --card-foreground:     #0f172a;
  --primary:             #0ea5e9;
  --primary-foreground:  #ffffff;
  --secondary:           #f1f5f9;
  --secondary-foreground:#0f172a;
  --muted-foreground:    #64748b;
  --accent-foreground:   #0f172a;
  --destructive:         #dc2626;
  --popover:             #ffffff;
  --popover-foreground:  #0f172a;
  --border:              #e2e8f0;
  --input:               #e2e8f0;
  --ring:                #0ea5e9;
}
```

- [ ] **Step 2: Verify build passes**

```bash
cd swing-trading-dashboard/frontend && npm run build 2>&1 | tail -5
```

- [ ] **Step 3: Manual smoke test (optional)**
Open the app in the browser, open DevTools console, run:
```js
document.documentElement.classList.add('light')
```
Verify the page switches to white/light colors. Remove with:
```js
document.documentElement.classList.remove('light')
```

- [ ] **Step 4: Commit**

```bash
git add swing-trading-dashboard/frontend/src/index.css
git commit -m "feat: add .light CSS variable override block for light mode"
```

---

## Task 5: Wrap `main.jsx` with `AppSettingsProvider`

**Files:**
- Modify: `src/main.jsx`

- [ ] **Step 1: Update `main.jsx`**

Replace the entire file content with:

```jsx
import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import { AppSettingsProvider } from './contexts/AppSettingsContext.jsx'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <AppSettingsProvider>
      <App />
    </AppSettingsProvider>
  </React.StrictMode>
)
```

- [ ] **Step 2: Verify build passes**

```bash
cd swing-trading-dashboard/frontend && npm run build 2>&1 | tail -5
```

- [ ] **Step 3: Commit**

```bash
git add swing-trading-dashboard/frontend/src/main.jsx
git commit -m "feat: wrap App with AppSettingsProvider"
```

---

## Task 6: Install shadcn Switch + create `src/components/Settings.jsx`

**Files:**
- Create: `src/components/Settings.jsx`
- Auto-generated: `src/components/ui/switch.jsx` (via shadcn CLI)

- [ ] **Step 1: Install the shadcn Switch component**

```bash
cd swing-trading-dashboard/frontend && npx shadcn@latest add switch
```
Expected: creates `src/components/ui/switch.jsx`.

- [ ] **Step 2: Create `Settings.jsx`**

```jsx
// src/components/Settings.jsx
import { Moon, Sun } from 'lucide-react'
import { Switch } from './ui/switch'
import { useAppSettings } from '../contexts/AppSettingsContext'

export default function Settings() {
  const { theme, lang, setTheme, setLang, tr } = useAppSettings()

  return (
    <div style={{ flex: 1, overflow: 'auto', padding: '24px 20px', maxWidth: 480 }}>

      {/* Page header */}
      <h1 className="font-sans text-xl font-semibold text-t-text mb-6">
        {tr('settings.title')}
      </h1>

      {/* Theme card */}
      <div className="card p-4 mb-4">
        <div className="flex items-center justify-between">
          <div>
            <p className="font-sans text-sm font-semibold text-t-text">
              {tr('settings.theme')}
            </p>
            <p className="font-sans text-xs text-t-muted mt-0.5">
              {tr('settings.themeDesc')}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Moon size={15} className="text-t-muted" />
            <Switch
              checked={theme === 'light'}
              onCheckedChange={(checked) => setTheme(checked ? 'light' : 'dark')}
            />
            <Sun size={15} className="text-t-muted" />
          </div>
        </div>
        <div className="flex gap-2 mt-3">
          {['dark', 'light'].map((opt) => (
            <button
              key={opt}
              onClick={() => setTheme(opt)}
              className={[
                'flex-1 py-1.5 rounded-md text-xs font-sans font-medium border transition-colors',
                theme === opt
                  ? 'bg-t-accent/10 text-t-accent border-t-accent/30'
                  : 'text-t-muted border-t-border hover:bg-white/5',
              ].join(' ')}
            >
              {opt === 'dark' ? tr('settings.dark') : tr('settings.light')}
            </button>
          ))}
        </div>
      </div>

      {/* Language card */}
      <div className="card p-4">
        <div className="mb-3">
          <p className="font-sans text-sm font-semibold text-t-text">
            {tr('settings.language')}
          </p>
          <p className="font-sans text-xs text-t-muted mt-0.5">
            {tr('settings.langDesc')}
          </p>
        </div>
        <div className="flex gap-2">
          {[
            { value: 'en', label: tr('settings.english') },
            { value: 'he', label: tr('settings.hebrew') },
          ].map(({ value, label }) => (
            <button
              key={value}
              onClick={() => setLang(value)}
              className={[
                'flex-1 py-1.5 rounded-md text-sm font-sans font-medium border transition-colors',
                lang === value
                  ? 'bg-t-accent/10 text-t-accent border-t-accent/30'
                  : 'text-t-muted border-t-border hover:bg-white/5',
              ].join(' ')}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

    </div>
  )
}
```

- [ ] **Step 3: Update `App.jsx` — import Settings and replace the settings stub**

Find this block in `App.jsx`:
```jsx
        {/* ── SETTINGS — stub ───────────────────────────────── */}
        {['settings'].includes(activePage) && (
          <div style={{
            flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center',
            color: 'var(--muted)', flexDirection: 'column', gap: 8,
          }}>
            <span style={{ fontSize: 32 }}>🚧</span>
            <span style={{ fontSize: 13, fontFamily: '"IBM Plex Mono", monospace' }}>
              {activePage.toUpperCase()} — coming soon
            </span>
          </div>
        )}
```

Replace with:
```jsx
        {/* ── SETTINGS ──────────────────────────────────────── */}
        {activePage === 'settings' && <Settings />}
```

Add the import at the top of `App.jsx` with the other component imports:
```jsx
import Settings from './components/Settings.jsx'
```

- [ ] **Step 4: Verify build passes**

```bash
cd swing-trading-dashboard/frontend && npm run build 2>&1 | tail -5
```

- [ ] **Step 5: Manual test**
Navigate to Settings page — verify theme toggle switches dark/light and persists across refresh; language toggle switches language.

- [ ] **Step 6: Commit**

```bash
git add swing-trading-dashboard/frontend/src/components/Settings.jsx
git add swing-trading-dashboard/frontend/src/components/ui/switch.jsx
git add swing-trading-dashboard/frontend/src/App.jsx
git commit -m "feat: add Settings page with theme + language toggles"
```

---

## Task 7: Translate `Sidebar.jsx` and `BottomTabBar.jsx`

**Files:**
- Modify: `src/components/Sidebar.jsx`
- Modify: `src/components/BottomTabBar.jsx`

**Pattern:** The nav items are currently static arrays defined outside the component. Move the label lookup inside the component using `tr()`. Store translation keys in the arrays instead of display strings.

- [ ] **Step 1: Update `Sidebar.jsx`**

Change the `NAV_ITEMS` array to use translation keys instead of display strings:
```jsx
const NAV_ITEMS = [
  { id: 'scanner',     icon: ScanLine,  labelKey: 'nav.scanner'     },
  { id: 'watchlist',   icon: Star,      labelKey: 'nav.watchlist'   },
  { id: 'favorites',   icon: Heart,     labelKey: 'nav.favorites'   },
  { id: 'portfolio',   icon: Briefcase, labelKey: 'nav.portfolio'   },
  { id: 'diagnostics', icon: Activity,  labelKey: 'nav.diagnostics' },
]
```

Add the import at the top:
```jsx
import { useAppSettings } from '../contexts/AppSettingsContext'
```

Inside the `Sidebar` component, add:
```jsx
  const { tr } = useAppSettings()
```

In the render, change `{label}` to `{tr(labelKey)}`:
```jsx
// In NAV_ITEMS.map destructure:
{NAV_ITEMS.map(({ id, icon: Icon, labelKey }) => {
  // ...
  <Icon size={17} strokeWidth={1.75} />
  {tr(labelKey)}
```

Also translate the Settings button label (find the `title="Settings"` button near the bottom):
```jsx
// Before:
title="Settings"
// ...
<Settings size={17} strokeWidth={1.75} />
Settings

// After:
title={tr('nav.settings')}
// ...
<Settings size={17} strokeWidth={1.75} />
{tr('nav.settings')}
```

**Font note:** Hebrew strings use Inter (font-sans). Sidebar labels currently use `font-mono`. When `lang === 'he'`, switch to `font-sans`. Update the button className:
```jsx
const { tr, lang } = useAppSettings()
// ...
const fontClass = lang === 'he' ? 'font-sans' : 'font-mono'
// In button className, replace 'font-mono' with fontClass
```

- [ ] **Step 2: Update `BottomTabBar.jsx`**

Change the `TABS` array to use translation keys:
```jsx
const TABS = [
  { id: 'scanner',   icon: ScanLine,       labelKey: 'nav.tab.scanner'   },
  { id: 'watchlist', icon: Star,           labelKey: 'nav.tab.watchlist' },
  { id: 'favorites', icon: Heart,          labelKey: 'nav.tab.favorites' },
  { id: 'portfolio', icon: Briefcase,      labelKey: 'nav.tab.portfolio' },
  { id: 'more',      icon: MoreHorizontal, labelKey: 'nav.tab.more'      },
]
```

Add import and hook:
```jsx
import { useAppSettings } from '../contexts/AppSettingsContext'

export default function BottomTabBar({ activePage, onNavigate }) {
  const { tr, lang } = useAppSettings()
  // ...
```

In render, change `{label}` to `{tr(labelKey)}`. The `<span>` currently uses `fontFamily: '"IBM Plex Mono", monospace'`. For Hebrew, switch to Inter:
```jsx
<span style={{
  fontSize: 9,
  fontFamily: lang === 'he' ? '"Inter", sans-serif' : '"IBM Plex Mono", monospace',
  fontWeight: 700,
  letterSpacing: lang === 'he' ? '0' : '0.06em',
  textTransform: lang === 'he' ? 'none' : 'uppercase',
  lineHeight: 1,
}}>
  {tr(labelKey)}
</span>
```

- [ ] **Step 3: Verify build passes**

```bash
cd swing-trading-dashboard/frontend && npm run build 2>&1 | tail -5
```

- [ ] **Step 4: Commit**

```bash
git add swing-trading-dashboard/frontend/src/components/Sidebar.jsx
git add swing-trading-dashboard/frontend/src/components/BottomTabBar.jsx
git commit -m "feat: translate Sidebar and BottomTabBar nav labels"
```

---

## Task 8: Translate `TopBar.jsx`

**Files:**
- Modify: `src/components/TopBar.jsx`

- [ ] **Step 1: Update `TopBar.jsx`**

Add import:
```jsx
import { useAppSettings } from '../contexts/AppSettingsContext'
```

Inside the component, add:
```jsx
const { tr, lang } = useAppSettings()
```

Replace the `PAGE_TITLES` object lookup with `tr()` calls. Change:
```jsx
const PAGE_TITLES = {
  scanner:     'Scanner',
  watchlist:   'Watchlist',
  favorites:   'Favorites',
  portfolio:   'Portfolio',
  analytics:   'Analytics',
  diagnostics: 'Diagnostics',
  settings:    'Settings',
  more:        'More',
}
// ...
const title = PAGE_TITLES[activePage] ?? activePage
```

To:
```jsx
const PAGE_TITLE_KEYS = {
  scanner:     'nav.scanner',
  watchlist:   'nav.watchlist',
  favorites:   'nav.favorites',
  portfolio:   'nav.portfolio',
  analytics:   'nav.analytics',
  diagnostics: 'nav.diagnostics',
  settings:    'nav.settings',
  more:        'nav.more',
}
// ...
const titleKey = PAGE_TITLE_KEYS[activePage]
const title = titleKey ? tr(titleKey) : activePage
```

Translate the scan button label. Find the button that shows "Run Scan" / scanning state and replace the text with:
```jsx
{isScanning ? tr('btn.scanning') : tr('btn.runScan')}
```

Translate the search input placeholder:
```jsx
placeholder={tr('search.placeholder')}
```

For the title `<span>`, if it uses `font-mono`, add the Hebrew font switch:
```jsx
className={`font-semibold tracking-wider ${lang === 'he' ? 'font-sans' : 'font-mono'}`}
```

- [ ] **Step 2: Verify build passes**

```bash
cd swing-trading-dashboard/frontend && npm run build 2>&1 | tail -5
```

- [ ] **Step 3: Commit**

```bash
git add swing-trading-dashboard/frontend/src/components/TopBar.jsx
git commit -m "feat: translate TopBar page titles, scan button, search placeholder"
```

---

## Task 9: Translate `Header.jsx`

**Files:**
- Modify: `src/components/Header.jsx`

- [ ] **Step 1: Read `Header.jsx` to identify all hardcoded strings**

Read the file: `src/components/Header.jsx`

- [ ] **Step 2: Add import and hook**

```jsx
import { useAppSettings } from '../contexts/AppSettingsContext'
// inside component:
const { tr } = useAppSettings()
```

- [ ] **Step 3: Replace regime label strings**

Replace hardcoded regime strings like `'AGGRESSIVE'`, `'SELECTIVE'`, `'DEFENSIVE'` with:
```jsx
tr('status.aggressive')
tr('status.selective')
tr('status.defensive')
```

Replace any hardcoded labels like `'Regime Score'`, `'Market'`, `'SPY Close'`, `'EMA20'`, `'SMA50'`, `'Breadth'`, `'VIX'` with their `regime.*` or `market.*` tr() equivalents.

**Font note:** Wrap Hebrew-displayed strings in a conditional font class:
```jsx
className={`${lang === 'he' ? 'font-sans' : 'font-mono'} ...`}
```
Add `lang` to the destructure: `const { tr, lang } = useAppSettings()`

- [ ] **Step 4: Verify build passes**

```bash
cd swing-trading-dashboard/frontend && npm run build 2>&1 | tail -5
```

- [ ] **Step 5: Commit**

```bash
git add swing-trading-dashboard/frontend/src/components/Header.jsx
git commit -m "feat: translate Header regime banner labels"
```

---

## Task 10: Translate `ScannerTable.jsx` and `SetupTable.jsx`

**Files:**
- Modify: `src/components/ScannerTable.jsx`
- Modify: `src/components/SetupTable.jsx`

- [ ] **Step 1: Read both files to identify all hardcoded strings**

Read: `src/components/ScannerTable.jsx` and `src/components/SetupTable.jsx`

- [ ] **Step 2: Add import + hook to both files**

```jsx
import { useAppSettings } from '../contexts/AppSettingsContext'
// inside component:
const { tr, lang } = useAppSettings()
```

- [ ] **Step 3: Translate column headers**

Replace hardcoded column header strings with tr() calls:
- `'Ticker'` → `tr('table.ticker')`
- `'Setup'` → `tr('table.setup')`
- `'Score'` → `tr('table.score')`
- `'Entry'` → `tr('table.entry')`
- `'Stop'` → `tr('table.stop')`
- `'Target'` → `tr('table.target')`
- `'R:R'` → `tr('table.rr')`
- `'RS'` → `tr('table.rs')`
- `'Sector'` → `tr('table.sector')`
- Any empty state messages → `tr('msg.noResults')`, `tr('msg.loading')`

- [ ] **Step 4: Verify build passes**

```bash
cd swing-trading-dashboard/frontend && npm run build 2>&1 | tail -5
```

- [ ] **Step 5: Commit**

```bash
git add swing-trading-dashboard/frontend/src/components/ScannerTable.jsx
git add swing-trading-dashboard/frontend/src/components/SetupTable.jsx
git commit -m "feat: translate ScannerTable and SetupTable column headers"
```

---

## Task 11: Translate `StockIntelPanel.jsx`

**Files:**
- Modify: `src/components/StockIntelPanel.jsx`

- [ ] **Step 1: Read the file to identify all hardcoded strings**

Read: `src/components/StockIntelPanel.jsx`

- [ ] **Step 2: Add import + hook**

```jsx
import { useAppSettings } from '../contexts/AppSettingsContext'
// inside component:
const { tr, lang } = useAppSettings()
```

- [ ] **Step 3: Translate section labels and buttons**

Replace strings matching these patterns:
- `'Trade Plan'` → `tr('intel.tradePlan')`
- `'Analysis'` → `tr('intel.analysis')`
- `'Signals'` → `tr('intel.signals')`
- `'Entry Zone'` / `'Entry'` → `tr('intel.entryZone')`
- `'Stop Loss'` / `'Stop'` → `tr('intel.stopLoss')`
- `'Target'` → `tr('intel.target')`
- `'R:R'` → `tr('intel.rr')`
- `'Support'` → `tr('intel.support')`
- `'Resistance'` → `tr('intel.resistance')`
- `'RS Line'` → `tr('intel.rsLine')`
- `'Analyze'` / `'Analyzing...'` buttons → `tr('btn.analyze')` / `tr('msg.analyzing')`
- Verdict labels: `'STRONG'` → `tr('verdict.strong')`, `'CAUTION'` → `tr('verdict.caution')`, etc.
- `'Select a ticker...'` → `tr('msg.selectTicker')`

**Font note:** Section labels that use `font-mono` need to switch to `font-sans` when `lang === 'he'`. Apply the same font conditional pattern as other components.

- [ ] **Step 4: Verify build passes**

```bash
cd swing-trading-dashboard/frontend && npm run build 2>&1 | tail -5
```

- [ ] **Step 5: Commit**

```bash
git add swing-trading-dashboard/frontend/src/components/StockIntelPanel.jsx
git commit -m "feat: translate StockIntelPanel section labels and verdict badges"
```

---

## Task 12: Translate `PortfolioTab.jsx` and `WatchlistPanel.jsx`

**Files:**
- Modify: `src/components/PortfolioTab.jsx`
- Modify: `src/components/WatchlistPanel.jsx`

- [ ] **Step 1: Read both files**

Read: `src/components/PortfolioTab.jsx` and `src/components/WatchlistPanel.jsx`

- [ ] **Step 2: Add import + hook to both files**

```jsx
import { useAppSettings } from '../contexts/AppSettingsContext'
const { tr, lang } = useAppSettings()
```

- [ ] **Step 3: Translate PortfolioTab strings**

Key strings to replace:
- Column headers: `'Ticker'` → `tr('table.ticker')`, `'Entry'` → `tr('table.entry')`, `'Stop'` → `tr('table.stop')`, `'Target'` → `tr('table.target')`, `'P&L'` → `tr('table.pnl')`, `'Status'` → `tr('table.status')`, `'Shares'` → `tr('table.shares')`
- Status badges: `'HOLD'` → `tr('portfolio.hold')`, `'CAUTION'` → `tr('portfolio.caution')`, `'EXIT'` → `tr('portfolio.exit')`
- `'Open Trades'` → `tr('portfolio.openTrades')`
- `'Add Trade'` → `tr('portfolio.addTrade')`
- Empty state → `tr('msg.noTrades')`

- [ ] **Step 4: Translate WatchlistPanel strings**

Key strings to replace:
- Labels → relevant `table.*` keys
- Empty state → `tr('msg.noWatchlist')` + `tr('msg.noWatchlistHint')`
- Button labels → `tr('btn.add')`, `tr('btn.remove')`

- [ ] **Step 5: Verify build passes**

```bash
cd swing-trading-dashboard/frontend && npm run build 2>&1 | tail -5
```

- [ ] **Step 6: Commit**

```bash
git add swing-trading-dashboard/frontend/src/components/PortfolioTab.jsx
git add swing-trading-dashboard/frontend/src/components/WatchlistPanel.jsx
git commit -m "feat: translate PortfolioTab and WatchlistPanel strings"
```

---

## Task 13: Translate remaining components

**Files:**
- Modify: `src/components/DiagnosticsTab.jsx`
- Modify: `src/components/StatCards.jsx`
- Modify: `src/components/MarketOverview.jsx`
- Modify: `src/components/ScannerFilters.jsx`
- Modify: `src/components/MobileSignalSheet.jsx`
- Modify: `src/App.jsx` (more-page menu labels)

For each file:

- [ ] **Step 1: Read the file**
- [ ] **Step 2: Add `import { useAppSettings }` and `const { tr, lang } = useAppSettings()`**
- [ ] **Step 3: Replace hardcoded strings with `tr()` calls using keys from Task 1's translations file**

**DiagnosticsTab key replacements:**
- `'Diagnostics'` → `tr('diag.title')`
- `'Live Trades'` → `tr('diag.liveSource')`
- `'Backtest'` → `tr('diag.backtestSource')`
- `'Win Rate'` → `tr('diag.winRate')`
- `'Avg R'` → `tr('diag.avgR')`
- `'Profit Factor'` → `tr('diag.profitFactor')`
- `'Max Drawdown'` → `tr('diag.maxDrawdown')`
- `'Total Trades'` → `tr('diag.totalTrades')`
- `'Setup Breakdown'` → `tr('diag.setupBreakdown')`
- No backtest data message → `tr('msg.noBacktest')`

**StatCards key replacements:**
- Any regime/market stat labels → matching `market.*` or `regime.*` keys
- Scan status → `tr('scan.lastRun')`, `tr('scan.progress')`

**MarketOverview key replacements:**
- `'Market Overview'` → `tr('market.overview')`
- `'Top Sectors'` → `tr('market.topSectors')`
- `'Market Breadth'` → `tr('market.breadth')`

**ScannerFilters key replacements:**
- Filter button labels: `'All'` → `tr('filter.all')`, `'VCP'` → `tr('filter.vcp')`, etc.
- `'Min Score'` → `tr('filter.minScore')`
- `'Sort By'` → `tr('filter.sortBy')`

**MobileSignalSheet key replacements:**
- All column/label strings → matching `table.*`, `intel.*`, `setup.*` keys

**App.jsx more-page menu:**
Find the `more` page section with the menu items array:
```jsx
{ id: 'diagnostics', label: 'Diagnostics', Icon: Activity      },
{ id: 'settings',    label: 'Settings',    Icon: SettingsIcon  },
```
Add `useAppSettings` import and hook to `App.jsx`, then replace with:
```jsx
import { useAppSettings } from './contexts/AppSettingsContext'
// Inside App component:
const { tr } = useAppSettings()
// In the array:
{ id: 'diagnostics', label: tr('nav.diagnostics'), Icon: Activity    },
{ id: 'settings',    label: tr('nav.settings'),    Icon: SettingsIcon},
```

- [ ] **Step 4: Verify build passes after all changes**

```bash
cd swing-trading-dashboard/frontend && npm run build 2>&1 | tail -5
```

- [ ] **Step 5: Commit**

```bash
git add swing-trading-dashboard/frontend/src/components/DiagnosticsTab.jsx
git add swing-trading-dashboard/frontend/src/components/StatCards.jsx
git add swing-trading-dashboard/frontend/src/components/MarketOverview.jsx
git add swing-trading-dashboard/frontend/src/components/ScannerFilters.jsx
git add swing-trading-dashboard/frontend/src/components/MobileSignalSheet.jsx
git add swing-trading-dashboard/frontend/src/App.jsx
git commit -m "feat: translate DiagnosticsTab, StatCards, MarketOverview, ScannerFilters, MobileSignalSheet, App more-menu"
```

---

## Task 14: End-to-end verification + VPS deploy

- [ ] **Step 1: Full build verification**

```bash
cd swing-trading-dashboard/frontend && npm run build
```
Expected: build exits 0 with no errors.

- [ ] **Step 2: Manual browser verification checklist**
- [ ] Navigate to Settings page → theme toggle switches dark/light immediately
- [ ] Refresh page → theme preference persists
- [ ] Switch to Hebrew → all UI chrome (nav, column headers, buttons) displays Hebrew
- [ ] Refresh page → language preference persists
- [ ] Switch back to English → all UI chrome back to English
- [ ] Light mode: backgrounds white, text dark, accent blue — no dark artifacts
- [ ] Dark mode: original dark theme fully restored
- [ ] Hebrew strings render in Inter (not IBM Plex Mono) — no garbled characters
- [ ] `tr()` fallback works: if a key is missing, the key string itself shows (no crash)

- [ ] **Step 3: Deploy to VPS**

```bash
# Commit any remaining changes
git push origin main

# On VPS:
ssh root@<vps-ip>
cd /opt/dashboard
git pull
cd swing-trading-dashboard/frontend
npm install
npm run build
systemctl restart dashboard.service
```

- [ ] **Step 4: Verify VPS deployment**

```bash
curl -s http://localhost:5173 | head -5
# or check via browser
```

---

## Notes for Implementer

1. **`tr` vs `t` naming:** Always use `tr` — never rename to `t`. The `t` name collides with `setups.map(t => ...)` and similar loop variables throughout the codebase.

2. **Font switching for Hebrew:** Any element displaying translated strings that currently uses `font-mono` / `IBM Plex Mono` must switch to `font-sans` / `Inter` when `lang === 'he'`. IBM Plex Mono does not contain Hebrew characters. Pattern:
   ```jsx
   const { tr, lang } = useAppSettings()
   // ...
   className={lang === 'he' ? 'font-sans' : 'font-mono'}
   ```

3. **No RTL layout:** Hebrew is text-only. The overall layout (sidebar left, tables LTR) does not change. Do NOT add `dir="rtl"` to containers.

4. **Translation fallback:** `tr(key)` returns the English string if Hebrew is missing, and the key itself as a last resort. This means partial Hebrew rollout never breaks the UI.

5. **Static context arrays (NAV_ITEMS, TABS, PAGE_TITLES):** These are defined outside the component and can't call hooks. The pattern is: store translation keys in the array, call `tr(key)` when rendering inside the component.

6. **CSS variable tokens that stay static hex:** `accentDim`, `goDim`, `haltDim`, `blueDim`, `pink` in `tailwind.config.js` have no CSS var equivalents. They remain static hex and will not change in light mode — this is acceptable (they are dim/muted tints used sparingly).

7. **shadcn `Switch` component:** Must be installed via `npx shadcn@latest add switch` before implementing `Settings.jsx`. The component will appear at `src/components/ui/switch.jsx`.
