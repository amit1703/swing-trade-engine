import StockIntelPanel from './StockIntelPanel.jsx'
import { useAppSettings } from '../contexts/AppSettingsContext'

export default function MobileSignalSheet({ onClose, setup, livePrices, analysis, analysisLoading }) {
  const { tr, lang } = useAppSettings()
  return (
    <div
      className="mobile-sheet-overlay"
      onClick={onClose}
    >
      <div
        className="mobile-sheet"
        onClick={e => e.stopPropagation()}
      >
        <div className="mobile-sheet-handle" />
        <button className="mobile-sheet-close" onClick={onClose}>✕</button>
        <div className="mobile-sheet-content">
          <StockIntelPanel
            setup={setup}
            livePrices={livePrices}
            analysis={analysis}
            analysisLoading={analysisLoading}
          />
        </div>
      </div>
    </div>
  )
}
