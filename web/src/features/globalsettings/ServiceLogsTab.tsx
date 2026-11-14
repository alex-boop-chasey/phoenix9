// Phoenix settings > Logs: Phoenix's own logs (the API log and the updater log), each opening as plain text.
import { useQuery } from "@tanstack/react-query"
import { useRef } from "react"
import { useSearchParams } from "react-router"

import { ErrorState } from "@/components/ErrorState"
import { LogList } from "@/features/logs/LogList"
import { LogViewer } from "@/features/logs/LogViewer"
import { api } from "@/lib/api"

/** The Logs section of Phoenix settings: Phoenix's own logs with size and last change; pick one to read it. */
export function ServiceLogsTab() {
  const [params, setParams] = useSearchParams()
  const viewer = useRef<HTMLDivElement>(null)
  const list = useQuery({ queryKey: ["service-logs"], queryFn: api.serviceLogs })
  const id = params.get("log") ?? ""

  function select(next: string) {
    const p = new URLSearchParams(params)
    p.set("log", next)
    setParams(p, { replace: true })
    viewer.current?.scrollIntoView?.({ behavior: "smooth", block: "start" })
  }

  return (
    <section className="stackg" aria-label="Phoenix logs">
      <p className="help">Phoenix's own logs: what the dashboard's server and the updater did.</p>
      <div className="console">
        <div className="min-w-0">
          {list.error ? (
            <ErrorState error={list.error} onRetry={() => void list.refetch()} />
          ) : !list.data ? (
            <div className="lglist"><p className="loading help" style={{ padding: 16 }}>Loading logs…</p></div>
          ) : (
            <LogList
              entries={list.data} selected={id} onSelect={select} label="Phoenix logs"
              empty="No logs yet. Phoenix writes them as it works."
            />
          )}
        </div>
        <div ref={viewer} className="min-w-0">
          <LogViewer project="" id={id} service />
        </div>
      </div>
    </section>
  )
}
