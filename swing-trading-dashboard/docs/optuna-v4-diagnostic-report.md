# Optuna v4 — Deep Diagnostic Report

**Generated:** 2026-03-10 11:16
**Universe:** 35 tickers + SPY
**WFO Config:** IS=36m / OOS=6m / step=6m (4 windows)
**OOS Period:** 2023-11-20 → 2025-09-08
**Parameters:** v4 best (trial #951, score=0.5932)

---

## 1. Trade Breakdown by Setup

| Setup | Trades | Win Rate | Avg Win R | Avg Loss R | Expectancy | PF |
|---|---|---|---|---|---|---|
| BASE | 1 | 100.0% | +2.66R | 0.00R | 14.19% | inf |
| PULLBACK | 21 | 38.1% | +1.06R | -0.26R | 1.63% | 2.59 |
| RES_BREAKOUT | 8 | 50.0% | +2.05R | -1.00R | 4.35% | 8.15 |
| VCP | 13 | 61.5% | +0.43R | -0.58R | -0.57% | 0.75 |
| **TOTAL** | **43** | **48.8%** | **+1.08R** | **-0.47R** | **1.76%** | **2.36** |

## 2. Win/Loss Statistics

| Metric | Value |
|---|---|
| Total trades | 43 |
| Wins | 21 (48.8%) |
| Losses | 22 (51.2%) |
| Average win (pnl%) | +6.27% |
| Average loss (pnl%) | -2.53% |
| Largest win | +25.94% |
| Largest loss | -13.15% |
| Average win R-multiple | +1.083R |
| Average loss R-multiple | -0.468R |
| Average R-multiple (all) | 0.290R |
| Expectancy (per trade) | 1.764% |
| Gross profit | +131.57% |
| Gross loss | -55.71% |
| Profit factor | 2.362 |
| Net portfolio P&L | +14.32% |
| Max drawdown | 2.17% (2024-07-11 → 2024-10-01) |

**Exit reason breakdown:**

| Exit Reason | Count | % |
|---|---|---|
| STOP | 34 | 79.1% |
| TARGET | 6 | 14.0% |
| EOD | 3 | 7.0% |

## 3. Trade Distribution Over Time

### By Year

| Year | Trades | Win Rate | Net P&L | PF |
|---|---|---|---|---|
| 2023 | 5 | 100.0% | +10.49% | inf |
| 2024 | 27 | 44.4% | +2.58% | 1.28 |
| 2025 | 11 | 36.4% | +1.25% | 1.00 |

### By Quarter

| Quarter | Trades | Win Rate | Net P&L |
|---|---|---|---|
| 2023-Q4 | 5 | 100.0% | +10.49% |
| 2024-Q1 | 12 | 50.0% | +1.69% |
| 2024-Q2 | 3 | 33.3% | +1.64% |
| 2024-Q3 | 6 | 16.7% | -1.59% |
| 2024-Q4 | 6 | 66.7% | +0.84% |
| 2025-Q1 | 2 | 100.0% | +2.94% |
| 2025-Q3 | 9 | 22.2% | -1.69% |

## 4. Equity Curve

Portfolio starts at 0%. Each trade adds `portfolio_pnl_pct` (1% risk model).

| Exit Date | Trade # | Ticker | R | Cum. P&L |
|---|---|---|---|---|
| 2023-12-13 | 1 | PANW (PULLBACK) | +3.21R ▲ | +3.21% |
| 2023-12-28 | 2 | ISRG (RES_BREAKOUT) | +2.58R ▲ | +5.43% |
| 2023-12-28 | 3 | ISRG (RES_BREAKOUT) | +2.84R ▲ | +7.70% |
| 2023-12-28 | 4 | ISRG (RES_BREAKOUT) | +1.64R ▲ | +9.34% |
| 2023-12-28 | 5 | ISRG (RES_BREAKOUT) | +1.15R ▲ | +10.49% |
| 2024-01-02 | 6 | AAPL (PULLBACK) | -1.00R ▼ | +9.59% |
| 2024-02-05 | 7 | GOOGL (PULLBACK) | +0.63R ▲ | +10.18% |
| 2024-02-09 | 8 | DXCM (PULLBACK) | +0.12R ▲ | +10.30% |
| 2024-02-13 | 9 | GOOGL (VCP) | +0.12R ▲ | +10.41% |
| 2024-02-13 | 10 | GOOGL (PULLBACK) | -0.04R ▼ | +10.37% |
| 2024-02-20 | 11 | MSFT (PULLBACK) | +0.89R ▲ | +11.27% |
| 2024-02-20 | 12 | SNOW (VCP) | +1.60R ▲ | +12.87% |
| 2024-02-26 | 13 | GOOGL (VCP) | +0.01R ▲ | +12.88% |
| 2024-03-05 | 14 | MSFT (PULLBACK) | -0.24R ▼ | +12.64% |
| 2024-03-15 | 15 | MSFT (PULLBACK) | -0.04R ▼ | +12.60% |
| 2024-03-15 | 16 | DXCM (VCP) | -0.31R ▼ | +12.29% |
| 2024-03-15 | 17 | V (PULLBACK) | -0.11R ▼ | +12.18% |
| 2024-05-23 | 18 | DE (VCP) | -1.00R ▼ | +11.18% |
| 2024-05-23 | 19 | NVDA (BASE) | +2.66R ▲ | +13.84% |
| 2024-06-13 | 20 | AMZN (PULLBACK) | -0.02R ▼ | +13.81% |
| 2024-07-11 | 21 | AMZN (VCP) | +0.39R ▲ | +14.20% |
| 2024-07-11 | 22 | META (RES_BREAKOUT) | -1.00R ▼ | +13.92% |
| 2024-07-11 | 23 | META (RES_BREAKOUT) | -1.00R ▼ | +13.64% |
| 2024-07-15 | 24 | ENPH (RES_BREAKOUT) | -1.00R ▼ | +13.26% |
| 2024-07-17 | 25 | ENPH (RES_BREAKOUT) | -1.00R ▼ | +13.22% |
| 2024-07-18 | 26 | CRWD (PULLBACK) | -1.00R ▼ | +12.22% |
| 2024-10-01 | 27 | ISRG (PULLBACK) | -0.20R ▼ | +12.03% |
| 2024-10-31 | 28 | ISRG (PULLBACK) | +0.29R ▲ | +12.32% |
| 2024-10-31 | 29 | NVDA (VCP) | +0.13R ▲ | +12.45% |
| 2024-12-03 | 30 | ISRG (VCP) | +0.36R ▲ | +12.82% |
| 2024-12-18 | 31 | META (VCP) | -0.40R ▼ | +12.42% |
| 2024-12-20 | 32 | MSFT (VCP) | +0.65R ▲ | +13.07% |
| 2025-01-13 | 33 | GOOGL (PULLBACK) | +2.33R ▲ | +15.10% |
| 2025-02-21 | 34 | JPM (PULLBACK) | +0.91R ▲ | +16.01% |
| 2025-07-03 | 35 | DXCM (VCP) | +0.17R ▲ | +16.18% |
| 2025-07-10 | 36 | PANW (PULLBACK) | -0.06R ▼ | +16.12% |
| 2025-07-30 | 37 | VEEV (PULLBACK) | -0.01R ▼ | +16.10% |
| 2025-07-30 | 38 | VEEV (PULLBACK) | -0.07R ▼ | +16.03% |
| 2025-07-30 | 39 | VEEV (PULLBACK) | +0.07R ▲ | +16.11% |
| 2025-08-01 | 40 | DE (PULLBACK) | -0.37R ▼ | +15.74% |
| 2025-08-01 | 41 | DE (PULLBACK) | -0.24R ▼ | +15.50% |
| 2025-08-18 | 42 | SBUX (VCP) | -0.19R ▼ | +15.32% |
| 2025-09-08 | 43 | SBUX (VCP) | -1.00R ▼ | +14.32% |

**Final equity:** +14.32%
**Max drawdown:** 2.17% (peak 2024-07-11 → trough 2024-10-01)

## 5. Consecutive Loss / Win Statistics

| Metric | Value |
|---|---|
| Max winning streak | 5 trades |
| Max losing streak | 6 trades |
| Avg winning streak | 2.6 trades |
| Avg losing streak | 2.8 trades |

**Win/Loss sequence (W=win, L=loss):**

`WWWWWLWWWLWWWLLLLLWLWLLLLLLWWWLWWWWLLLWLLLL`

## 6. R-Multiple Distribution

| R Bucket | Count | % | Distribution |
|---|---|---|---|
| -1R (stop) | 8 | 18.6% | █████░░░░░░░░░░░░░░░░░░░░░░░░░ |
| 0 to -0.5R (partial stop) | 14 | 32.6% | █████████░░░░░░░░░░░░░░░░░░░░░ |
| 0 to 1R (small win/scratch) | 13 | 30.2% | █████████░░░░░░░░░░░░░░░░░░░░░ |
| 1R to 2R | 3 | 7.0% | ██░░░░░░░░░░░░░░░░░░░░░░░░░░░░ |
| 2R to 5R | 5 | 11.6% | ███░░░░░░░░░░░░░░░░░░░░░░░░░░░ |
| 5R+ (runner) | 0 | 0.0% | ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ |

**All R values:** min=-1.00 | median=-0.01 | mean=0.29 | max=3.21

## 7. Holding Time Analysis

| Metric | Value |
|---|---|
| Average hold | 19.2 days |
| Median hold | 15 days |
| Shortest hold | 1 days |
| Longest hold | 77 days |

**Hold duration distribution:**

| Duration | Count | % | Distribution |
|---|---|---|---|
| 1–3 days | 8 | 18.6% | █████░░░░░░░░░░░░░░░░░░░░░░░░░ |
| 4–7 days | 4 | 9.3% | ██░░░░░░░░░░░░░░░░░░░░░░░░░░░░ |
| 8–14 days | 9 | 20.9% | ██████░░░░░░░░░░░░░░░░░░░░░░░░ |
| 15–30 days | 12 | 27.9% | ████████░░░░░░░░░░░░░░░░░░░░░░ |
| 31+ days | 10 | 23.3% | ██████░░░░░░░░░░░░░░░░░░░░░░░░ |

## 8. Market Exposure

| Metric | Value |
|---|---|
| Total OOS calendar days | 731 |
| Total hold-days (all trades) | 825 |
| Avg trades open simultaneously | 1.13 |
| Rough exposure (hold-days / OOS days) | 112.9% |

> Note: Exposure calculation counts each trade's holding period independently.
> With MAX_OPEN_POSITIONS=5, maximum theoretical exposure is 5×1%=5% equity at risk at any time.

## 9. Per-Window Performance (Regime Analysis)

Each OOS window represents 6 months. Performance variation across windows
reveals regime sensitivity — good windows correspond to trending markets.

| Window | OOS Period | Trades | Win Rate | PF | Net P&L |
|---|---|---|---|---|---|
| W1 ✅ | 2023-09-16 → 2024-03-16 | 17 | 64.7% | 7.72 | +12.18% |
| W2 ❌ | 2024-03-16 → 2024-09-16 | 9 | 22.2% | 0.75 | +0.05% |
| W3 ✅ | 2024-09-16 → 2025-03-16 | 8 | 75.0% | 7.72 | +3.79% |
| W4 ❌ | 2025-03-16 → 2025-09-16 | 9 | 22.2% | 0.07 | -1.69% |

Legend: ✅ PF ≥ 2.0 (strong) | ⚠️ PF 1.0–2.0 (marginal) | ❌ PF < 1.0 (losing window)

## 10. Ticker Concentration

| Ticker | Trades | Win Rate | Net Contribution | % of Total Trades |
|---|---|---|---|---|
| ISRG | 7 | 86% | +7.73% | 16.3% |
| GOOGL | 5 | 80% | +2.71% | 11.6% |
| MSFT | 4 | 50% | +1.26% | 9.3% |
| DXCM | 3 | 67% | -0.02% | 7.0% |
| DE | 3 | 0% | -1.61% | 7.0% |
| META | 3 | 0% | -0.96% | 7.0% |
| VEEV | 3 | 33% | -0.01% | 7.0% |
| PANW | 2 | 50% | +3.15% | 4.7% |
| NVDA | 2 | 100% | +2.79% | 4.7% |
| AMZN | 2 | 50% | +0.36% | 4.7% |
| ENPH | 2 | 0% | -0.41% | 4.7% |
| SBUX | 2 | 0% | -1.19% | 4.7% |
| AAPL | 1 | 0% | -0.90% | 2.3% |
| SNOW | 1 | 100% | +1.60% | 2.3% |
| V | 1 | 0% | -0.11% | 2.3% |
| CRWD | 1 | 0% | -1.00% | 2.3% |
| JPM | 1 | 100% | +0.91% | 2.3% |

**Top 5 tickers:** 22 trades (51.2% of total)

**Herfindahl concentration index:** 0.0817
(0 = perfectly distributed, 1 = all trades in one ticker; <0.10 = well diversified)

## 11. Summary Diagnostics

### Statistical Reliability

- 🟡 **THIN** — fewer than 50 OOS trades. Confidence intervals are wide. Treat with caution.
- **OOS trades:** 43 | **Win rate 95% CI:** 33.9% – 63.8% (point estimate: 48.8%)
- **Recommended minimum:** 100 OOS trades for live deployment confidence

### Concentration Risk

- 🟢 **WELL DISTRIBUTED** — top 5 tickers = 51.2% of trades.
- Herfindahl index: 0.0817

### Performance Quality

- 🟢 **LOW DRAWDOWN** — 2.17%. System demonstrates strong drawdown control.
- 🟡 **GOOD PROFIT FACTOR** — 2.36. Solid edge.
- 🔴 **INCONSISTENT** — only 2/4 windows profitable.

### Universe Recommendation

- 🔴 **EXPAND UNIVERSE** — critical. Current sample is too thin for live deployment confidence.
- Current: 35 tickers → generates ~43 OOS trades over ~2y
- To reach 100 OOS trades: estimate ~81 tickers needed

### Key Risks for Live Trading

1. **Statistical thinness:** 43 trades → confidence intervals wide. Single bad month can look like strategy failure.
2. **Regime dependency:** System requires REGIME_SELECTIVE_THRESHOLD=59. If SPY weakens, the system goes dark for months.
3. **TRAIL=4.16 ATR sensitivity:** Wide trailing stops can give back significant open profit in a sharp market reversal.
4. **yfinance data quality:** Live scanner uses yfinance; backtests use cached adjusted prices. Small discrepancies may exist.
5. **OOS ≠ Live:** Walk-forward avoids lookahead but cannot replicate slippage, partial fills, or regime breaks between windows.

---

*Generated by v4_diagnostic.py on 2026-03-10 11:16*