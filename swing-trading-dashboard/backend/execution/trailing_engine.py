"""
Shared trailing stop logic.

Two public functions:
  advance_ema20_trail(state, bar) — bar-by-bar update; used by backtest engine.
  compute_live_trail(...)         — stateless; used by live portfolio enrichment.

Both read parameters exclusively from TRAIL_CONFIG. No hardcoded multipliers here.
"""
from __future__ import annotations

from typing import Dict, Optional

from config.trailing_config import TRAIL_CONFIG


def advance_ema20_trail(state: Dict, bar: Dict) -> None:
    """
    Apply one bar of EMA20 trail logic to a trade state dict in-place.

    Phase 1 (before trigger): stop stays fixed at initial_stop.
    Phase 2 (after trigger):  stop trails to previous bar's EMA20
                               (or EMA20 + offset when price is extended).

    Trigger condition (requires bars_since_entry >= 2):
      - ref_level is None  → trigger immediately on bar 2 (HTF/LCE)
      - close > ref_level + trigger_atr_mult * ATR → trigger

    State keys mutated: trailing_stop, _trail_triggered,
                        _bars_since_entry, _prev_ema20.
    """
    cfg    = TRAIL_CONFIG["ema"]
    trig   = cfg["trigger_atr_mult"]        # 1.5
    ext_t  = cfg["extension_threshold_atr"] # 2.5
    ext_o  = cfg["extension_offset_atr"]    # 1.5
    buffer = state.get("_ema_break_buffer", 0.0)  # Optuna-tunable; 0.0 = exact EMA20

    ema20 = bar["ema20"]
    atr14 = bar.get("atr14", 0.0)
    close = bar["close"]
    stop  = state["trailing_stop"]

    bars = state.get("_bars_since_entry", 0) + 1
    state["_bars_since_entry"] = bars

    prev_ema20 = ema20 if state.get("_prev_ema20") is None else state["_prev_ema20"]

    # Phase 2 trigger check (1-bar delay enforced by bars >= 2)
    if not state.get("_trail_triggered", False) and bars >= 2:
        ref_level = state.get("_ref_level")
        if ref_level is None:
            state["_trail_triggered"] = True
        elif atr14 > 0 and close > ref_level + trig * atr14:
            state["_trail_triggered"] = True

    if state.get("_trail_triggered", False):
        if atr14 > 0 and close > ema20 + ext_t * atr14:
            # Extended move: lock in gains above EMA20; buffer doesn't apply here
            new_trail = ema20 + ext_o * atr14
        else:
            # Normal phase 2: trail to previous bar EMA20, offset down by buffer
            # buffer=0.0 → exact EMA20; buffer=0.005 → 0.5% below EMA20
            new_trail = prev_ema20 * (1.0 - buffer)
        if new_trail > stop:
            state["trailing_stop"] = new_trail

    state["_prev_ema20"] = ema20


def compute_live_trail(
    current_stop: float,
    entry_price: float,
    current_price: float,
    prev_ema20: Optional[float],
    current_ema20: float,
) -> float:
    """
    Compute the live portfolio trailing stop using EMA20 floor.

    Stateless — called once per price refresh (not bar-by-bar replay).
    Phase 1/2 gating is omitted because live enrichment has no per-bar history.

    Rules:
      - Only trails when current_price > entry_price (in profit)
      - Uses PREVIOUS bar's EMA20 as floor (no lookahead)
      - Stop can only move up (ratchet)
    """
    if entry_price <= 0 or current_ema20 <= 0 or current_price <= entry_price:
        return current_stop
    floor = (prev_ema20
             if (prev_ema20 is not None and prev_ema20 > 0)
             else current_ema20)
    return max(current_stop, floor)


def log_trail_config() -> None:
    """Print active trailing configuration. Call once at system startup."""
    cfg = TRAIL_CONFIG
    ema = cfg["ema"]
    print(f"Trailing Mode:  {cfg['mode'].upper()}")
    print(f"EMA Period:     {ema['period']}")
    print(f"Trigger:        {ema['trigger_atr_mult']} ATR above ref level")
    print(f"Extension:      {ema['extension_threshold_atr']} / {ema['extension_offset_atr']} ATR")
    print(f"Prev-bar trail: {ema['use_previous_bar']}")
