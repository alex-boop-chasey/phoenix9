// The updates panel: installed, previous and newest version, Install update, Roll back, progress and the update log.
import { useQueryClient } from "@tanstack/react-query"
import { useEffect, useRef, useState } from "react"
import { toast } from "sonner"

import { ConfirmDialog } from "@/components/ConfirmDialog"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { api, post } from "@/lib/api"
import { useInfo, useUpdate } from "@/lib/queries"
import type { UpdateStatus } from "@/lib/types"

const POLL_MS = 3000
const GIVE_UP_MS = 10 * 60 * 1000
const WORKED = ["installed", "already-installed", "recovered", "rolled-back-manual"]
const ROLLED_BACK = ["rolled-back", "rolled-back-unhealthy"]

type Action = "install" | "rollback"

interface Wait {
  action: Action
  /** Plain words for the waiting state. */
  text: string
  /** Plain words once it is over (empty while waiting). */
  result: string
  failed: boolean
}

/** What the finished status says happened, in plain words. */
export function outcome(st: UpdateStatus): { text: string; failed: boolean } {
  const last = st.last
  if (!last) return { text: `Now ${st.installed?.tag ?? "updated"}`, failed: false }
  if (WORKED.includes(last.result)) return { text: `Now ${st.installed?.tag ?? last.tag ?? "updated"}`, failed: false }
  if (ROLLED_BACK.includes(last.result)) return { text: `Rolled back: ${last.reason || last.result}`, failed: true }
  return { text: `The update did not go ahead: ${last.reason || last.result}`, failed: true }
}

/** Installed/previous/newest version with Install update and Roll back, driven by GET /api/update. */
export function UpdatePanel({ bare = false }: { bare?: boolean }) {
  const { data: info } = useInfo()
  const supported = !!info?.update.supported
  const { data: st } = useUpdate(supported)
  const qc = useQueryClient()
  const [confirm, setConfirm] = useState<Action | null>(null)
  const [busy, setBusy] = useState(false)
  const [wait, setWait] = useState<Wait | null>(null)
  const timer = useRef<ReturnType<typeof setInterval> | null>(null)

  const stop = () => {
    if (timer.current) clearInterval(timer.current)
    timer.current = null
  }
  useEffect(() => stop, [])

  /** Poll GET /api/update every 3 s (failed polls are normal: the API restarts) until the result is in. */
  function watch(action: Action, before: UpdateStatus) {
    const started = Date.now()
    const fromTag = before.installed?.tag ?? ""
    const fromAt = before.last?.at ?? ""
    const verb = action === "install" ? "Installing…" : "Rolling back…"
    setWait({ action, text: verb, result: "", failed: false })
    stop()
    timer.current = setInterval(() => {
      void api.update().then(
        (now) => {
          const changed = (now.installed?.tag ?? "") !== fromTag || (now.last?.at ?? "") !== fromAt
          if (!now.running && changed) {
            stop()
            const done = outcome(now)
            setWait({ action, text: "", result: done.text, failed: done.failed })
            qc.setQueryData(["update"], now)
            void qc.invalidateQueries({ queryKey: ["info"] })
            return
          }
          setWait({ action, text: now.running ? `${verb}${now.waiting ? ` ${now.waiting}` : ""}` : verb, result: "", failed: false })
        },
        () => setWait({ action, text: "Restarting…", result: "", failed: false }),
      )
      if (Date.now() - started >= GIVE_UP_MS) {
        stop()
        setWait({
          action, text: "", failed: true,
          result: "Phoenix did not come back after 10 minutes. Open the update log below, or run `phoenix update status` on the server.",
        })
      }
    }, POLL_MS)
  }

  async function run(action: Action) {
    const path = info?.update.endpoints?.[action]
    if (!st || !path) return
    setBusy(true)
    try {
      await post(path, action === "install" ? { yes: true, tag: st.newest ?? undefined } : { yes: true })
      watch(action, st)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "That did not start.")
    } finally {
      setBusy(false)
    }
  }

  async function check() {
    try {
      qc.setQueryData(["update"], await api.update(true))
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not check for updates.")
    }
  }

  const waiting = wait !== null && wait.result === ""
  const noInstallWhy = !st ? "" : st.busy ? st.busy_reason || "A build is busy" : st.running ? "An update is running"
    : !st.update_available ? "Phoenix is up to date" : ""
  const installOff = !st || waiting || busy || !!noInstallWhy
  const endpoints = info?.update.endpoints

  const body = !info || (supported && !st) ? (
    <p className="text-sm text-muted-foreground">Loading…</p>
  ) : !supported || !st ? (
    <p className="text-sm">
      Installed: v{info.update.installed || info.version}. Installing updates from the dashboard comes in a later update.
    </p>
  ) : (
    <div className="flex flex-col gap-3 text-sm">
      <div className="flex flex-wrap gap-x-6 gap-y-1">
        <span>Installed: {st.installed?.tag ?? "not installed yet"}</span>
        <span>Previous: {st.previous?.tag ?? "none"}</span>
        <span>Newest: {st.newest ?? "unknown"}</span>
      </div>
      {wait && wait.result === "" && <p role="status">{wait.text}</p>}
      {wait && wait.result !== "" && (
        wait.failed ? (
          <Alert variant="destructive"><AlertDescription>{wait.result}</AlertDescription></Alert>
        ) : (
          <p role="status">{wait.result}</p>
        )
      )}
      <div className="flex flex-wrap items-center gap-2">
        {endpoints?.install && (
          <Button disabled={installOff} onClick={() => setConfirm("install")}>
            Install update {st.newest ?? ""}
          </Button>
        )}
        {endpoints?.rollback && (
          <Button variant="outline" disabled={!st.can_rollback || waiting || busy} onClick={() => setConfirm("rollback")}>
            Roll back{st.previous ? ` to ${st.previous.tag}` : ""}
          </Button>
        )}
        <button type="button" className="text-primary underline-offset-4 hover:underline" onClick={() => void check()}>
          Check for updates
        </button>
      </div>
      {endpoints?.install && noInstallWhy && <p className="text-muted-foreground">{noInstallWhy}</p>}
      <details>
        <summary className="cursor-pointer">Last update log</summary>
        <pre className="mt-2 max-h-72 overflow-auto rounded-md bg-muted p-3 text-xs whitespace-pre-wrap">
          {st.log_tail.length ? st.log_tail.join("\n") : "Nothing logged yet."}
        </pre>
      </details>
      <ConfirmDialog
        open={confirm !== null}
        onOpenChange={(open) => !open && setConfirm(null)}
        title={confirm === "rollback" ? "Roll back Phoenix?" : `Install ${st.newest ?? "the update"}?`}
        body="Phoenix will restart; the dashboard is away for a few seconds."
        confirmLabel={confirm === "rollback" ? "Roll back" : "Install"}
        destructive={confirm === "rollback"}
        onConfirm={() => {
          const action = confirm
          setConfirm(null)
          if (action) void run(action)
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
