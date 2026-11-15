// The bell card: what needs Alex, one row per item drawn as plain text, with a button that opens its page.

/** One bell item as the Phoenix pack sends it. */
export interface BellRow { kind: string; title: string; detail: string; link: string }

function isObject(v: unknown): v is Record<string, unknown> { return !!v && typeof v === "object" && !Array.isArray(v) }
function isText(v: unknown): v is string { return typeof v === "string" }

/** The text, whether it came plain or wrapped as quoted data. */
function textOf(v: unknown): string {
  if (isText(v)) return v
  return isObject(v) && isText(v.data) ? v.data : ""
}

/** The bell rows when every one fits (kind, title and a hash link), else null. */
export function bellFrom(data: unknown): BellRow[] | null {
  const list = isObject(data) ? data.items : null
  if (!Array.isArray(list)) return null
  const out: BellRow[] = []
  for (const r of list) {
    if (!isObject(r) || !isText(r.kind) || !isText(r.link) || !r.link.startsWith("#/")) return null
    out.push({ kind: r.kind, title: textOf(r.title), detail: textOf(r.detail), link: r.link })
  }
  return out
}

/** The bell's items; the button on a row opens its page. */
export function BellCard({ rows }: { rows: BellRow[] }) {
  if (!rows.length) return <p data-testid="bell-card-empty">Nothing needs you.</p>
  return (
    <section className="ag-card" aria-label="What needs you" data-testid="bell-card">
      <ul className="ag-list">
        {rows.map((r, i) => (
          <li key={i} className="ag-row-f" data-testid="bell-row">
            <span className="flex flex-col gap-0.5 min-w-0">
              <span className="ag-item-t">{r.title}</span>
              {r.detail ? <span className="ag-item-s">{r.detail}</span> : null}
            </span>
            <button type="button" className="btn btn-sm" onClick={() => { window.location.hash = r.link }}>Open</button>
          </li>
        ))}
      </ul>
    </section>
  )
}
