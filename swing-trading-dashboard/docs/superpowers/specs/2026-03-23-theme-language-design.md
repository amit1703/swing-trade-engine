# Theme & Language Settings — Design Spec
*Date: 2026-03-23*

---

## Goal

Add Dark/Light mode toggle and Hebrew/English language toggle to the app, accessible from the Settings page.

## Decisions Made

| Question | Decision |
|---|---|
| Where do toggles live? | Settings page (dedicated) |
| Translation depth | Full UI chrome — all static strings translated |
| Light mode aesthetic | Clean White — white bg, slate text, blue (#0ea5e9) accent |
| RTL layout? | No — text-only Hebrew, LTR layout unchanged |
| Backend narratives | English only for now |

---

## Architecture

### New Files

**`src/i18n/translations.js`**
Single source of truth for all UI strings. Structure:
```js
export const translations = {
  en: {
    'nav.scanner': 'Scanner',
    'nav.watchlist': 'Watchlist',
    // ...~250 keys
  },
  he: {
    'nav.scanner': 'סורק',
    'nav.watchlist': 'רשימת מעקב',
    // ...same keys in Hebrew
  }
}

export function t(lang, key) {
  return translations[lang]?.[key] ?? translations['en'][key] ?? key
}
```

Key namespaces:
- `nav.*` — sidebar and topbar navigation
- `status.*` — regime labels (AGGRESSIVE, SELECTIVE, DEFENSIVE)
- `table.*` — column headers (Entry, Stop, Target, Score, R:R, etc.)
- `setup.*` — setup type names (VCP, Pullback, Watchlist, etc.)
- `btn.*` — button labels (Run Scan, Save, Cancel, etc.)
- `settings.*` — settings page labels
- `verdict.*` — analysis verdict labels (STRONG, CAUTION, etc.)
- `filter.*` — filter bar labels
- `msg.*` — empty states, loading messages, error messages
- `regime.*` — regime component labels
- `scan.*` — scan status messages

**`src/contexts/AppSettingsContext.jsx`**
React context — the single place that reads/writes localStorage and exposes settings to all components.

```jsx
export const AppSettingsContext = createContext()

export function AppSettingsProvider({ children }) {
  const [theme, setThemeState] = useState(() => localStorage.getItem('theme') || 'dark')
  const [lang, setLangState] = useState(() => localStorage.getItem('lang') || 'en')

  const setTheme = (t) => {
    setThemeState(t)
    localStorage.setItem('theme', t)
  }
  const setLang = (l) => {
    setLangState(l)
    localStorage.setItem('lang', l)
  }

  // Apply to <html> element
  useEffect(() => {
    const html = document.documentElement
    html.classList.toggle('dark', theme === 'dark')
    html.classList.toggle('light', theme === 'light')
    html.setAttribute('lang', lang)
  }, [theme, lang])

  const translate = (key) => t(lang, key)

  return (
    <AppSettingsContext.Provider value={{ theme, lang, setTheme, setLang, t: translate }}>
      {children}
    </AppSettingsContext.Provider>
  )
}

export const useAppSettings = () => useContext(AppSettingsContext)
```

### Modified Files

**`src/main.jsx`** (or `src/index.jsx`)
Wrap `<App />` with `<AppSettingsProvider>`.

**`src/index.css`**
Add light mode CSS variable overrides under `.light`:
```css
.light {
  --bg:          #ffffff;
  --surface:     #f8fafc;
  --panel:       #f1f5f9;
  --card:        #ffffff;
  --card-border: #e2e8f0;
  --text:        #0f172a;
  --muted:       #64748b;
  --accent:      #0ea5e9;
  --go:          #16a34a;
  --halt:        #dc2626;
  --blue:        #0ea5e9;
  --radius-card: 8px;
  --shadow-card: 0 1px 3px rgba(0,0,0,0.08);
}

/* shadcn/ui overrides for light mode */
.light {
  --background: 255 255 255;
  --foreground: 15 23 42;
  --card: 248 250 252;
  --border: 226 232 240;
  --muted: 241 245 249;
  --muted-foreground: 100 116 139;
  --primary: 14 165 233;
}
```

Dark mode vars stay exactly as they are (no changes to existing `:root` block).

**`src/components/Settings.jsx`** (new component)
Replaces the inline "coming soon" stub in App.jsx.

Layout:
- Page header: "Settings" / "הגדרות"
- Two setting cards side by side (or stacked on mobile):
  1. **Theme card**: label + Dark/Light toggle (sun/moon icons, shadcn Switch)
  2. **Language card**: label + EN/עברית toggle (flag or text pill)
- Each card shows current value and switches immediately on toggle

**All other components**
Replace hardcoded English strings with `t('key')` calls. Components to update:
- `Sidebar.jsx` — nav labels
- `TopBar.jsx` — scan button, search placeholder, status text
- `ScannerTable.jsx` / `SetupTable.jsx` — column headers, empty states
- `Header.jsx` — regime banner labels
- `StockIntelPanel.jsx` — section labels, verdict badges, button text
- `PortfolioTab.jsx` — column headers, status labels
- `DiagnosticsTab.jsx` — section labels, stat card labels
- `WatchlistPanel.jsx` — labels, empty states
- `StatCards.jsx` — card labels
- `MarketOverview.jsx` — labels
- `ScannerFilters.jsx` — filter labels

---

## Light Mode Color Palette

| Token | Dark | Light |
|---|---|---|
| `--bg` | #000000 | #ffffff |
| `--surface` | #0d1117 | #f8fafc |
| `--panel` | #161b22 | #f1f5f9 |
| `--card` | #1c2128 | #ffffff |
| `--card-border` | #30363d | #e2e8f0 |
| `--text` | #e6edf3 | #0f172a |
| `--muted` | #7d8590 | #64748b |
| `--accent` | #50d8f0 | #0ea5e9 |
| `--go` | #00c87a | #16a34a |
| `--halt` | #ff2d55 | #dc2626 |

---

## Translation Strategy

- ~250 static keys covering all UI chrome
- `t(key)` falls back to English if Hebrew key missing — no broken UI during incremental rollout
- Hebrew text uses native RTL rendering via CSS (`direction: rtl` on text elements where needed) without flipping the overall LTR layout
- Backend-generated text (AI narratives, trade plan descriptions) remains English in this version

---

## Out of Scope

- Backend narrative translation
- RTL layout mirroring (sidebar stays left, tables stay LTR)
- Language auto-detection from browser
- Per-component language override
