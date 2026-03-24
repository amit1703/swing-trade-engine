/**
 * SRBandPrimitive — lightweight-charts v4 ISeriesPrimitive
 *
 * Renders S/R zones as white lines / white bands on a black background.
 *
 * KDE bands   → white fill + white dashed borders + "R/S $level" label
 * Pivot lines → white solid line + "PIV $level" label
 *
 * Supports `setVisible(bool)` for the chart toggle bar.
 */

class BandPaneRenderer {
  constructor(zone, getSeriesFn) {
    this._zone = zone
    this._getSeries = getSeriesFn
    this._visible = true
  }

  draw(target) {
    if (!this._visible) return

    const series = this._getSeries()
    if (!series) return

    const { upper, lower, level, type, source } = this._zone

    target.useMediaCoordinateSpace(({ context: ctx, mediaSize }) => {
      const y1 = series.priceToCoordinate(upper)
      const y2 = series.priceToCoordinate(lower)

      if (y1 === null || y2 === null) return

      const minY = Math.min(y1, y2)
      const maxY = Math.max(y1, y2)
      const bandH = maxY - minY

      if (bandH < 0.5) return

      const w = mediaSize.width
      const isPivot = source === 'pivot' || source === 'watchlist_pivot'
      const isRes   = type === 'RESISTANCE'

      ctx.save()

      if (isPivot) {
        // Pivot: single sharp white horizontal line
        const yLevel = series.priceToCoordinate(level ?? upper)
        if (yLevel !== null) {
          const lineAlpha = isRes ? 0.85 : 0.60
          ctx.strokeStyle = `rgba(255,255,255,${lineAlpha})`
          ctx.lineWidth   = 1.5
          ctx.setLineDash([])
          ctx.beginPath()
          ctx.moveTo(0, Math.round(yLevel) + 0.5)
          ctx.lineTo(w, Math.round(yLevel) + 0.5)
          ctx.stroke()

          // Label at right edge
          const label = `PIV ${(level ?? upper).toFixed(2)}`
          ctx.font = '600 9px "IBM Plex Mono", monospace'
          ctx.textAlign = 'right'
          ctx.textBaseline = 'bottom'
          const textY = Math.round(yLevel) - 3
          const metrics = ctx.measureText(label)
          const pad = 4
          // Pill background
          ctx.fillStyle = 'rgba(0,0,0,0.55)'
          ctx.fillRect(w - metrics.width - pad * 2 - 4, textY - 10, metrics.width + pad * 2, 11)
          // Text
          ctx.fillStyle = `rgba(255,255,255,${lineAlpha})`
          ctx.fillText(label, w - pad - 4, textY)
        }
      } else {
        // KDE band: white fill + white dashed borders
        const fillAlpha   = isRes ? 0.09 : 0.07
        const strokeAlpha = isRes ? 0.65 : 0.55

        ctx.fillStyle = `rgba(255,255,255,${fillAlpha})`
        ctx.fillRect(0, minY, w, bandH)

        ctx.strokeStyle = `rgba(255,255,255,${strokeAlpha})`
        ctx.lineWidth   = 1.0
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

        // Label at right edge inside band
        if (bandH > 8) {
          const midY = (minY + maxY) / 2
          const levelVal = level ?? ((upper + lower) / 2)
          const label = (isRes ? 'R ' : 'S ') + levelVal.toFixed(2)
          ctx.font = '600 8px "IBM Plex Mono", monospace'
          ctx.textAlign = 'right'
          ctx.textBaseline = 'middle'
          ctx.fillStyle = `rgba(255,255,255,${strokeAlpha + 0.1})`
          ctx.fillText(label, w - 6, midY)
        }
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

  /** Toggle visibility without detaching the primitive. */
  setVisible(v) {
    if (this._paneViews[0]) {
      this._paneViews[0]._renderer._visible = v
    }
  }

  updateAllViews() {}

  paneViews() {
    return this._paneViews
  }
}
