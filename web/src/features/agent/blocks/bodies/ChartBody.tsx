// Body of the chart card: bars or a sparkline drawn by hand in SVG, with the values as a hidden list.
import type { CardBodyProps } from "../cardBodies"
import { InlineFooter } from "./Footer"

interface Point { label: string; value: number }

const W = 300
const H = 100

function Bars({ series, max }: { series: Point[]; max: number }) {
  const slot = W / series.length
  return series.map((p, i) => {
    const h = max > 0 ? (Math.max(p.value, 0) / max) * (H - 4) : 0
    return <rect key={i} data-testid="bar" x={i * slot + slot * 0.1} width={slot * 0.8} y={H - h} height={h} fill="var(--primary)" />
  })
}

function Spark({ series, min, max }: { series: Point[]; min: number; max: number }) {
  const span = max - min || 1
  const step = series.length > 1 ? W / (series.length - 1) : 0
  const pts = series.map((p, i) => `${(series.length > 1 ? i * step : W / 2).toFixed(1)},${(H - 4 - ((p.value - min) / span) * (H - 8)).toFixed(1)}`)
  return <polyline data-testid="spark-line" points={pts.join(" ")} fill="none" stroke="var(--primary)" strokeWidth={2} />
}

/** A bar chart or sparkline with an accessible label and its values as a visually hidden list. */
export function ChartBody({ data }: CardBodyProps) {
  const d = (data ?? {}) as { kind?: string; series?: Point[]; footer?: string }
  const series = Array.isArray(d.series) ? d.series : []
  const values = series.map((p) => p.value)
  const max = Math.max(0, ...values)
  const min = Math.min(...values)
  const kind = d.kind === "spark" ? "spark" : "bars"
  const label = `${kind === "spark" ? "Line" : "Bar"} chart of ${series.length} values`
  return (
    <div data-testid="card-chart">
      {series.length > 0 && (
        <svg viewBox={`0 0 ${W} ${H}`} className="h-24 w-full" role="img" aria-label={label} preserveAspectRatio="none">
          {kind === "bars" ? <Bars series={series} max={max} /> : <Spark series={series} min={min} max={max} />}
        </svg>
      )}
      <ul className="sr-only" data-testid="chart-values">
        {series.map((p, i) => <li key={i}>{p.label}: {p.value}</li>)}
      </ul>
      <InlineFooter text={d.footer} />
    </div>
  )
}
