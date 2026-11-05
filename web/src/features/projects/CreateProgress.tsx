// The launch checklist: one line per creation step, with a spinner, tick or cross.
import { Icon } from "@/components/Icon"
import { Indicator } from "@/components/Indicator"
import type { JobStep } from "@/lib/types"

/** One line per step so far; the list grows as the server reports each step. */
export function CreateProgress({ steps }: { steps: JobStep[] }) {
  return (
    <ol className="launch" aria-label="Progress" aria-live="polite">
      {steps.length === 0 && <li className="pend">Starting…</li>}
      {steps.map((s, i) => (
        <li key={i} data-status={s.status}>
          {s.status === "running" && <span className="ind ind-run sm" data-testid="spinner" role="img" aria-label="Working" />}
          {s.status === "done" && <span aria-label="Done" role="img" className="ind ind-ok sm"><Icon name="check" size="xs" /></span>}
          {s.status === "failed" && <Indicator kind="failed" small />}
          <span>{s.label}</span>
        </li>
      ))}
    </ol>
  )
}
