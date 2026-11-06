// The updates panel: installed, previous and newest version, Install update, Roll back, progress and the update log.
import { useQueryClient } from "@tanstack/react-query"
import { useEffect, useRef, useState } from "react"
import { toast } from "sonner"

import { ConfirmDialog } from "@/components/ConfirmDialog"
import { Icon } from "@/components/Icon"
import { Wheel } from "@/components/Indicator"
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
    <p className="small">Loading…</p>
  ) : !supported || !st ? (
    <p className="small">
      Installed: v{info.update.installed || info.version}. Installing updates from the dashboard comes in a later update.
    </p>
  ) : (
    <div className="stackg">
      <div className="trio">
        <div><span>Installed</span><b>{st.installed?.tag ?? "not installed yet"}</b></div>
        <div><span>Previous</span><b>{st.previous?.tag ?? "none"}</b></div>
        <div className={st.update_available ? "new" : ""}><span>Newest</span><b>{st.newest ?? "unknown"}</b></div>
      </div>
      {st.off_release_note && <p className="small">{st.off_release_note}</p>}
      {wait && wait.result === "" && <p role="status" className="row"><Wheel />{wait.text}</p>}
      {wait && wait.result !== "" && (
        wait.failed
          ? <p role="alert" className="cfgerr"><Icon name="warning-circle" size="sm" />{wait.result}</p>
          : <p role="status" className="light ok"><i></i>{wait.result}</p>
      )}
      <div className="row">
        {endpoints?.install && (
          <button type="button" className="btn btn-primary" disabled={installOff} onClick={() => setConfirm("install")}>
            <Icon name="arrow-circle-up" />Install update {st.newest ?? ""}
          </button>
        )}
        {endpoints?.rollback && (
          <button type="button" className="btn btn-danger" disabled={!st.can_rollback || waiting || busy} onClick={() => setConfirm("rollback")}>
            <Icon name="arrow-counter-clockwise" />Roll back{st.previous ? ` to ${st.previous.tag}` : ""}
          </button>
        )}
      </div>
      <div className="row">
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => void check()}>
          <Icon name="arrows-clockwise" />Check for updates
        </button>
      </div>
      {endpoints?.install && noInstallWhy && <p className="small">{noInstallWhy}</p>}
      <details>
        <summary className="small" style={{ cursor: "pointer" }}>Last update log</summary>
        <pre className="mono small" style={{ maxHeight: 288, overflow: "auto", whiteSpace: "pre-wrap", marginTop: 8 }}>
          {st.log_tail.length ? st.log_tail.join("\n") : "Nothing logged yet."}
        </pre>
      </details>
      <div className="blk-info">
        <Icon name="info" />
        <span>Installing waits for any build step that is running, then the dashboard is down for a few seconds while the update is swapped in.</span>
      </div>
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
    <section className="board" aria-labelledby="g-u" id="updBoard">
      <div className="board-h">
        <h2 className="h2" id="g-u">Phoenix updates</h2>
        {st?.update_available && <span className="sp"><span className="light lrun"><i></i>{st.newest} available</span></span>}
      </div>
      <div className="board-b">{body}</div>
    </section>
  )
}
