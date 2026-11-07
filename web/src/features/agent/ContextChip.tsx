// The chip under the Phoenix agent panel header: where Alex is, and the switch to send it along.
import { useLocation } from "react-router"

import { Icon } from "@/components/Icon"
import { useAgentStatus } from "@/features/agent/useAgent"
import { changedParts, contextLine, readPageContext, toldFor } from "@/features/agent/pageContext"

/** The context the next message would carry: the page, and only its parts that changed. */
export function useNextContext() {
  const { pathname, search } = useLocation()
  const session = useAgentStatus().data?.session_id ?? "none"
  const page = readPageContext(pathname, search)
  const parts = changedParts(page.context, toldFor(session))
  return { page, parts, session, line: contextLine(parts) }
}

/** Shows "Working in <project>", the run, and the Send page context switch. */
export function ContextChip({ on, onChange }: { on: boolean; onChange: (on: boolean) => void }) {
  const { page, line } = useNextContext()
  const tip = on ? line || "Nothing new to send: the agent already knows this page." : "Page context is off: nothing is sent."
  return (
    <div className={`ag-ctx${on ? "" : " off"}`} data-testid="agent-context">
      <span className="ag-ctx-text" title={tip} aria-label={`Context: ${tip}`} tabIndex={0}>
        <Icon name="folder-simple" size="sm" /> Working in {page.context.project ?? "Phoenix"}
        {page.selected && <> · <span className="mono">{page.selected}</span></>}
      </span>
      <label>
        <input type="checkbox" role="switch" checked={on} onChange={(e) => onChange(e.target.checked)} />
        Send page context
      </label>
    </div>
  )
}
