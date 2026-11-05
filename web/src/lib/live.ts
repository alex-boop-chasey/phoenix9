// Live updates: server-sent events, with a polling fallback when the stream breaks.
import { useQueryClient, type QueryClient } from "@tanstack/react-query"
import { useEffect, useRef, useState } from "react"

import { api, eventsUrl } from "@/lib/api"
import { keys, liveMode } from "@/lib/queries"
import type { PhoenixEvent } from "@/lib/types"

export const POLL_MS = 4000

/** Refresh the queries an event could have changed (command events are ignored). */
export function invalidateForEvent(qc: QueryClient, ev: Pick<PhoenixEvent, "type" | "project" | "run">) {
  if (ev.type === "command") return
  const inv = (queryKey: readonly unknown[]) => void qc.invalidateQueries({ queryKey })
  inv(keys.projects())
  inv(keys.gates())
  if (ev.type.startsWith("update.")) inv(keys.info())
  if (ev.type.startsWith("deploy.")) inv(keys.global())
  if (!ev.project) return
  inv(keys.project(ev.project))
  inv(keys.builds(ev.project))
  inv(keys.logs(ev.project))
  if (ev.type === "settings.changed" || ev.type === "project.changed") {
    inv(keys.settings(ev.project))
    inv(keys.explain(ev.project))
    inv(keys.changelog(ev.project))
  }
  if (ev.run) inv(keys.run(ev.project, ev.run))
}

/** Listen for events (optionally of one project); returns whether we are "live" or "polling". */
export function useLiveEvents(project?: string, onEvent?: (ev: PhoenixEvent) => void): { mode: "live" | "polling" } {
  const qc = useQueryClient()
  const [mode, setMode] = useState<"live" | "polling">("live")
  const handler = useRef(onEvent)
  useEffect(() => {
    handler.current = onEvent
  })

  useEffect(() => {
    let stopped = false
    let source: EventSource | null = null
    let timer: ReturnType<typeof setTimeout> | undefined
    let last: number | undefined

    const deliver = (ev: PhoenixEvent) => {
      invalidateForEvent(qc, ev)
      handler.current?.(ev)
    }

    const poll = async () => {
      if (stopped) return
      try {
        const res = await api.eventsRecent({ project, after: last })
        if (last !== undefined) res.events.forEach(deliver)
        last = res.next
      } catch {
        // keep trying; the next tick may work
      }
      if (!stopped) timer = setTimeout(poll, POLL_MS)
    }

    const startPolling = () => {
      source?.close()
      source = null
      liveMode.current = "polling"
      setMode("polling")
      void poll()
    }

    if (typeof EventSource === "undefined") {
      startPolling()
    } else {
      source = new EventSource(eventsUrl(project))
      source.onopen = () => { liveMode.current = "live"; setMode("live") }
      source.onmessage = (m: MessageEvent) => onFrame(m)
      source.onerror = () => startPolling()
    }

    function onFrame(m: MessageEvent) {
      try {
        const ev = JSON.parse(m.data as string) as PhoenixEvent
        const id = Number(m.lastEventId)
        if (Number.isFinite(id) && m.lastEventId !== "") {
          last = id
          ev.id = id
        }
        deliver(ev)
      } catch {
        // a broken frame is ignored
      }
    }

    // Frames are named by event type, so listen for each known type as well as the default.
    if (source) {
      for (const type of EVENT_TYPES) source.addEventListener(type, (m) => onFrame(m as MessageEvent))
    }

    return () => {
      stopped = true
      source?.close()
      if (timer) clearTimeout(timer)
    }
  }, [project, qc])

  return { mode }
}

const EVENT_TYPES = [
  "run.queued", "run.started", "run.finished", "run.step.started", "run.step.finished", "task.started",
  "task.finished", "gate.opened", "gate.answered", "project.created", "project.changed", "settings.changed",
  "update.started", "update.installed", "update.failed", "update.rolledback", "deploy.finished", "run.held",
  "command",
]
