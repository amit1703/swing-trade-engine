import { TrendingUp, TrendingDown, Minus, Activity } from 'lucide-react'
import { useAppSettings } from '../contexts/AppSettingsContext'

function RegimeCard({ regime, tr }) {
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
        <span className="stat-card-label">{tr('market.regime')}</span>
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
            {(regime.regime_score * 100).toFixed(1)}/100
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


function SpyCard({ regime, tr }) {
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
        <span className="stat-card-label">{tr('market.spyTrend')}</span>
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

function RegimeBanner({ regime }) {
  const regimeType = regime?.regime
  const isAggr = regimeType === 'AGGRESSIVE'
  const isSel  = regimeType === 'SELECTIVE'
  const isDef  = regimeType === 'DEFENSIVE' || (regime && !regime.is_bullish && regimeType)

  if (!regimeType) return null

  let bg, border, icon, title, body

  if (isAggr) {
    bg     = 'rgba(0,200,122,0.07)'
    border = 'rgba(0,200,122,0.25)'
    icon   = '✓'
    title  = 'BULL MARKET — SYSTEM ACTIVE'
    body   = 'Conditions are right. Long swing setups have statistical edge. Run the scanner and take high-quality setups.'
  } else if (isSel) {
    bg     = 'rgba(245,166,35,0.08)'
    border = 'rgba(245,166,35,0.35)'
    icon   = '⚠'
    title  = 'CHOPPY / SIDEWAYS — REDUCED EDGE'
    body   = 'Market is mixed. Long-only mechanics underperform in sideways conditions. If you trade, cut position size in half and only take the highest-scoring setups. Consider standing aside.'
  } else if (isDef) {
    bg     = 'rgba(255,45,85,0.08)'
    border = 'rgba(255,45,85,0.40)'
    icon   = '✕'
    title  = 'BEAR MARKET — DO NOT TRADE THIS SYSTEM'
    body   = 'This is a long-only swing scanner. Long setups lose money in downtrends — the WFO data confirms this. Every stop hit accelerates losses. The correct action is cash. Wait for the regime to return to BULL before trading.'
  } else {
    return null
  }

  const titleColor = isAggr ? 'var(--go)' : isSel ? 'var(--accent)' : 'var(--halt)'

  return (
    <div style={{
      margin: '0 16px 10px',
      padding: '10px 14px',
      background: bg,
      border: `1px solid ${border}`,
      borderRadius: 8,
      display: 'flex',
      gap: 10,
      alignItems: 'flex-start',
      flexShrink: 0,
    }}>
      <span style={{ fontSize: 14, color: titleColor, flexShrink: 0, marginTop: 1 }}>{icon}</span>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
        <span style={{
          fontSize: 10, fontWeight: 700, letterSpacing: '0.1em',
          fontFamily: '"IBM Plex Mono", monospace', color: titleColor,
        }}>
          {title}
        </span>
        <span style={{ fontSize: 11, color: 'var(--text)', lineHeight: 1.5 }}>
          {body}
        </span>
      </div>
    </div>
  )
}

export default function StatCards({ regime }) {
  const { tr, lang } = useAppSettings()
  return (
    <>
      <div className="stat-cards-row flex gap-3 px-4 py-3 flex-shrink-0">
        <RegimeCard regime={regime} tr={tr} />
        <SpyCard regime={regime} tr={tr} />
      </div>
      <RegimeBanner regime={regime} />
    </>
  )
}
