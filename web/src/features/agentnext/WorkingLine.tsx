// One quiet line for what the agent is doing in plain words, then a small "N steps" list once it answered.
import { Icon } from "@/components/Icon"
import type { ToolCallItem } from "./components"
import { toolWords } from "./toolWords"

/** This turn's steps in plain words, newest last, a small check on each finished one. */
function StepList({ calls }: { calls: ToolCallItem[] }) {
  return (
    <ol className="ag-steps">
      {calls.map((c) => (
        <li key={c.toolCallId}>
          {c.running ? toolWords(c.toolName).doing : toolWords(c.toolName).done}
          {!c.running && <Icon name="check" size="xs" title="Done" />}
        </li>
      ))}
    </ol>
  )
}

/** While the agent works: "Working… · <newest step>"; after: a closed "N steps" list (nothing when there were none). */
export function WorkingLine({ calls, running }: { calls: ToolCallItem[]; running: boolean }) {
  if (running) {
    const newest = [...calls].reverse().find((c) => c.running)
    return (
      <div className="ag-working ag-busy" data-testid="agent-working">
        <p aria-live="polite">{newest ? `Working… · ${toolWords(newest.toolName).doing}` : "Working…"}</p>
        {calls.length > 0 && (
          <details>
            <summary>Show steps</summary>
            <StepList calls={calls} />
          </details>
        )}
      </div>
    )
  }
  if (!calls.length) return null
  return (
    <details className="ag-working" data-testid="agent-steps">
      <summary>{calls.length === 1 ? "1 step" : `${calls.length} steps`}</summary>
      <StepList calls={calls} />
    </details>
  )
}
