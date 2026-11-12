// The search results card: one row per result (kind badge, title, snippet), all drawn as plain text.

/** One search result as the Phoenix pack sends it. */
export interface SearchRow { kind: string; title: string; snippet: string; link: string }

function isObject(v: unknown): v is Record<string, unknown> { return !!v && typeof v === "object" && !Array.isArray(v) }
function isText(v: unknown): v is string { return typeof v === "string" }

/** The snippet text, whether it came plain or wrapped as quoted data. */
function snippetText(v: unknown): string {
  if (isText(v)) return v
  return isObject(v) && isText(v.data) ? v.data : ""
}

/** The result rows when every one fits (kind, title and a hash link), else null. */
export function searchFrom(data: unknown): SearchRow[] | null {
  const list = isObject(data) ? data.results : null
  if (!Array.isArray(list)) return null
  const out: SearchRow[] = []
  for (const r of list) {
    if (!isObject(r) || !isText(r.kind) || !isText(r.title) || !isText(r.link) || !r.link.startsWith("#/")) return null
    out.push({ kind: r.kind, title: r.title, snippet: snippetText(r.snippet), link: r.link })
  }
  return out
}

/** Search results: a click on a row opens its page. */
export function SearchResultsCard({ rows }: { rows: SearchRow[] }) {
  if (!rows.length) return <p data-testid="search-empty">No results.</p>
  return (
    <section className="flex flex-col gap-2" aria-label="Search results" data-testid="search-results-card">
      {rows.map((r, i) => (
        <button key={i} type="button" className="card w-full text-left" data-testid="search-row" onClick={() => { window.location.hash = r.link }}>
          <span className="badge text-xs uppercase">{r.kind}</span>
          <strong className="block">{r.title}</strong>
          {r.snippet ? <span className="block text-sm text-muted-foreground">{r.snippet}</span> : null}
        </button>
      ))}
    </section>
  )
}
