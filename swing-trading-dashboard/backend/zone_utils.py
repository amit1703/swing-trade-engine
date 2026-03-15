"""
Shared zone utility for engine take-profit targeting.
"""
import os
import sys
from typing import Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from constants import TARGET_RR


def nearest_resistance_target(
    entry: float,
    zones: List[Dict],
    risk: float,
    tp_multiple: float = None,
) -> Tuple[float, float]:
    """
    Return (take_profit, rr) using the nearest KDE RESISTANCE zone above entry.

    Logic:
      - Collect all zones with type=="RESISTANCE" and zone["lower"] > entry
      - Use the lowest of those (nearest supply above entry) as take_profit
      - If computed R:R < 1.0, fall back to tp_multiple (or TARGET_RR if not given)

    Falls back to (entry + fallback_rr * risk, fallback_rr) when:
      - zones is empty or None
      - No resistance zone is above entry
      - The nearest zone yields R:R < 1.0 (too close to entry to be useful)
    """
    fallback_rr = tp_multiple if tp_multiple is not None else TARGET_RR
    fallback_tp = round(entry + fallback_rr * risk, 2)

    if not zones or risk <= 0:
        return fallback_tp, fallback_rr

    candidates = [
        float(z["lower"])
        for z in zones
        if z.get("type") == "RESISTANCE" and float(z.get("lower", 0)) > entry
    ]

    if not candidates:
        return fallback_tp, fallback_rr

    target = round(min(candidates), 2)
    rr = (target - entry) / risk

    if rr < 1.0:
        return fallback_tp, fallback_rr

    return target, round(rr, 2)
