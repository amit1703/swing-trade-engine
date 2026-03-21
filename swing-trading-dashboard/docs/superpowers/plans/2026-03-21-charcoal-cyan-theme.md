# Charcoal + Cyan Theme Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the blue-tinted dark theme with a pure charcoal palette and swap the amber accent (`#F5A623`) for bright-soft cyan (`#50d8f0`).

**Architecture:** All color definitions live in exactly two files — `frontend/src/index.css` (CSS custom properties + hardcoded rgba values) and `frontend/tailwind.config.js` (Tailwind `t.*` tokens). No component files change. The update is a direct value substitution across both files plus three hardcoded rgba instances.

**Tech Stack:** CSS custom properties, Tailwind CSS v3, React 18 + Vite.

---

## File Map

| File | Action |
|------|--------|
| `frontend/src/index.css` | Update `:root` variables + 3 hardcoded `rgba(245,166,35,...)` values |
| `frontend/tailwind.config.js` | Update `t.*` color tokens |

---

## Task 1: Update index.css

**Files:**
- Modify: `frontend/src/index.css`

- [ ] **Step 1: Read the file**

Read `frontend/src/index.css` in full before editing.

- [ ] **Step 2: Replace the `:root` block**

Replace the entire `:root { ... }` block (lines 8–44) with:

```css
:root {
  --bg:           #000000;
  --surface:      #0d0d0d;
  --panel:        #111111;
  --card:         #131313;
  --card-border:  #222222;
  --border:       #1e1e1e;
  --border-light: #2a2a2a;
  --text:         #e0e0e0;
  --muted:        #555555;
  --accent:       #50d8f0;
  --go:           #00c87a;
  --halt:         #ff2d55;
  --blue:         #4a9eff;
  --purple:       #9B6EFF;
  --radius-card:  12px;
  --shadow-card:  0 4px 24px rgba(0,0,0,0.5);

  /* shadcn/ui required variables — hex format, matching our palette */
  --background:            #000000;
  --foreground:            #e0e0e0;
  --card-foreground:       #e0e0e0;
  --primary:               #50d8f0;
  --primary-foreground:    #000000;
  --secondary:             #1e1e1e;
  --secondary-foreground:  #e0e0e0;
  --muted-foreground:      #555555;
  --accent-foreground:     #e0e0e0;
  --destructive:           #ff2d55;
  --destructive-foreground:#ffffff;
  --popover:               #131313;
  --popover-foreground:    #e0e0e0;
  --ring:                  #50d8f0;
  --input:                 #1e1e1e;
  --radius:                0.5rem;
  --radius-md:             0.375rem;
}
```

- [ ] **Step 3: Update `::selection`**

Find and replace:
```css
::selection { background: rgba(245,166,35,0.25); color: #fff; }
```
with:
```css
::selection { background: rgba(80,216,240,0.2); color: #fff; }
```

- [ ] **Step 4: Update `.row-near-entry` hardcoded amber values**

Find and replace the `.row-near-entry` block:
```css
  .row-near-entry td {
    background: rgba(245,166,35,0.035) !important;
  }
  .row-near-entry td:first-child {
    border-left: 3px solid rgba(245,166,35,0.65) !important;
    padding-left: 5px !important;
  }
```
with:
```css
  .row-near-entry td {
    background: rgba(80,216,240,0.035) !important;
  }
  .row-near-entry td:first-child {
    border-left: 3px solid rgba(80,216,240,0.65) !important;
    padding-left: 5px !important;
  }
```

- [ ] **Step 5: Verify no amber hex values remain**

Run:
```bash
grep -n "F5A623\|245,166,35" frontend/src/index.css
```
Expected: no output (zero matches).

- [ ] **Step 6: Commit index.css**

```bash
git add frontend/src/index.css
git commit -m "feat: charcoal+cyan theme — update index.css variables"
```

---

## Task 2: Update tailwind.config.js

**Files:**
- Modify: `frontend/tailwind.config.js`

- [ ] **Step 1: Read the file**

Read `frontend/tailwind.config.js` in full before editing.

- [ ] **Step 2: Replace the `t` color object**

Find the `t: { ... }` block inside `theme.extend.colors` and replace it with:

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

- [ ] **Step 3: Verify no amber hex values remain**

```bash
grep -n "F5A623\|7a5010\|003a50" frontend/tailwind.config.js
```
Expected: no output.

- [ ] **Step 4: Build check**

```bash
cd frontend && npx vite build 2>&1 | tail -10
```
Expected: `✓ built in` with no errors. Warnings about chunk size are fine.

- [ ] **Step 5: Commit tailwind.config.js**

```bash
cd ..
git add frontend/tailwind.config.js
git commit -m "feat: charcoal+cyan theme — update tailwind color tokens"
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

After deploying, check:
- [ ] Backgrounds are neutral dark grey (no blue tint visible)
- [ ] Selected row highlights in cyan, not amber
- [ ] Active nav item is cyan, not amber
- [ ] Sort arrows in watchlist/scanner are cyan
- [ ] RS blue dot (●) is visually distinct from the cyan accent (it should look more blue)
- [ ] Green signals (`#00c87a`) and red stop-loss (`#ff2d55`) unchanged
- [ ] Scanner "near-entry" row stripe is cyan-tinted, not amber
