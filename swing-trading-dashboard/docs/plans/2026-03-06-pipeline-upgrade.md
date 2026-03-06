# Pipeline Upgrade — Tasks 1, 5, 6, 7, 15

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Upgrade the scan pipeline with a centralized indicator engine, earnings blackout filter, liquidity gate, bulk data download, and granular performance timing.

**Architecture:** Indicators computed once per ticker in `indicator_engine.py` → passed to liquidity + earnings gates → surviving tickers fed to trading engines. Bulk `yf.download()` batches replace per-ticker calls. Timing captured at fetch / indicator / engine / DB phases.

**Tech Stack:** Python 3.10, FastAPI, yfinance, pandas, numpy, aiosqlite

---

### Task 5+6+7+1+15: constants.py + indicator_engine.py + main.py

**Files:**
- Modify: `backend/constants.py`
- Create: `backend/indicators/__init__.py`
- Create: `backend/indicators/indicator_engine.py`
- Modify: `backend/main.py`
- Create: `backend/cache/earnings_cache.json` (auto-created at runtime)

See implementation in adjacent commit.
