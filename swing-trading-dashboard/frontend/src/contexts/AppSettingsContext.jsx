// src/contexts/AppSettingsContext.jsx
import { createContext, useContext, useState, useEffect } from 'react'
import { translations } from '../i18n/translations'

export const AppSettingsContext = createContext(null)

export function AppSettingsProvider({ children }) {
  const [theme, setThemeState] = useState(
    () => localStorage.getItem('theme') || 'dark'
  )
  const [lang, setLangState] = useState(
    () => localStorage.getItem('lang') || 'en'
  )

  const setTheme = (val) => {
    setThemeState(val)
    localStorage.setItem('theme', val)
  }

  const setLang = (val) => {
    setLangState(val)
    localStorage.setItem('lang', val)
  }

  // Apply theme class and lang attribute to <html>
  useEffect(() => {
    const html = document.documentElement
    html.classList.toggle('dark', theme === 'dark')
    html.classList.toggle('light', theme === 'light')
    html.setAttribute('lang', lang)
  }, [theme, lang])

  // tr() — named 'tr' (not 't') to avoid collision with common loop variable t
  const tr = (key) =>
    translations[lang]?.[key] ?? translations['en'][key] ?? key

  return (
    <AppSettingsContext.Provider value={{ theme, lang, setTheme, setLang, tr }}>
      {children}
    </AppSettingsContext.Provider>
  )
}

export const useAppSettings = () => useContext(AppSettingsContext)
