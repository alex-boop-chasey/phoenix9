// Body of the log card: the last lines of a log in a scroll box.
import type { CardBodyProps } from "../cardBodies"

const MAX = 200

/** The mono lines of a log card, at most 200. */
export function LogBody({ data }: CardBodyProps) {
  const d = (data ?? {}) as { lines?: string[]; truncated?: boolean }
  const all = Array.isArray(d.lines) ? d.lines : []
  const lines = all.slice(-MAX)
  if (lines.length === 0) return <p className="muted" data-testid="log-empty">This log is empty.</p>
  return (
    <div data-testid="card-log">
      {d.truncated || all.length > MAX ? <p className="muted" data-testid="log-truncated">showing the last {lines.length} lines</p> : null}
      <pre className="ag-code mono max-h-64 overflow-auto whitespace-pre-wrap break-words" tabIndex={0} data-testid="log-lines">
        {lines.join("\n")}
      </pre>
    </div>
  )
}
