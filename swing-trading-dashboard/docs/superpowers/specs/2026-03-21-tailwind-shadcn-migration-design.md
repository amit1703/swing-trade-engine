# Tailwind + shadcn/ui Migration Design

## Overview

Migrate the React frontend from inline CSS to Tailwind CSS + shadcn/ui component library, applying a polished dark terminal aesthetic inspired by a provided reference design. The migration is **styling-only** — no changes to props, state, API calls, or business logic.

---

## Goals

- Replace inline `style={{}}` props with Tailwind utility classes across all frontend components
- Install shadcn/ui for primitive components (Button, Card, Badge, Input, Separator)
- Apply consistent dark theme using the existing CSS variable + Tailwind color token system
- Keep trading signal colors (`--go`, `--halt`, `--accent`) as CSS variables for dynamic use
- App stays fully functional throughout the migration (layered approach)

## Non-Goals

- No TypeScript migration
- No changes to App.jsx state management or routing
- No changes to backend
- No new features or behavioral changes
- No changes to lightweight-charts canvas rendering in TradingChart.jsx

---

## Current State

**Tailwind is already installed and configured.** `tailwindcss`, `postcss`, and `autoprefixer` are in `devDependencies`. `@tailwind` directives are at the top of `src/index.css`. A comprehensive `tailwind.config.js` exists with:
- All color tokens under the `t.*` namespace: `t.bg`, `t.panel`, `t.card`, `t.cardBorder`, `t.border`, `t.text`, `t.muted`, `t.accent`, `t.go`, `t.halt`, `t.blue`, `t.purple`, `t.pink`, and dim variants
- Font families: `font-mono` (IBM Plex Mono), `font-condensed` (Barlow Condensed), `font-sans` (Inter)
- Custom animations: `shimmer`, `fadeUp`, `scanIn`, `blink`, `pulse_halt`
- Custom shadows: `shadow-card`, `shadow-glow`, `shadow-glowRed`

**IBM Plex Mono is already loaded** from Google Fonts in `index.html`.

**CSS variables already exist** in `src/index.css` as hex values: `--accent: #F5A623`, `--go: #00c87a`, `--halt: #ff2d55`, `--muted: #4a5a72`, `--panel: #0c111a`, `--card: #0f1520`, `--border: #1a2535`, `--text: #c8cdd6`, etc.

**shadcn/ui is NOT installed** — that is the only dependency gap.

**Existing components use inline CSS exclusively** — Tailwind classes are defined in the config but largely unused in the `.jsx` component files.

**The current sidebar is icon-only (60px wide).** The new sidebar will be wider (`w-56`, 224px) with icon + label nav items — this is a deliberate layout change. `App.jsx` must accommodate the new width in the same Layer 1 commit.

---

## Color Palette

All color tokens already exist. Components should use Tailwind `t.*` classes.

| Tailwind class | Value | Usage |
|----------------|-------|-------|
| `bg-t-bg` | `#000000` | Root app background |
| `bg-t-panel` | `#0c111a` | Sidebar, header panels |
| `bg-t-card` | `#0f1520` | Card surfaces |
| `border-t-cardBorder` | `#1e2d42` | Card borders |
| `border-t-border` | `#1a2535` | Dividers |
| `text-t-text` | `#c8cdd6` | Primary body text |
| `text-t-muted` | `#4a5a72` | Secondary/label text |
| `text-t-accent` | `#F5A623` | Active nav, selected rows, highlights |
| `text-t-go` | `#00c87a` | Bullish signals, profit |
| `text-t-halt` | `#ff2d55` | Stop losses, loss |
| `text-t-blue` | `#00C8FF` | RS blue dot, info |

**Active nav color change:** The current sidebar's `.nav-btn.active` is green (`var(--go)`). The new sidebar active state is amber (`text-t-accent` / `bg-t-accent/10`). **This is an intentional design change.**

**Dynamic signal colors** (computed per-row in JS) must stay as inline `style={{ color: 'var(--go)' }}` — Tailwind cannot resolve dynamically-constructed class names. Static uses (e.g., a known "profit" label) can use `text-t-go`.

**Always use `bg-t-card`, `text-t-accent`, etc. (our `t.*` tokens).** Do NOT use shadcn's color classes (`bg-card`, `bg-primary`, `bg-accent`) in our component code — they will be configured to work but using our tokens is explicit and avoids confusion.

---

## Architecture

### Layer 0 — shadcn/ui Setup (one-time, no Tailwind install needed)

Tailwind, PostCSS, and Autoprefixer are already installed. Only shadcn/ui setup is needed.

**Step 1: Configure path alias in `vite.config.js`**

The project uses `"type": "module"` in `package.json` (ESM). `__dirname` is not available in ESM. Use the correct ESM-compatible form:

```js
import { fileURLToPath } from 'url'
import { dirname, resolve } from 'path'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const __dirname = dirname(fileURLToPath(import.meta.url))

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': resolve(__dirname, './src') }
  },
  server: { /* keep existing proxy config unchanged */ }
})
```

**Step 2: Create `jsconfig.json`** at `frontend/` root for VS Code alias resolution:
```json
{ "compilerOptions": { "baseUrl": ".", "paths": { "@/*": ["./src/*"] } } }
```

**Step 3: Add `darkMode` to `tailwind.config.js`**

Add `darkMode: 'class'` at the top level of the config export. Some shadcn component variants use `dark:` prefixes. Since our app is permanently dark, we do not add a `dark` class to `<html>` — all our colors are defined in `:root`, so `dark:` variants remain unused. Adding the key prevents Tailwind from tree-shaking `dark:` utilities that shadcn components reference internally.

**Step 4: Run shadcn init** (requires Steps 1–3 to be applied first — alias must exist before the wizard validates paths)
```bash
npx shadcn@latest init
```

Wizard answers for a plain-JS Vite project:
- Style: **Default**
- Base color: **Neutral**
- **TypeScript: No** — project is plain JS; choosing Yes generates `.tsx` files that Vite won't process
- CSS variables: **Yes**
- Global CSS file: `src/index.css`
- Tailwind config: `tailwind.config.js`
- Components alias: `@/components`
- Utils alias: `@/lib/utils`
- Add `tailwindcss-animate` plugin: **Yes** — some shadcn components use `animate-in`/`fade-in` utilities

This generates `src/components/ui/` (`.jsx` files), `src/lib/utils.js`, and installs peer dependencies: `clsx`, `tailwind-merge`, `class-variance-authority`. These appearing in `package.json` is expected and correct.

**Step 5: Fix CSS variable collision in `index.css`**

shadcn's init appends its own `:root` block to `index.css` with HSL-format values (e.g., `--card: 222 27% 9%`). Our existing `:root` block uses hex values for the same names (e.g., `--card: #0f1520`). **Do not mix formats in the same variable name** — CSS `background: var(--card)` with an HSL channel string (no `hsl()` wrapper) will fail to render.

Resolution: **delete the shadcn-generated `:root` block entirely**, then add only the new shadcn-specific variables to our existing `:root` block as hex values:

```css
/* Add these to the existing :root block — hex format matches our convention */
--background:            #000000;   /* = t.bg */
--foreground:            #c8cdd6;   /* = t.text */
--card-foreground:       #c8cdd6;   /* text on card surfaces */
--primary:               #F5A623;   /* = t.accent / --accent */
--primary-foreground:    #000000;   /* text on amber backgrounds */
--secondary:             #1a2535;   /* = t.border */
--secondary-foreground:  #c8cdd6;
--muted-foreground:      #4a5a72;   /* = --muted */
--accent-foreground:     #c8cdd6;   /* text on accent hover bg (ghost button hover) */
--destructive:           #ff2d55;   /* = --halt */
--destructive-foreground:#ffffff;
--popover:               #0f1520;   /* = t.card */
--popover-foreground:    #c8cdd6;
--ring:                  #F5A623;   /* = --accent */
--input:                 #1a2535;   /* = --border */
--radius:                0.5rem;
```

Do NOT redefine `--card`, `--border`, `--accent`, `--muted` — our existing hex values for these are already correct and shadcn's entries would duplicate them. `--destructive` IS defined above because our existing `:root` uses `--halt` for red, not `--destructive`.

**Step 6: Fix `tailwind.config.js` shadcn color entries**

shadcn's init adds a `colors` block to `tailwind.config.js` using `hsl(var(--xxx))` format (e.g., `background: "hsl(var(--background))"`). Since our CSS variables are hex (not HSL channel strings), `hsl(#000000)` is invalid CSS. Update every shadcn-generated color entry to use `var(--xxx)` instead of `hsl(var(--xxx))`:

```js
// Replace the shadcn-generated colors entries:
background: "var(--background)",
foreground: "var(--foreground)",
card: { DEFAULT: "var(--card)", foreground: "var(--card-foreground)" },
primary: { DEFAULT: "var(--primary)", foreground: "var(--primary-foreground)" },
secondary: { DEFAULT: "var(--secondary)", foreground: "var(--secondary-foreground)" },
muted: { DEFAULT: "var(--muted)", foreground: "var(--muted-foreground)" },
accent: { DEFAULT: "var(--accent)", foreground: "var(--accent-foreground)" },
destructive: { DEFAULT: "var(--destructive)", foreground: "var(--destructive-foreground)" },
border: "var(--border)",
input: "var(--input)",
ring: "var(--ring)",
```

Merge these into the existing `colors:` section of `tailwind.config.js` alongside (not replacing) the existing `t: { ... }` tokens.

**Step 7: Install shadcn/ui components**
```bash
npx shadcn@latest add button card input badge separator
```

Do NOT add `dialog` — `SystemGuideModal.jsx` uses a custom overlay that will be restyled with Tailwind in Layer 3; the shadcn Dialog adds unnecessary complexity.

**Verification:** Run `npm run dev`. App should load without errors. Existing inline CSS components should look unchanged.

---

### Layer 1 — Shell (3 files)

Commit all three files together — they are coupled by the sidebar width change.

**`App.jsx`** — Outer layout wrapper
- Replace root `div` inline styles with `className="flex h-screen bg-t-bg overflow-hidden"`
- The sidebar is now `w-56` (224px) — the main content area `flex-1` adapts automatically
- Replace all flex layout wrappers with Tailwind classes
- No logic changes

**`Sidebar.jsx`** — Left navigation (significant visual redesign)
- Width: `w-56` (224px) — **wider than current icon-only sidebar**
- Root element must be `<aside>` or `<nav>` (not `<div>`) — `src/index.css` has a mobile media query `nav { width: 48px !important }` that collapses the sidebar on screens ≤640px. If using `<aside>`, migrate that mobile rule to `aside { width: 48px !important }` at the same time.
- Background: `bg-t-panel border-r border-t-border flex flex-col h-full`
- Logo area (top): amber gradient icon + `"SCANR"` label — `font-mono text-t-accent text-lg font-semibold`
- Nav items (map to existing pages + all their existing `onClick` callbacks):
  - Scanner → `LayoutDashboard`
  - Watchlist → `List`
  - Favorites → `Heart`
  - Portfolio → `Briefcase`
  - Analytics → `BarChart3`
  - Diagnostics → `Activity`
- Active item style: `bg-t-accent/10 text-t-accent border border-t-accent/20`
- Inactive item style: `text-t-muted hover:bg-white/5 hover:text-t-text`
- Uses shadcn `Button variant="ghost"` with `w-full justify-start gap-3 font-mono`
- Bottom: Settings item
- **Note: active nav color changes from green to amber** — this is intentional

**`TopBar.jsx`** — Top header bar
- Background: `bg-t-panel border-b border-t-border px-6 py-3`
- Left: page title (`font-mono text-xl font-semibold text-t-accent`) + version tag with `Terminal` icon
- Center: shadcn `Input` with `placeholder="Search tickers..."` — wraps existing `searchVal` state and `setSearchVal`/`onSearchTicker` (already wired, pure restyle)
- Right: regime badge (Tailwind colored text + bg) + scan button as shadcn `Button`
- Dev mode toggle + dry run toggle: keep as small text buttons, restyle with Tailwind

---

### Layer 2 — Page Containers (4 files)

**`Header.jsx`** — Market regime banner
- Wrapper: `bg-t-card border border-t-cardBorder rounded-card shadow-card p-4`
- Regime score bar: `bg-t-border rounded-full h-1.5` track, `bg-t-accent h-full rounded-full` fill
- All existing props and callbacks unchanged

**`MarketOverview.jsx`** — Market overview cards
- Grid: `grid grid-cols-2 md:grid-cols-4 gap-4`
- Each stat: shadcn `Card` with `bg-t-card border-t-cardBorder shadow-card`
- `CardHeader`: label in `text-t-muted font-mono text-xs uppercase tracking-widest`
- `CardContent`: value in `font-condensed text-2xl font-bold` with signal color

**`StatCards.jsx`** — Summary stat cards
- Same card pattern as MarketOverview
- Colored left border per type: `border-l-4 border-t-go` / `border-l-4 border-t-halt` / `border-l-4 border-t-accent`

**`ScannerFilters.jsx`** — Filter bar
- Wrapper: `flex items-center gap-2 flex-wrap p-3 border-b border-t-border bg-t-panel`
- Active filter: shadcn `Button` with `bg-t-accent/10 text-t-accent border border-t-accent/20`
- Inactive filter: shadcn `Button variant="outline"` with `text-t-muted border-t-border`

---

### Layer 3 — Inner Components (10 files)

All components: **props and behavior unchanged, styling migrated.** One commit per component.

**`ScannerTable.jsx`**
- Table wrapper: `bg-t-card border border-t-cardBorder rounded-card shadow-card overflow-hidden`
- Update `.terminal-table` in `@layer components` to use `@apply` directives
- Selected row: `bg-t-accent/5` with `border-l-2 border-t-accent`; near-entry row: `bg-t-accent/[0.035]`
- EARLY/OPTIMAL/EXTENDED badges: shadcn `Badge`
- Setup type badges: keep inline color style (dynamic per type — cannot use static Tailwind class)
- Show/hide extended: shadcn `Button variant="ghost" size="sm"`

**`WatchlistPanel.jsx`**
- Panel: `bg-t-panel h-full flex flex-col overflow-hidden`
- Section headers: `flex items-center justify-between px-3 py-1.5 border-b border-t-border bg-white/[0.02]`
- Watch rows: Tailwind hover + amber left border for selected item
- Star + TV link: Tailwind padding/sizing

**`FavoritesPage.jsx`**
- Empty state: `flex-1 flex flex-col items-center justify-center gap-3 text-t-muted`
- Setup rows: same migration as ScannerTable rows; full inline CSS → Tailwind

**`SetupTable.jsx`**
- Same migration as ScannerTable
- `accentColor` prop still drives header left border (keep as inline style — dynamic value)

**`StockIntelPanel.jsx`**
- Panel: `bg-t-panel flex flex-col overflow-y-auto`
- Section cards: shadcn `Card` with `bg-t-card border-t-cardBorder`
- Trade plan grid: `grid grid-cols-2 gap-2`
- Signal pills: shadcn `Badge`

**`PortfolioTab.jsx`**
- Table: same migration as ScannerTable
- P/L values: keep inline style for dynamic color; layout → Tailwind

**`DiagnosticsTab.jsx`**, **`BacktestPanel.jsx`**, **`EngineHealthPanel.jsx`**
- Card wrappers → shadcn `Card` with `bg-t-card border-t-cardBorder`
- Layout → Tailwind grid/flex
- Data values → keep inline style for dynamic signal colors

**`DebugDrawer.jsx`**
- Dev-mode overlay: `fixed inset-y-0 right-0 w-96 bg-t-panel border-l border-t-border shadow-2xl z-50`
- Content layout → Tailwind; signal colors → inline style

**`SystemGuideModal.jsx`**
- Do NOT add shadcn Dialog — use the existing custom backdrop + panel overlay pattern
- Backdrop: `fixed inset-0 bg-black/60 backdrop-blur-sm z-50`
- Modal panel: `bg-t-card border border-t-cardBorder rounded-card shadow-2xl`
- Inner layout → Tailwind

**`TradingChart.jsx`**
- Wrapper: `bg-t-panel rounded-card border border-t-cardBorder` + Tailwind sizing
- Toolbar buttons: shadcn `Button variant="ghost" size="sm"`
- Chart canvas: untouched

---

## Migration Order & Commit Strategy

Each layer is a separate commit or group of commits. App is functional after every layer.

1. **Layer 0:** `chore: install shadcn/ui, configure alias, reconcile CSS variables`
2. **Layer 1:** `feat(ui): migrate shell — App, Sidebar, TopBar`
3. **Layer 2:** `feat(ui): migrate page containers — Header, MarketOverview, StatCards, ScannerFilters`
4. **Layer 3:** One commit per component: `feat(ui): migrate ScannerTable to Tailwind`, etc.

---

## Testing

- After Layer 0: `npm run dev` loads without errors; existing inline CSS components look unchanged
- After Layer 1: page switching works, sidebar active state updates on click, new wider sidebar doesn't overlap content
- After Layer 2: scan trigger, filter toggles, regime display all functional
- After Layer 3: scanner table sorting + row selection, watchlist star/click, favorites page, portfolio P/L display, chart rendering, debug drawer (dev mode), system guide modal open/close
- No automated visual regression tests exist currently
