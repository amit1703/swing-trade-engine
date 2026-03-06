"""
narrative.py — Deterministic trade plan generator (no LLM required).

generate_narrative(setup, regime) -> str

Returns a 3-4 sentence trading plan string incorporating:
  - Regime context (bullish / bearish market)
  - Pattern type and quality
  - Entry price, initial stop, first TP target
  - EMA20 trailing stop reminder
"""
from __future__ import annotations


def generate_narrative(setup: dict, regime: str) -> str:
    """
    Build a plain-English 3-4 sentence trading plan for a setup.

    Parameters
    ----------
    setup  : dict — one row from get_latest_setups() (fields: ticker,
             setup_type, entry, stop_loss, take_profit, plus metadata keys)
    regime : str  — "BULLISH" | "BEARISH" | "NEUTRAL"

    Returns
    -------
    str — narrative paragraph, never empty, never raises
    """
    try:
        return _build(setup, regime)
    except Exception:
        ticker = str(setup.get("ticker", "")).upper()
        return f"{ticker} setup detected. Review entry, stop, and target levels before acting."


def _build(setup: dict, regime: str) -> str:
    ticker     = str(setup.get("ticker", "")).upper()
    setup_type = str(setup.get("setup_type", ""))
    entry      = setup.get("entry")
    stop       = setup.get("stop_loss")
    target     = setup.get("take_profit")

    # ── 1. Regime sentence ────────────────────────────────────────────────────
    if regime == "BULLISH":
        regime_line = "The broader market is in a confirmed uptrend (SPY above its 20-day EMA), which improves the odds for long breakouts."
    elif regime == "BEARISH":
        regime_line = "Caution: the broader market is in a downtrend (SPY below its 20-day EMA) — reduce size and demand tighter confirmation."
    else:
        regime_line = "The broader market is in a mixed or neutral regime — wait for clear-day follow-through before adding exposure."

    # ── 2. Pattern sentence ───────────────────────────────────────────────────
    if setup_type == "VCP":
        is_lead = setup.get("is_rs_lead", False)
        is_brk  = setup.get("is_breakout", False) or setup.get("signal") == "BRK"
        is_tdl  = setup.get("is_trendline_breakout", False)
        is_kde  = setup.get("is_kde_breakout", False)
        vol_r   = setup.get("volume_ratio")
        vol_str = f" (volume {vol_r:.1f}× average)" if vol_r else ""
        if is_lead:
            pattern_line = (
                f"{ticker} is an RS-Lead breakout — it is outperforming SPY on the 3-month and "
                f"near-52-week basis with institutional volume confirmation{vol_str}."
            )
        elif is_kde:
            pattern_line = (
                f"{ticker} has broken above a key KDE resistance zone{vol_str}, confirming "
                f"institutional demand and signaling a potential momentum continuation."
            )
        elif is_brk:
            pattern_line = (
                f"{ticker} has cleared its VCP resistance on above-average volume{vol_str}, "
                f"signaling an accumulation breakout."
            )
        elif is_tdl:
            pattern_line = (
                f"{ticker} has broken above a descending trendline{vol_str}, marking a potential "
                f"trend reversal from a basing pattern."
            )
        else:
            pattern_line = (
                f"{ticker} is coiling tightly below resistance with volume drying up — "
                f"a classic VCP setup awaiting a volume-expansion breakout."
            )

    elif setup_type == "PULLBACK":
        is_ascending = setup.get("is_ascending_tdl", False)
        is_relaxed   = setup.get("is_relaxed", False)
        cci          = setup.get("cci_today")
        cci_str      = f" (CCI {cci:.0f})" if cci is not None else ""
        if is_ascending:
            pattern_line = (
                f"{ticker} is pulling back to touch an ascending trendline for a third-touch bounce "
                f"— classic trend-continuation with trendline support{cci_str}."
            )
        elif is_relaxed:
            pattern_line = (
                f"{ticker} is showing a relaxed pullback into the EMA zone with the CCI hooking "
                f"upward{cci_str} — lower-conviction entry; size accordingly."
            )
        else:
            pattern_line = (
                f"{ticker} has pulled back to EMA support with the CCI hooking up from oversold "
                f"territory{cci_str} — high-quality trend-continuation setup."
            )

    elif setup_type == "BASE":
        base_type = setup.get("base_type", "")
        signal    = setup.get("signal", "")
        quality   = setup.get("quality_score")
        q_str     = f" (quality {int(quality)}/100)" if quality is not None else ""
        if base_type == "CUP_HANDLE":
            base_name = "Cup-and-Handle"
        elif base_type == "FLAT_BASE":
            base_name = "Flat Base"
        else:
            base_name = "base"
        if signal == "BRK":
            pattern_line = (
                f"{ticker} has formed a {base_name}{q_str} and is breaking out of the pattern — "
                f"this is the ideal entry point with price leaving the base."
            )
        else:
            pattern_line = (
                f"{ticker} has formed a {base_name}{q_str} and is still within the base — "
                f"a breakout on expanding volume is the trigger to enter."
            )

    elif setup_type == "RES_BREAKOUT":
        days  = setup.get("days_since_breakout", 0)
        vol_r = setup.get("volume_ratio")
        vol_str = f" with {vol_r:.1f}× average volume" if vol_r else ""
        if days == 0:
            pattern_line = (
                f"{ticker} is breaking above a key KDE resistance level today{vol_str} — "
                f"early institutional entry opportunity."
            )
        elif days == 1:
            pattern_line = (
                f"{ticker} broke above a key KDE resistance level yesterday{vol_str} — "
                f"still within the actionable follow-through window."
            )
        else:
            pattern_line = (
                f"{ticker} broke above a key KDE resistance level {days} days ago{vol_str} — "
                f"look for a pullback-to-breakout-level retest entry."
            )

    else:
        pattern_line = f"{ticker} has triggered a {setup_type} setup based on technical criteria."

    # ── 3. Price levels sentence ───────────────────────────────────────────────
    parts = []
    if entry is not None:
        parts.append(f"entry at ${entry:.2f}")
    if stop is not None:
        if entry is not None and entry > 0:
            risk_pct = (entry - stop) / entry * 100
            parts.append(f"initial stop at ${stop:.2f} ({risk_pct:.1f}% risk)")
        else:
            parts.append(f"initial stop at ${stop:.2f}")
    if target is not None:
        if entry is not None and stop is not None and entry > stop:
            rr = (target - entry) / (entry - stop)
            parts.append(f"first target ${target:.2f} ({rr:.1f}R)")
        else:
            parts.append(f"first target ${target:.2f}")

    price_line = ("Plan: " + ", ".join(parts) + ".") if parts else ""

    # ── 4. Trail reminder ─────────────────────────────────────────────────────
    trail_line = "Trail stop to the 20-day EMA once price extends beyond the initial target."

    return " ".join(filter(None, [regime_line, pattern_line, price_line, trail_line]))
