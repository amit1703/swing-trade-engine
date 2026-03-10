import { TrendingUp, TrendingDown, Minus, Activity } from 'lucide-react'

function RegimeCard({ regime }) {
  const regimeType  = regime?.regime
  const isNoData    = !regime || !regimeType
  const isAggr      = regimeType === 'AGGRESSIVE'
  const isSel       = regimeType === 'SELECTIVE'
  const isDef       = regimeType === 'DEFENSIVE' || (regime && !regime.is_bullish && !isNoData)

  const label = isAggr ? 'BULL' : isSel ? 'NEUTRAL' : isDef ? 'HALT' : 'NO DATA'
  const color = isAggr ? 'var(--go)' : isSel ? 'var(--accent)' : isDef ? 'var(--halt)' : 'var(--muted)'
  const bg    = isAggr ? 'rgba(0,200,122,0.08)'  : isSel ? 'rgba(245,166,35,0.08)' : isDef ? 'rgba(255,45,85,0.08)' : 'transparent'
  const isBullish = regime?.is_bullish

  return (
    <div className="stat-card" style={{ minWidth: 220 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span className="stat-card-label">Market Regime</span>
        <Activity size={14} color="var(--muted)" />
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <span className="stat-card-value" style={{ color }}>{label}</span>
        {regime?.regime_score != null && (
          <span style={{
            fontSize: 10, padding: '2px 7px', borderRadius: 5,
            background: bg, border: `1px solid ${color}40`,
            color, fontFamily: '"IBM Plex Mono", monospace', fontWeight: 700,
          }}>
            {regime.regime_score}/100
          </span>
        )}
      </div>

      {regime && !isNoData && (
        <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
          {regime.spy_close > 0 && (
            <span style={{ fontSize: 9, fontFamily: '"IBM Plex Mono", monospace', color: 'var(--muted)' }}>
              SPY <span style={{ color: 'var(--text)' }}>${regime.spy_close?.toFixed(2)}</span>
            </span>
          )}
          {regime.vix > 0 && (
            <span style={{ fontSize: 9, fontFamily: '"IBM Plex Mono", monospace', color: 'var(--muted)' }}>
              VIX <span style={{ color: 'var(--text)' }}>{regime.vix?.toFixed(1)}</span>
            </span>
          )}
          {regime.breadth_pct != null && (
            <span style={{ fontSize: 9, fontFamily: '"IBM Plex Mono", monospace', color: 'var(--muted)' }}>
              BRD <span style={{ color: regime.breadth_pct > 0.6 ? 'var(--go)' : regime.breadth_pct > 0.4 ? 'var(--accent)' : 'var(--halt)' }}>
                {Math.round(regime.breadth_pct * 100)}%
              </span>
            </span>
          )}
          <span style={{ fontSize: 9, fontFamily: '"IBM Plex Mono", monospace', color: 'var(--muted)' }}>
            VCP<span style={{ color: isBullish ? 'var(--go)' : 'var(--halt)', marginLeft: 1 }}>{isBullish ? '✔' : '✖'}</span>
            {' '}PB<span style={{ color: isBullish ? 'var(--go)' : 'var(--halt)', marginLeft: 1 }}>{isBullish ? '✔' : '✖'}</span>
          </span>
        </div>
      )}
    </div>
  )
}


function SpyCard({ regime }) {
  const close  = regime?.spy_close ?? 0
  const ema20  = regime?.spy_20ema ?? 0
  const sma50  = regime?.spy_sma50 ?? 0

  const aboveEma = close > 0 && ema20 > 0 && close > ema20
  const aboveSma = close > 0 && sma50 > 0 && close > sma50

  let trend = 'NO DATA'
  let trendColor = 'var(--muted)'
  let TrendIcon = Minus

  if (close > 0 && ema20 > 0) {
    if (aboveEma && aboveSma)  { trend = 'UPTREND';   trendColor = 'var(--go)';     TrendIcon = TrendingUp   }
    else if (!aboveEma)        { trend = 'DOWNTREND'; trendColor = 'var(--halt)';   TrendIcon = TrendingDown }
    else                       { trend = 'MIXED';     trendColor = 'var(--accent)'; TrendIcon = Minus        }
  }

  return (
    <div className="stat-card">
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span className="stat-card-label">SPY Trend</span>
        <TrendIcon size={14} color={trendColor} />
      </div>
      <span className="stat-card-value" style={{ color: trendColor }}>{trend}</span>
      {close > 0 && (
        <span className="stat-card-sub">
          ${close.toFixed(2)}
          {ema20 > 0 && <> · EMA20 <span style={{ color: aboveEma ? 'var(--go)' : 'var(--halt)' }}>{aboveEma ? '↑' : '↓'}</span></>}
          {sma50 > 0 && <> · SMA50 <span style={{ color: aboveSma ? 'var(--go)' : 'var(--halt)' }}>{aboveSma ? '↑' : '↓'}</span></>}
        </span>
      )}
    </div>
  )
}

export default function StatCards({ regime }) {
  return (
    <div style={{ display: 'flex', gap: 12, padding: '12px 16px', flexShrink: 0 }}>
      <RegimeCard regime={regime} />
      <SpyCard regime={regime} />
    </div>
  )
}
