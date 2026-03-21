import { ScanLine, Star, Heart, Briefcase, MoreHorizontal } from 'lucide-react'

const TABS = [
  { id: 'scanner',   icon: ScanLine,       label: 'Scanner' },
  { id: 'watchlist', icon: Star,           label: 'WL'      },
  { id: 'favorites', icon: Heart,          label: 'Favs'    },
  { id: 'portfolio', icon: Briefcase,      label: 'Port'    },
  { id: 'more',      icon: MoreHorizontal, label: 'More'    },
]

export default function BottomTabBar({ activePage, onNavigate }) {
  return (
    <nav
      className="bottom-tab-bar"
      style={{
        position: 'fixed',
        bottom: 0,
        left: 0,
        right: 0,
        height: 'calc(56px + env(safe-area-inset-bottom))',
        background: 'var(--panel)',
        borderTop: '1px solid var(--border)',
        alignItems: 'stretch',
        zIndex: 100,
        paddingBottom: 'env(safe-area-inset-bottom)',
      }}
    >
      {TABS.map(({ id, icon: Icon, label }) => {
        const isActive = activePage === id || (id === 'more' && ['analytics', 'diagnostics', 'settings'].includes(activePage))
        return (
          <button
            key={id}
            onClick={() => onNavigate(id)}
            style={{
              flex: 1,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '2px',
              background: 'none',
              border: 'none',
              cursor: 'pointer',
              color: isActive ? 'var(--accent)' : 'var(--muted)',
              padding: '6px 0',
            }}
          >
            <Icon size={20} strokeWidth={1.75} />
            <span style={{
              fontSize: 9,
              fontFamily: '"IBM Plex Mono", monospace',
              fontWeight: 700,
              letterSpacing: '0.06em',
              textTransform: 'uppercase',
              lineHeight: 1,
            }}>
              {label}
            </span>
          </button>
        )
      })}
    </nav>
  )
}
