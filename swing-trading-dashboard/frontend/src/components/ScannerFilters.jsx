import { Filter, Flame } from 'lucide-react'

const SETUP_TYPES = ['ALL', 'VCP', 'PULLBACK', 'BASE', 'RES-BRK', 'HTF', 'LCE']

export default function ScannerFilters({ filters, onFiltersChange }) {
  const { minScore, setupType, hotOnly, searchQuery } = filters
  const update = (key, val) => onFiltersChange({ ...filters, [key]: val })

  return (
    <div className="flex items-center gap-2.5 flex-wrap px-4 py-2 bg-t-card border-b border-t-cardBorder flex-shrink-0">
      <Filter size={13} className="text-t-muted flex-shrink-0" />
      <span className="font-mono text-[10px] text-t-muted tracking-wider font-semibold">FILTER</span>

      <div className="flex items-center gap-1.5">
        <span className="font-mono text-[10px] text-t-muted">Score ≥</span>
        <input
          type="number" min={0} max={100} step={5}
          value={minScore}
          onChange={e => update('minScore', Number(e.target.value))}
          className="w-12 text-center bg-t-panel border border-t-border rounded px-2 py-0.5 font-mono text-[11px] text-t-text outline-none focus:border-t-accent"
        />
      </div>

      <div className="w-px h-4 bg-t-border flex-shrink-0" />

      <div className="flex items-center gap-1">
        {SETUP_TYPES.map(t => (
          <button
            key={t}
            onClick={() => update('setupType', t)}
            className={`font-mono text-[9px] font-bold px-2 py-0.5 rounded border transition-colors ${
              setupType === t
                ? 'bg-t-accent/10 text-t-accent border-t-accent/30'
                : 'bg-t-panel text-t-muted border-transparent hover:text-t-text'
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      <div className="w-px h-4 bg-t-border flex-shrink-0" />

      <input
        value={searchQuery}
        onChange={e => update('searchQuery', e.target.value.toUpperCase())}
        placeholder="TICKER..."
        className="w-20 bg-t-panel border border-t-border rounded px-2 py-0.5 font-mono text-[11px] text-t-text outline-none focus:border-t-accent"
      />

      <div className="flex-1" />

      <button
        onClick={() => update('hotOnly', !hotOnly)}
        className={`flex items-center gap-1.5 px-2.5 py-1 rounded border font-mono text-[10px] font-bold transition-colors ${
          hotOnly
            ? 'bg-t-accent/10 text-t-accent border-t-accent/30'
            : 'bg-t-panel text-t-muted border-t-border hover:text-t-text'
        }`}
      >
        <Flame size={11} /> HOT
      </button>
    </div>
  )
}
