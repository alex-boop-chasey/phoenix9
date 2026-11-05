// The Health board at the top of Phoenix settings: one chip per health check, green tick or red with the reason.
import { Icon } from "@/components/Icon"
import { RelativeTime } from "@/components/RelativeTime"
import type { DoctorResult } from "@/lib/types"

/** "claude-token" -> "Claude token". */
export function checkLabel(name: string): string {
  const text = name.replace(/[-_]/g, " ")
  return text.charAt(0).toUpperCase() + text.slice(1)
}

/** The board: a summary badge, when it was checked and the chips. */
export function HealthBoard({ result, loading, error }: { result?: DoctorResult; loading: boolean; error?: string }) {
  const bad = result ? result.checks.filter((c) => !c.ok).length : 0
  return (
    <section className="board" aria-labelledby="g-h">
      <div className="board-h">
        <Icon name="stethoscope" size="lg" className={bad ? "text-bad" : "text-ok"} />
        <h2 className="h2" id="g-h">Health</h2>
        <span className="sp">
          {result && (bad === 0
            ? <span className="badge b-ok"><Icon name="check-circle" />All good</span>
            : <span className="badge b-bad"><Icon name="warning-circle" />{bad} {bad === 1 ? "problem" : "problems"}</span>)}
          {result?.checked_at && <span className="small"> Checked <RelativeTime iso={result.checked_at} /></span>}
        </span>
      </div>
      <div className="board-b health" id="healthChips">
        {loading && !result && <span className="small">Checking…</span>}
        {error && <span className="small" role="alert">{error}</span>}
        {result?.checks.map((c) => (
          <button
            key={c.name} type="button" className={c.ok ? "hchip" : "hchip bad"}
            title={c.ok ? c.detail : `${c.detail}${c.fix ? ` Fix: ${c.fix}` : ""}`}
            data-check={c.name} data-ok={c.ok}
          >
            <Icon name={c.ok ? "check-circle" : "x-circle"} />
            {checkLabel(c.name)}{c.ok ? "" : `: ${c.detail}`}
          </button>
        ))}
      </div>
    </section>
  )
}
