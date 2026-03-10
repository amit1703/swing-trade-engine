import {
  ScanLine,
  Star,
  Briefcase,
  BarChart2,
  Settings,
} from 'lucide-react'

const NAV_ITEMS = [
  { id: 'scanner',   icon: ScanLine,  label: 'Scanner'   },
  { id: 'watchlist', icon: Star,      label: 'Watchlist' },
  { id: 'portfolio', icon: Briefcase, label: 'Portfolio' },
  { id: 'analytics', icon: BarChart2, label: 'Analytics' },
]

export default function Sidebar({ activePage, onNavigate }) {
  return (
    <nav
      style={{
        width: 60,
        flexShrink: 0,
        background: 'var(--surface)',
        borderRight: '1px solid var(--border)',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        paddingTop: 12,
        paddingBottom: 12,
        gap: 4,
      }}
    >
      {/* Logo mark */}
      <div style={{
        width: 36,
        height: 36,
        borderRadius: 8,
        background: 'var(--go)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        marginBottom: 12,
        flexShrink: 0,
      }}>
        <span style={{
          fontFamily: '"Barlow Condensed", sans-serif',
          fontWeight: 700,
          fontSize: 14,
          color: '#000',
          letterSpacing: '-0.03em',
        }}>SC</span>
      </div>

      {/* Main nav */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 4, width: '100%', alignItems: 'center' }}>
        {NAV_ITEMS.map(({ id, icon: Icon, label }) => (
          <button
            key={id}
            className={`nav-btn ${activePage === id ? 'active' : ''}`}
            onClick={() => onNavigate(id)}
            title={label}
          >
            <Icon size={18} strokeWidth={1.75} />
          </button>
        ))}
      </div>

      {/* Settings at bottom */}
      <button
        className={`nav-btn ${activePage === 'settings' ? 'active' : ''}`}
        onClick={() => onNavigate('settings')}
        title="Settings"
      >
        <Settings size={18} strokeWidth={1.75} />
      </button>
    </nav>
  )
}
