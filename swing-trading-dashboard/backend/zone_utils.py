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
) -> Tuple[float, float]:
    """
    Return (take_profit, rr) using the nearest KDE RESISTANCE zone above entry.

    Logic:
      - Collect all zones with type=="RESISTANCE" and zone["lower"] > entry
      - Use the lowest of those (nearest supply above entry) as take_profit
      - If computed R:R < 1.0, fall back to the fixed TARGET_RR multiplier

    Falls back to (entry + TARGET_RR * risk, TARGET_RR) when:
      - zones is empty or None
      - No resistance zone is above entry
      - The nearest zone yields R:R < 1.0 (too close to entry to be useful)
    """
    fallback_tp = round(entry + TARGET_RR * risk, 2)

    if not zones or risk <= 0:
        return fallback_tp, TARGET_RR

    candidates = [
        float(z["lower"])
        for z in zones
        if z.get("type") == "RESISTANCE" and float(z.get("lower", 0)) > entry
    ]

    if not candidates:
        return fallback_tp, TARGET_RR

    target = round(min(candidates), 2)
    rr = (target - entry) / risk

    if rr < 1.0:
        return fallback_tp, TARGET_RR

    return target, round(rr, 2)
