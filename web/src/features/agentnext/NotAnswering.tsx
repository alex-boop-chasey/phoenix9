// The drawer's card for when the agent does not answer: why, and (when its service is down) a Restart button.
import { useEffect, useRef, useState } from "react"

import { ConfirmDialog } from "@/components/ConfirmDialog"
import { Icon } from "@/components/Icon"
import { useRestartAgentService } from "@/lib/queries"
import { Mark } from "./cardparts"
import { agentAvailable, type NotAnswering } from "./runtime"

/** How often to look whether the agent answers again after a restart. */
export const RESTART_LOOK_MS = 3_000
/** How long to keep looking before saying it did not come back. */
export const RESTART_LIMIT_MS = 30_000

/** The card's heading for each reason, in plain words. */
const HEADINGS: Record<NotAnswering, string> = {
  "no-key": "The agent has no API key yet",
  "not-running": "The agent is not running",
  "not-set-up": "The agent is not set up yet",
}

type Restart = "idle" | "restarting" | "failed"

/** Shown in place of the conversation; `onBack` runs once the agent answers again after a restart. */
export function NotAnsweringCard({ reason, message, onBack }: { reason: NotAnswering; message: string; onBack: () => void }) {
  const restart = useRestartAgentService()
  const [ask, setAsk] = useState(false)
  const [state, setState] = useState<Restart>("idle")
  const [why, setWhy] = useState("")
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined)
  useEffect(() => () => clearTimeout(timer.current), [])

  /** Look again every few seconds until the agent answers or the time is up. */
  const watch = (until: number) => {
    timer.current = setTimeout(() => {
      void agentAvailable().then((got) => {
        if (got.ok) return onBack()
        if (Date.now() + RESTART_LOOK_MS > until) {
          setWhy("The agent did not come back within 30 seconds. Try again, or check its service on the server.")
          setState("failed")
          return
        }
        watch(until)
      })
    }, RESTART_LOOK_MS)
  }

  const go = () => {
    setAsk(false)
    setWhy("")
    setState("restarting")
    restart.mutate(undefined, {
      onSuccess: () => watch(Date.now() + RESTART_LIMIT_MS),
      onError: (e) => {
        setWhy(`The restart did not work: ${e instanceof Error ? e.message : "no answer from Phoenix."}`)
        setState("failed")
      },
    })
  }

  return (
    <div className="ag-card ag-asleep" role="status" data-testid="agent-not-answering">
      <h3 className="ag-card-h"><Icon name="moon" size="sm" className="ag-quiet" />{HEADINGS[reason]}</h3>
      <p className="ag-card-b ag-quiet">{message}</p>
      {state === "restarting" && <p role="status" className="ag-card-b">Restarting the agent…</p>}
      {state === "failed" && <p role="alert" className="ag-card-b ag-result"><Mark ok={false} /><span>{why}</span></p>}
      {reason === "not-running" && (
        <>
          <div className="ag-card-f">
            <button className="btn btn-primary" disabled={state === "restarting"} onClick={() => setAsk(true)}>Restart the agent</button>
          </div>
          <ConfirmDialog
            open={ask}
            onOpenChange={setAsk}
            title="Restart the agent?"
            body="This restarts the agent's service. Your conversations are kept."
            confirmLabel="Restart"
            onConfirm={go}
          />
        </>
      )}
    </div>
  )
}
