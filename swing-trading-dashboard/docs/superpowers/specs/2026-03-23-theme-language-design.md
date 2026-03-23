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

// Named 'tr' throughout — never 't' — to avoid collision with loop variable t
export function tr(lang, key) {
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

  const setTheme = (val) => {
    setThemeState(val)
    localStorage.setItem('theme', val)
  }
  const setLang = (val) => {
    setLangState(val)
    localStorage.setItem('lang', val)
  }

  // Apply to <html> element
  useEffect(() => {
    const html = document.documentElement
    html.classList.toggle('dark', theme === 'dark')
    html.classList.toggle('light', theme === 'light')
    html.setAttribute('lang', lang)
  }, [theme, lang])

  // tr() — named 'tr' (not 't') to avoid collision with common loop variable t
  const tr = (key) => translations[lang]?.[key] ?? translations['en'][key] ?? key

  return (
    <AppSettingsContext.Provider value={{ theme, lang, setTheme, setLang, tr }}>
      {children}
    </AppSettingsContext.Provider>
  )
}

export const useAppSettings = () => useContext(AppSettingsContext)
```

**Usage in components:**
```jsx
const { tr } = useAppSettings()
// ...
<span>{tr('nav.scanner')}</span>
```

`tr` is used throughout (not `t`) to avoid colliding with the widespread `t` loop variable in existing code (e.g. `setups.map(t => ...)`).

### Modified Files

**`src/main.jsx`**
Wrap `<App />` with `<AppSettingsProvider>`.

**`tailwind.config.js`** — convert `t-*` color tokens from static hex to CSS variable references so the light mode override actually takes effect. Currently these are hardcoded hex values that ignore CSS variable overrides entirely.

```js
// BEFORE (static hex — immune to CSS var overrides):
't-bg': '#000000',
't-text': '#e0e0e0',

// AFTER (references CSS vars — responds to .light overrides):
't-bg':          'var(--bg)',
't-surface':     'var(--surface)',
't-panel':       'var(--panel)',
't-card':        'var(--card)',
't-card-border': 'var(--card-border)',
't-text':        'var(--text)',
't-muted':       'var(--muted)',
't-accent':      'var(--accent)',
't-go':          'var(--go)',
't-halt':        'var(--halt)',
't-blue':        'var(--blue)',
't-purple':      'var(--purple)',
```

This is essential — without this change, all `bg-t-*`, `text-t-*`, `border-t-*` Tailwind classes will stay dark regardless of the theme toggle, as they resolve to hardcoded hex at build time.

**`src/index.css`**
Add a `.light` CSS variable override block. All values are hex (consistent with how `:root` defines them in this project — no space-separated RGB). Also adds missing vars (`--border-light`, `--blue`, `--purple`) that exist in `:root` but are absent from the existing palette table.

```css
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
  --radius-card:  12px;   /* match :root value */
  --shadow-card:  0 1px 3px rgba(0,0,0,0.08);

  /* shadcn/ui token overrides for light mode (hex, matching project convention) */
  --background:   #ffffff;
  --foreground:   #0f172a;
  --primary:      #0ea5e9;
  --secondary:    #f1f5f9;
  --muted-foreground: #64748b;
  --popover:      #ffffff;
  --popover-foreground: #0f172a;
  --border:       #e2e8f0;
  --input:        #e2e8f0;
  --ring:         #0ea5e9;
  --destructive:  #dc2626;
}
```

Dark mode vars stay exactly as they are in `:root` (zero changes to existing block).

**`src/components/Settings.jsx`** (new component)
Replaces the inline "coming soon" stub in App.jsx's `activePage === 'settings'` block.

Layout:
- Page header: `tr('settings.title')` ("Settings" / "הגדרות")
- Two setting cards:
  1. **Theme card**: label + Dark/Light toggle (sun/moon icons, shadcn Switch)
  2. **Language card**: label + EN/עברית toggle (text pill buttons)
- **Prerequisite**: run `npx shadcn@latest add switch` before implementing — `switch.jsx` is not yet in `src/components/ui/`
- Each card switches immediately on toggle (no save button needed — persisted to localStorage instantly)

**All other components** — replace hardcoded English strings with `tr('key')` calls:
- `Sidebar.jsx` — nav labels
- `TopBar.jsx` — scan button, search placeholder, status text
- `BottomTabBar.jsx` — mobile tab labels (Scanner, WL, Favs, Port, More)
- `ScannerTable.jsx` / `SetupTable.jsx` — column headers, empty states
- `Header.jsx` — regime banner labels
- `StockIntelPanel.jsx` — section labels, verdict badges, button text
- `PortfolioTab.jsx` — column headers, status labels
- `DiagnosticsTab.jsx` — section labels, stat card labels
- `WatchlistPanel.jsx` — labels, empty states
- `StatCards.jsx` — card labels
- `MarketOverview.jsx` — labels
- `ScannerFilters.jsx` — filter labels
- `MobileSignalSheet.jsx` — mobile detail sheet strings
- `App.jsx` — the "more" page menu labels (Diagnostics, Settings, etc.)

---

## Light Mode Color Palette

| Token | Dark (`:root`) | Light (`.light`) |
|---|---|---|
| `--bg` | #000000 | #ffffff |
| `--surface` | #0d1117 | #f8fafc |
| `--panel` | #161b22 | #f1f5f9 |
| `--card` | #1c2128 | #ffffff |
| `--card-border` | #30363d | #e2e8f0 |
| `--border` | #1e1e1e | #e2e8f0 |
| `--border-light` | #2a2a2a | #f0f4f8 |
| `--text` | #e6edf3 | #0f172a |
| `--muted` | #7d8590 | #64748b |
| `--accent` | #50d8f0 | #0ea5e9 |
| `--go` | #00c87a | #16a34a |
| `--halt` | #ff2d55 | #dc2626 |
| `--blue` | #58a6ff | #0ea5e9 |
| `--purple` | #bc8cff | #8b5cf6 |

---

## Translation Strategy

- ~250 static keys covering all UI chrome
- `tr(key)` falls back to English if Hebrew key missing — no broken UI during rollout
- Hebrew text: `direction: rtl` is applied only at the string/element level, not the container. The overall LTR layout (sidebar left, tables left-to-right) is unchanged.
- Font note: Hebrew characters do not exist in `IBM Plex Mono`. Elements displaying Hebrew strings must use `font-sans` (Inter), not `font-mono`, to avoid height/baseline mismatches. The implementer must audit each translated element and remove `font-mono` when the active language is Hebrew.
- Table column headers with `text-left` alignment will display correctly in Hebrew since layout direction is not flipped.
- Backend-generated text (AI narratives, trade plan descriptions) remains English in this version.

---

## Out of Scope

- Backend narrative translation
- RTL layout mirroring (sidebar stays left, tables stay LTR)
- Language auto-detection from browser
- Per-component language override
