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

export const triggerScan = (force = false, dryRun = false) => {
  const params = new URLSearchParams()
  if (force)  params.set('force', 'true')
  if (dryRun) params.set('dry_run', 'true')
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

export const closeTrade = (id) =>
  fetch(`/api/trades/${id}`, { method: 'DELETE' }).then(handleResponse)
