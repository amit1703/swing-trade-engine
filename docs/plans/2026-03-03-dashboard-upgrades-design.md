# Dashboard Upgrades Design

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Date:** 2026-03-03

## Features

### 1. Live Price Column
New `GET /api/prices?tickers=A,B,C` endpoint. Returns last price per ticker from yfinance, 60s in-memory cache. Frontend polls every 60s while tab is visible. SetupTable gains a "Now $" column (between Ticker and Entry) coloured green ≥ entry, amber within 3%, muted otherwise.

### 3. Watchlist Ranking
Replace distance_pct sort with composite score: `(1 - distance_pct/5.0)*0.5 + rs_score_norm*0.3 + rs_blue_dot*0.2`. Show top 15 by default with "Show all" toggle. Confirmed BRK items always shown.

### 4. Daily Email Digest
APScheduler in FastAPI: scan at 7:30 AM ET, email at 8:00 AM ET. HTML dark-themed email with SPY regime, all setup sections, badges. Gmail SMTP. Credentials in `.env`: `EMAIL_FROM`, `EMAIL_PASSWORD`, `EMAIL_TO` (default: amit.izhari@gmail.com).

### 7. Pullback Engine Fix
- Widen KDE zone tolerance: 0.5% → 2.0%
- Add pure EMA path: uptrend + EMA rejection + CCI hook + vol dry-up (no zone required)

### 8. Options Engine Fix
- ADV floor: 1,000,000 → 500,000
- Min score: 60 → 45
- Per-ticker try/except with 10s timeout, log failures
