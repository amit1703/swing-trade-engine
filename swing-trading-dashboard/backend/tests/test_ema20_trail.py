import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

def test_meta_keys_include_support_level():
    """support_level must be captured from signal into _setup_meta."""
    from backtest_engine import _BACKTEST_META_KEYS
    assert "support_level" in _BACKTEST_META_KEYS

def test_meta_keys_include_geometry():
    """geometry must be captured for BASE base_high lookup."""
    from backtest_engine import _BACKTEST_META_KEYS
    assert "geometry" in _BACKTEST_META_KEYS


def test_extract_ref_level_res_breakout():
    from backtest_engine import _extract_ref_level
    meta = {"resistance_level": 150.0, "zone_upper": 150.0}
    assert _extract_ref_level(meta, "RES_BREAKOUT") == 150.0


def test_extract_ref_level_vcp():
    from backtest_engine import _extract_ref_level
    meta = {"resistance_level": 200.0}
    assert _extract_ref_level(meta, "VCP") == 200.0


def test_extract_ref_level_pullback():
    from backtest_engine import _extract_ref_level
    meta = {"support_level": 95.0, "support_source": "KDE_SUPPORT"}
    assert _extract_ref_level(meta, "PULLBACK") == 95.0


def test_extract_ref_level_base():
    from backtest_engine import _extract_ref_level
    meta = {"geometry": {"base_high": 180.0, "base_low": 160.0}}
    assert _extract_ref_level(meta, "BASE") == 180.0


def test_extract_ref_level_htf_returns_none():
    """HTF has no reference level — returns None to trigger EMA20 from day 1."""
    from backtest_engine import _extract_ref_level
    meta = {"volume_ratio": 1.5}
    assert _extract_ref_level(meta, "HTF") is None


def test_extract_ref_level_missing_key_returns_none():
    """Graceful fallback when setup_meta doesn't have the expected key."""
    from backtest_engine import _extract_ref_level
    assert _extract_ref_level({}, "PULLBACK") is None
    assert _extract_ref_level({}, "VCP") is None


def test_backtest_params_default_trail_mode():
    """Default trail_mode must be 'ema20'."""
    from backtest_engine import BacktestParams
    assert BacktestParams().trail_mode == "ema20"

def test_backtest_params_atr_mode():
    """trail_mode='atr' must be accepted."""
    from backtest_engine import BacktestParams
    p = BacktestParams(trail_mode="atr")
    assert p.trail_mode == "atr"


def _make_ema20_state(ref_level=None, trail_triggered=False,
                      bars_since_entry=0, prev_ema20=None,
                      initial_stop=90.0) -> dict:
    """Helper: trade state dict pre-configured for EMA20 trail mode."""
    return {
        "entry_price":      100.0,
        "trailing_stop":    initial_stop,
        "take_profit":      200.0,
        "entry_date":       "2024-01-01",
        "setup_type":       "PULLBACK",
        "_trail_mode":      "ema20",
        "_trail_triggered": trail_triggered,
        "_bars_since_entry": bars_since_entry,
        "_ref_level":       ref_level,
        "_prev_ema20":      prev_ema20,
    }

def _bar(close=105.0, low=103.0, high=107.0, ema20=98.0, atr14=2.0):
    return {"date": "2024-01-02", "open": 104.0,
            "high": high, "low": low, "close": close,
            "ema20": ema20, "atr14": atr14}


# --- Phase 1: stop stays fixed before Phase 2 triggers ---

def test_ema20_phase1_stop_unchanged_before_trigger():
    """Before Phase 2 triggers, trailing_stop must not move."""
    from backtest_engine import _manage_open_trade
    state = _make_ema20_state(ref_level=110.0, trail_triggered=False, bars_since_entry=1)
    _manage_open_trade(state, _bar(close=105.0, ema20=98.0, atr14=2.0))
    assert state["trailing_stop"] == 90.0  # unchanged

def test_ema20_phase1_stop_unchanged_on_entry_bar():
    """On entry bar (bars_since_entry==0->1 after update), Phase 2 must not fire."""
    from backtest_engine import _manage_open_trade
    # ref_level=100, close=106 > 100 + 1.5*2=103 but it's bar 1 -- no trigger
    state = _make_ema20_state(ref_level=100.0, bars_since_entry=0)
    _manage_open_trade(state, _bar(close=106.0, ema20=98.0, atr14=2.0))
    assert state["_trail_triggered"] is False
    assert state["trailing_stop"] == 90.0


# --- Phase 2 trigger ---

def test_ema20_phase2_triggers_when_close_above_ref_plus_atr():
    """close > ref_level + 1.5*ATR on bar >= 2 must trigger Phase 2."""
    from backtest_engine import _manage_open_trade
    # ref=100, atr=2 -> threshold=103; close=104 -> should trigger
    state = _make_ema20_state(ref_level=100.0, trail_triggered=False, bars_since_entry=1)
    _manage_open_trade(state, _bar(close=104.0, ema20=98.0, atr14=2.0))
    assert state["_trail_triggered"] is True

def test_ema20_phase2_does_not_trigger_below_threshold():
    """close <= ref_level + 1.5*ATR must NOT trigger Phase 2."""
    from backtest_engine import _manage_open_trade
    # ref=100, atr=2 -> threshold=103; close=102.9 -> no trigger
    state = _make_ema20_state(ref_level=100.0, trail_triggered=False, bars_since_entry=1)
    _manage_open_trade(state, _bar(close=102.9, ema20=98.0, atr14=2.0))
    assert state["_trail_triggered"] is False

def test_ema20_phase2_htf_triggers_on_bar2_no_ref():
    """HTF (ref_level=None) must trigger Phase 2 automatically on bar 2."""
    from backtest_engine import _manage_open_trade
    state = _make_ema20_state(ref_level=None, trail_triggered=False, bars_since_entry=1)
    _manage_open_trade(state, _bar(close=104.0, ema20=98.0, atr14=2.0))
    assert state["_trail_triggered"] is True


# --- Phase 3: EMA20 trail ---

def test_ema20_phase3_normal_uses_prev_ema20():
    """After trigger, normal trail = max(current_stop, prev_ema20)."""
    from backtest_engine import _manage_open_trade
    # prev_ema20=99, current_stop=90 -> new_stop=99
    state = _make_ema20_state(trail_triggered=True, bars_since_entry=2,
                               prev_ema20=99.0, initial_stop=90.0)
    _manage_open_trade(state, _bar(close=105.0, ema20=100.0, atr14=2.0))
    assert state["trailing_stop"] == 99.0

def test_ema20_phase3_stop_only_moves_up():
    """Stop must never decrease -- new_trail below current stop is ignored."""
    from backtest_engine import _manage_open_trade
    # prev_ema20=85, current_stop=90 -> max(85,90)=90, no change
    state = _make_ema20_state(trail_triggered=True, bars_since_entry=2,
                               prev_ema20=85.0, initial_stop=90.0)
    _manage_open_trade(state, _bar(close=105.0, ema20=86.0, atr14=2.0))
    assert state["trailing_stop"] == 90.0  # unchanged -- prev_ema20 below stop

def test_ema20_phase3_extended_uses_ema20_plus_buffer():
    """close > ema20 + 2.5*ATR -> trail = current_ema20 + 1.5*ATR."""
    from backtest_engine import _manage_open_trade
    # close=111, ema20=100, atr=2 -> extended threshold=105; 111>105 -> trail=100+3=103
    state = _make_ema20_state(trail_triggered=True, bars_since_entry=2,
                               prev_ema20=98.0, initial_stop=90.0)
    _manage_open_trade(state, _bar(close=111.0, ema20=100.0, atr14=2.0))
    assert abs(state["trailing_stop"] - 103.0) < 0.001  # 100 + 1.5*2

def test_ema20_phase3_prev_ema20_updated_each_bar():
    """_prev_ema20 must equal the current bar's ema20 after the call."""
    from backtest_engine import _manage_open_trade
    state = _make_ema20_state(trail_triggered=True, bars_since_entry=2,
                               prev_ema20=98.0, initial_stop=90.0)
    _manage_open_trade(state, _bar(close=105.0, ema20=100.5, atr14=2.0))
    assert state["_prev_ema20"] == 100.5

def test_ema20_stop_exit_uses_gap_fill_price():
    """Stop-out fills at min(open, stop), same as ATR mode."""
    from backtest_engine import _manage_open_trade
    state = _make_ema20_state(trail_triggered=True, bars_since_entry=3,
                               prev_ema20=98.0, initial_stop=95.0)
    state["trailing_stop"] = 95.0
    # low=93 <= stop=95, open=94 -> fill at min(94,95)=94
    bar = _bar(close=93.0, low=93.0, high=96.0, ema20=97.0, atr14=2.0)
    bar["open"] = 94.0
    closed, exit_price, reason = _manage_open_trade(state, bar)
    assert closed is True
    assert exit_price == 94.0
    assert reason == "STOP"


# --- ATR fallback ---

def test_atr_fallback_mode_unchanged():
    """trail_mode='atr' must behave identically to the original implementation."""
    from backtest_engine import _manage_open_trade
    state = {
        "entry_price":   100.0,
        "trailing_stop":  90.0,
        "take_profit":   200.0,
        "entry_date":    "2024-01-01",
        "setup_type":    "PULLBACK",
        "_trail_mode":   "atr",
        "trail_mult_override": 4.25,
    }
    bar = _bar(close=108.0, low=106.0, high=110.0, ema20=95.0, atr14=1.0)
    _manage_open_trade(state, bar)
    # ATR trail: 108 - 4.25*1.0 = 103.75; ema20=95 -> max=103.75
    assert abs(state["trailing_stop"] - 103.75) < 0.01


def test_trade_record_has_trail_fields():
    """TradeRecord must have trail_mode and trail_phase fields."""
    from backtest_engine import TradeRecord
    tr = TradeRecord(
        ticker="AAPL", setup_type="PULLBACK",
        signal_date="2024-01-01", entry_date="2024-01-02",
        entry_price=100.0, initial_stop=90.0, take_profit=150.0,
        exit_date="2024-01-10", exit_price=95.0, exit_reason="STOP",
        holding_days=8,
    )
    assert hasattr(tr, "trail_mode")
    assert hasattr(tr, "trail_phase")
    d = tr.to_dict()
    assert "trail_mode" in d
    assert "trail_phase" in d


def test_trail_config_has_required_keys():
    from config.trailing_config import TRAIL_CONFIG
    assert TRAIL_CONFIG["mode"] == "ema20"
    ema = TRAIL_CONFIG["ema"]
    assert ema["period"] == 20
    assert ema["trigger_atr_mult"] == 1.5
    assert ema["extension_threshold_atr"] == 2.5
    assert ema["extension_offset_atr"] == 1.5
    assert ema["use_previous_bar"] is True
    assert ema["allow_same_bar_trigger"] is False


def test_trail_config_validate_passes():
    from config.trailing_config import validate_trail_config
    validate_trail_config()  # must not raise
