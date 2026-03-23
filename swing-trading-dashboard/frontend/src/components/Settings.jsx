// src/components/Settings.jsx
import { Moon, Sun } from 'lucide-react'
import { Switch } from './ui/switch'
import { useAppSettings } from '../contexts/AppSettingsContext'

export default function Settings() {
  const { theme, lang, setTheme, setLang, tr } = useAppSettings()

  return (
    <div style={{ flex: 1, overflow: 'auto', padding: '24px 20px', maxWidth: 480 }}>

      {/* Page header */}
      <h1 className="font-sans text-xl font-semibold text-t-text mb-6">
        {tr('settings.title')}
      </h1>

      {/* Theme card */}
      <div className="card p-4 mb-4">
        <div className="flex items-center justify-between">
          <div>
            <p className="font-sans text-sm font-semibold text-t-text">
              {tr('settings.theme')}
            </p>
            <p className="font-sans text-xs text-t-muted mt-0.5">
              {tr('settings.themeDesc')}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Moon size={15} className="text-t-muted" />
            <Switch
              checked={theme === 'light'}
              onCheckedChange={(checked) => setTheme(checked ? 'light' : 'dark')}
            />
            <Sun size={15} className="text-t-muted" />
          </div>
        </div>
        <div className="flex gap-2 mt-3">
          {['dark', 'light'].map((opt) => (
            <button
              key={opt}
              onClick={() => setTheme(opt)}
              className={[
                'flex-1 py-1.5 rounded-md text-xs font-sans font-medium border transition-colors',
                theme === opt
                  ? 'bg-t-accent/10 text-t-accent border-t-accent/30'
                  : 'text-t-muted border-t-border hover:bg-white/5',
              ].join(' ')}
            >
              {opt === 'dark' ? tr('settings.dark') : tr('settings.light')}
            </button>
          ))}
        </div>
      </div>

      {/* Language card */}
      <div className="card p-4">
        <div className="mb-3">
          <p className="font-sans text-sm font-semibold text-t-text">
            {tr('settings.language')}
          </p>
          <p className="font-sans text-xs text-t-muted mt-0.5">
            {tr('settings.langDesc')}
          </p>
        </div>
        <div className="flex gap-2">
          {[
            { value: 'en', label: tr('settings.english') },
            { value: 'he', label: tr('settings.hebrew') },
          ].map(({ value, label }) => (
            <button
              key={value}
              onClick={() => setLang(value)}
              className={[
                'flex-1 py-1.5 rounded-md text-sm font-sans font-medium border transition-colors',
                lang === value
                  ? 'bg-t-accent/10 text-t-accent border-t-accent/30'
                  : 'text-t-muted border-t-border hover:bg-white/5',
              ].join(' ')}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

    </div>
  )
}
