/**
 * API client — all requests proxied through Vite to http://localhost:8000
 */

const handleResponse = async (res) => {
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText)
    throw new Error(`API ${res.status}: ${text}`)
  }
  return res.json()
}

export const fetchRegime = () =>
  fetch('/api/regime').then(handleResponse)

export const fetchSetups = (type) =>
  fetch(`/api/setups/${type}`).then(handleResponse)

export const fetchAllSetups = () =>
  fetch('/api/setups').then(handleResponse)

export const fetchWatchlist = () =>
  fetch('/api/watchlist').then(handleResponse)

export const fetchChartData = (ticker) =>
  fetch(`/api/chart/${ticker}`).then(handleResponse)

export const fetchSrZones = (ticker) =>
  fetch(`/api/sr-zones/${ticker}`).then(handleResponse)

export const triggerScan = (force = false, dryRun = false, tickers = null) => {
  const params = new URLSearchParams()
  if (force)   params.set('force', 'true')
  if (dryRun)  params.set('dry_run', 'true')
  if (tickers) params.set('tickers', tickers)
  const qs = params.toString()
  return fetch(`/api/run-scan${qs ? '?' + qs : ''}`, { method: 'POST' }).then(handleResponse)
}

export const fetchDebugTicker = (ticker) =>
  fetch(`/api/debug/${ticker}`).then(handleResponse)

export const fetchScanStatus = () =>
  fetch('/api/scan-status').then(handleResponse)

// ── Trades ────────────────────────────────────────────────────────────────

export const fetchTrades = () =>
  fetch('/api/trades').then(handleResponse)

export const addTrade = (body) =>
  fetch('/api/trades', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }).then(handleResponse)

export const closeTrade = (id, exitPrice = null, exitDate = null) =>
  fetch(`/api/trades/${id}`, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ exit_price: exitPrice, exit_date: exitDate }),
  }).then(handleResponse)

export const fetchClosedTrades = () =>
  fetch('/api/trades/closed').then(handleResponse)

export const fetchOptionsSetups = () =>
  fetch('/api/setups/options-catalyst').then(handleResponse)

export const fetchPrices = (tickers) =>
  fetch(`/api/prices?tickers=${tickers.join(',')}`).then(handleResponse)

export const fetchMarketOverview = () =>
  fetch('/api/market-overview').then(handleResponse)

export const runBacktest = (ticker, startDate, endDate, setupTypes = ['VCP', 'PULLBACK', 'BASE']) =>
  fetch('/api/run-backtest', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ticker, start_date: startDate, end_date: endDate, setup_types: setupTypes }),
  }).then(handleResponse)

export const fetchBacktestResults = (ticker) =>
  fetch(`/api/backtest-results/${encodeURIComponent(ticker)}`).then(handleResponse)

// ─── Walk-Forward Validation ─────────────────────────────────────────────────

export async function wfoDownload(tickers) {
  const res = await fetch('/api/wfo/download', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tickers }),
  })
  return res.json()
}

export async function wfoDownloadStatus(jobId) {
  const res = await fetch(`/api/wfo/download-status/${jobId}`)
  return res.json()
}

export async function wfoRun(params) {
  const res = await fetch('/api/wfo/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  return res.json()
}

export async function wfoStatus(runId) {
  const res = await fetch(`/api/wfo/status/${runId}`)
  return res.json()
}

export async function wfoResults(runId) {
  const res = await fetch(`/api/wfo/results/${runId}`)
  return res.json()
}

export function wfoExportUrl(runId) {
  return `/api/wfo/export/${runId}`
}

export async function wfoAudit(runId, period = 'oos') {
  const res = await fetch(`/api/wfo/audit/${runId}?period=${period}`)
  return res.json()
}

export const buildUniverse = () =>
  fetch('/api/build-universe', { method: 'POST' }).then(handleResponse)

export const fetchAnalysis = (ticker) =>
  fetch(`/api/analyze/${ticker}`).then(handleResponse)
