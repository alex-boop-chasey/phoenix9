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
    <section className="flex flex-col gap-2" aria-label="What needs you" data-testid="bell-card">
      {rows.map((r, i) => (
        <div key={i} className="card flex flex-col gap-1" data-testid="bell-row">
          <strong>{r.title}</strong>
          {r.detail ? <span className="block text-sm text-muted-foreground">{r.detail}</span> : null}
          <button type="button" className="btn" onClick={() => { window.location.hash = r.link }}>Open</button>
        </div>
      ))}
    </section>
  )
}
