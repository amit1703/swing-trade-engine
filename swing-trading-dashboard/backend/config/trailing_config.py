"""
Single source of truth for trailing stop configuration.

All modules that implement trailing stop logic MUST import from here.
No module may define its own trail parameters.
"""

TRAIL_CONFIG: dict = {
    "mode": "ema20",   # system-wide default — change here to switch globally

    "ema": {
        "period":                    20,
        "trigger_atr_mult":          1.5,   # close must exceed ref_level + N*ATR to trigger Phase 2
        "extension_threshold_atr":   2.5,   # close > EMA20 + N*ATR → use buffer trail
        "extension_offset_atr":      1.5,   # buffer trail = EMA20 + N*ATR
        "use_previous_bar":          True,  # trail anchors to PREVIOUS bar's EMA (no lookahead)
        "allow_same_bar_trigger":    False, # Phase 2 cannot fire on entry bar
    },

    # NOTE: ATR fallback parameters are NOT read from here.
    # When trail_mode="atr" is used (A/B testing only), _manage_open_trade reads
    # constants.TRAIL_ATR_MULT and _TRAIL_ATR_BY_SETUP from backtest_engine.py.
    # This section is documentation only — do not add code that reads TRAIL_CONFIG["atr"].
    "atr": {
        "multiplier": 4.25,   # for reference only — active ATR fallback reads constants.py
    },
}


def validate_trail_config() -> None:
    """
    Assert config is well-formed and mode is ema20.
    Call at system startup.

    Raises AssertionError if any invariant is violated.
    """
    assert TRAIL_CONFIG["mode"] == "ema20", (
        f"TRAIL_CONFIG mode is '{TRAIL_CONFIG['mode']}' — expected 'ema20'. "
        "Edit config/trailing_config.py to restore it."
    )
    ema = TRAIL_CONFIG["ema"]
    required = ("period", "trigger_atr_mult", "extension_threshold_atr",
                "extension_offset_atr", "use_previous_bar", "allow_same_bar_trigger")
    for key in required:
        assert key in ema, f"TRAIL_CONFIG['ema'] missing required key: '{key}'"
