/**
 * SRBandPrimitive — lightweight-charts v4 ISeriesPrimitive
 *
 * Renders a filled horizontal band between `zone.upper` and `zone.lower`
 * with dashed border lines. Drawn behind candles (zOrder = 'bottom').
 *
 * RESISTANCE zones → red fill / red dashes
 * SUPPORT zones    → green fill / green dashes
 */

class BandPaneRenderer {
  constructor(zone, getSeriesFn) {
    this._zone = zone
    this._getSeries = getSeriesFn
  }

  draw(target) {
    const series = this._getSeries()
    if (!series) return

    const { upper, lower, type, source } = this._zone

    target.useMediaCoordinateSpace(({ context: ctx, mediaSize }) => {
      const y1 = series.priceToCoordinate(upper)
      const y2 = series.priceToCoordinate(lower)

      if (y1 === null || y2 === null) return

      const minY = Math.min(y1, y2)
      const maxY = Math.max(y1, y2)
      const bandH = maxY - minY

      if (bandH < 0.5) return

      const w = mediaSize.width

      const isPivot = source === 'pivot'
      const isRes   = type === 'RESISTANCE'

      ctx.save()

      if (isPivot) {
        // Pivot resistance: single sharp horizontal line at the level price.
        // No fill — avoids stacked rectangles cluttering the chart.
        const yLevel = series.priceToCoordinate(this._zone.level)
        if (yLevel !== null) {
          ctx.strokeStyle = isRes ? 'rgba(255, 140, 0, 0.90)' : 'rgba(0, 229, 255, 0.85)'
          ctx.lineWidth   = 1.5
          ctx.setLineDash([])
          ctx.beginPath()
          ctx.moveTo(0, Math.round(yLevel) + 0.5)
          ctx.lineTo(w, Math.round(yLevel) + 0.5)
          ctx.stroke()
        }
      } else {
        // KDE band: filled rectangle with dashed border lines
        const fillColor   = isRes ? 'rgba(255, 45, 85, 0.18)' : 'rgba(0, 200, 122, 0.16)'
        const strokeColor = isRes ? 'rgba(255, 45, 85, 0.75)' : 'rgba(0, 200, 122, 0.75)'

        ctx.fillStyle = fillColor
        ctx.fillRect(0, minY, w, bandH)

        ctx.strokeStyle = strokeColor
        ctx.lineWidth   = 1.2
        ctx.setLineDash([5, 4])

        ctx.beginPath()
        ctx.moveTo(0, minY + 0.5)
        ctx.lineTo(w, minY + 0.5)
        ctx.stroke()

        ctx.beginPath()
        ctx.moveTo(0, maxY + 0.5)
        ctx.lineTo(w, maxY + 0.5)
        ctx.stroke()

        ctx.setLineDash([])
      }

      ctx.restore()
    })
  }
}

class BandPaneView {
  constructor(zone, getSeriesFn) {
    this._renderer = new BandPaneRenderer(zone, getSeriesFn)
  }

  renderer() {
    return this._renderer
  }

  zOrder() {
    return 'bottom'
  }
}

export class SRBandPrimitive {
  constructor(zone) {
    this._zone = zone
    this._series = null
    this._paneViews = []
  }

  attached({ series }) {
    this._series = series
    const getSeries = () => this._series
    this._paneViews = [new BandPaneView(this._zone, getSeries)]
  }

  detached() {
    this._series = null
    this._paneViews = []
  }

  updateAllViews() {}

  paneViews() {
    return this._paneViews
  }
}
