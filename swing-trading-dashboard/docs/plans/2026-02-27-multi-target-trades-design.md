# Multi-Target Trades Design

**Goal:** Replace the single `target` field on each trade with 1–3 independent price targets (T1, T2, T3), displayed as separate columns in the portfolio table and entered via a dynamic form.

**Architecture:** Store targets as a JSON array in a new `targets_json` column on the `trades` table. Keep the legacy `target` column for backward compatibility, always written as `targets[0]`. The API and frontend consume the array exclusively.

**Tech Stack:** SQLite (aiosqlite), FastAPI/Pydantic, React 18

---

## Database

One new nullable column added via a safe migration in `init_db()`:

```sql
ALTER TABLE trades ADD COLUMN targets_json TEXT;
```

- `init_db()` runs `ALTER TABLE trades ADD COLUMN targets_json TEXT` wrapped in a try/except to handle "duplicate column" on existing databases.
- **Writing:** `add_trade()` accepts `targets: list[float]` (1–3 items). Serialises to `targets_json`. Writes `targets[0]` to the legacy `target` column so raw DB reads remain valid.
- **Reading:** `get_trades()` returns `"targets": json.loads(targets_json)` if present, else falls back to `[target]`. Old rows are transparently upgraded at read time.

---

## Backend API

**`TradeIn` Pydantic model** — replace `target: float` with:
```python
targets: List[float]   # 1–3 items; validated length 1 ≤ len ≤ 3
```

**`POST /api/trades`** — accepts new model, passes `targets` list to `add_trade()`.

**`GET /api/trades`** — each trade in the response now contains:
```json
{ "targets": [149.00, 156.00] }
```
The `_enrich_trade()` health/P&L logic is untouched — it doesn't reference targets.

---

## Frontend — AddTradeModal (PortfolioTab.jsx)

Replace the single "Target $" field with a dynamic 1–3 target section:

- **T1** — always visible, required. Auto-filled by the position sizer at 2:1 R:R (same as today).
- **T2** — hidden until user clicks `+ T2`. Shows a number input. Removable via `× remove`.
- **T3** — hidden until user clicks `+ T3` (only after T2 is added). Same pattern.
- Quick-fill buttons next to T2/T3: `+1R` and `+2R` (fills `entry + N × risk`) to save manual math.
- Validation: all entered targets must be > entry price; T2 > T1 if both present; T3 > T2 if all three present.
- The position sizer button still fills T1 (2:1) and quantity; T2/T3 remain manual.

Form state change:
```js
// Before
{ target: '' }

// After
{ targets: ['', '', ''] }   // indices 0–2; empty string = not set
```

Submission sends `targets` array of only the non-empty numeric values.

---

## Frontend — PortfolioTab Table

Replace the single "Target $" column with three columns:

| T1 $ | T2 $ | T3 $ |
|------|------|------|
| 149.00 | 156.00 | — |

- All three columns use `color: var(--go)` (green), same as the old Target column.
- If T2 or T3 is not set, render `<Dash />` (existing helper).
- The `take_profit` field from scan setups (used elsewhere) is unaffected.

---

## api.js

`addTrade()` passes `targets` array in the request body. The existing fetch wrapper handles the change with no structural modification.

---

## Migration Safety

- Existing trades in the DB have `targets_json = NULL`. `get_trades()` falls back to `[target]` for these rows, so they render as T1-only trades with T2/T3 showing `—`.
- No data loss. No manual DB edits needed.
