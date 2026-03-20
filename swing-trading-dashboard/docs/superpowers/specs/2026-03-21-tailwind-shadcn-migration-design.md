# Tailwind + shadcn/ui Migration Design

## Overview

Migrate the React frontend from inline CSS to Tailwind CSS + shadcn/ui component library, applying a polished dark terminal aesthetic inspired by a provided reference design. The migration is styling-only — no changes to props, state, API calls, or business logic.

---

## Goals

- Replace inline `style={{}}` props with Tailwind utility classes across all frontend components
- Install shadcn/ui for primitive components (Button, Card, Badge, Input, Separator)
- Apply consistent dark theme: near-black backgrounds, amber accent, glass-morphism cards
- Keep trading signal colors (`--go`, `--halt`, `--accent`) as CSS variables for dynamic use
- App stays fully functional throughout the migration (layered approach)

## Non-Goals

- No TypeScript migration
- No changes to App.jsx state management or routing
- No changes to backend
- No new features or behavioral changes
- No changes to lightweight-charts canvas rendering in TradingChart.jsx

---

## Color Palette

| Token | Value | Usage |
|-------|-------|-------|
| App background | `#0f0f14` | Root div |
| Sidebar + header bg | `#0a0a0f` | Sidebar, TopBar |
| Card surface | `gray-900/50` + `backdrop-blur-sm` | All card panels |
| Amber accent | `#F5A623` (`amber-400`) | Active nav, selected rows, highlights |
| Go (bullish) | `#00C87A` (`--go`) | Positive signals, profit |
| Halt (bearish) | `#FF2D55` (`--halt`) | Stop losses, loss |
| Muted text | `gray-500` | Labels, secondary text |
| Border | `gray-800` | Dividers, card borders |
| Body text | `gray-200` | Primary text |

Trading signal colors (`--go`, `--halt`, `--accent`) are kept as CSS variables and applied via inline `style` or a thin set of CSS utility classes — Tailwind cannot resolve dynamic CSS variable references in class names.

---

## Architecture

### Dependency Setup (Layer 0 — one-time)

1. Install Tailwind CSS v3 + PostCSS + Autoprefixer into `frontend/`
2. Create `tailwind.config.js` extending Tailwind's default theme:
   - Custom color `amber.400 = #F5A623`
   - Extend `fontFamily.mono` to include `"IBM Plex Mono"`
   - Content paths: `./src/**/*.{js,jsx}`
3. Create `postcss.config.js`
4. Update `src/styles/index.css`:
   - Add `@tailwind base`, `@tailwind components`, `@tailwind utilities` directives at top
   - Keep existing CSS variables in `:root` (all `--panel`, `--accent`, `--go`, etc.)
   - Add shadcn/ui required CSS variables (background, foreground, card, etc.) mapped to our palette
   - Restyle `.terminal-table` inside `@layer components` to match new palette
5. Run `npx shadcn@latest init` → generates `src/components/ui/` with primitives
6. Install shadcn/ui components: `button`, `card`, `input`, `badge`, `separator`

### Layer 1 — Shell (3 files)

**`App.jsx`** — Outer layout wrapper
- Replace root `div` inline styles with `className="flex h-screen bg-[#0f0f14] overflow-hidden"`
- Replace flex layout wrappers with Tailwind classes
- No logic changes

**`Sidebar.jsx`** — Left navigation
- New structure matching reference design: logo area → nav items → bottom nav
- Logo: gradient icon (`TrendingUp` from lucide) + "SCANNER" monospace label
- Nav items map to existing pages: Scanner, Watchlist, Portfolio, Analytics, Diagnostics
- Active item style: `bg-amber-500/10 text-amber-400 border border-amber-500/20`
- Inactive: `text-gray-400 hover:bg-gray-800 hover:text-gray-200`
- Bottom section: Settings item
- Uses shadcn `Button` component with `variant="ghost"`

**`TopBar.jsx`** — Top header bar
- Background: `bg-[#0a0a0f] border-b border-gray-800`
- Left: page title (dynamic, based on active page) + version tag with `Terminal` icon
- Center: search input (shadcn `Input`) wired to existing `filters.searchQuery`
- Right: regime badge (AGGRESSIVE=amber, SELECTIVE=yellow, DEFENSIVE=red) + scan button

### Layer 2 — Page Containers (4 files)

**`Header.jsx`** — Market regime banner + scan trigger
- Restyle as a card-like banner using Tailwind; keep all existing props and callbacks
- Regime score displayed as a progress-bar-style indicator

**`MarketOverview.jsx`** — Market overview cards
- Migrate to shadcn `Card` + `CardHeader` + `CardContent`
- Stat cards match reference design: colored icon badge + value + trend indicator

**`StatCards.jsx`** — Summary stat cards
- Same pattern as MarketOverview — shadcn Card, Tailwind layout, colored borders per card type

**`ScannerFilters.jsx`** — Filter bar
- Replace inline div styles with Tailwind flex layout
- Filter buttons use shadcn `Button` with `variant="outline"` for inactive, filled for active

### Layer 3 — Inner Components (~9 files)

All components in Layer 3 follow the same rule: **props and behavior unchanged, styling migrated.**

**`ScannerTable.jsx`**
- Table wrapper: `bg-gray-900/50 backdrop-blur-sm border border-gray-800 rounded-lg`
- Header cells: Tailwind text/spacing classes, sort icons kept
- Row hover: `hover:bg-gray-800/50`; selected row: `bg-amber-500/5 border-l-2 border-amber-400`
- Signal badges (EARLY/OPTIMAL/EXTENDED): shadcn `Badge` with variant colors
- Setup type badges: keep inline color style (dynamic per type)
- Show/hide extended button: shadcn `Button`

**`WatchlistPanel.jsx`**
- Panel shell: `bg-[#0a0a0f] border-r border-gray-800`
- Section headers: Tailwind typography
- Watch rows: hover state with Tailwind; selected with amber left border
- TV link and star button: keep as-is, just restyle with Tailwind padding/color classes

**`SetupTable.jsx`**
- Same migration pattern as ScannerTable
- `accentColor` prop still drives the header border (kept as inline style)

**`StockIntelPanel.jsx`**
- Panel wrapper: `bg-[#0a0a0f]` with Tailwind padding/flex
- Section cards: shadcn `Card` with `bg-gray-900/50`
- Trade plan grid: Tailwind grid layout
- Signal pills: shadcn `Badge`

**`PortfolioTab.jsx`**
- Table migrated same as ScannerTable
- P/L values: inline style for dynamic color (--go/--halt), Tailwind for layout

**`DiagnosticsTab.jsx`**, **`BacktestPanel.jsx`**, **`EngineHealthPanel.jsx`**
- Card wrappers → shadcn Card
- Layout → Tailwind grid/flex
- Data values → keep inline style for signal colors

**`TradingChart.jsx`**
- Wrapper div: Tailwind sizing + `bg-[#0a0a0f] rounded-lg border border-gray-800`
- Toolbar buttons: shadcn `Button variant="ghost"`
- Chart canvas itself: untouched

---

## CSS Variable Bridge

The existing CSS variables are preserved and augmented with shadcn/ui expected variables. Key mapping:

```css
:root {
  /* Existing trading variables — unchanged */
  --accent: #F5A623;
  --go: #00C87A;
  --halt: #FF2D55;
  --muted: #6B7280;
  --panel: #0a0a0f;
  --card: #111118;
  --border: #1f2937;
  --text: #e5e7eb;

  /* shadcn/ui variables — mapped to our palette */
  --background: #0f0f14;
  --foreground: #e5e7eb;
  --card-foreground: #e5e7eb;
  --popover: #0a0a0f;
  --popover-foreground: #e5e7eb;
  --primary: #F5A623;
  --primary-foreground: #000000;
  --secondary: #1f2937;
  --secondary-foreground: #e5e7eb;
  --muted-foreground: #6B7280;
  --accent-foreground: #000000;
  --destructive: #FF2D55;
  --destructive-foreground: #ffffff;
  --border: #1f2937;
  --input: #1f2937;
  --ring: #F5A623;
  --radius: 0.5rem;
}
```

---

## `.terminal-table` Migration

The `.terminal-table` class is used in `ScannerTable` and `SetupTable`. It moves into `@layer components` in `index.css`:

```css
@layer components {
  .terminal-table {
    @apply w-full text-xs font-mono border-collapse;
  }
  .terminal-table thead th {
    @apply px-2 py-2 text-gray-500 text-left uppercase tracking-widest font-bold border-b border-gray-800 bg-gray-900/80;
  }
  .terminal-table tbody td {
    @apply px-2 py-2 border-b border-gray-800/50;
  }
  .terminal-table tbody tr:hover {
    @apply bg-gray-800/30;
  }
}
```

---

## Migration Order & Commit Strategy

Each layer is a separate commit (or group of commits). The app is functional after each layer.

1. **Layer 0:** `chore: install tailwind + shadcn/ui, configure theme`
2. **Layer 1:** `feat(ui): migrate shell — App, Sidebar, TopBar`
3. **Layer 2:** `feat(ui): migrate page containers — Header, MarketOverview, StatCards, ScannerFilters`
4. **Layer 3:** Multiple commits per component: `feat(ui): migrate ScannerTable to Tailwind`, etc.

---

## Testing

- After each layer commit: visually verify all pages render without console errors
- After Layer 1: confirm page switching still works
- After Layer 2: confirm scan trigger, filter interactions work
- After Layer 3: confirm scanner table sorting, row selection, watchlist star/click, portfolio P/L display, chart rendering
- No automated visual regression tests (none exist currently)
