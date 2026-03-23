import { ScanLine, Star, Heart, Briefcase, MoreHorizontal } from 'lucide-react'
import { useAppSettings } from '../contexts/AppSettingsContext'

const TABS = [
  { id: 'scanner',   icon: ScanLine,       labelKey: 'nav.tab.scanner'   },
  { id: 'watchlist', icon: Star,           labelKey: 'nav.tab.watchlist' },
  { id: 'favorites', icon: Heart,          labelKey: 'nav.tab.favorites' },
  { id: 'portfolio', icon: Briefcase,      labelKey: 'nav.tab.portfolio' },
  { id: 'more',      icon: MoreHorizontal, labelKey: 'nav.tab.more'      },
]

export default function BottomTabBar({ activePage, onNavigate }) {
  const { tr, lang } = useAppSettings()
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
      {TABS.map(({ id, icon: Icon, labelKey }) => {
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
              fontFamily: lang === 'he' ? '"Inter", sans-serif' : '"IBM Plex Mono", monospace',
              fontWeight: 700,
              letterSpacing: lang === 'he' ? '0' : '0.06em',
              textTransform: lang === 'he' ? 'none' : 'uppercase',
              lineHeight: 1,
            }}>
              {tr(labelKey)}
            </span>
          </button>
        )
      })}
    </nav>
  )
}
