# Live Scanner Full BacktestParams Injection Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Override `take_profit` and `rr` on every live scanner signal using `_LIVE_PARAMS.tp_multiple` so displayed levels match the backtest exactly.

**Architecture:** Engines (3/5/6) already use `getattr(params, ...)` for all params including stop_atr, brk_min_pct, etc. — they are fully wired. The only missing piece is `tp_multiple` override in `main.py` post-signal. Add one helper function `_apply_tp_multiple(signal, params)` and call it at 4 signal collection points in `scan_ticker`.

**Tech Stack:** Python, BacktestParams dataclass, main.py live scanner.

---

### Task 1: Add `_apply_tp_multiple` helper and tests

**Files:**
- Modify: `backend/main.py` (near line 174, after `_LIVE_PARAMS = BacktestParams()`)
- Test: `backend/tests/test_live_params_tp_override.py` (create new)

**Context:**
- `BacktestParams.tp_multiple = 4.3458` (trial #433 default)
- Backtest override (backtest_engine.py line 946): `take_profit = round(entry_price + self.params.tp_multiple * _risk, 2)`
- Live scanner currently leaves `take_profit` as-is from engine output (nearest zone or 2:1 fallback)
- `rr` field on the signal should also be updated to reflect the new TP

**Step 1: Write the failing tests**

Create `backend/tests/test_live_params_tp_override.py`:

```python
"""Tests for _apply_tp_multiple helper in main.py."""
import importlib
import sys
import types
import pytest


def _load_helper():
    """Import only the _apply_tp_multiple function from main.py without running the app."""
    # We extract just the function by reading and exec-ing a minimal snippet
    import ast, pathlib
    src = pathlib.Path(__file__).parent.parent / "main.py"
    tree = ast.parse(src.read_text())
    # Find the function def
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_apply_tp_multiple":
            # Compile just that function
            mod = ast.Module(body=[node], type_ignores=[])
            code = compile(mod, str(src), "exec")
            ns = {}
            exec(code, ns)
            return ns["_apply_tp_multiple"]
    raise ImportError("_apply_tp_multiple not found in main.py")


class FakeParams:
    tp_multiple = 4.3458


def test_tp_override_basic():
    """take_profit = entry + tp_multiple * (entry - stop_loss)."""
    fn = _load_helper()
    signal = {"entry": 100.0, "stop_loss": 95.0, "take_profit": 110.0, "rr": 2.0}
    result = fn(signal, FakeParams())
    expected_tp = round(100.0 + 4.3458 * 5.0, 2)  # 100 + 21.729 = 121.73
    assert result["take_profit"] == expected_tp
    assert result["rr"] == round(4.3458, 3)


def test_tp_override_modifies_in_place():
    """Helper modifies the dict in place AND returns it."""
    fn = _load_helper()
    signal = {"entry": 50.0, "stop_loss": 48.0, "take_profit": 54.0, "rr": 2.0}
    returned = fn(signal, FakeParams())
    assert returned is signal  # same object


def test_tp_override_skips_invalid_entry():
    """If entry <= 0, signal is returned unchanged."""
    fn = _load_helper()
    signal = {"entry": 0.0, "stop_loss": 0.0, "take_profit": 0.0, "rr": 0.0}
    result = fn(signal, FakeParams())
    assert result["take_profit"] == 0.0


def test_tp_override_skips_inverted_levels():
    """If stop_loss >= entry (broken signal), signal is returned unchanged."""
    fn = _load_helper()
    signal = {"entry": 95.0, "stop_loss": 100.0, "take_profit": 110.0, "rr": 2.0}
    result = fn(signal, FakeParams())
    assert result["take_profit"] == 110.0  # unchanged


def test_tp_override_fallback_when_no_tp_multiple():
    """Falls back to tp_multiple=2.0 when params has no tp_multiple attribute."""
    fn = _load_helper()

    class MinimalParams:
        pass

    signal = {"entry": 100.0, "stop_loss": 95.0, "take_profit": 110.0, "rr": 2.0}
    result = fn(signal, MinimalParams())
    expected_tp = round(100.0 + 2.0 * 5.0, 2)  # 100 + 10 = 110
    assert result["take_profit"] == expected_tp
    assert result["rr"] == 2.0
```

**Step 2: Run tests to verify they fail**

```bash
cd /Users/amit/Documents/GitHub/superpowers/swing-trading-dashboard/backend
python -m pytest tests/test_live_params_tp_override.py -v
```

Expected: `ImportError: _apply_tp_multiple not found in main.py`

**Step 3: Add the helper function to main.py**

In `main.py`, after line 174 (`_LIVE_PARAMS = BacktestParams()`), add:

```python
def _apply_tp_multiple(signal: dict, params) -> dict:
    """Override take_profit and rr using params.tp_multiple × risk.

    Mirrors backtest_engine.py line 946:
        take_profit = entry + tp_multiple × (entry - stop_loss)

    Modifies signal in place and returns it. No-ops if entry/stop are invalid.
    """
    entry     = signal.get("entry", 0.0)
    stop_loss = signal.get("stop_loss", 0.0)
    if entry > 0 and stop_loss > 0 and entry > stop_loss:
        risk         = entry - stop_loss
        tp_mult      = getattr(params, "tp_multiple", 2.0)
        signal["take_profit"] = round(entry + tp_mult * risk, 2)
        signal["rr"]          = round(tp_mult, 3)
    return signal
```

**Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_live_params_tp_override.py -v
```

Expected: 5 tests PASS

**Step 5: Commit**

```bash
git add backend/main.py backend/tests/test_live_params_tp_override.py
git commit -m "feat: add _apply_tp_multiple helper to align live TP with BacktestParams"
```

---

### Task 2: Apply TP override at all 4 signal collection points in scan_ticker

**Files:**
- Modify: `backend/main.py`

**Context:**
There are 4 places in `scan_ticker` (the live scanner loop) where a signal dict is sanitized and then appended to `collected_setups`. Each needs one call to `_apply_tp_multiple` after the sanitization try/except block passes.

The 4 signal collection points (approximate lines):
1. **Strict pullback** (~line 1313): `pb` sanitized, then `pb["sector"] = ...`, `collected_setups.append(pb)`
2. **Relaxed pullback** (~line 1337): `pb_relaxed` sanitized, then `collected_setups.append(pb_relaxed)`
3. **Base pattern** (~line 1361): `base` sanitized, then `base["sector"] = ...`, `collected_setups.append(base)`
4. **Resistance breakout** (~line 1400): `res_brk` sanitized, then `res_brk["sector"] = ...`, `collected_setups.append(res_brk)`

**Step 1: Write the failing integration test**

Add to `backend/tests/test_live_params_tp_override.py`:

```python
def test_tp_override_rr_matches_tp_multiple():
    """rr field after override equals tp_multiple (not derived from TP/stop ratio)."""
    fn = _load_helper()
    # Simulate a breakout signal where engine returned nearest-zone TP
    signal = {"entry": 150.0, "stop_loss": 145.0, "take_profit": 160.0, "rr": 2.0}
    params = FakeParams()  # tp_multiple = 4.3458
    fn(signal, params)
    # rr should now be tp_multiple, not (160-150)/(150-145)=2.0
    assert signal["rr"] == round(4.3458, 3)
    assert signal["take_profit"] == round(150.0 + 4.3458 * 5.0, 2)
```

Run: `python -m pytest tests/test_live_params_tp_override.py::test_tp_override_rr_matches_tp_multiple -v`
Expected: PASS (helper already handles this)

**Step 2: Apply override at strict pullback collection point**

Find this block in `main.py` (~line 1320):
```python
                        pb["sector"]   = SECTORS.get(ticker, "Unknown")
                        pb["rs_score"] = rs_score
                        pb["vol_ratio"] = pb.get("volume_ratio", pb.get("vol_ratio", 0.0))
                        collected_setups.append(pb)
```

Change to:
```python
                        _apply_tp_multiple(pb, _LIVE_PARAMS)
                        pb["sector"]   = SECTORS.get(ticker, "Unknown")
                        pb["rs_score"] = rs_score
                        pb["vol_ratio"] = pb.get("volume_ratio", pb.get("vol_ratio", 0.0))
                        collected_setups.append(pb)
```

**Step 3: Apply override at relaxed pullback collection point**

Find this block (~line 1344):
```python
                                pb_relaxed["sector"] = SECTORS.get(ticker, "Unknown")
                                collected_setups.append(pb_relaxed)
```

Change to:
```python
                                _apply_tp_multiple(pb_relaxed, _LIVE_PARAMS)
                                pb_relaxed["sector"] = SECTORS.get(ticker, "Unknown")
                                collected_setups.append(pb_relaxed)
```

**Step 4: Apply override at base pattern collection point**

Find this block (~line 1367):
```python
                            base["sector"]       = SECTORS.get(ticker, "Unknown")
                            base["rs_score"]     = rs_score
```

Change to:
```python
                            _apply_tp_multiple(base, _LIVE_PARAMS)
                            base["sector"]       = SECTORS.get(ticker, "Unknown")
                            base["rs_score"]     = rs_score
```

**Step 5: Apply override at resistance breakout collection point**

Find this block (~line 1406):
```python
                                res_brk["sector"]       = SECTORS.get(ticker, "Unknown")
                                # Inject RS + volume fields not computed by engine6
                                res_brk["rs_score"]     = rs_score
```

Change to:
```python
                                _apply_tp_multiple(res_brk, _LIVE_PARAMS)
                                res_brk["sector"]       = SECTORS.get(ticker, "Unknown")
                                # Inject RS + volume fields not computed by engine6
                                res_brk["rs_score"]     = rs_score
```

**Step 6: Run all TP override tests**

```bash
python -m pytest tests/test_live_params_tp_override.py -v
```

Expected: All 6 tests PASS

**Step 7: Run full test suite to check for regressions**

```bash
python -m pytest tests/ -x -q 2>&1 | tail -20
```

Expected: All passing, no regressions

**Step 8: Commit**

```bash
git add backend/main.py
git commit -m "feat: apply tp_multiple override to all live scanner signals"
```
