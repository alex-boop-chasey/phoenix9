// The Update history list: what the updater recorded (installs and roll-backs), newest first.
import { useUpdateHistory } from "@/lib/queries"
import type { UpdateHistoryRow } from "@/lib/types"

const WORDS: Record<string, string> = {
  installed: "Installed", "already-installed": "Already installed", recovered: "Recovered", "rolled-back-manual": "Rolled back",
  "rolled-back": "Went back after a problem", "rolled-back-unhealthy": "Went back: failed its health check",
}

function line(r: UpdateHistoryRow): string {
  const what = WORDS[r.result] ?? (r.action === "rollback" ? "Roll back" : "Update")
  const bad = !["installed", "already-installed", "recovered", "rolled-back-manual"].includes(r.result)
  return `${what}${bad && !WORDS[r.result] ? ` did not go ahead (${r.result})` : ""}${r.reason ? ` · ${r.reason}` : ""}`
}

/** The history card. */
export function UpdateHistory() {
  const q = useUpdateHistory()
  const rows = q.data?.history ?? []
  return (
    <section className="card" aria-labelledby="g-uh">
      <h2 className="h2" id="g-uh" style={{ fontSize: 22, marginBottom: 10 }}>Update history</h2>
      {q.isLoading ? <p className="small">Loading…</p> : rows.length === 0 ? (
        <p className="small">Nothing recorded yet.</p>
      ) : (
        <ul className="thread">
          {rows.map((r, i) => (
            <li key={`${r.at}-${i}`} className={["installed", "already-installed", "recovered", "rolled-back-manual"].includes(r.result) ? "" : "bad"}>
              <i></i><time dateTime={r.at}>{r.at.slice(0, 10)}</time>
              <span>{r.tag && <span className="tag">{r.tag}</span>} {line(r)}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
