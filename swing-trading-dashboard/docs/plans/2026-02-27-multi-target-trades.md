# Multi-Target Trades Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the single `target` field on each trade with 1–3 independent price targets (T1/T2/T3), stored as a JSON array, displayed as separate table columns, and entered via a dynamic form.

**Architecture:** Add a nullable `targets_json TEXT` column to the `trades` SQLite table. Keep the existing `target` column written as `targets[0]` for backward compatibility. The API reads `targets_json` and falls back to `[target]` for old rows. Frontend form grows T2/T3 fields dynamically; portfolio table replaces one Target column with three.

**Tech Stack:** Python/aiosqlite (DB), FastAPI/Pydantic (API), React 18 (frontend)

---

### Task 1: DB migration — add `targets_json` column

**Files:**
- Modify: `swing-trading-dashboard/backend/database.py`
- Create:  `swing-trading-dashboard/backend/tests/test_trades_db.py`

**Context:**
`database.py` holds all SQLite logic. `init_db()` creates tables. `add_trade()` inserts a row. `get_trades()` fetches rows. The `trades` table currently has a single `target REAL NOT NULL` column. We add `targets_json TEXT` (nullable) and migrate the read/write helpers. `json` is already imported in the file.

**Step 1: Write the failing tests**

Create `swing-trading-dashboard/backend/tests/test_trades_db.py`:

```python
"""Tests for multi-target trades DB layer."""
import asyncio
import json
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from database import init_db, add_trade, get_trades


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def tmp_db(tmp_path):
    db = str(tmp_path / "test.db")
    run(init_db(db))
    return db


def test_add_trade_single_target_returns_targets_list(tmp_db):
    """add_trade with targets=[150.0] → get_trades returns targets=[150.0]."""
    run(add_trade(tmp_db, {
        "ticker": "AAPL",
        "entry_price": 140.0,
        "quantity": 10,
        "stop_loss": 135.0,
        "targets": [150.0],
        "entry_date": "2026-01-01",
    }))
    trades = run(get_trades(tmp_db))
    assert len(trades) == 1
    assert trades[0]["targets"] == [150.0]


def test_add_trade_two_targets(tmp_db):
    """add_trade with targets=[150, 160] → get_trades returns both."""
    run(add_trade(tmp_db, {
        "ticker": "NVDA",
        "entry_price": 140.0,
        "quantity": 5,
        "stop_loss": 134.0,
        "targets": [150.0, 160.0],
        "entry_date": "2026-01-01",
    }))
    trades = run(get_trades(tmp_db))
    assert trades[0]["targets"] == [150.0, 160.0]


def test_add_trade_three_targets(tmp_db):
    """add_trade with three targets → all three returned."""
    run(add_trade(tmp_db, {
        "ticker": "TSLA",
        "entry_price": 200.0,
        "quantity": 3,
        "stop_loss": 192.0,
        "targets": [210.0, 220.0, 230.0],
        "entry_date": "2026-01-01",
    }))
    trades = run(get_trades(tmp_db))
    assert trades[0]["targets"] == [210.0, 220.0, 230.0]


def test_legacy_row_fallback(tmp_db):
    """Rows with targets_json=NULL fall back to [target] — backward compat."""
    import aiosqlite

    async def _insert_legacy(db_path):
        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                """INSERT INTO trades
                   (ticker, entry_price, quantity, stop_loss, target, entry_date)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                ("MSFT", 300.0, 2, 290.0, 315.0, "2025-12-01"),
            )
            await db.commit()

    run(_insert_legacy(tmp_db))
    trades = run(get_trades(tmp_db))
    # Legacy row: targets_json is NULL, should fall back to [target]
    assert trades[0]["targets"] == [315.0]


def test_legacy_target_col_written_as_t1(tmp_db):
    """add_trade sets target column = targets[0] for backward compat."""
    import aiosqlite

    run(add_trade(tmp_db, {
        "ticker": "GOOG",
        "entry_price": 180.0,
        "quantity": 4,
        "stop_loss": 174.0,
        "targets": [190.0, 200.0],
        "entry_date": "2026-01-02",
    }))

    async def _raw_target(db_path):
        async with aiosqlite.connect(db_path) as db:
            async with db.execute("SELECT target FROM trades WHERE ticker='GOOG'") as cur:
                row = await cur.fetchone()
                return row[0]

    raw_target = run(_raw_target(tmp_db))
    assert raw_target == 190.0
```

**Step 2: Run tests to confirm they fail**

```bash
cd swing-trading-dashboard/backend
python -m pytest tests/test_trades_db.py -v
```

Expected: all 5 tests FAIL (add_trade/get_trades signatures don't match yet).

**Step 3: Implement the migration in `database.py`**

3a. In `init_db()`, add the migration after `await db.commit()` (around line 107):

```python
async def init_db(db_path: str) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(_CREATE_SCAN_RUNS)
        await db.execute(_CREATE_MARKET_REGIME)
        await db.execute(_CREATE_SCAN_SETUPS)
        await db.execute(_CREATE_SR_ZONES)
        await db.execute(_CREATE_TRADES)
        for idx_sql in _INDEXES:
            await db.execute(idx_sql)
        await db.commit()
        # Migration: add targets_json column if it does not yet exist
        try:
            await db.execute("ALTER TABLE trades ADD COLUMN targets_json TEXT")
            await db.commit()
        except Exception:
            pass  # column already exists — safe to ignore
```

3b. Replace `add_trade()` (lines 308–325) with:

```python
async def add_trade(db_path: str, trade: Dict) -> int:
    """Insert a new active trade; returns the new row id."""
    targets = trade.get("targets") or [trade["target"]]
    targets_json = json.dumps([float(t) for t in targets])
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            """INSERT INTO trades
               (ticker, entry_price, quantity, stop_loss, target, targets_json, entry_date, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                trade["ticker"].upper(),
                trade["entry_price"],
                trade["quantity"],
                trade["stop_loss"],
                float(targets[0]),
                targets_json,
                trade["entry_date"],
                trade.get("notes", ""),
            ),
        )
        await db.commit()
        return cur.lastrowid
```

3c. Replace `get_trades()` (lines 328–352) with:

```python
async def get_trades(db_path: str, status: str = "active") -> List[Dict]:
    """Return all trades with the given status."""
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            """SELECT id, ticker, entry_price, quantity, stop_loss, target, targets_json,
                      entry_date, notes, status, created_at
               FROM trades WHERE status = ? ORDER BY created_at DESC""",
            (status,),
        ) as cur:
            rows = await cur.fetchall()
            result = []
            for r in rows:
                targets = json.loads(r[6]) if r[6] else [r[5]]
                result.append({
                    "id":          r[0],
                    "ticker":      r[1],
                    "entry_price": r[2],
                    "quantity":    r[3],
                    "stop_loss":   r[4],
                    "target":      r[5],
                    "targets":     targets,
                    "entry_date":  r[7],
                    "notes":       r[8],
                    "status":      r[9],
                    "created_at":  r[10],
                })
            return result
```

**Step 4: Run tests to confirm they pass**

```bash
cd swing-trading-dashboard/backend
python -m pytest tests/test_trades_db.py -v
```

Expected: all 5 tests PASS.

**Step 5: Run full test suite to confirm no regressions**

```bash
python -m pytest tests/ -v
```

Expected: all tests PASS (green).

**Step 6: Commit**

```bash
git add backend/database.py backend/tests/test_trades_db.py
git commit -m "feat(db): add targets_json column; support 1-3 price targets per trade"
```

---

### Task 2: Backend API — update `TradeIn` model and endpoint

**Files:**
- Modify: `swing-trading-dashboard/backend/main.py:931-938` (TradeIn model)
- Modify: `swing-trading-dashboard/backend/main.py:1007-1011` (create_trade endpoint)
- Modify: `swing-trading-dashboard/backend/tests/test_trades_db.py` (add API model tests)

**Context:**
`TradeIn` (line 931) is the Pydantic request body for `POST /api/trades`. It currently has `target: float`. We replace it with `targets: List[float]` validated to 1–3 items. `main.py` already imports `List` from `typing` (line 37). Pydantic v2 uses `Field` with `min_length`/`max_length` for list validation.

**Step 1: Write the failing test**

Add to `backend/tests/test_trades_db.py`:

```python
def test_trade_in_model_rejects_empty_targets():
    """TradeIn must reject an empty targets list."""
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    from main import TradeIn
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        TradeIn(
            ticker="AAPL", entry_price=140, quantity=10,
            stop_loss=135, targets=[], entry_date="2026-01-01"
        )


def test_trade_in_model_rejects_four_targets():
    """TradeIn must reject more than 3 targets."""
    from main import TradeIn
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        TradeIn(
            ticker="AAPL", entry_price=140, quantity=10,
            stop_loss=135, targets=[150, 160, 170, 180], entry_date="2026-01-01"
        )


def test_trade_in_model_accepts_one_to_three():
    """TradeIn accepts 1, 2, or 3 targets."""
    from main import TradeIn
    m1 = TradeIn(ticker="A", entry_price=100, quantity=1, stop_loss=95, targets=[110], entry_date="2026-01-01")
    assert m1.targets == [110]
    m3 = TradeIn(ticker="B", entry_price=100, quantity=1, stop_loss=95, targets=[110,120,130], entry_date="2026-01-01")
    assert len(m3.targets) == 3
```

**Step 2: Run to confirm failure**

```bash
cd swing-trading-dashboard/backend
python -m pytest tests/test_trades_db.py::test_trade_in_model_rejects_empty_targets -v
```

Expected: ImportError or AttributeError (model has `target` not `targets`).

**Step 3: Update `TradeIn` in `main.py`**

Replace lines 931–938:

```python
class TradeIn(BaseModel):
    ticker:      str
    entry_price: float
    quantity:    float
    stop_loss:   float
    targets:     List[float] = Field(..., min_length=1, max_length=3)
    entry_date:  str
    notes:       str = ""
```

Also add `Field` to the pydantic import at the top of main.py (line 46):
```python
from pydantic import BaseModel, Field
```

The `create_trade` endpoint (line 1007–1011) needs no changes — `body.model_dump()` already includes `targets`.

**Step 4: Run the new tests**

```bash
python -m pytest tests/test_trades_db.py -v
```

Expected: all 8 tests PASS.

**Step 5: Run full test suite**

```bash
python -m pytest tests/ -v
```

Expected: all tests PASS.

**Step 6: Commit**

```bash
git add backend/main.py backend/tests/test_trades_db.py
git commit -m "feat(api): replace target float with targets list (1-3) in TradeIn model"
```

---

### Task 3: Frontend — dynamic T1/T2/T3 form in AddTradeModal

**Files:**
- Modify: `swing-trading-dashboard/frontend/src/components/PortfolioTab.jsx`

**Context:**
`AddTradeModal` is defined at line 283 of `PortfolioTab.jsx`. It currently has a single "Target $" `ModalField` (line 480–487) and a `calcPositionSize` function (line 306–311) that sets `form.target`. We replace the single field with a dynamic section showing T1 always, T2/T3 revealed by clicking buttons. The `addTrade` API function in `api.js` uses `JSON.stringify(body)` so no change is needed there — passing `targets: [...]` instead of `target: ...` just works.

**Step 1: Update form state — replace `target` with `targets`**

In `AddTradeModal`, find the `useState` for `form` (line 284–292). Replace:

```js
// BEFORE
const [form, setForm] = useState({
    ticker:      '',
    entry_price: '',
    stop_loss:   '',
    quantity:    '',
    target:      '',
    entry_date:  new Date().toISOString().slice(0, 10),
    notes:       '',
})
```

With:

```js
// AFTER
const [form, setForm] = useState({
    ticker:      '',
    entry_price: '',
    stop_loss:   '',
    quantity:    '',
    targets:     ['', '', ''],   // [T1, T2, T3] — empty string = not set
    entry_date:  new Date().toISOString().slice(0, 10),
    notes:       '',
})
const [targetCount, setTargetCount] = useState(1)
```

**Step 2: Update `calcPositionSize` to fill T1**

Replace (line 306–311):

```js
// BEFORE
const calcPositionSize = () => {
    if (risk <= 0) { setError('Entry must be greater than Stop Loss'); return }
    const qty = Math.floor(RISK_AMOUNT / risk)
    const tgt = +(entry + 2 * risk).toFixed(2)
    setForm((f) => ({ ...f, quantity: String(qty), target: String(tgt) }))
    setError('')
}
```

With:

```js
// AFTER
const calcPositionSize = () => {
    if (risk <= 0) { setError('Entry must be greater than Stop Loss'); return }
    const qty = Math.floor(RISK_AMOUNT / risk)
    const t1  = +(entry + 2 * risk).toFixed(2)
    setForm((f) => {
        const targets = [...f.targets]
        targets[0] = String(t1)
        return { ...f, quantity: String(qty), targets }
    })
    setError('')
}
```

**Step 3: Update the position sizer preview label**

Find the sizer preview span (line 441–446). Replace `2:1 target: $...` reference:

```js
// BEFORE
: <span className="text-t-accent font-600">{Math.floor(RISK_AMOUNT / risk)} shares  ·  2:1 target: ${+(entry + 2*risk).toFixed(2)}</span>
```

With:

```js
// AFTER
: <span className="text-t-accent font-600">{Math.floor(RISK_AMOUNT / risk)} shares  ·  T1: ${+(entry + 2*risk).toFixed(2)}</span>
```

**Step 4: Replace the "Target $" `ModalField` section with the dynamic T1/T2/T3 section**

Find the "Row: Quantity + Target" grid (lines 471–488). Replace the entire `<ModalField label="Target $"...>` block:

```jsx
{/* Row: Quantity */}
<div className="grid grid-cols-1">
    <ModalField label="Quantity (shares)">
        <ModalInput
            type="number" step="1" min="1"
            value={form.quantity}
            onChange={set('quantity')}
            placeholder="0"
        />
    </ModalField>
</div>

{/* Targets section */}
<div style={{ borderBottom: '1px solid var(--border)' }}>
    {/* T1 — always visible */}
    <div style={{ borderBottom: '1px solid var(--border)' }}>
        <ModalField label="T1 $ (required)" hint="2:1 auto-filled">
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <ModalInput
                    type="number" step="0.01" min="0"
                    value={form.targets[0]}
                    onChange={(e) => setForm(f => { const t = [...f.targets]; t[0] = e.target.value; return { ...f, targets: t } })}
                    placeholder="0.00"
                    style={{ flex: 1 }}
                />
                {risk > 0 && (
                    <button type="button" onClick={() => setForm(f => { const t = [...f.targets]; t[0] = String(+(entry + 2*risk).toFixed(2)); return { ...f, targets: t } })}
                        style={{ fontSize: 9, padding: '2px 6px', background: 'rgba(245,166,35,0.1)', border: '1px solid rgba(245,166,35,0.3)', color: 'var(--accent)', cursor: 'pointer', fontFamily: 'IBM Plex Mono, monospace', letterSpacing: '0.06em' }}>
                        +2R
                    </button>
                )}
            </div>
        </ModalField>
    </div>

    {/* T2 */}
    {targetCount >= 2 ? (
        <div style={{ borderBottom: '1px solid var(--border)' }}>
            <ModalField label="T2 $">
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <ModalInput
                        type="number" step="0.01" min="0"
                        value={form.targets[1]}
                        onChange={(e) => setForm(f => { const t = [...f.targets]; t[1] = e.target.value; return { ...f, targets: t } })}
                        placeholder="0.00"
                        style={{ flex: 1 }}
                    />
                    {risk > 0 && (
                        <button type="button" onClick={() => setForm(f => { const t = [...f.targets]; t[1] = String(+(entry + 3*risk).toFixed(2)); return { ...f, targets: t } })}
                            style={{ fontSize: 9, padding: '2px 6px', background: 'rgba(245,166,35,0.1)', border: '1px solid rgba(245,166,35,0.3)', color: 'var(--accent)', cursor: 'pointer', fontFamily: 'IBM Plex Mono, monospace', letterSpacing: '0.06em' }}>
                            +3R
                        </button>
                    )}
                    <button type="button" onClick={() => { setTargetCount(1); setForm(f => { const t = [...f.targets]; t[1] = ''; t[2] = ''; return { ...f, targets: t } }) }}
                        style={{ fontSize: 9, padding: '2px 6px', background: 'transparent', border: '1px solid var(--border-light)', color: 'var(--muted)', cursor: 'pointer', fontFamily: 'IBM Plex Mono, monospace', letterSpacing: '0.06em' }}>
                        ×
                    </button>
                </div>
            </ModalField>
        </div>
    ) : (
        <div className="px-4 py-2" style={{ borderBottom: '1px solid var(--border)', background: 'var(--panel)' }}>
            <button type="button" onClick={() => setTargetCount(2)}
                style={{ fontSize: 9, padding: '2px 8px', background: 'transparent', border: '1px solid var(--border-light)', color: 'var(--muted)', cursor: 'pointer', fontFamily: 'IBM Plex Mono, monospace', letterSpacing: '0.06em', textTransform: 'uppercase' }}>
                + T2
            </button>
        </div>
    )}

    {/* T3 — only available after T2 is added */}
    {targetCount >= 2 && (
        targetCount >= 3 ? (
            <ModalField label="T3 $">
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <ModalInput
                        type="number" step="0.01" min="0"
                        value={form.targets[2]}
                        onChange={(e) => setForm(f => { const t = [...f.targets]; t[2] = e.target.value; return { ...f, targets: t } })}
                        placeholder="0.00"
                        style={{ flex: 1 }}
                    />
                    {risk > 0 && (
                        <button type="button" onClick={() => setForm(f => { const t = [...f.targets]; t[2] = String(+(entry + 4*risk).toFixed(2)); return { ...f, targets: t } })}
                            style={{ fontSize: 9, padding: '2px 6px', background: 'rgba(245,166,35,0.1)', border: '1px solid rgba(245,166,35,0.3)', color: 'var(--accent)', cursor: 'pointer', fontFamily: 'IBM Plex Mono, monospace', letterSpacing: '0.06em' }}>
                            +4R
                        </button>
                    )}
                    <button type="button" onClick={() => { setTargetCount(2); setForm(f => { const t = [...f.targets]; t[2] = ''; return { ...f, targets: t } }) }}
                        style={{ fontSize: 9, padding: '2px 6px', background: 'transparent', border: '1px solid var(--border-light)', color: 'var(--muted)', cursor: 'pointer', fontFamily: 'IBM Plex Mono, monospace', letterSpacing: '0.06em' }}>
                        ×
                    </button>
                </div>
            </ModalField>
        ) : (
            <div className="px-4 py-2" style={{ background: 'var(--panel)' }}>
                <button type="button" onClick={() => setTargetCount(3)}
                    style={{ fontSize: 9, padding: '2px 8px', background: 'transparent', border: '1px solid var(--border-light)', color: 'var(--muted)', cursor: 'pointer', fontFamily: 'IBM Plex Mono, monospace', letterSpacing: '0.06em', textTransform: 'uppercase' }}>
                    + T3
                </button>
            </div>
        )
    )}
</div>
```

**Step 5: Update `handleSubmit` validation and submission**

Replace the target validation block in `handleSubmit` (find the lines checking `tgt`):

```js
// BEFORE (remove these lines)
const tgt = parseFloat(form.target)
...
if (!tgt || tgt <= ep) { setError('Target must be above entry price'); return }
```

Replace with:

```js
// AFTER
const t1 = parseFloat(form.targets[0])
const t2 = form.targets[1] !== '' ? parseFloat(form.targets[1]) : null
const t3 = form.targets[2] !== '' ? parseFloat(form.targets[2]) : null

if (!t1 || t1 <= ep)                  { setError('T1 must be above entry price'); return }
if (t2 !== null && t2 <= t1)          { setError('T2 must be above T1'); return }
if (t3 !== null && (t2 === null || t3 <= t2)) { setError('T3 must be above T2'); return }
```

And update the `addTrade` call in `handleSubmit` to pass `targets`:

```js
// BEFORE
const result = await addTrade({
    ticker:      form.ticker.trim().toUpperCase(),
    entry_price: ep,
    quantity:    qty,
    stop_loss:   sl,
    target:      tgt,
    entry_date:  form.entry_date,
    notes:       form.notes,
})
```

```js
// AFTER
const targets = [t1, t2, t3].filter((v) => v !== null)
const result = await addTrade({
    ticker:      form.ticker.trim().toUpperCase(),
    entry_price: ep,
    quantity:    qty,
    stop_loss:   sl,
    targets,
    entry_date:  form.entry_date,
    notes:       form.notes,
})
```

**Step 6: Manual test — open Add Trade modal**

- Start the frontend: `cd frontend && npm run dev`
- Open the Portfolio tab
- Click `+ ADD TRADE`
- Verify: T1 field visible, `+ T2` button visible, `+ T3` not visible
- Fill Entry $140, Stop $134, click `RISK $200` → T1 auto-fills to $152 (2R), qty fills
- Click `+ T2` → T2 field appears with `+3R` quick-fill and `×` remove
- Click `+3R` on T2 → fills T2 = entry + 3×risk
- Click `+ T3` → T3 appears with `+4R` and `×`
- Click `×` on T2 → T2 and T3 both disappear
- Submit with T1 only → trade added

**Step 7: Commit**

```bash
git add frontend/src/components/PortfolioTab.jsx
git commit -m "feat(portfolio): dynamic T1/T2/T3 target form with quick-fill buttons"
```

---

### Task 4: Frontend — T1/T2/T3 columns in portfolio table

**Files:**
- Modify: `swing-trading-dashboard/frontend/src/components/PortfolioTab.jsx`

**Context:**
The portfolio table `<thead>` has a "Target $" column and the `<tbody>` rows render `{fmt2(t.target)}`. We replace these with three columns using the `targets` array now returned by the API.

**Step 1: Replace the table header**

Find in the `<thead>`:
```jsx
<th>Target $</th>
```

Replace with:
```jsx
<th>T1 $</th>
<th>T2 $</th>
<th>T3 $</th>
```

**Step 2: Replace the Target cell in table rows**

Find in the `<tbody>` row:
```jsx
{/* Target */}
<td style={{ color: 'var(--go)' }}>{fmt2(t.target)}</td>
```

Replace with:
```jsx
{/* T1 */}
<td style={{ color: 'var(--go)' }}>{fmt2(t.targets?.[0] ?? t.target)}</td>
{/* T2 */}
<td style={{ color: 'var(--go)' }}>
    {t.targets?.[1] != null ? fmt2(t.targets[1]) : <Dash />}
</td>
{/* T3 */}
<td style={{ color: 'var(--go)' }}>
    {t.targets?.[2] != null ? fmt2(t.targets[2]) : <Dash />}
</td>
```

**Step 3: Manual test**

- Backend running: `uvicorn main:app --reload`
- Add a new trade with T1 + T2
- Verify table shows T1 and T2 in green, T3 shows `—`
- Add a trade with only T1 → T2 and T3 both show `—`
- Refresh page → verify trades persist correctly

**Step 4: Run backend tests one final time**

```bash
cd swing-trading-dashboard/backend
python -m pytest tests/ -v
```

Expected: all tests PASS.

**Step 5: Commit**

```bash
git add frontend/src/components/PortfolioTab.jsx
git commit -m "feat(portfolio): replace Target column with T1/T2/T3 columns in trades table"
```
