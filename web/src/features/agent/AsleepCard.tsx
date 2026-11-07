// The "asleep" card of the Phoenix agent panel: Wake it (after a confirmation) and Open in Claude app.
import { useQueryClient } from "@tanstack/react-query"
import { useEffect, useRef, useState } from "react"

import { ConfirmDialog } from "@/components/ConfirmDialog"
import { Icon } from "@/components/Icon"
import { agentKeys, useRestartAgent, type AgentStatus } from "@/features/agent/useAgent"
import { get } from "@/lib/api"

export const WAKE_LIMIT_MS = 60_000
const WAKE_POLL_MS = 2_000

type Wake = "idle" | "waking" | "failed"

/** The card shown instead of the conversation while the Phoenix agent is asleep. */
export function AsleepCard({ appUrl }: { appUrl?: string }) {
  const qc = useQueryClient()
  const restart = useRestartAgent()
  const [ask, setAsk] = useState(false)
  const [wake, setWake] = useState<Wake>("idle")
  const [why, setWhy] = useState("")
  const timers = useRef<{ poll?: ReturnType<typeof setInterval>; limit?: ReturnType<typeof setTimeout> }>({})

  const stop = () => {
    clearInterval(timers.current.poll)
    clearTimeout(timers.current.limit)
  }
  useEffect(() => stop, [])

  const awake = (status: AgentStatus) => {
    stop()
    qc.setQueryData(agentKeys.status(), status)
    void qc.invalidateQueries({ queryKey: agentKeys.status() })
    setWake("idle")
  }

  const watch = () => {
    timers.current.poll = setInterval(() => {
      get<AgentStatus>("agent").then((s) => { if (s.state !== "asleep") awake(s) }, () => {})
    }, WAKE_POLL_MS)
    timers.current.limit = setTimeout(() => {
      stop()
      setWhy("The Phoenix agent did not wake. Try again, or check the service on the server.")
      setWake("failed")
    }, WAKE_LIMIT_MS)
  }

  const go = () => {
    setAsk(false)
    setWhy("")
    setWake("waking")
    restart.mutate(undefined, {
      onSuccess: watch,
      onError: (e) => {
        setWhy(e instanceof Error ? e.message : "The restart did not start.")
        setWake("failed")
      },
    })
  }

  return (
    <div className="empty ag-asleep" role="status">
      <div className="ec"><Icon name="moon" /></div>
      <h3 className="h3">The Phoenix agent is asleep</h3>
      <p className="ag-empty">It is not running, so it cannot read or answer messages.</p>
      {wake === "waking" && <p role="status">Waking the Phoenix agent…</p>}
      {wake === "failed" && <p role="alert" className="ag-fail">{why}</p>}
      <div className="ag-actions">
        <button className="btn btn-primary" disabled={wake === "waking"} onClick={() => setAsk(true)}>Wake it</button>
        {appUrl && (
          <a className="btn" href={appUrl} target="_blank" rel="noopener noreferrer">Open in Claude app</a>
        )}
      </div>
      <ConfirmDialog
        open={ask}
        onOpenChange={setAsk}
        title="Wake the Phoenix agent?"
        body="This restarts the Phoenix agent's service. Its conversation is kept."
        confirmLabel="Wake it"
        onConfirm={go}
      />
    </div>
  )
}
