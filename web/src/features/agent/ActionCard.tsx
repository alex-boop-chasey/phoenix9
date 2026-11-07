// Action cards of the Phoenix agent panel: one compact row per tool call, and a group for three or more in a row.
import { useId, useState } from "react"

import { Icon, type IconName } from "@/components/Icon"
import type { ActionItem } from "@/features/agent/useAgent"

/** The icon for a tool name. */
export function toolIcon(tool: string): IconName {
  switch (tool) {
    case "Bash": return "terminal"
    case "Edit": case "Write": case "MultiEdit": return "pencil-simple"
    case "Read": return "file-text"
    case "SendMessage": return "chat-circle-text"
    case "Agent": return "users"
    default: return "gear"
  }
}

const STATUS_LABEL = { running: "Running", ok: "Done", error: "Failed" } as const

/** The status dot with a text label for screen readers. */
export function StatusDot({ status }: { status: ActionItem["status"] }) {
  return (
    <>
      <span className={`ag-dot ag-dot-${status}`} data-status={status} aria-hidden="true" />
      <span className="sr-only">{STATUS_LABEL[status]}</span>
    </>
  )
}

/** The excerpt clipped to its first 6 lines. */
export function clipExcerpt(text: string, max = 6): string {
  return text.split("\n").slice(0, max).join("\n")
}

/** One tool call: icon, title, status and a chevron that shows the excerpt. */
export function ActionCard({ item }: { item: ActionItem }) {
  const [open, setOpen] = useState(false)
  const panel = useId()
  return (
    <div className="ag-action" data-testid="agent-action" data-tool={item.tool}>
      <div className="ag-action-h">
        <Icon name={toolIcon(item.tool)} size="sm" />
        <span className="ag-action-title" title={item.input_summary || item.title}>{item.title}</span>
        <StatusDot status={item.status} />
        <button
          type="button"
          className="ag-chev"
          aria-expanded={open}
          aria-controls={panel}
          aria-label={`${open ? "Hide" : "Show"} details: ${item.title}`}
          onClick={() => setOpen((o) => !o)}
        >
          <Icon name="caret-down" size="sm" />
        </button>
      </div>
      {open && (
        <pre id={panel} className="ag-excerpt" data-testid="agent-excerpt">
          {item.excerpt ? clipExcerpt(item.excerpt) : "No output."}
        </pre>
      )}
    </div>
  )
}

/** Three or more actions in a row, collapsed into one "n actions" line. */
export function ActionGroup({ items }: { items: ActionItem[] }) {
  const [open, setOpen] = useState(false)
  const panel = useId()
  const running = items.filter((i) => i.status === "running").length
  const failed = items.filter((i) => i.status === "error").length
  return (
    <div className="ag-group" data-testid="agent-action-group">
      <button type="button" className="ag-group-h" aria-expanded={open} aria-controls={panel} onClick={() => setOpen((o) => !o)}>
        <Icon name="list-checks" size="sm" />
        <span style={{ flex: 1 }}>{items.length} actions</span>
        {running > 0 && <StatusDot status="running" />}
        {running === 0 && failed > 0 && <StatusDot status="error" />}
        <Icon name={open ? "caret-down" : "caret-right"} size="sm" />
      </button>
      {open && (
        <div id={panel} className="ag-group">
          {items.map((it) => <ActionCard key={`${it.id}-${it.line}`} item={it} />)}
        </div>
      )}
    </div>
  )
}
