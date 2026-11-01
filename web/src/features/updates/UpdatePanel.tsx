// The updates panel: installed and newest version, Install update, Roll back and a link to the update log.
import { useEffect, useRef, useState } from "react"
import { Link } from "react-router"
import { toast } from "sonner"

import { ConfirmDialog } from "@/components/ConfirmDialog"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { api, post } from "@/lib/api"
import { useInfo } from "@/lib/queries"

const POLL_MS = 2000
const GIVE_UP_MS = 3 * 60 * 1000

/** Installed/newest version with Install update and Roll back, driven by /api/info `update`. */
export function UpdatePanel({ bare = false }: { bare?: boolean }) {
  const { data: info, refetch } = useInfo()
  const update = info?.update
  const [restarting, setRestarting] = useState(false)
  const [failed, setFailed] = useState("")
  const [rollback, setRollback] = useState(false)
  const [busy, setBusy] = useState(false)
  const from = useRef("")
  const timer = useRef<ReturnType<typeof setInterval> | null>(null)
  const started = useRef(0)

  const stop = () => {
    if (timer.current) clearInterval(timer.current)
    timer.current = null
  }
  useEffect(() => stop, [])

  /** Poll /api/info every 2 s until the version changes or 3 minutes pass. */
  function watch(before: string) {
    from.current = before
    started.current = Date.now()
    setRestarting(true)
    setFailed("")
    stop()
    timer.current = setInterval(() => {
      void api.info().then(
        (now) => {
          if (now.update.installed !== from.current || now.version !== from.current) {
            stop()
            setRestarting(false)
            void refetch()
          }
        },
        () => undefined, // the dashboard is down during the swap
      )
      if (Date.now() - started.current >= GIVE_UP_MS) {
        stop()
        setRestarting(false)
        setFailed("Phoenix did not come back after 3 minutes. Check the Logs tab of phoenix9 for the update log.")
      }
    }, POLL_MS)
  }

  async function run(path: string, label: string) {
    if (!update) return
    setBusy(true)
    try {
      await post(path, {})
      watch(update.installed)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : `${label} did not start.`)
    } finally {
      setBusy(false)
    }
  }

  const body = !update ? (
    <p className="text-sm text-muted-foreground">Loading…</p>
  ) : !update.supported ? (
    <p className="text-sm">
      Installed: v{update.installed || info?.version}. Installing updates from the dashboard comes in a later update.
    </p>
  ) : (
    <div className="flex flex-col gap-3 text-sm">
      <div className="flex flex-wrap gap-x-6 gap-y-1">
        <span>Installed: v{update.installed}</span>
        <span>Newest: v{update.newest}</span>
      </div>
      {restarting && <p role="status">Phoenix is restarting; this page reconnects by itself.</p>}
      {failed && (
        <Alert variant="destructive"><AlertDescription>{failed}</AlertDescription></Alert>
      )}
      <div className="flex flex-wrap items-center gap-2">
        {update.endpoints?.install && (
          <Button
            disabled={!update.can_install || restarting || busy}
            onClick={() => void run(update.endpoints!.install!, "The update")}
          >
            Install update v{update.newest}
          </Button>
        )}
        {update.endpoints?.rollback && (
          <Button variant="outline" disabled={restarting || busy} onClick={() => setRollback(true)}>
            Roll back
          </Button>
        )}
        <Link to="/p/phoenix9/logs?kind=service" className="text-primary underline-offset-4 hover:underline">
          Last update log
        </Link>
      </div>
      {update.endpoints?.install && !update.can_install && update.reason && (
        <p className="text-muted-foreground">{update.reason}</p>
      )}
      <p className="text-muted-foreground">The dashboard is down for a few seconds while the update is swapped in.</p>
      <ConfirmDialog
        open={rollback}
        onOpenChange={setRollback}
        title="Roll back Phoenix?"
        body="Phoenix goes back to the previous installed version. The dashboard is down for a few seconds."
        confirmLabel="Roll back"
        destructive
        onConfirm={() => {
          setRollback(false)
          if (update.endpoints?.rollback) void run(update.endpoints.rollback, "The roll back")
        }}
      />
    </div>
  )

  if (bare) return body
  return (
    <Card>
      <CardHeader><CardTitle>Phoenix updates</CardTitle></CardHeader>
      <CardContent>{body}</CardContent>
    </Card>
  )
}
