import { useState, useMemo } from 'react'
import { ArrowUpDown, ArrowUp, ArrowDown } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { useAppSettings } from '../contexts/AppSettingsContext'

const SETUP_TYPE_LABEL = {
  VCP:                'VCP',
  PULLBACK:           'PB',
  'PULLBACK-RLX':     'PB-RLX',
  BASE:               'BASE',
  'RES-BREAKOUT':     'BRK',
  HTF:                'HTF',
  LCE:                'LCE',
}

const TYPE_COLOR = {
  VCP:                '#F5A623',
  PULLBACK:           '#00C8FF',
  'PULLBACK-RLX':     '#00C8FF',
  BASE:               '#9B6EFF',
  'RES-BREAKOUT':     '#00c87a',
  HTF:                '#FF6EC7',
  LCE:                '#9B6EFF',
}

function SortIcon({ col, sortCol, sortDir }) {
  if (sortCol !== col) return <ArrowUpDown size={9} color="var(--muted)" />
  return sortDir === 'desc' ? <ArrowDown size={9} color="var(--accent)" /> : <ArrowUp size={9} color="var(--accent)" />
}

export default function ScannerTable({ allSetups, filters, selectedTicker, onSelectTicker, livePrices = {}, devMode = false, onDebug, favorites = [], onToggleFavorite }) {
  const { tr, lang } = useAppSettings()
  const [sortCol, setSortCol] = useState('score')
  const [sortDir, setSortDir] = useState('desc')
  const [showExtended, setShowExtended] = useState(false)

  const handleSort = (col) => {
    if (sortCol === col) setSortDir(d => d === 'desc' ? 'asc' : 'desc')
    else { setSortCol(col); setSortDir('desc') }
  }

  const rows = useMemo(() => {
    let data = [...allSetups]

    if (filters.setupType !== 'ALL') {
      data = data.filter(s => {
        const t = (s.setup_type ?? '').toUpperCase().replace(/_/g, '-')
        const f = filters.setupType
        if (f === 'VCP')      return t === 'VCP'
        if (f === 'PULLBACK') return t.startsWith('PULLBACK')
        if (f === 'BASE')     return t === 'BASE'
        if (f === 'RES-BRK')  return t === 'RES-BREAKOUT'
        if (f === 'HTF')      return t === 'HTF'
        if (f === 'LCE')      return t === 'LCE'
        return true
      })
    }
    if (filters.minScore > 0) data = data.filter(s => (s.setup_score ?? 0) >= filters.minScore)
    if (filters.hotOnly)      data = data.filter(s => s.hot_sector)
    if (filters.searchQuery)  data = data.filter(s => s.ticker?.includes(filters.searchQuery))

    data.sort((a, b) => {
      let av, bv
      if (sortCol === 'score')  { av = a.setup_score ?? 0; bv = b.setup_score ?? 0 }
      else if (sortCol === 'rs')  { av = a.rs_score ?? -99; bv = b.rs_score ?? -99 }
      else if (sortCol === 'rr')  { av = a.rr ?? 0; bv = b.rr ?? 0 }
      else if (sortCol === 'vol') { av = a.vol_ratio ?? 0; bv = b.vol_ratio ?? 0 }
      else if (sortCol === 'ticker') { av = a.ticker ?? ''; bv = b.ticker ?? '' }
      else { av = a.setup_score ?? 0; bv = b.setup_score ?? 0 }
      return sortDir === 'desc'
        ? (typeof av === 'string' ? bv.localeCompare(av) : bv - av)
        : (typeof av === 'string' ? av.localeCompare(bv) : av - bv)
    })

    if (!showExtended) {
      data = data.filter(s => {
        const lp  = livePrices[s.ticker]
        const atr = s.atr ?? 0
        if (!lp || atr <= 0 || !s.entry) return true
        return (lp - s.entry) / atr < 0.5
      })
    }

    return data
  }, [allSetups, filters, sortCol, sortDir, showExtended, livePrices])

  const COLS = [
    { col: 'score',  label: tr('table.score'),  align: 'right' },
    { col: 'ticker', label: tr('table.ticker'), align: 'left'  },
    { col: null,     label: 'TYPE',             align: 'left'  },
    { col: null,     label: 'PRICE',            align: 'right' },
    { col: 'vol',    label: tr('table.vol'),    align: 'right' },
    { col: 'rs',     label: tr('table.rs'),     align: 'right' },
    { col: null,     label: 'DIST',             align: 'right' },
    { col: null,     label: tr('table.entry'),  align: 'right' },
    { col: null,     label: tr('table.stop'),   align: 'right' },
    { col: 'rr',     label: tr('table.rr'),     align: 'right' },
    { col: null,     label: tr('table.sector'), align: 'left'  },
  ]

  return (
    <div className="flex flex-col flex-1 min-h-0">
      <div className="px-2.5 py-1.5 border-b border-t-border flex justify-end flex-shrink-0 bg-t-card">
        <button
          onClick={() => setShowExtended(v => !v)}
          className={`font-mono text-[8px] font-bold tracking-widest uppercase px-2 py-1 rounded border transition-all ${
            showExtended
              ? 'bg-t-halt/10 border-t-halt/30 text-t-halt'
              : 'border-t-border text-t-muted hover:text-t-text'
          }`}
        >
          {showExtended ? '✕ hide extended' : '+ show extended'}
        </button>
      </div>
      <div className="flex-1 overflow-auto min-h-0">
        <table className="terminal-table">
          <thead>
            <tr>
              {COLS.map(({ col, label, align }) => (
                <th
                  key={label}
                  style={{ textAlign: align, cursor: col ? 'pointer' : 'default', userSelect: 'none', whiteSpace: 'nowrap' }}
                  onClick={col ? () => handleSort(col) : undefined}
                >
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 3 }}>
                    {label}
                    {col && <SortIcon col={col} sortCol={sortCol} sortDir={sortDir} />}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td colSpan={11} style={{ textAlign: 'center', color: 'var(--muted)', padding: '24px', fontSize: 11 }}>
                  {tr('msg.noResults')}
                </td>
              </tr>
            )}
            {rows.map((s, i) => {
              const isSelected  = selectedTicker === s.ticker
              const livePrice   = livePrices[s.ticker]
              const dist        = (livePrice && s.entry > 0) ? ((livePrice - s.entry) / s.entry) * 100 : null
              const isNearEntry = dist !== null && dist > -3 && dist < 0
              const atr         = s.atr ?? 0
              const entryAtrDist = (livePrice && atr > 0 && s.entry > 0) ? (livePrice - s.entry) / atr : null
              const entryQuality = entryAtrDist === null ? null
                : entryAtrDist < 0.1 ? 'EARLY'
                : entryAtrDist < 0.5 ? 'OPTIMAL'
                : 'EXTENDED'
              const isVolSurge  = s.is_vol_surge
              const score       = typeof s.setup_score === 'number' ? Math.round(s.setup_score) : null
              const scoreColor  = score === null ? 'var(--muted)' : score >= 80 ? 'var(--go)' : score >= 60 ? 'var(--accent)' : 'var(--muted)'
              const _rawType    = (s.setup_type ?? '').toUpperCase().replace(/_/g, '-')
              const typeKey     = (s.is_relaxed && _rawType === 'PULLBACK') ? 'PULLBACK-RLX' : _rawType
              const typeLabel   = SETUP_TYPE_LABEL[typeKey] ?? typeKey
              const typeColor   = TYPE_COLOR[typeKey] ?? 'var(--muted)'
              const rsInt       = s.rs_score != null ? Math.round(s.rs_score * 100) : null
              const rsLabel     = rsInt === null ? '—' : rsInt >= 0 ? `+${rsInt}` : `${rsInt}`
              const rsColor     = rsInt === null ? 'var(--muted)' : rsInt >= 5 ? 'var(--go)' : 'var(--muted)'
              const daysOld     = s.setup_date ? Math.floor((Date.now() - new Date(s.setup_date).getTime()) / 86400000) : null
              const isFavorited = favorites.includes(s.ticker)
              const rowBg       = isVolSurge ? 'rgba(0,200,122,0.04)' : isSelected ? 'rgba(245,166,35,0.05)' : undefined
              const borderLeft  = isSelected ? '2px solid var(--accent)' : isNearEntry ? '2px solid rgba(245,166,35,0.6)' : isVolSurge ? '2px solid rgba(0,200,122,0.4)' : '2px solid transparent'

              return (
                <tr
                  key={`${s.ticker}-${s.setup_type}-${i}`}
                  className={`${isSelected ? 'selected' : ''} ${isNearEntry ? 'row-near-entry' : ''}`}
                  style={{ background: rowBg, borderLeft }}
                  onClick={() => onSelectTicker(s.ticker)}
                  onDoubleClick={devMode && onDebug ? () => onDebug(s.ticker) : undefined}
                >
                  <td style={{ textAlign: 'right', width: 40 }}>
                    <span style={{ color: scoreColor, fontWeight: 700, fontSize: 11 }}>{score ?? '—'}</span>
                  </td>
                  <td style={{ textAlign: 'left' }}>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                        <span style={{ fontWeight: 700, fontSize: 11, color: isSelected ? 'var(--accent)' : 'var(--text)' }}>
                          {s.ticker}
                        </span>
                        {s.hot_sector && <span style={{ fontSize: 9 }}>🔥</span>}
                        {s.rs_blue_dot && (
                          <span style={{ width: 5, height: 5, borderRadius: '50%', background: 'var(--blue)', flexShrink: 0, boxShadow: '0 0 4px var(--blue)' }} />
                        )}
                        <button
                          onClick={e => { e.stopPropagation(); onToggleFavorite?.(s.ticker) }}
                          title={isFavorited ? 'Remove from favorites' : 'Add to favorites'}
                          style={{
                            background: 'none', border: 'none', cursor: 'pointer',
                            padding: '0 1px', fontSize: 10, lineHeight: 1,
                            color: isFavorited ? 'var(--accent)' : 'var(--muted)',
                            opacity: isFavorited ? 1 : 0.35,
                            transition: 'color 0.15s, opacity 0.15s',
                          }}
                          onMouseEnter={e => { e.currentTarget.style.opacity = '1'; e.currentTarget.style.color = 'var(--accent)' }}
                          onMouseLeave={e => { e.currentTarget.style.opacity = isFavorited ? '1' : '0.35'; e.currentTarget.style.color = isFavorited ? 'var(--accent)' : 'var(--muted)' }}
                        >
                          {isFavorited ? '★' : '☆'}
                        </button>
                      </div>
                      {daysOld != null && daysOld >= 1 && (
                        <span style={{ fontSize: 8, color: daysOld >= 5 ? 'rgba(255,45,85,0.6)' : 'var(--muted)' }}>{daysOld}d ago</span>
                      )}
                    </div>
                  </td>
                  <td style={{ textAlign: 'left' }}>
                    <span style={{ display: 'inline-block', padding: '1px 5px', borderRadius: 4, fontSize: 8, fontWeight: 700, letterSpacing: '0.06em', background: `${typeColor}18`, color: typeColor, border: `1px solid ${typeColor}30` }}>
                      {typeLabel}
                    </span>
                  </td>
                  <td style={{ textAlign: 'right' }}>
                    {livePrice ? (
                      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 1 }}>
                        <span style={{ color: dist === null ? 'var(--text)' : dist >= 0 ? 'var(--go)' : dist > -3 ? 'var(--accent)' : 'var(--muted)', fontWeight: 600 }}>
                          ${livePrice.toFixed(2)}
                        </span>
                        {dist !== null && (
                          <span style={{ fontSize: 8, color: dist >= 0 ? 'var(--go)' : dist > -3 ? 'var(--accent)' : 'var(--muted)' }}>
                            {dist >= 0 ? `▲${Math.abs(dist).toFixed(1)}%` : `${Math.abs(dist).toFixed(1)}%↓`}
                          </span>
                        )}
                        {entryQuality && (
                          <Badge
                            variant="outline"
                            className={`text-[7px] px-1 py-0 font-mono font-bold h-auto ${
                              entryQuality === 'EARLY'   ? 'border-t-go/30 text-t-go bg-t-go/15' :
                              entryQuality === 'OPTIMAL' ? 'border-t-accent/30 text-t-accent bg-t-accent/15' :
                                                           'border-t-halt/30 text-t-halt bg-t-halt/15'
                            }`}
                          >
                            {entryQuality}
                          </Badge>
                        )}
                      </div>
                    ) : <span style={{ color: 'var(--muted)' }}>—</span>}
                  </td>
                  <td style={{ textAlign: 'right', color: s.is_vol_surge ? 'var(--go)' : 'var(--muted)' }}>{s.vol_ratio ? `×${Number(s.vol_ratio).toFixed(1)}` : '—'}</td>
                  <td style={{ textAlign: 'right', color: rsColor }}>{rsLabel}</td>
                  <td style={{ textAlign: 'right', color: dist !== null && dist > -3 && dist < 0 ? 'var(--accent)' : 'var(--muted)' }}>
                    {dist !== null ? (dist >= 0 ? `+${Math.abs(dist).toFixed(1)}%` : `${Math.abs(dist).toFixed(1)}%↓`) : '—'}
                  </td>
                  <td style={{ textAlign: 'right' }}>{s.entry ? `$${s.entry.toFixed(2)}` : '—'}</td>
                  <td style={{ textAlign: 'right', color: 'var(--halt)' }}>{s.stop_loss ? `$${s.stop_loss.toFixed(2)}` : '—'}</td>
                  <td style={{ textAlign: 'right', color: s.rr && Number(s.rr) >= 2 ? 'var(--go)' : 'var(--muted)' }}>{s.rr ? Number(s.rr).toFixed(1) : '—'}</td>
                  <td style={{ textAlign: 'left', color: 'var(--muted)', fontSize: 9 }}>{s.sector ? s.sector.substring(0, 12) : '—'}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
