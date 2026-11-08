// The choice reply block: stacked option tiles; picking sends one message to the agent, then the block is read-only.
import { useRef, useState } from "react"

import { Button } from "@/components/ui/button"
import type { BlockProps } from "@/features/agent/blocks/types"
import { oneLine } from "@/features/agent/blocks/oneLine"
import { useSendToAgent } from "@/features/agent/useAgent"

interface Option { key: string; label: string; detail?: string; recommended?: boolean }
interface Choice { id: string; question: string; mode: "single" | "multi"; options: Option[]; other?: boolean }

function parseChoice(json: string): Choice | null {
  try {
    const c = JSON.parse(json) as Choice
    return c && typeof c.id === "string" && Array.isArray(c.options) ? c : null
  } catch {
    return null
  }
}

/** The answer text of the first later user item that answers this choice, or null. */
function answeredBy(id: string, later: string[]): string | null {
  const head = `[Phoenix panel · choice ${id}`
  for (const t of later) {
    if (!t.startsWith(head)) continue
    const rest = t.slice(head.length)
    if (rest[0] !== "]" && !rest.startsWith(" ·")) continue
    const end = t.indexOf("] ")
    return end >= 0 ? t.slice(end + 2) : ""
  }
  return null
}

/** Shows a checked choice block and sends the pick through the agent send route. */
export function ChoiceBlock({ json, frozen = false, later = [] }: BlockProps) {
  const choice = parseChoice(json)
  const send = useSendToAgent()
  const [picked, setPicked] = useState<Set<string>>(new Set())
  const [otherText, setOtherText] = useState("")
  const [chose, setChose] = useState<string | null>(null)
  const tiles = useRef<(HTMLElement | null)[]>([])

  if (!choice) return <div className="ag-block ag-block-choice" data-testid="block-choice"><pre className="ag-code mono"><code>{json}</code></pre></div>

  const answer = chose ?? answeredBy(choice.id, later)
  const readOnly = frozen || answer !== null
  const multi = choice.mode === "multi"
  const count = choice.options.length + (choice.other ? 1 : 0)

  function post(text: string, shown: string) {
    setChose(shown)
    send.mutate({ text: oneLine(text) }, { onError: () => setChose(null) })
  }

  function pick(o: Option) {
    if (readOnly) return
    if (!multi) return post(`[Phoenix panel · choice ${choice!.id}] ${oneLine(o.label)}`, o.label)
    const next = new Set(picked)
    if (!next.delete(o.key)) next.add(o.key)
    setPicked(next)
  }

  function sendMulti() {
    const labels = choice!.options.filter((o) => picked.has(o.key)).map((o) => oneLine(o.label))
    if (labels.length) post(`[Phoenix panel · choice ${choice!.id}] ${labels.join(", ")}`, labels.join(", "))
  }

  function sendOther() {
    const t = otherText.trim()
    if (t && !readOnly) post(`[Phoenix panel · choice ${choice!.id} · other] ${t}`, t)
  }

  function onKey(e: React.KeyboardEvent, n: number) {
    const step = e.key === "ArrowDown" || e.key === "ArrowRight" ? 1 : e.key === "ArrowUp" || e.key === "ArrowLeft" ? -1 : 0
    if (!step) return
    e.preventDefault()
    tiles.current[(n + step + count) % count]?.focus()
  }

  return (
    <div className="ag-block ag-block-choice ag-choice" data-testid="block-choice" data-frozen={frozen ? "true" : undefined}
      data-readonly={readOnly ? "true" : undefined} role={multi ? "group" : "radiogroup"} aria-label={choice.question}>
      <div className="ag-choice-q">{choice.question}</div>
      {choice.options.map((o, n) => (
        <button key={o.key} type="button" className="ag-tile" role={multi ? "checkbox" : "radio"}
          aria-checked={multi ? picked.has(o.key) : false} disabled={readOnly}
          ref={(el) => { tiles.current[n] = el }} onKeyDown={(e) => onKey(e, n)} onClick={() => pick(o)}>
          {multi && <input type="checkbox" tabIndex={-1} aria-hidden="true" readOnly checked={picked.has(o.key)} />}
          <span>
            <span>{o.label}</span>
            {o.recommended && <span className="pill">Recommended</span>}
            {o.detail && <span className="ag-tile-detail">{o.detail}</span>}
          </span>
        </button>
      ))}
      {choice.other && (
        <div className="ag-tile"
          onKeyDown={(e) => { if (e.key !== "ArrowUp" && e.key !== "ArrowDown") return; onKey(e, choice.options.length) }}>
          <label htmlFor={`other-${choice.id}`}>Other:</label>
          <input id={`other-${choice.id}`} ref={(el) => { tiles.current[choice.options.length] = el }} className="ag-choice-other" type="text" value={otherText} disabled={readOnly}
            onChange={(e) => setOtherText(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); sendOther() } }} />
          <Button type="button" size="sm" disabled={readOnly || !otherText.trim()} onClick={sendOther}>Send</Button>
        </div>
      )}
      {multi && !readOnly && <Button type="button" size="sm" disabled={picked.size === 0} onClick={sendMulti}>Send</Button>}
      {answer !== null && <div className="ag-choice-answer muted" data-testid="choice-answer">You chose: {answer}</div>}
    </div>
  )
}
