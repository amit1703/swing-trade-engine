import StockIntelPanel from './StockIntelPanel.jsx'

export default function MobileSignalSheet({ onClose, setup, livePrices, analysis, analysisLoading }) {
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
