/**
 * TradingChart — lightweight-charts v4 component
 *
 * Layout  (top → bottom):
 *   ┌──────────────────────────────────┐
 *   │  Chart legend (HTML overlay)     │
 *   │  Candlestick + EMA8/EMA20/SMA50  │  ← mainContainer
 *   │  S/R bands (SRBandPrimitive)     │
 *   ├──────────────────────────────────┤
 *   │  CCI (20) line chart             │  ← cciContainer
 *   │  ─100 / 0 / +100 ref lines       │
 *   └──────────────────────────────────┘
 *
 * Charts are destroyed + re-created when chartData changes (ticker click).
 * Time ranges are kept in sync via subscribeVisibleTimeRangeChange.
 */

import { useEffect, useRef, useState } from 'react'
import { createChart, CrosshairMode, LineStyle, PriceScaleMode } from 'lightweight-charts'
import { SRBandPrimitive } from '../sr-band-primitive.js'

// ── Design tokens (match index.css variables) ──────────────────────────────
const COLORS = {
  bg:           '#000000',    // pure black background
  surface:      '#050a0f',
  border:       '#1a2535',
  text:         '#c8cdd6',
  muted:        '#4a5a72',
  accent:       '#F5A623',
  go:           '#00c87a',
  halt:         '#ff2d55',
  ema8:         '#9B6EFF',    // purple
  ema20:        '#FFD700',    // yellow
  sma50:        '#4CAF50',    // green
  cci:          '#9B6EFF',
  cciOb:        'rgba(255, 45, 85, 0.12)',
  cciOs:        'rgba(0, 200, 122, 0.10)',
  rs:           '#F5A623',    // amber — RS line
  rsBlueDot:    '#00c87a',    // green — RS at 52-week high
  sma200:       '#FF5C8A',    // red-pink
  trendline:    '#FFFFFF',    // white — descending TDL
  trendlineAsc: '#FFFFFF',    // white — ascending TDL
  baseFlatBox:  'rgba(255, 255, 255, 0.05)',
  baseFlatEdge: 'rgba(255, 255, 255, 0.5)',
  cupArc:       'rgba(255, 255, 255, 0.5)',
}

const SHARED_CHART_OPTS = {
  layout: {
    background: { color: COLORS.bg },
    textColor: COLORS.muted,
    fontFamily: '"IBM Plex Mono", monospace',
    fontSize: 10,
  },
  grid: {
    vertLines: { color: '#101825', style: LineStyle.Solid },
    horzLines: { color: '#101825', style: LineStyle.Solid },
  },
  crosshair: {
    mode: CrosshairMode.Normal,
    vertLine: { color: 'rgba(245, 166, 35, 0.4)', labelBackgroundColor: '#1a2535' },
    horzLine: { color: 'rgba(245, 166, 35, 0.25)', labelBackgroundColor: '#1a2535' },
  },
  rightPriceScale: {
    borderColor: COLORS.border,
    textColor: COLORS.muted,
    scaleMargins: { top: 0.08, bottom: 0.05 },
    autoScale: true,
  },
  timeScale: {
    borderColor: COLORS.border,
    timeVisible: true,
    secondsVisible: false,
    rightOffset: 8,
    kineticScrollEnabled: false,
  },
  handleScale: {
    mouseWheel: false,          // wheel zooms only when Ctrl/Cmd held (see wheel listener)
    pinch: true,
    axisPressedMouseMove: { time: true, price: true },
    axisDoubleClickReset: { time: true, price: true },
  },
  handleScroll: {
    mouseWheel: true,           // default: wheel pans
    pressedMouseMove: true,
    horzTouchDrag: true,
    vertTouchDrag: false,
  },
}

// ─────────────────────────────────────────────────────────────────────────────

export default function TradingChart({ ticker, chartData, loading }) {
  const mainRef    = useRef(null)
  const cciRef     = useRef(null)
  const rsRef      = useRef(null)
  const wrapRef    = useRef(null)
  const seriesRef  = useRef({})   // holds series + primitives for visibility toggles
  const chartsRef  = useRef({})   // holds mainChart / cciChart / rsChart for AUTO button

  // Legend state — updated on crosshair move
  const [legend, setLegend] = useState(null)

  // Visibility toggles: ema / sma / tdl / sr / rs / vol
  const [vis, setVis] = useState({ ema: true, sma: true, tdl: true, sr: true, rs: true, vol: true })

  // Chart creation effect must be defined BEFORE visibility effects so React
  // runs it first (effects execute in definition order), ensuring seriesRef is
  // populated before visibility effects apply options.
  useEffect(() => {
    if (!chartData || !mainRef.current || !cciRef.current || !rsRef.current) return

    const mainEl = mainRef.current
    const cciEl  = cciRef.current
    const rsEl   = rsRef.current

    // ── Create charts ──────────────────────────────────────────────────────
    const mainChart = createChart(mainEl, {
      ...SHARED_CHART_OPTS,
      height: mainEl.clientHeight || 440,
      width:  mainEl.clientWidth  || 800,
      timeScale: {
        ...SHARED_CHART_OPTS.timeScale,
        visible: true,
      },
    })

    const cciChart = createChart(cciEl, {
      ...SHARED_CHART_OPTS,
      height: cciEl.clientHeight || 160,
      width:  cciEl.clientWidth  || 800,
      rightPriceScale: {
        ...SHARED_CHART_OPTS.rightPriceScale,
        scaleMargins: { top: 0.1, bottom: 0.1 },
      },
      layout: {
        ...SHARED_CHART_OPTS.layout,
        fontSize: 9,
      },
    })

    const rsChart = createChart(rsEl, {
      ...SHARED_CHART_OPTS,
      height: rsEl.clientHeight || 100,
      width:  rsEl.clientWidth  || 800,
      rightPriceScale: {
        ...SHARED_CHART_OPTS.rightPriceScale,
        scaleMargins: { top: 0.15, bottom: 0.15 },
      },
      timeScale: {
        ...SHARED_CHART_OPTS.timeScale,
        visible: false,
      },
      layout: {
        ...SHARED_CHART_OPTS.layout,
        fontSize: 9,
      },
    })

    // ── Ctrl/Cmd+scroll = zoom, plain scroll = pan ─────────────────────────
    const makeWheelHandler = (chart) => (e) => {
      const wantZoom = e.ctrlKey || e.metaKey
      chart.applyOptions({
        handleScale: { mouseWheel: wantZoom },
        handleScroll: { mouseWheel: !wantZoom },
      })
    }

    const mainWheelHandler = makeWheelHandler(mainChart)
    const cciWheelHandler  = makeWheelHandler(cciChart)
    const rsWheelHandler   = makeWheelHandler(rsChart)

    mainEl.addEventListener('wheel', mainWheelHandler, { passive: true })
    cciEl.addEventListener('wheel', cciWheelHandler,   { passive: true })
    rsEl.addEventListener('wheel', rsWheelHandler,     { passive: true })

    // ── Candlestick series ─────────────────────────────────────────────────
    const candleSeries = mainChart.addCandlestickSeries({
      upColor:          COLORS.go,
      downColor:        COLORS.halt,
      borderUpColor:    COLORS.go,
      borderDownColor:  COLORS.halt,
      wickUpColor:      'rgba(0, 200, 122, 0.75)',
      wickDownColor:    'rgba(255, 45, 85, 0.75)',
      priceLineVisible: true,
      priceLineColor:   'rgba(245,166,35,0.5)',
      priceLineStyle:   LineStyle.Dashed,
      priceLineWidth:   1,
      lastValueVisible: true,
    })
    if (chartData.candles?.length) candleSeries.setData(chartData.candles)

    // ── Volume histogram (bottom 25% of main chart) ─────────────────────────
    const volSeries = mainChart.addHistogramSeries({
      priceFormat:   { type: 'volume' },
      priceScaleId:  'volume',
      lastValueVisible: false,
      priceLineVisible: false,
    })
    mainChart.priceScale('volume').applyOptions({
      scaleMargins: { top: 0.78, bottom: 0 },
    })
    if (chartData.candles?.length) {
      volSeries.setData(chartData.candles.map((c) => ({
        time:  c.time,
        value: c.volume,
        color: c.close >= c.open ? 'rgba(0,200,122,0.30)' : 'rgba(255,45,85,0.25)',
      })))
    }

    // Volume 50-bar SMA line on same scale
    const volSmaData = []
    const candles = chartData.candles ?? []
    if (candles.length >= 50) {
      for (let i = 49; i < candles.length; i++) {
        let sum = 0
        for (let j = i - 49; j <= i; j++) sum += candles[j].volume
        volSmaData.push({ time: candles[i].time, value: sum / 50 })
      }
    }
    const volSmaSeries = mainChart.addLineSeries({
      color:            'rgba(245,166,35,0.55)',
      lineWidth:        1,
      lineStyle:        LineStyle.Dashed,
      priceScaleId:     'volume',
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    })
    if (volSmaData.length) volSmaSeries.setData(volSmaData)

    // ── S/R Band primitives (attached to candle series) ────────────────────
    const srPrimitivesList = []
    if (chartData.sr_zones?.length) {
      chartData.sr_zones.forEach((zone) => {
        try {
          const prim = new SRBandPrimitive(zone)
          candleSeries.attachPrimitive(prim)
          srPrimitivesList.push(prim)
        } catch (e) {
          // Fallback: draw two price lines if primitive API unavailable
          const isPivot = zone.source === 'pivot'
          const c = isPivot
            ? (zone.type === 'RESISTANCE' ? '#FF8C00' : '#00E5FF')
            : (zone.type === 'RESISTANCE' ? COLORS.halt : COLORS.go)
          candleSeries.createPriceLine({ price: zone.upper, color: c, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: false, title: '' })
          candleSeries.createPriceLine({ price: zone.lower, color: c, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: false, title: `${zone.type[0]} ${zone.level}` })
        }
      })
    }

    // ── EMA 8 (purple, thin solid) ──────────────────────────────────────
    const ema8Series = mainChart.addLineSeries({
      color:            COLORS.ema8,
      lineWidth:        1,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    })
    if (chartData.ema8?.length) ema8Series.setData(chartData.ema8)

    // ── EMA 20 (yellow, thin solid) ─────────────────────────────────────────
    const ema20Series = mainChart.addLineSeries({
      color:            COLORS.ema20,
      lineWidth:        1,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    })
    if (chartData.ema20?.length) ema20Series.setData(chartData.ema20)

    // ── SMA 50 (orange, solid) ─────────────────────────────────────────────
    const sma50Series = mainChart.addLineSeries({
      color:            COLORS.sma50,
      lineWidth:        1.5,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    })
    if (chartData.sma50?.length) sma50Series.setData(chartData.sma50)

    // ── SMA 200 (red-pink, thick solid) ────────────────────────────────────
    const sma200Series = mainChart.addLineSeries({
      color:            COLORS.sma200,
      lineWidth:        2,
      lineStyle:        LineStyle.Solid,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    })
    if (chartData.sma200?.length) sma200Series.setData(chartData.sma200)

    // ── Trendlines (descending = resistance, ascending = support) ──────
    let descTrendlineSeries = null
    let ascTrendlineSeries  = null

    if (chartData.trendline?.descending?.series?.length) {
      descTrendlineSeries = mainChart.addLineSeries({
        color:            COLORS.trendline,
        lineWidth:        1.5,
        lineStyle:        LineStyle.Solid,
        priceLineVisible: false,
        lastValueVisible: true,
        lastPriceAnimation: 0,
        crosshairMarkerVisible: false,
        title: 'TDL',
      })
      descTrendlineSeries.setData(chartData.trendline.descending.series)
    }

    if (chartData.trendline?.ascending?.series?.length) {
      ascTrendlineSeries = mainChart.addLineSeries({
        color:            COLORS.trendlineAsc,
        lineWidth:        1.5,
        lineStyle:        LineStyle.Solid,
        priceLineVisible: false,
        lastValueVisible: true,
        lastPriceAnimation: 0,
        crosshairMarkerVisible: false,
        title: 'ASC',
      })
      ascTrendlineSeries.setData(chartData.trendline.ascending.series)
    }

    // ── Base Pattern Overlays ───────────────────────────────────────────
    if (chartData.base_setup?.geometry) {
      const bs = chartData.base_setup
      const geo = bs.geometry

      if (bs.base_type === 'FLAT_BASE' && geo.start_date && geo.end_date) {
        // Flat Base: draw two horizontal price lines (top/bottom of box)
        // and a shaded area series between them
        const topLine = mainChart.addLineSeries({
          color: COLORS.baseFlatEdge,
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        })
        topLine.setData([
          { time: geo.start_date, value: geo.base_high },
          { time: geo.end_date,   value: geo.base_high },
        ])

        const bottomLine = mainChart.addLineSeries({
          color: COLORS.baseFlatEdge,
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        })
        bottomLine.setData([
          { time: geo.start_date, value: geo.base_low },
          { time: geo.end_date,   value: geo.base_low },
        ])

        // Entry price line
        if (bs.entry) {
          candleSeries.createPriceLine({
            price: bs.entry,
            color: COLORS.go,
            lineWidth: 1,
            lineStyle: LineStyle.Dashed,
            axisLabelVisible: true,
            title: 'ENTRY',
          })
        }

        // Add markers at the corners
        candleSeries.setMarkers([
          { time: geo.start_date, position: 'aboveBar', color: COLORS.baseFlatEdge, shape: 'square', text: 'FB' },
        ])
      }

      if (bs.base_type === 'CUP_HANDLE' && geo.left_peak_date && geo.cup_bottom_date && geo.right_rim_date) {
        // Cup & Handle: draw arc from left peak → cup bottom → right rim
        // Approximate with line series through key points
        const cupSeries = mainChart.addLineSeries({
          color: COLORS.cupArc,
          lineWidth: 2,
          lineStyle: LineStyle.Solid,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        })

        // Build cup curve: left peak → bottom → right rim
        // Use candle data to trace the actual lows through the cup region
        const cupPoints = []
        const candles = chartData.candles || []
        let inCup = false
        let pastCup = false
        for (const c of candles) {
          if (c.time === geo.left_peak_date) inCup = true
          if (inCup && !pastCup) {
            cupPoints.push({ time: c.time, value: c.low })
          }
          if (c.time === geo.right_rim_date) pastCup = true
        }
        if (cupPoints.length > 0) {
          cupSeries.setData(cupPoints)
        }

        // Handle area: right rim → handle low
        if (geo.handle_low && geo.handle_high) {
          candleSeries.createPriceLine({
            price: geo.handle_high,
            color: COLORS.cupArc,
            lineWidth: 1,
            lineStyle: LineStyle.Dashed,
            axisLabelVisible: true,
            title: 'PIVOT',
          })
          candleSeries.createPriceLine({
            price: geo.handle_low,
            color: 'rgba(155, 110, 255, 0.3)',
            lineWidth: 1,
            lineStyle: LineStyle.Dotted,
            axisLabelVisible: false,
            title: '',
          })
        }

        // Markers
        candleSeries.setMarkers([
          { time: geo.left_peak_date,  position: 'aboveBar', color: COLORS.cupArc, shape: 'arrowDown', text: 'L' },
          { time: geo.cup_bottom_date, position: 'belowBar', color: COLORS.cupArc, shape: 'arrowUp',   text: 'B' },
          { time: geo.right_rim_date,  position: 'aboveBar', color: COLORS.cupArc, shape: 'arrowDown', text: 'R' },
        ])

        // Entry price line
        if (bs.entry) {
          candleSeries.createPriceLine({
            price: bs.entry,
            color: COLORS.go,
            lineWidth: 1,
            lineStyle: LineStyle.Dashed,
            axisLabelVisible: true,
            title: 'ENTRY',
          })
        }
      }
    }

    // ── RS Line series ─────────────────────────────────────────────────────
    const rsSeries = rsChart.addLineSeries({
      color:            COLORS.rs,
      lineWidth:        1.5,
      priceLineVisible: false,
      lastValueVisible: true,
      crosshairMarkerVisible: true,
      crosshairMarkerRadius: 3,
    })
    if (chartData.rs_line?.length) rsSeries.setData(chartData.rs_line)

    // 52-week RS high reference line
    if (chartData.rs_52w_high != null) {
      rsSeries.createPriceLine({
        price:            chartData.rs_52w_high,
        color:            COLORS.rsBlueDot,
        lineWidth:        1,
        lineStyle:        LineStyle.Dashed,
        axisLabelVisible: true,
        title:            '52W',
      })
    }

    // Blue dot marker — last bar when RS is at 52-week high
    if (chartData.rs_blue_dot && chartData.rs_line?.length) {
      const lastPt = chartData.rs_line[chartData.rs_line.length - 1]
      rsSeries.setMarkers([{
        time:     lastPt.time,
        position: 'aboveBar',
        color:    COLORS.rsBlueDot,
        shape:    'circle',
        text:     '●',
      }])
    }

    // ── CCI line series ────────────────────────────────────────────────────
    const cciSeries = cciChart.addLineSeries({
      color:            COLORS.cci,
      lineWidth:        1,
      priceLineVisible: false,
      lastValueVisible: true,
      crosshairMarkerVisible: true,
      crosshairMarkerRadius: 3,
    })
    if (chartData.cci?.length) cciSeries.setData(chartData.cci)

    // CCI reference lines
    const cciRefLines = [
      { price: 100,  title: '+100', color: 'rgba(255, 45, 85, 0.45)',   lineStyle: LineStyle.Dashed },
      { price: -100, title: '-100', color: 'rgba(0, 200, 122, 0.45)',  lineStyle: LineStyle.Dashed },
      { price: 0,    title: '  0',  color: 'rgba(200, 205, 214, 0.15)', lineStyle: LineStyle.Solid  },
    ]
    cciRefLines.forEach((rl) => {
      cciSeries.createPriceLine({
        price:              rl.price,
        color:              rl.color,
        lineWidth:          1,
        lineStyle:          rl.lineStyle,
        axisLabelVisible:   true,
        title:              rl.title,
      })
    })

    // ── Fit content ────────────────────────────────────────────────────────
    mainChart.timeScale().fitContent()

    // ── Sync time ranges (main ↔ rs ↔ cci) ────────────────────────────────
    let mainSyncing = false
    let rsSyncing   = false
    let cciSyncing  = false

    mainChart.timeScale().subscribeVisibleTimeRangeChange((range) => {
      if (rsSyncing || cciSyncing || !range) return
      mainSyncing = true
      rsChart.timeScale().setVisibleRange(range)
      cciChart.timeScale().setVisibleRange(range)
      mainSyncing = false
    })

    rsChart.timeScale().subscribeVisibleTimeRangeChange((range) => {
      if (mainSyncing || cciSyncing || !range) return
      rsSyncing = true
      mainChart.timeScale().setVisibleRange(range)
      cciChart.timeScale().setVisibleRange(range)
      rsSyncing = false
    })

    cciChart.timeScale().subscribeVisibleTimeRangeChange((range) => {
      if (mainSyncing || rsSyncing || !range) return
      cciSyncing = true
      mainChart.timeScale().setVisibleRange(range)
      rsChart.timeScale().setVisibleRange(range)
      cciSyncing = false
    })

    // ── Crosshair legend ───────────────────────────────────────────────────
    mainChart.subscribeCrosshairMove((param) => {
      if (!param.time || !param.seriesData) {
        setLegend(null)
        return
      }
      const candle = param.seriesData.get(candleSeries)
      const e8     = param.seriesData.get(ema8Series)
      const e20    = param.seriesData.get(ema20Series)
      const s50    = param.seriesData.get(sma50Series)
      const s200   = param.seriesData.get(sma200Series)
      const tlDesc = descTrendlineSeries ? param.seriesData.get(descTrendlineSeries) : null
      const tlAsc  = ascTrendlineSeries  ? param.seriesData.get(ascTrendlineSeries)  : null

      setLegend({
        time:      param.time,
        open:      candle?.open,
        high:      candle?.high,
        low:       candle?.low,
        close:     candle?.close,
        ema8:      e8?.value,
        ema20:     e20?.value,
        sma50:     s50?.value,
        sma200:    s200?.value,
        trendlineDesc: tlDesc?.value,
        trendlineAsc:  tlAsc?.value,
      })
    })

    // ── Store series refs for visibility toggles ───────────────────────────
    seriesRef.current = {
      ema8:   ema8Series,
      ema20:  ema20Series,
      sma50:  sma50Series,
      sma200: sma200Series,
      descTL: descTrendlineSeries,
      ascTL:  ascTrendlineSeries,
      srPrimitives: srPrimitivesList,
      rsSeries,
      rsChart,
      mainChart,
      volSeries,
      volSmaSeries,
    }

    // ── Store chart instance refs for AUTO button ──────────────────────────
    chartsRef.current = { mainChart, cciChart, rsChart }

    // ── Resize observer ────────────────────────────────────────────────────
    const wrap = wrapRef.current
    const observer = new ResizeObserver(() => {
      if (!wrap) return
      const w = wrap.clientWidth
      mainChart.applyOptions({ width: w })
      rsChart.applyOptions({ width: w })
      cciChart.applyOptions({ width: w })
    })
    if (wrap) observer.observe(wrap)

    // ── Cleanup ────────────────────────────────────────────────────────────
    return () => {
      mainEl.removeEventListener('wheel', mainWheelHandler)
      cciEl.removeEventListener('wheel', cciWheelHandler)
      rsEl.removeEventListener('wheel', rsWheelHandler)
      chartsRef.current = {}        // clear chart refs on cleanup
      seriesRef.current = {}
      observer.disconnect()
      try { mainChart.remove() } catch (_) {}
      try { rsChart.remove()   } catch (_) {}
      try { cciChart.remove()  } catch (_) {}
      setLegend(null)
    }
  }, [chartData]) // re-create charts whenever data changes

  // ── Visibility effects — defined AFTER chart creation so they run after it ─
  useEffect(() => {
    seriesRef.current.ema8?.applyOptions({ visible: vis.ema })
    seriesRef.current.ema20?.applyOptions({ visible: vis.ema })
  }, [vis.ema, chartData])

  useEffect(() => {
    seriesRef.current.sma50?.applyOptions({ visible: vis.sma })
    seriesRef.current.sma200?.applyOptions({ visible: vis.sma })
  }, [vis.sma, chartData])

  useEffect(() => {
    seriesRef.current.descTL?.applyOptions({ visible: vis.tdl })
    seriesRef.current.ascTL?.applyOptions({ visible: vis.tdl })
  }, [vis.tdl, chartData])

  useEffect(() => {
    seriesRef.current.srPrimitives?.forEach(p => p.setVisible(vis.sr))
    seriesRef.current.mainChart?.applyOptions({})
  }, [vis.sr, chartData])

  useEffect(() => {
    seriesRef.current.rsSeries?.applyOptions({ visible: vis.rs })
    seriesRef.current.rsChart?.applyOptions({})
  }, [vis.rs, chartData])

  useEffect(() => {
    seriesRef.current.volSeries?.applyOptions({ visible: vis.vol })
    seriesRef.current.volSmaSeries?.applyOptions({ visible: vis.vol })
  }, [vis.vol, chartData])

  const handleAutoReset = () => {
    const { mainChart, cciChart, rsChart } = chartsRef.current
    if (!mainChart) return
    mainChart.timeScale().fitContent()
    mainChart.priceScale('right').applyOptions({ autoScale: true })
    cciChart?.timeScale().fitContent()
    cciChart?.priceScale('right').applyOptions({ autoScale: true })
    rsChart?.timeScale().fitContent()
    rsChart?.priceScale('right').applyOptions({ autoScale: true })
  }

  // ── Empty states ──────────────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="terminal-placeholder">
        <span className="text-t-accent text-[13px] tracking-widest font-600 uppercase terminal-cursor">
          LOADING {ticker}
        </span>
        <span className="text-[10px] text-t-muted tracking-widest">fetching market data…</span>
      </div>
    )
  }

  if (!chartData) {
    return (
      <div className="terminal-placeholder">
        <div className="flex flex-col items-center gap-3">
          {/* ASCII chart placeholder */}
          <pre className="text-t-border text-[10px] leading-tight select-none">
{`  ┌──────────────────────────┐
  │  no ticker selected      │
  │                          │
  │  click any row to load   │
  │  a chart                 │
  │                          │
  └──────────────────────────┘`}
          </pre>
          <span className="text-[10px] text-t-muted tracking-widest uppercase">
            Select a ticker from the tables
          </span>
        </div>
      </div>
    )
  }

  return (
    <div ref={wrapRef} className="flex flex-col h-full overflow-hidden">

      {/* Main price chart with floating overlay */}
      <div className="flex-1 min-h-0 relative">

        {/* Floating TradingView-style legend overlay */}
        <div style={{
          position: 'absolute', top: 8, left: 10, zIndex: 10,
          pointerEvents: 'none', userSelect: 'none',
          display: 'flex', flexDirection: 'column', gap: 2,
        }}>
          {/* Row 1: Company name + market cap */}
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
            <span style={{ color: '#FFFFFF', fontSize: 13, fontWeight: 700, letterSpacing: '0.5px' }}>
              {chartData.ticker_info?.name || ticker}
            </span>
            {chartData.ticker_info?.market_cap != null && (
              <span style={{ color: COLORS.muted, fontSize: 10, fontFamily: '"IBM Plex Mono", monospace' }}>
                {fmtCap(chartData.ticker_info.market_cap)}
              </span>
            )}
          </div>

          {/* Row 2: Ticker · Timeframe · Sector · Industry */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 10 }}>
            <span style={{ color: COLORS.accent, fontWeight: 600, letterSpacing: '1px' }}>{ticker}</span>
            <span style={{ color: COLORS.border }}>·</span>
            <span style={{ color: COLORS.muted, textTransform: 'uppercase', letterSpacing: '1px', fontSize: 9 }}>1D</span>
            {chartData.ticker_info?.sector && (<>
              <span style={{ color: COLORS.border }}>·</span>
              <span style={{ color: COLORS.muted, fontSize: 9 }}>{chartData.ticker_info.sector}</span>
            </>)}
            {chartData.ticker_info?.industry && (<>
              <span style={{ color: COLORS.border }}>·</span>
              <span style={{ color: COLORS.muted, fontSize: 9 }}>{chartData.ticker_info.industry}</span>
            </>)}
          </div>

          {/* Row 3: ATR + 200 SMA status + Earnings warning */}
          {(() => {
            const earningsDate = chartData.earnings_date
              ? new Date(chartData.earnings_date + 'T00:00:00')
              : null
            const daysToEarnings = earningsDate
              ? Math.ceil((earningsDate.getTime() - Date.now()) / 86400000)
              : null
            const earningsWarning = daysToEarnings != null && daysToEarnings >= 0 && daysToEarnings <= 14
            return earningsWarning ? (
              <div style={{ display: 'flex', alignItems: 'center', gap: 4, marginTop: 2 }}>
                <span style={{
                  fontSize: 8, padding: '2px 7px', borderRadius: 3, fontWeight: 700,
                  background: 'rgba(255,165,0,0.15)',
                  color: '#FFA500',
                  border: '1px solid rgba(255,165,0,0.4)',
                  letterSpacing: '0.05em',
                }}>
                  ⚠ EARNINGS {daysToEarnings === 0 ? 'TODAY' : `${daysToEarnings}d`}
                </span>
              </div>
            ) : null
          })()}
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 10, marginTop: 2 }}>
            {chartData.ticker_info?.atr != null && (
              <span style={{ color: COLORS.text, fontFamily: '"IBM Plex Mono", monospace' }}>
                ATR(14)&nbsp;
                <span style={{ color: '#FFFFFF', fontWeight: 600 }}>{chartData.ticker_info.atr.toFixed(2)}</span>
                {chartData.ticker_info.atr_pct != null && (
                  <span style={{ color: COLORS.muted, marginLeft: 4 }}>({chartData.ticker_info.atr_pct}%)</span>
                )}
              </span>
            )}
            {chartData.ticker_info?.above_200sma != null && (
              <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                <span style={{
                  width: 6, height: 6, borderRadius: '50%',
                  background: chartData.ticker_info.above_200sma ? COLORS.go : COLORS.halt,
                  boxShadow: `0 0 4px ${chartData.ticker_info.above_200sma ? COLORS.go : COLORS.halt}`,
                }} />
                <span style={{ color: COLORS.muted, fontSize: 9, letterSpacing: '0.5px' }}>
                  {chartData.ticker_info.above_200sma ? 'Above' : 'Below'} 200 SMA
                </span>
              </span>
            )}
            {chartData.base_setup && (
              <span style={{
                fontSize: 8, padding: '2px 6px', borderRadius: 3,
                background: chartData.base_setup.base_type === 'CUP_HANDLE'
                  ? 'rgba(155,110,255,0.15)' : 'rgba(0,200,122,0.12)',
                color: chartData.base_setup.base_type === 'CUP_HANDLE'
                  ? COLORS.cupArc : COLORS.baseFlatEdge,
                border: `1px solid ${chartData.base_setup.base_type === 'CUP_HANDLE'
                  ? 'rgba(155,110,255,0.3)' : 'rgba(0,200,122,0.3)'}`,
                fontWeight: 700,
              }}>
                {chartData.base_setup.base_type === 'CUP_HANDLE' ? 'CUP & HANDLE' : 'FLAT BASE'}
                {' '}Q{chartData.base_setup.quality_score}
              </span>
            )}
          </div>

          {/* Row 4: MA values (from crosshair) */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 9, marginTop: 1 }}>
            <LegendItem dot={COLORS.ema8}  label="EMA 8"  value={legend?.ema8}  />
            <LegendItem dot={COLORS.ema20} label="EMA 20" value={legend?.ema20} />
            <LegendItem dot={COLORS.sma50} label="SMA 50" value={legend?.sma50} />
            {chartData.sma200?.length > 0 && (
              <LegendItem dot={COLORS.sma200} label="SMA 200" value={legend?.sma200} />
            )}
            {chartData.trendline?.descending?.series?.length > 0 && (
              <LegendItem dot={COLORS.trendline} label="TDL-R" value={legend?.trendlineDesc} />
            )}
            {chartData.trendline?.ascending?.series?.length > 0 && (
              <LegendItem dot={COLORS.trendlineAsc} label="TDL-S" value={legend?.trendlineAsc} />
            )}
          </div>

          {/* Row 5: OHLC from crosshair */}
          {legend?.open != null && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 10, fontFamily: '"IBM Plex Mono", monospace', marginTop: 1 }}>
              <span style={{ color: COLORS.muted }}>O <span style={{ color: COLORS.text }}>{pf(legend.open)}</span></span>
              <span style={{ color: COLORS.muted }}>H <span style={{ color: COLORS.go }}>{pf(legend.high)}</span></span>
              <span style={{ color: COLORS.muted }}>L <span style={{ color: COLORS.halt }}>{pf(legend.low)}</span></span>
              <span style={{ color: COLORS.muted }}>C <span style={{ color: legend.close >= legend.open ? COLORS.go : COLORS.halt, fontWeight: 600 }}>{pf(legend.close)}</span></span>
            </div>
          )}
        </div>

        {/* Visibility toggle bar — top right */}
        <div style={{
          position: 'absolute', top: 8, right: 10, zIndex: 10,
          display: 'flex', alignItems: 'center', gap: 4,
        }}>
          <VisToggle label="EMA" active={vis.ema} activeColor={COLORS.ema8}
            onClick={() => setVis(v => ({ ...v, ema: !v.ema }))} />
          <VisToggle label="SMA" active={vis.sma} activeColor={COLORS.sma50}
            onClick={() => setVis(v => ({ ...v, sma: !v.sma }))} />
          <VisToggle label="TDL" active={vis.tdl} activeColor="rgba(255,255,255,0.8)"
            onClick={() => setVis(v => ({ ...v, tdl: !v.tdl }))} />
          <VisToggle label="S/R" active={vis.sr} activeColor="rgba(255,255,255,0.6)"
            onClick={() => setVis(v => ({ ...v, sr: !v.sr }))} />
          {chartData.rs_line?.length > 0 && (
            <VisToggle label="RS" active={vis.rs} activeColor={COLORS.rs}
              onClick={() => setVis(v => ({ ...v, rs: !v.rs }))} />
          )}
          <VisToggle label="VOL" active={vis.vol} activeColor="rgba(0,200,122,0.6)"
            onClick={() => setVis(v => ({ ...v, vol: !v.vol }))} />
        </div>

        {/* AUTO reset button — bottom-right of main chart */}
        {chartData && (
          <button
            onClick={handleAutoReset}
            style={{
              position: 'absolute', bottom: 8, right: 10, zIndex: 10,
              fontFamily: '"IBM Plex Mono", monospace',
              fontSize: 9,
              fontWeight: 700,
              letterSpacing: '0.08em',
              padding: '3px 8px',
              background: 'rgba(0,0,0,0.75)',
              border: '1px solid rgba(245,166,35,0.45)',
              color: 'rgba(245,166,35,0.85)',
              cursor: 'pointer',
              backdropFilter: 'blur(4px)',
              userSelect: 'none',
            }}
          >
            AUTO
          </button>
        )}

        <div
          ref={mainRef}
          className="chart-container"
          style={{ width: '100%', height: '100%' }}
        />
      </div>

      {/* RS Line sub-chart */}
      <div className="flex-shrink-0 border-t border-t-border" style={{ height: 100 }}>
        <div className="section-label" style={{ padding: '4px 10px' }}>
          <span className="inline-block w-1.5 h-1.5 rounded-full" style={{ background: COLORS.rs }} />
          RS Line
          {chartData.rs_blue_dot && (
            <span style={{
              marginLeft: 6, fontSize: 8, padding: '1px 5px', borderRadius: 3,
              background: 'rgba(0,200,122,0.15)', color: COLORS.rsBlueDot,
              border: '1px solid rgba(0,200,122,0.3)', fontWeight: 700,
            }}>
              ● BLUE DOT
            </span>
          )}
          <span className="ml-auto text-[9px] text-t-muted">ticker / SPY</span>
        </div>
        <div ref={rsRef} style={{ height: 'calc(100% - 24px)' }} />
      </div>

      {/* CCI sub-chart */}
      <div className="flex-shrink-0 border-t border-t-border" style={{ height: 160 }}>
        <div className="section-label" style={{ padding: '4px 10px' }}>
          <span className="inline-block w-1.5 h-1.5 rounded-full" style={{ background: COLORS.cci }} />
          CCI (20)
          <span className="ml-auto text-[9px] text-t-muted">
            OB&nbsp;+100 &nbsp;/&nbsp; OS&nbsp;-100
          </span>
        </div>
        <div ref={cciRef} style={{ height: 'calc(100% - 24px)' }} />
      </div>

    </div>
  )
}

// ── Sub-components ─────────────────────────────────────────────────────────

function LegendItem({ dot, label, value }) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 3 }}>
      <span style={{ width: 8, height: 2, borderRadius: 1, background: dot, flexShrink: 0 }} />
      <span style={{ color: COLORS.muted, fontSize: 9, letterSpacing: '0.3px' }}>{label}</span>
      {value != null && (
        <span style={{ fontFamily: '"IBM Plex Mono", monospace', fontSize: 10, color: dot }}>
          {value.toFixed(2)}
        </span>
      )}
    </span>
  )
}

function VisToggle({ label, active, activeColor, onClick }) {
  return (
    <button
      onClick={onClick}
      style={{
        fontFamily: '"IBM Plex Mono", monospace',
        fontSize: 9,
        fontWeight: 700,
        letterSpacing: '0.08em',
        padding: '3px 8px',
        background: 'rgba(0,0,0,0.75)',
        border: `1px solid ${active ? activeColor : 'rgba(255,255,255,0.1)'}`,
        color: active ? activeColor : 'rgba(255,255,255,0.2)',
        cursor: 'pointer',
        textDecoration: active ? 'none' : 'line-through',
        backdropFilter: 'blur(4px)',
        transition: 'border-color 0.15s, color 0.15s',
        userSelect: 'none',
      }}
    >
      {label}
    </button>
  )
}

// ── Helpers ────────────────────────────────────────────────────────────────
const pf = (n) => n?.toFixed(2) ?? '—'

/** Format market cap: 1.23T / 5.72B / 340M / 12.5M */
const fmtCap = (n) => {
  if (n == null) return '—'
  if (n >= 1e12) return `${(n / 1e12).toFixed(2)}T`
  if (n >= 1e9)  return `${(n / 1e9).toFixed(2)}B`
  if (n >= 1e6)  return `${(n / 1e6).toFixed(1)}M`
  return n.toLocaleString()
}
