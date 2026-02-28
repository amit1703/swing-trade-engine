/**
 * SetupTable — Reusable dense data grid for VCP / Pullback setups
 *
 * Columns: TICKER | ENTRY | STOP | TARGET | R:R | INFO
 *
 * Row highlighting:
 *   - Green background  → Volume Surge confirmed (is_vol_surge === true)
 *   - Amber border-left → Selected ticker
 *
 * Info column badges (VCP):
 *   BRK  → Confirmed breakout (is_breakout true, vol surge, RS+)
 *   DRY  → Coiled spring dry-up below resistance
 *   Vol ratio shown as "×1.8" next to badge
 *   RS+  → Stock 3m RS outperforming SPY (rs_vs_spy > 0)
 */
export default function SetupTable({ title, accentColor, setups, selectedTicker, onSelectTicker, loading, devMode, onDebug }) {
  const count = setups.length

  const color = accentColor === 'blue'
    ? { badge: 'bg-t-blueDim text-t-blue border border-t-blue/30', dot: '#00C8FF', sectionDot: 'bg-t-blue' }
    : accentColor === 'green'
    ? { badge: 'bg-t-goDim text-t-go border border-t-go/30', dot: '#00c87a', sectionDot: 'bg-t-go' }
    : { badge: 'bg-t-accentDim text-t-accent border border-t-accent/30', dot: '#F5A623', sectionDot: 'bg-t-accent' }

  return (
    <div className="flex flex-col border-b border-t-border" style={{ background: 'var(--panel)' }}>

      {/* Section header */}
      <div className="section-label">
        <span className={`inline-block w-1.5 h-1.5 rounded-full ${color.sectionDot}`} />
        {title}
        <span className={`badge ${color.badge} ml-auto`}>
          {count} setup{count !== 1 ? 's' : ''}
        </span>
      </div>

      {/* Table */}
      {loading ? (
        <div className="p-2 flex flex-col gap-1">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="shimmer-row" style={{ opacity: 1 - i * 0.25 }} />
          ))}
        </div>
      ) : count === 0 ? (
        <div className="py-5 text-center text-t-muted text-[10px] tracking-widest uppercase">
          No setups
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="terminal-table">
            <thead>
              <tr>
                <th style={{ textAlign: 'left' }}>Ticker</th>
                <th>Entry $</th>
                <th>Stop $</th>
                <th>Target $</th>
                <th>R:R</th>
                <th style={{ textAlign: 'left' }}>Signal</th>
                {devMode && <th style={{ width: 24 }} />}
              </tr>
            </thead>
            <tbody>
              {setups.map((s) => {
                const isSelected        = selectedTicker === s.ticker
                const isVolSurge        = s.is_vol_surge === true
                const isBrk             = s.is_breakout === true
                const isRsPlus          = typeof s.rs_vs_spy === 'number' && s.rs_vs_spy > 0
                const isTrendlineBreakout = s.is_trendline_breakout === true
                const isKdeBreakout     = s.is_kde_breakout === true
                const isRelaxed         = s.is_relaxed === true
                const isRsLead          = s.is_rs_lead === true
                const isAscendingTdl    = s.is_ascending_tdl === true
                const isCupHandle       = s.base_type === 'CUP_HANDLE'
                const isFlatBase        = s.base_type === 'FLAT_BASE'
                const qualityScore      = typeof s.quality_score === 'number' ? s.quality_score : null
                const isBaseBrk         = s.setup_type === 'BASE' && s.signal === 'BRK'
                const isBaseDry         = s.setup_type === 'BASE' && s.signal === 'DRY'

                // Row background: green tint for volume-surge rows
                const rowStyle = isVolSurge
                  ? { background: 'rgba(0, 200, 122, 0.06)', borderLeft: '2px solid rgba(0,200,122,0.45)' }
                  : isSelected
                  ? {}
                  : {}

                return (
                  <tr
                    key={`${s.ticker}-${s.setup_type}`}
                    className={isSelected ? 'selected' : ''}
                    style={rowStyle}
                    onClick={() => onSelectTicker(s.ticker)}
                  >
                    {/* Ticker */}
                    <td>
                      <span
                        className="font-600 tracking-wide"
                        style={{ color: isSelected ? 'var(--accent)' : color.dot }}
                      >
                        {s.ticker}
                      </span>
                      {s.hot_sector && (
                        <span title={`Hot sector: ${s.sector ?? ''} (3+ setups)`} style={{ marginLeft: 3, fontSize: 10 }}>🔥</span>
                      )}
                    </td>

                    {/* Entry */}
                    <td className="text-t-text">{fmt(s.entry)}</td>

                    {/* Stop — red */}
                    <td style={{ color: 'var(--halt)' }}>{fmt(s.stop_loss)}</td>

                    {/* Target — green */}
                    <td style={{ color: 'var(--go)' }}>{fmt(s.take_profit)}</td>

                    {/* R:R */}
                    <td className="text-t-muted">{s.rr?.toFixed(1) ?? '2.0'}</td>

                    {/* Signal column */}
                    <td style={{ textAlign: 'left' }}>
                      {s.setup_type === 'VCP' ? (
                        <div className="flex items-center gap-1 flex-wrap">
                          {/* LEAD badge — RS LEAD setups (cyan, priority) */}
                          {isRsLead && (
                            <span
                              className="badge"
                              style={{ background: 'rgba(0,200,255,0.10)', color: '#00C8FF', border: '1px solid rgba(0,200,255,0.3)', fontWeight: 700 }}
                            >
                              LEAD
                            </span>
                          )}

                          {/* KDE badge — only if NOT RS LEAD */}
                          {!isRsLead && isKdeBreakout && (
                            <span
                              className="badge"
                              style={{ background: 'rgba(0,200,255,0.10)', color: '#00C8FF', border: '1px solid rgba(0,200,255,0.3)', fontWeight: 700 }}
                            >
                              KDE
                            </span>
                          )}

                          {/* BRK / DRY badge — only if NOT RS LEAD and NOT KDE breakout */}
                          {!isRsLead && !isKdeBreakout && (
                            <span
                              className="badge"
                              style={isBrk
                                ? { background: 'rgba(0,200,122,0.18)', color: 'var(--go)', border: '1px solid rgba(0,200,122,0.4)', fontWeight: 700 }
                                : { background: 'rgba(245,166,35,0.12)', color: 'var(--accent)', border: '1px solid rgba(245,166,35,0.3)' }
                              }
                            >
                              {isBrk ? 'BRK' : 'DRY'}
                            </span>
                          )}

                          {/* Volume ratio — shown for all VCP */}
                          {s.volume_ratio != null && (
                            <span
                              className="font-mono text-[8px] tabular-nums"
                              style={{ color: isVolSurge ? 'var(--go)' : 'var(--muted)' }}
                            >
                              ×{s.volume_ratio.toFixed(1)}
                            </span>
                          )}

                          {/* RS+ badge — only when outperforming SPY */}
                          {isRsPlus && (
                            <span
                              className="badge"
                              style={{ background: 'rgba(0,200,255,0.10)', color: '#00C8FF', border: '1px solid rgba(0,200,255,0.3)', fontSize: 8 }}
                            >
                              RS+
                            </span>
                          )}

                          {/* TDL badge — trendline breakout */}
                          {isTrendlineBreakout && (
                            <span
                              className="badge"
                              style={{ background: 'rgba(255,255,255,0.08)', color: '#FFFFFF', border: '1px solid rgba(255,255,255,0.25)', fontSize: 8 }}
                            >
                              TDL
                            </span>
                          )}
                        </div>
                      ) : s.setup_type === 'PULLBACK' ? (
                        /* Pullback: show CCI value + ASC-TDL badge + RLX badge */
                        <div className="flex items-center gap-1">
                          <span className="text-t-muted text-[9px]">
                            CCI {s.cci_today?.toFixed(0) ?? '—'}
                          </span>

                          {/* ASC-TDL badge — Ascending trendline pullback (NEW) */}
                          {isAscendingTdl && (
                            <span
                              className="badge"
                              style={{
                                background: '#FF6B35',
                                color: 'white',
                                border: 'none',
                                fontSize: '7px',
                                fontWeight: '700',
                                letterSpacing: '0.5px',
                                padding: '2px 4px',
                              }}
                              title="Ascending Trendline Pullback (3rd touch bounce)"
                            >
                              ASC-TDL
                            </span>
                          )}

                          {isRelaxed && (
                            <span
                              className="badge"
                              style={{ background: 'rgba(245,166,35,0.12)', color: 'var(--accent)', border: '1px solid rgba(245,166,35,0.3)', fontSize: 7 }}
                            >
                              RLX
                            </span>
                          )}
                        </div>
                      ) : s.setup_type === 'RES_BREAKOUT' ? (
                        /* Resistance Breakout: level, break%, vol ratio, days since */
                        <div className="flex items-center gap-1 flex-wrap">
                          <span
                            className="badge"
                            style={{ background: 'rgba(0,200,122,0.18)', color: 'var(--go)',
                                     border: '1px solid rgba(0,200,122,0.4)', fontWeight: 700 }}
                          >
                            BRK
                          </span>
                          {s.resistance_level != null && (
                            <span className="font-mono text-[8px] tabular-nums text-t-muted">
                              L{s.resistance_level.toFixed(2)}
                            </span>
                          )}
                          {s.volume_ratio != null && (
                            <span className="font-mono text-[8px] tabular-nums"
                              style={{ color: 'var(--go)' }}>
                              ×{s.volume_ratio.toFixed(1)}
                            </span>
                          )}
                          {s.days_since_breakout != null && (
                            <span className="font-mono text-[8px] tabular-nums text-t-muted">
                              {s.days_since_breakout === 0 ? 'today' : `${s.days_since_breakout}d ago`}
                            </span>
                          )}
                        </div>
                      ) : (
                        /* BASE: C&H / FLAT pattern badge + BRK/DRY signal + quality score + RS+ */
                        <div className="flex items-center gap-1 flex-wrap">
                          {/* Pattern type badge */}
                          {isCupHandle && (
                            <span
                              className="badge"
                              style={{ background: 'rgba(38,166,154,0.12)', color: '#26a69a',
                                       border: '1px solid rgba(38,166,154,0.35)', fontWeight: 700 }}
                            >
                              C&amp;H
                            </span>
                          )}
                          {isFlatBase && (
                            <span
                              className="badge"
                              style={{ background: 'rgba(66,165,245,0.12)', color: '#42a5f5',
                                       border: '1px solid rgba(66,165,245,0.35)', fontWeight: 700 }}
                            >
                              FLAT
                            </span>
                          )}

                          {/* BRK / DRY signal */}
                          <span
                            className="badge"
                            style={isBaseBrk
                              ? { background: 'rgba(0,200,122,0.12)', color: 'var(--go)', border: '1px solid rgba(0,200,122,0.3)', fontWeight: 700 }
                              : { background: 'rgba(245,166,35,0.12)', color: 'var(--accent)', border: '1px solid rgba(245,166,35,0.3)', fontWeight: 700 }
                            }
                          >
                            {isBaseBrk ? 'BRK' : 'DRY'}
                          </span>

                          {/* Quality score */}
                          {qualityScore !== null && (
                            <span
                              className="badge"
                              style={{ fontFamily: 'monospace', fontSize: 9,
                                       background: 'rgba(255,255,255,0.04)', color: 'var(--t-muted)',
                                       border: '1px solid var(--border)' }}
                              title={`Quality score: ${qualityScore}/100`}
                            >
                              Q{qualityScore}
                            </span>
                          )}

                          {/* RS+ badge */}
                          {isRsPlus && (
                            <span
                              className="badge"
                              style={{ fontSize: 7, background: 'rgba(0,200,255,0.08)', color: '#00C8FF',
                                       border: '1px solid rgba(0,200,255,0.2)', fontWeight: 600 }}
                            >
                              RS+
                            </span>
                          )}
                        </div>
                      )}
                    </td>

                    {/* Dev mode debug button */}
                    {devMode && (
                      <td style={{ width: 24, textAlign: 'center' }}>
                        <button
                          onClick={(e) => { e.stopPropagation(); onDebug?.(s.ticker) }}
                          title={`Debug ${s.ticker}`}
                          style={{
                            background: 'none',
                            border: '1px solid var(--border-light)',
                            color: 'var(--muted)',
                            fontSize: 8,
                            padding: '1px 4px',
                            cursor: 'pointer',
                            fontFamily: 'IBM Plex Mono, monospace',
                            letterSpacing: '0.05em',
                          }}
                          onMouseEnter={e => { e.currentTarget.style.color = 'var(--accent)'; e.currentTarget.style.borderColor = 'var(--accent)' }}
                          onMouseLeave={e => { e.currentTarget.style.color = 'var(--muted)'; e.currentTarget.style.borderColor = 'var(--border-light)' }}
                        >
                          ?
                        </button>
                      </td>
                    )}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

/** Format a price number to 2 decimal places */
const fmt = (n) => (n == null ? '—' : n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }))
