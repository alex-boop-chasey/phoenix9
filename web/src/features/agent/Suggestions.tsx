// The thin strip under the context chip: up to three report lines worth a mention. Collapsed when empty.
import { Link } from "react-router"

import { useMarkSuggestion, useSendToAgent, useSuggestions } from "@/features/agent/useAgent"
import { toast } from "sonner"

const REPORT_LINK = "/p/home/logs?log=reports%2Fstatus.md"

/** The Suggestions strip: Ask, Snooze 1 day and Dismiss per line, and a link to the full report. */
export function Suggestions() {
  const list = useSuggestions().data?.suggestions ?? []
  const mark = useMarkSuggestion()
  const send = useSendToAgent()
  const busyKey = mark.isPending ? mark.variables?.key : undefined
  if (!list.length) return null
  // Only the key goes to the agent (keys are plain characters); the line's text comes from builds and projects, so the
  // agent reads it itself with `phoenix suggest show <key>` and treats it as information, never as Alex's words.
  const ask = (key: string) =>
    send.mutate({ text: `Tell me about suggestion ${key}.` }, { onError: (e) => toast.error(e instanceof Error ? e.message : "The message was not sent.") })
  const act = (key: string, what: "snooze" | "dismiss") =>
    mark.mutate({ key, what }, { onError: (e) => toast.error(e instanceof Error ? e.message : "That did not work.") })
  return (
    <section className="ag-sugg" aria-label="Suggestions" data-testid="agent-suggestions">
      <div className="ag-sugg-h">
        <strong>Suggestions</strong>
        <Link to={REPORT_LINK}>Full report</Link>
      </div>
      <ul>
        {list.map((s) => (
          <li key={s.key}>
            <span className="ag-sugg-text">{s.text}</span>
            <span className="ag-sugg-acts">
              <button className="btn btn-sm" disabled={busyKey === s.key} onClick={() => ask(s.key)}>Ask</button>
              <button className="btn btn-ghost btn-sm" disabled={busyKey === s.key} onClick={() => act(s.key, "snooze")}>Snooze 1 day</button>
              <button className="btn btn-ghost btn-sm" disabled={busyKey === s.key} onClick={() => act(s.key, "dismiss")}>Dismiss</button>
            </span>
          </li>
        ))}
      </ul>
    </section>
  )
}
