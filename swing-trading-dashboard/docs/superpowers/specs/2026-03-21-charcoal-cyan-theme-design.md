# Charcoal + Cyan Theme — Design Spec

**Date:** 2026-03-21
**Status:** Approved by user

---

## Goal

Replace the current blue-tinted dark theme with a pure charcoal (neutral grey) palette, and replace the amber `#F5A623` accent with a bright-soft cyan `#50d8f0`. All signal colors (green, red) and layout are unchanged.

---

## Scope

Two files only:

| File | Action |
|------|--------|
| `frontend/src/index.css` | Update `:root` CSS variables |
| `frontend/tailwind.config.js` | Update `t.*` color tokens to match |

No component files change. No layout changes. No new components.

---

## Color Changes

### Backgrounds & Surfaces (remove all blue tint)

| Variable | Old | New |
|----------|-----|-----|
| `--bg` | `#000000` | `#000000` (unchanged) |
| `--surface` | `#080c12` | `#0d0d0d` |
| `--panel` | `#0c111a` | `#111111` |
| `--card` | `#0f1520` | `#131313` |
| `--card-border` | `#1e2d42` | `#222222` |
| `--border` | `#1a2535` | `#1e1e1e` |
| `--border-light` | `#253347` | `#2a2a2a` |

### Text

| Variable | Old | New |
|----------|-----|-----|
| `--text` | `#c8cdd6` | `#e0e0e0` |
| `--muted` | `#4a5a72` | `#555555` |

### Accent — amber → cyan

| Variable | Old | New |
|----------|-----|-----|
| `--accent` | `#F5A623` | `#50d8f0` |

### RS Blue Dot — shift to avoid clash with new accent

| Variable | Old | New |
|----------|-----|-----|
| `--blue` | `#00C8FF` | `#4a9eff` |

### Unchanged

| Variable | Value |
|----------|-------|
| `--go` | `#00c87a` |
| `--halt` | `#ff2d55` |
| `--purple` | `#9B6EFF` |
| `--radius-card` | `12px` |
| `--shadow-card` | `0 4px 24px rgba(0,0,0,0.5)` |

---

## Shadcn Variables (index.css)

Shadcn vars live in the same `:root` block and must mirror the palette:

| Variable | Old | New |
|----------|-----|-----|
| `--background` | `#000000` | `#000000` |
| `--foreground` | `#c8cdd6` | `#e0e0e0` |
| `--card-foreground` | `#c8cdd6` | `#e0e0e0` |
| `--primary` | `#F5A623` | `#50d8f0` |
| `--primary-foreground` | `#000000` | `#000000` |
| `--secondary` | `#1a2535` | `#1e1e1e` |
| `--secondary-foreground` | `#c8cdd6` | `#e0e0e0` |
| `--muted-foreground` | `#4a5a72` | `#555555` |
| `--accent-foreground` | `#c8cdd6` | `#e0e0e0` |
| `--destructive` | `#ff2d55` | `#ff2d55` (unchanged) |
| `--popover` | `#0f1520` | `#131313` |
| `--popover-foreground` | `#c8cdd6` | `#e0e0e0` |
| `--ring` | `#F5A623` | `#50d8f0` |
| `--input` | `#1a2535` | `#1e1e1e` |
| `--destructive-foreground` | `#ffffff` | `#ffffff` (unchanged) |
| `--radius` | `0.5rem` | `0.5rem` (unchanged) |
| `--radius-md` | `0.375rem` | `0.375rem` (unchanged) |

---

## Tailwind Config Changes (tailwind.config.js)

The `t` color namespace must be updated to match. Derived `Dim` variants are updated proportionally (same hue, lower lightness/opacity):

| Token | Old | New |
|-------|-----|-----|
| `t.surface` | `#080c12` | `#0d0d0d` |
| `t.panel` | `#0c111a` | `#111111` |
| `t.card` | `#0f1520` | `#131313` |
| `t.cardBorder` | `#1e2d42` | `#222222` |
| `t.border` | `#1a2535` | `#1e1e1e` |
| `t.borderLight` | `#253347` | `#2a2a2a` |
| `t.text` | `#c8cdd6` | `#e0e0e0` |
| `t.muted` | `#4a5a72` | `#555555` |
| `t.accent` | `#F5A623` | `#50d8f0` |
| `t.accentDim` | `#7a5010` | `#0d4050` |
| `t.blue` | `#00C8FF` | `#4a9eff` |
| `t.blueDim` | `#003a50` | `#0a1f3a` |

Unchanged tokens: `t.bg`, `t.go`, `t.goDim`, `t.halt`, `t.haltDim`, `t.purple`, `t.pink`.

---

## Hardcoded Accent Colors (index.css)

`.row-near-entry` in `index.css` contains hardcoded `rgba(245,166,35,...)` values (old amber) that are not CSS variables and must be updated manually:

| Selector | Old | New |
|----------|-----|-----|
| `.row-near-entry td` background | `rgba(245,166,35,0.035)` | `rgba(80,216,240,0.035)` |
| `.row-near-entry td:first-child` border-left | `rgba(245,166,35,0.65)` | `rgba(80,216,240,0.65)` |

---

## Selection & Scrollbar (index.css)

| Element | Old | New |
|---------|-----|-----|
| `::selection` background | `rgba(245,166,35,0.25)` | `rgba(80,216,240,0.2)` |
| `::-webkit-scrollbar-thumb:hover` | `var(--accent)` | `var(--accent)` (auto-updated via var) |

---

## nav-btn.active (index.css)

The active nav button currently uses green (`--go`) for its glow. This is intentional — active page = positive/active state — leave unchanged.

---

## What does NOT change

- Layout, spacing, typography, font sizes
- Component files (`.jsx`)
- Signal semantics: green = positive/go, red = halt/stop
- `--go`, `--halt`, `--purple` values
- Animation keyframes
- Box shadow values
- All `goDim`, `haltDim` dim variants
