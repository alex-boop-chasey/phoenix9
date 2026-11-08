// Body of the table card: a plain table that scrolls sideways on narrow screens.
import type { CardBodyProps } from "../cardBodies"
import { InlineFooter } from "./Footer"

/** A plain table of text and numbers. */
export function TableBody({ data }: CardBodyProps) {
  const d = (data ?? {}) as { columns?: string[]; rows?: (string | number)[][]; footer?: string }
  const columns = Array.isArray(d.columns) ? d.columns : []
  const rows = Array.isArray(d.rows) ? d.rows : []
  return (
    <div data-testid="card-table">
      <div className="overflow-x-auto" tabIndex={0} role="region" aria-label="Table, scrolls sideways">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr>{columns.map((c, i) => <th key={i} scope="col" className="whitespace-nowrap border-b px-2 py-1 text-left">{c}</th>)}</tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i}>
                {row.map((cell, j) => (
                  <td key={j} className={`border-b px-2 py-1 ${typeof cell === "number" ? "text-right tabular-nums" : ""}`}>{String(cell)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <InlineFooter text={d.footer} />
    </div>
  )
}
