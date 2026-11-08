// The confirm reply block: the action and exact command with Yes / No / Other; the agent runs the command, never Phoenix.
import { useRef, useState } from "react"

import { Button } from "@/components/ui/button"
import type { BlockProps } from "@/features/agent/blocks/types"
import { useSendToAgent } from "@/features/agent/useAgent"

interface Confirm { id: string; action: string; command: string; danger?: boolean }

function parseConfirm(json: string): Confirm | null {
  try {
    const c = JSON.parse(json) as Confirm
    return c && typeof c.id === "string" && typeof c.action === "string" && typeof c.command === "string" ? c : null
  } catch {
    return null
  }
}

/** The answer text of the first later user item that answers this confirm, or null. */
function answeredBy(id: string, later: string[]): string | null {
  const head = `[Phoenix panel · confirm ${id}`
  for (const t of later) {
    if (!t.startsWith(head)) continue
    const rest = t.slice(head.length)
    if (rest[0] !== "]" && !rest.startsWith(" ·")) continue
    const end = t.indexOf("] ")
    return end >= 0 ? t.slice(end + 2) : ""
  }
  return null
}

/** Shows a checked confirm block and sends yes, no or other text through the agent send route. */
export function ConfirmBlock({ json, frozen = false, later = [] }: BlockProps) {
  const confirm = parseConfirm(json)
  const send = useSendToAgent()
  const [otherText, setOtherText] = useState("")
  const [chose, setChose] = useState<string | null>(null)
  const tiles = useRef<(HTMLElement | null)[]>([])

  if (!confirm) return <div className="ag-block ag-block-confirm" data-testid="block-confirm"><pre className="ag-code mono"><code>{json}</code></pre></div>

  const answer = chose ?? answeredBy(confirm.id, later)
  const readOnly = frozen || answer !== null

  function post(text: string, shown: string) {
    setChose(shown)
    send.mutate({ text }, { onError: () => setChose(null) })
  }

  function sendOther() {
    const t = otherText.trim()
    if (t && !readOnly) post(`[Phoenix panel · confirm ${confirm!.id} · other] ${t}`, t)
  }

  function onKey(e: React.KeyboardEvent, n: number) {
    const step = e.key === "ArrowDown" || e.key === "ArrowRight" ? 1 : e.key === "ArrowUp" || e.key === "ArrowLeft" ? -1 : 0
    if (!step) return
    e.preventDefault()
    tiles.current[(n + step + 3) % 3]?.focus()
  }

  return (
    <div className="ag-block ag-block-confirm ag-choice" data-testid="block-confirm" data-frozen={frozen ? "true" : undefined}
      data-readonly={readOnly ? "true" : undefined} role="group" aria-label={confirm.action}>
      <div className="ag-choice-q">{confirm.action}</div>
      <pre className="ag-code mono" data-testid="confirm-command"><code>{confirm.command}</code></pre>
      <button type="button" className={`ag-tile${confirm.danger ? " ag-tile-danger" : ""}`} disabled={readOnly}
        ref={(el) => { tiles.current[0] = el }} onKeyDown={(e) => onKey(e, 0)}
        onClick={() => post(`[Phoenix panel · confirm ${confirm.id}] yes`, "Yes")}>Yes, do it</button>
      <button type="button" className="ag-tile" disabled={readOnly}
        ref={(el) => { tiles.current[1] = el }} onKeyDown={(e) => onKey(e, 1)}
        onClick={() => post(`[Phoenix panel · confirm ${confirm.id}] no`, "No")}>No</button>
      <div className="ag-tile" onKeyDown={(e) => { if (e.key === "ArrowUp" || e.key === "ArrowDown") onKey(e, 2) }}>
        <label htmlFor={`other-${confirm.id}`}>Other:</label>
        <input id={`other-${confirm.id}`} ref={(el) => { tiles.current[2] = el }} className="ag-choice-other" type="text" value={otherText} disabled={readOnly}
          onChange={(e) => setOtherText(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); sendOther() } }} />
        <Button type="button" size="sm" disabled={readOnly || !otherText.trim()} onClick={sendOther}>Send</Button>
      </div>
      {answer !== null && <div className="ag-choice-answer muted" data-testid="confirm-answer">You answered: {answer}</div>}
    </div>
  )
}
