# Swing Trading System — Full Audit Report
**Date:** 2026-03-08
**Scope:** Complete codebase review covering architecture, strategy logic, risk model, optimization, and production readiness.

---

## Executive Summary

The system is a quantitatively-driven swing trading platform built around William O'Neil / CANSLIM-style setups (VCP, Pullback, Base, Resistance Breakout). It has a solid foundation with meaningful backtesting, walk-forward optimization, and a recently upgraded risk model. The core mechanics are sound, but several gaps exist between the current state and production-readiness.

**Overall Maturity Score: 6.5 / 10**

---

## 1. System Architecture

### Structure
```
swing-trading-dashboard/
├── backend/                    # FastAPI Python server
│   ├── backtest_engine.py      # Core backtesting + TradeRecord
│   ├── wfo_engine.py           # Walk-Forward Optimization engine
│   ├── constants.py            # System-wide parameters
│   ├── engines/                # Signal detection engines (1–9)
│   ├── zone_utils.py           # Support/resistance zone utilities
│   └── tests/                  # pytest test suite
├── scripts/
│   ├── optimize_parameters.py  # Optuna optimizer (CLI)
│   └── representative_tickers.py  # 33 tickers across sectors
└── frontend/                   # React dashboard
```

### Assessment
- **Strengths:** Clean separation between signal generation, backtesting, and optimization. Async WFO engine handles multiple tickers efficiently.
- **Weaknesses:** No live data pipeline, no order management system, no paper trading layer.

---

## 2. Strategy Logic

### Implemented Setups

| Engine | Setup Type | Description |
|--------|------------|-------------|
| engine2 | VCP | Volatility Contraction Pattern with ATR-based stops |
| engine3 | Pullback | Trend pullback to moving averages |
| engine5 | Base | Flat base breakout |
| engine6 | RES_BREAKOUT | Resistance zone breakout with volume confirmation |
| engine8_htf | HTF | Higher timeframe filter overlay |
| engine9_low_cheat | Low Cheat | Low-of-day entry variant |

### Signal Quality
- Entries require relative strength (RS score vs SPY) above threshold
- Volume confirmation required on breakouts (configurable multiplier)
- ATR-based stops adapt to recent volatility
- Target R:R enforced per setup (configurable 1.8x–3.0x)

### Assessment
- **Strengths:** Multiple uncorrelated setup types increase opportunity frequency. RS filtering acts as a market condition filter.
- **Weaknesses:** No sector rotation logic, no market regime filter (e.g., SPY above/below 200MA), setups may fire freely in bear markets.

---

## 3. Indicators & Signal Engines

### Relative Strength (RS) Score
O'Neil composite RS: weighted average of 63/126/189/252-day price performance vs SPY.

```
rs_score = (0.4 × r63 + 0.2 × r126 + 0.2 × r189 + 0.2 × r252)
```

Normalized to 0–99 percentile rank across universe.

### Support/Resistance Zones (Engine 1)
Uses Kernel Density Estimation (KDE) on historical price levels to identify high-density zones. More robust than fixed lookback pivot detection.

### VCP Detection (Engine 2)
- Checks for tightening price ranges over rolling windows
- `VCP_TIGHT_RANGE_5D_PCT` controls minimum contraction threshold
- ATR-based stop placed below most recent swing low

### Assessment
- **Strengths:** KDE-based S/R is statistically principled and adapts to market structure. RS composite score is proven methodology.
- **Weaknesses:** No earnings filter (earnings gaps can invalidate setups). No liquidity filter (min ADV). No fundamental data integration.

---

## 4. Optimization (Optuna + WFO)

### Configuration
| Parameter | Value |
|-----------|-------|
| Framework | Optuna 4.7.0 |
| Sampler | TPESampler (seed=42) |
| Pruner | MedianPruner (startup=10, warmup=2) |
| Study name | trading_optimizer_v2 |
| WFO windows | 36m IS / 6m OOS / 6m step |
| Total tickers | SPY + 33 representative |
| Objective | Robustness score = (E × PF × √N) / (1 + DD × 2.5) |

### Parameter Search Space
| Parameter | Min | Max | Controls |
|-----------|-----|-----|----------|
| ATR_MULTIPLIER | 0.8 | 1.4 | Stop distance |
| VCP_TIGHTNESS_RANGE | 0.015 | 0.05 | VCP qualification |
| BREAKOUT_BUFFER_ATR | 0.1 | 0.5 | Entry trigger |
| BREAKOUT_VOL_MULT | 1.0 | 2.0 | Volume confirmation |
| TARGET_RR | 1.8 | 3.0 | Profit target |
| TRAIL_ATR_MULT | 1.0 | 2.5 | Trailing stop |

### Robustness Score Formula
```python
if total_trades < 40:   return -5.0   # insufficient sample
if max_drawdown > 35%:  return -10.0  # unacceptable risk

score = (expectancy × profit_factor × √total_trades) / (1 + drawdown × 2.5)
```

### Assessment
- **Strengths:** Walk-forward prevents in-sample overfitting. Penalizing low trade counts avoids lucky sparse results. Bayesian search (TPE) is efficient vs grid search.
- **Weaknesses:** Only 6 parameters optimized; entry logic structure is fixed. No multi-objective optimization (trade-off between return and drawdown). Single study run — no cross-validation across different time periods.

---

## 5. Backtesting Engine

### Recent Improvements (2026-03-08)
1. **Risk-based position sizing introduced** — `portfolio_pnl_pct` field on `TradeRecord`:
   ```python
   position_size_pct = min(RISK_PER_TRADE_PCT / stop_dist_pct, MAX_POSITION_SIZE_PCT)
   portfolio_pnl_pct = pnl_pct × position_size_pct / 100
   ```
2. **Multi-position support** — `open_trades: List[Dict]` replaces single `open_trade`
3. **Portfolio-wide position cap** — `_apply_portfolio_cap()` enforces MAX_OPEN_POSITIONS=5 across all tickers (FIFO by entry date)
4. **Equity curve compounding** — uses `portfolio_pnl_pct` so drawdown/profit_factor reflect actual capital at risk

### Position Sizing Constants
```python
RISK_PER_TRADE_PCT    = 1.0   # % of portfolio risked per trade
MAX_POSITION_SIZE_PCT = 20.0  # cap on any single position
MAX_OPEN_POSITIONS    = 5     # portfolio-wide concurrent position limit
```

### Before vs After Fix
| Metric | Before | After |
|--------|--------|-------|
| Max drawdown | ~62% | ~5–15% realistic |
| Equity curve | 100% position assumed | Risk-sized positions |
| Position cap | Per-ticker | Portfolio-wide |

### Assessment
- **Strengths:** Compounding is mathematically correct. Dynamic equity sizing is implicit (% of current equity). Portfolio cap prevents over-concentration.
- **Weaknesses:** No slippage model. No commission model. No partial fill simulation. All entries assumed at exact signal price.

---

## 6. Scanner

### Capabilities
- Daily scan against universe of tickers
- RS scoring and ranking
- Multi-engine signal detection
- Results exposed via FastAPI endpoints

### Assessment
- **Strengths:** Clean API design, async data fetching.
- **Weaknesses:** No real-time data — dependent on yfinance end-of-day data. No pre-market scan capability. No alert/notification system.

---

## 7. Risk Management

### Implemented
- 1% portfolio risk per trade (RISK_PER_TRADE_PCT)
- Maximum 20% position size (MAX_POSITION_SIZE_PCT)
- Maximum 5 concurrent positions (MAX_OPEN_POSITIONS)
- ATR-based initial stops
- Trailing stops via TRAIL_ATR_MULT
- Target R:R enforcement before entry

### Not Implemented
- Portfolio heat (total current risk exposure)
- Sector concentration limits
- Correlation-based position sizing
- Drawdown-based position size reduction
- Maximum loss per day/week kill switch
- Earnings blackout periods

---

## 8. Robustness & Testing

### Test Coverage
| Module | Tests | Coverage Areas |
|--------|-------|----------------|
| backtest_engine | ~15 tests | Position sizing, metrics, drawdown, equity curve |
| wfo_engine | ~8 tests | Window generation, portfolio cap, metrics |
| optimizer integration | 4 tests | End-to-end main(), metrics keys, empty windows |

### Test Quality
- TDD-compliant: failing tests written before implementation
- Integration test mocks `run_wfo` — no yfinance calls in CI
- Portfolio cap tested for concurrent, sequential, and partial-overlap scenarios

### Assessment
- **Strengths:** Core calculation logic well-tested. Integration test prevents regressions in optimization pipeline.
- **Weaknesses:** No tests for individual signal engines. No tests for RS calculation. No tests for API endpoints. No performance/load tests.

---

## 9. Missing Components

| Component | Priority | Impact |
|-----------|----------|--------|
| Market regime filter | HIGH | Prevents trading in bear markets |
| Earnings calendar integration | HIGH | Avoids gap risk around reports |
| Slippage + commission model | HIGH | Realistic P&L projection |
| Liquidity filter (min ADV) | MEDIUM | Avoids illiquid setups |
| Live data pipeline | MEDIUM | Required for actual use |
| Paper trading layer | MEDIUM | Validates live signal quality |
| Sector concentration limits | MEDIUM | Portfolio diversification |
| Alert/notification system | LOW | Operational utility |
| Fundamental data (EPS growth, RS Rating) | LOW | O'Neil-complete methodology |

---

## 10. Weak Points

### 1. No Market Regime Filter
The system generates signals regardless of overall market conditions. In a bear market or correction, even RS-strong stocks decline. A simple SPY 200MA filter would prevent trading in unfavorable regimes.

### 2. Single-Period WFO
The optimization uses one continuous WFO run from 2015–2024. This doesn't account for regime shifts (zero-rate era vs high-rate era). Parameters optimal for 2016–2021 may not hold in 2022–2024.

### 3. Look-Ahead Bias Risk
Signal engines must be verified to use only data available at signal date. KDE zone computation, ATR calculation, and RS scoring must all be evaluated as of the signal date, not the backtest end date.

### 4. No Transaction Costs
Backtested returns assume zero slippage and zero commissions. For mid-cap/small-cap stocks with wider spreads, actual returns will be materially lower.

### 5. Synthetic Portfolio Cap
`_apply_portfolio_cap()` filters trades post-hoc by FIFO date ordering. In live trading, which trade gets the slot depends on intraday timing, not just entry date. This approximation is reasonable for daily charts.

---

## 11. Recommended Improvements

### Short-Term (1–2 weeks)
1. **Add SPY 200MA market regime filter** — skip all signals when SPY < 200MA
2. **Add earnings date filter** — skip signals within 10 days of earnings
3. **Add minimum ADV filter** — require $5M+ average daily dollar volume
4. **Add slippage model** — assume 0.05–0.10% slippage on entries/exits

### Medium-Term (1–2 months)
1. **Multi-period WFO validation** — test parameters on 2016–2019, 2019–2022, 2022–2024 separately
2. **Portfolio heat tracking** — real-time total risk exposure calculation
3. **Drawdown circuit breaker** — reduce position sizes by 50% when portfolio DD > 10%
4. **Add engine test suite** — unit tests for each signal engine's core detection logic

### Long-Term (3+ months)
1. **Live data pipeline** — real-time intraday or end-of-day automated scanning
2. **Paper trading layer** — track live signals vs actual price evolution
3. **Fundamental data integration** — EPS growth rate, institutional ownership
4. **Multi-objective optimization** — Pareto front on (return, drawdown, trade frequency)

---

## 12. Maturity Score

| Dimension | Score | Notes |
|-----------|-------|-------|
| Strategy logic | 7/10 | Multiple setups, RS filtering, solid foundation |
| Backtesting rigor | 7/10 | Risk-sized, WFO-validated, no transaction costs |
| Risk management | 6/10 | Position sizing good, no regime/earnings filters |
| Code quality | 7/10 | Clean structure, typed, some test coverage |
| Test coverage | 5/10 | Core logic tested, engines/API untested |
| Production readiness | 3/10 | No live data, no paper trading, no ops layer |
| Optimization | 7/10 | Bayesian WFO is state-of-art, limited param space |

**Overall: 6.0 / 10**

The system is in a solid research/backtesting state. The core methodology (O'Neil-style setups + RS + ATR stops + WFO optimization) is sound and has a track record of working in practice. The primary gap is the distance between a backtested model and a live-tradeable system.

---

*Generated by Claude Code | 2026-03-08*
