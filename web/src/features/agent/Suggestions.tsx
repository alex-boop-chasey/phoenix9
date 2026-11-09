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
  if (!list.length) return null
  const ask = (text: string) =>
    send.mutate({ text: `${text} — go ahead?` }, { onError: (e) => toast.error(e instanceof Error ? e.message : "The message was not sent.") })
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
              <button className="btn btn-sm" onClick={() => ask(s.text)}>Ask</button>
              <button className="btn btn-ghost btn-sm" onClick={() => mark.mutate({ key: s.key, what: "snooze" })}>Snooze 1 day</button>
              <button className="btn btn-ghost btn-sm" onClick={() => mark.mutate({ key: s.key, what: "dismiss" })}>Dismiss</button>
            </span>
          </li>
        ))}
      </ul>
    </section>
  )
}
