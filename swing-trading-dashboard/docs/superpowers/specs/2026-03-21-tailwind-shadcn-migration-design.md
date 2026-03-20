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

**CSS variables already exist** in `src/index.css`: `--accent`, `--go`, `--halt`, `--muted`, `--panel`, `--card`, `--border`, `--text`, etc.

**shadcn/ui is NOT installed** — that is the only dependency gap.

**Existing components use inline CSS exclusively** — Tailwind classes are defined in the config but largely unused in the `.jsx` component files.

---

## Color Palette

All color tokens already exist. Components should use Tailwind classes that reference `t.*` tokens.

| Tailwind class | Value | Usage |
|----------------|-------|-------|
| `bg-t-bg` | `#000000` | Root app background |
| `bg-t-panel` | `#0c111a` | Sidebar, header panels |
| `bg-t-card` | `#0f1520` | Card surfaces |
| `border-t-cardBorder` | `#1e2d42` | Card borders |
| `border-t-border` | `#1a2535` | Dividers |
| `text-t-text` | `#c8cdd6` | Primary body text |
| `text-t-muted` | `#4a5a72` | Secondary/label text |
| `text-t-accent` | `#F5A623` | Active nav, selected rows |
| `text-t-go` | `#00c87a` | Bullish signals, profit |
| `text-t-halt` | `#ff2d55` | Stop losses, loss |
| `text-t-blue` | `#00C8FF` | RS blue dot, info |

**Dynamic signal colors** (computed per-row in JS) must stay as inline `style={{ color: 'var(--go)' }}` — Tailwind cannot resolve dynamically-constructed class names. Static uses (e.g., a known "profit" state) can use `text-t-go` class.

---

## Architecture

### Layer 0 — shadcn/ui Setup (one-time, no Tailwind install needed)

Tailwind, PostCSS, and Autoprefixer are already installed. Only shadcn/ui needs to be added.

1. **Configure path alias in `vite.config.js`** — shadcn/ui expects an `@/` import alias:
   ```js
   import path from 'path'
   // in defineConfig:
   resolve: {
     alias: { '@': path.resolve(__dirname, './src') }
   }
   ```

2. **Create `jsconfig.json`** at `frontend/` root so VS Code resolves the alias:
   ```json
   { "compilerOptions": { "baseUrl": ".", "paths": { "@/*": ["./src/*"] } } }
   ```

3. **Run shadcn init** — answer the wizard for a plain-JS Vite project:
   ```bash
   npx shadcn@latest init
   ```
   Wizard answers:
   - Style: Default
   - Base color: Neutral (we override with our tokens anyway)
   - **TypeScript: No** (project is plain JS — critical, must say No)
   - CSS variables: Yes
   - Global CSS file: `src/index.css`
   - Tailwind config: `tailwind.config.js`
   - Components alias: `@/components`
   - Utils alias: `@/lib/utils`

   This generates `src/components/ui/` (`.jsx` files) and `src/lib/utils.js`.

4. **Reconcile generated CSS variables** — shadcn's init appends its own `:root` block to `index.css`. After init, merge the shadcn-generated variables with the existing block:
   - Keep all existing `--bg`, `--panel`, `--card`, `--accent`, `--go`, `--halt`, etc. unchanged
   - Map shadcn's expected variables to our palette (shadcn uses `--background`, `--foreground`, `--primary`, etc.):
   ```css
   :root {
     /* shadcn/ui required variables — mapped to our palette */
     --background: 0 0% 0%;           /* maps to #000000 (hsl format) */
     --foreground: 218 16% 79%;       /* maps to #c8cdd6 */
     --card: 222 27% 9%;              /* maps to #0f1520 */
     --card-foreground: 218 16% 79%;
     --popover: 222 27% 9%;
     --popover-foreground: 218 16% 79%;
     --primary: 38 90% 54%;           /* maps to #F5A623 */
     --primary-foreground: 0 0% 0%;
     --secondary: 220 27% 16%;        /* maps to #1a2535 */
     --secondary-foreground: 218 16% 79%;
     --muted: 220 27% 16%;
     --muted-foreground: 220 15% 37%; /* maps to #4a5a72 */
     --accent: 220 27% 16%;
     --accent-foreground: 218 16% 79%;
     --destructive: 349 100% 59%;     /* maps to #ff2d55 */
     --destructive-foreground: 0 0% 100%;
     --border: 220 28% 16%;           /* maps to #1a2535 */
     --input: 220 28% 16%;
     --ring: 38 90% 54%;              /* matches primary */
     --radius: 0.5rem;
   }
   ```
   Note: shadcn uses HSL format for its CSS variables (`h s% l%`), not hex. Delete the duplicate block shadcn generates and replace with the above.

5. **Install shadcn/ui components:**
   ```bash
   npx shadcn@latest add button card input badge separator
   ```

6. **Update `terminal-table` in `@layer components`** — restyle using the existing CSS variable palette (already defined in `index.css`; no changes needed for Layer 0 — it will be updated in Layer 3 when ScannerTable is migrated).

### Layer 1 — Shell (3 files)

**`App.jsx`** — Outer layout wrapper
- Replace root `div` inline styles with `className="flex h-screen bg-t-bg overflow-hidden"`
- Replace all flex layout wrappers with Tailwind classes
- No logic changes

**`Sidebar.jsx`** — Left navigation
- New structure matching reference design: logo area → nav items → bottom nav
- Background: `bg-t-panel border-r border-t-border`
- Logo: `TrendingUp` icon from lucide in an amber gradient container + `"SCANR"` label in `font-mono text-t-accent`
- Nav items map to our pages: Scanner, Watchlist, Favorites, Portfolio, Analytics, Diagnostics
- Active item: `bg-t-accent/10 text-t-accent border border-t-accent/20`
- Inactive: `text-t-muted hover:bg-white/5 hover:text-t-text`
- Uses shadcn `Button` with `variant="ghost"`
- Bottom: Settings item
- Replaces existing `.nav-btn` CSS class; the new sidebar is wider (full labels visible, not icon-only)

**`TopBar.jsx`** — Top header bar
- Background: `bg-t-panel border-b border-t-border`
- Left: page title (dynamic, from existing `title` variable) + version tag with `Terminal` icon — existing logic unchanged
- Center: search input using shadcn `Input` — existing `searchVal` state and `onSearchTicker` prop are **already wired**; this is a pure restyle of the existing search input
- Right: existing regime badge (restyled with Tailwind), existing scan button (restyled as shadcn `Button`)

### Layer 2 — Page Containers (4 files)

**`Header.jsx`** — Market regime banner + scan trigger
- Restyle wrapper as `bg-t-card border border-t-cardBorder rounded-card shadow-card` using Tailwind; keep all existing props and callbacks
- Regime tier badge: `text-t-accent` for AGGRESSIVE, `text-yellow-400` for SELECTIVE, `text-t-halt` for DEFENSIVE

**`MarketOverview.jsx`** — Market overview cards
- Migrate to shadcn `Card` + `CardHeader` + `CardContent`
- Card base: `bg-t-card border-t-cardBorder shadow-card`

**`StatCards.jsx`** — Summary stat cards
- Same pattern as MarketOverview — shadcn Card, Tailwind layout, colored left border per card type (go/halt/accent)

**`ScannerFilters.jsx`** — Filter bar
- Replace inline div styles with Tailwind flex layout (`flex items-center gap-2 flex-wrap`)
- Active filter buttons: shadcn `Button` with solid amber style; inactive: `variant="outline"` with muted text

### Layer 3 — Inner Components (10 files)

All components in Layer 3: **props and behavior unchanged, styling migrated.**

**`ScannerTable.jsx`**
- Table wrapper: `bg-t-card border border-t-cardBorder rounded-card shadow-card overflow-hidden`
- Update `.terminal-table` in `@layer components` to use Tailwind `@apply` directives matching existing visual style
- Row hover: `hover:bg-white/[0.025]`; selected: `bg-t-accent/5 border-l-2 border-t-accent`
- Setup type badges: keep inline color style (dynamic per type)
- EARLY/OPTIMAL/EXTENDED badges: shadcn `Badge` with variant
- Show/hide extended button: shadcn `Button variant="ghost"`

**`WatchlistPanel.jsx`**
- Panel shell: `bg-t-panel` with Tailwind padding/flex
- Watch rows: Tailwind hover + amber left border for selected
- Star button and TV link: restyle padding/color with Tailwind

**`FavoritesPage.jsx`**
- Empty state: Tailwind flex centering
- Setup rows: same migration pattern as ScannerTable rows
- Full inline CSS → Tailwind

**`SetupTable.jsx`**
- Same migration pattern as ScannerTable
- `accentColor` prop still drives header border (kept as inline style — dynamic value)

**`StockIntelPanel.jsx`**
- Panel wrapper: `bg-t-panel` with Tailwind padding/flex
- Section cards: shadcn `Card` with `bg-t-card`
- Trade plan grid: Tailwind grid layout
- Signal pills: shadcn `Badge`

**`PortfolioTab.jsx`**
- Table migrated same as ScannerTable
- P/L values: inline style for dynamic color, Tailwind for layout

**`DiagnosticsTab.jsx`**, **`BacktestPanel.jsx`**, **`EngineHealthPanel.jsx`**
- Card wrappers → shadcn Card
- Layout → Tailwind grid/flex
- Data values → keep inline style for dynamic signal colors

**`DebugDrawer.jsx`**
- Dev-mode overlay: wrapper + panel → Tailwind sizing/positioning classes
- Content layout → Tailwind; keep any signal colors as inline style

**`SystemGuideModal.jsx`**
- Modal shell → shadcn/ui does not include a modal component in our install list; use existing overlay approach restyled with Tailwind classes
- Inner content layout → Tailwind

**`TradingChart.jsx`**
- Wrapper div: `bg-t-panel rounded-card border border-t-cardBorder` + Tailwind sizing
- Toolbar buttons: shadcn `Button variant="ghost"`
- Chart canvas: untouched

---

## Migration Order & Commit Strategy

Each layer is a separate commit (or group of commits). The app is functional after each layer.

1. **Layer 0:** `chore: install shadcn/ui, configure @/ alias, reconcile CSS variables`
2. **Layer 1:** `feat(ui): migrate shell — App, Sidebar, TopBar`
3. **Layer 2:** `feat(ui): migrate page containers — Header, MarketOverview, StatCards, ScannerFilters`
4. **Layer 3:** One commit per component: `feat(ui): migrate ScannerTable to Tailwind`, etc.

---

## Testing

- After each layer commit: open app in browser, verify all pages render without console errors
- After Layer 1: confirm page switching still works, sidebar active state updates on click
- After Layer 2: confirm scan trigger, filter toggles, regime display work
- After Layer 3: confirm scanner table sorting + row selection, watchlist star/click, favorites page, portfolio P/L display, chart rendering, debug drawer (dev mode), system guide modal
- No automated visual regression tests (none exist currently)
