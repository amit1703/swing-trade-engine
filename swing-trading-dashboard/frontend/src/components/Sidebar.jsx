import {
  ScanLine,
  Star,
  Heart,
  Briefcase,
  BarChart2,
  Activity,
  Settings,
  TrendingUp,
} from 'lucide-react'

const NAV_ITEMS = [
  { id: 'scanner',     icon: ScanLine,  label: 'Scanner'     },
  { id: 'watchlist',   icon: Star,      label: 'Watchlist'   },
  { id: 'favorites',   icon: Heart,     label: 'Favorites'   },
  { id: 'portfolio',   icon: Briefcase, label: 'Portfolio'   },
  { id: 'analytics',   icon: BarChart2, label: 'Analytics'   },
  { id: 'diagnostics', icon: Activity,  label: 'Diagnostics' },
]

export default function Sidebar({ activePage, onNavigate }) {
  return (
    <nav className="hidden sm:flex w-56 flex-shrink-0 bg-t-panel border-r border-t-border flex-col h-full">

      {/* Logo */}
      <div className="flex items-center gap-2.5 px-4 py-4 border-b border-t-border flex-shrink-0">
        <div className="size-8 rounded-lg bg-gradient-to-br from-t-accent to-t-go flex items-center justify-center flex-shrink-0">
          <TrendingUp size={16} className="text-black" strokeWidth={2.5} />
        </div>
        <span className="font-mono font-bold text-base text-t-accent tracking-wider">SCANR</span>
      </div>

      {/* Main nav */}
      <div className="flex-1 flex flex-col gap-1 px-2 py-3">
        {NAV_ITEMS.map(({ id, icon: Icon, label }) => {
          const isActive = activePage === id
          return (
            <button
              key={id}
              onClick={() => onNavigate(id)}
              title={label}
              className={[
                'w-full flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-mono font-medium transition-colors duration-150 border',
                isActive
                  ? 'bg-t-accent/10 text-t-accent border-t-accent/20'
                  : 'text-t-muted hover:bg-white/5 hover:text-t-text border-transparent',
              ].join(' ')}
            >
              <Icon size={17} strokeWidth={1.75} />
              {label}
            </button>
          )
        })}
      </div>

      {/* Bottom: Settings */}
      <div className="px-2 py-3 border-t border-t-border flex-shrink-0">
        <button
          onClick={() => onNavigate('settings')}
          title="Settings"
          className={[
            'w-full flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-mono font-medium transition-colors duration-150 border',
            activePage === 'settings'
              ? 'bg-t-accent/10 text-t-accent border-t-accent/20'
              : 'text-t-muted hover:bg-white/5 hover:text-t-text border-transparent',
          ].join(' ')}
        >
          <Settings size={17} strokeWidth={1.75} />
          Settings
        </button>
      </div>
    </nav>
  )
}
