import { useQuery } from "@tanstack/react-query"
import { useRef } from "react"
import { useSearchParams } from "react-router"

import { ErrorState } from "@/components/ErrorState"
import { Icon } from "@/components/Icon"
import { Wheel } from "@/components/Indicator"
import { api } from "@/lib/api"
import { useLiveEvents } from "@/lib/live"
import { keys, useBuilds } from "@/lib/queries"

import { LogFilters, type LogFilterValues } from "./LogFilters"
import { LogList } from "./LogList"
import { LogViewer } from "./LogViewer"

/** The Logs tab: filters, the matching entries, and the selected log as plain text. */
export function LogsTab({ name }: { name: string }) {
  const [params, setParams] = useSearchParams()
  const viewer = useRef<HTMLDivElement>(null)
  const list = useRef<HTMLDivElement>(null)
  useLiveEvents(name)

  const values: LogFilterValues = {
    run: params.get("run") ?? "",
    task: params.get("task") ?? "",
    step: params.get("step") ?? "",
    kinds: (params.get("kind") ?? "").split(",").filter(Boolean),
  }
  const id = params.get("log") ?? params.get("id") ?? ""

  function update(patch: Partial<LogFilterValues & { id: string; log: string }>) {
    const next = new URLSearchParams(params)
    for (const [k, v] of Object.entries(patch)) {
      const text = Array.isArray(v) ? v.join(",") : v
      if (text) next.set(k === "kinds" ? "kind" : k, text)
      else next.delete(k === "kinds" ? "kind" : k)
    }
    setParams(next, { replace: true })
  }

  const runs = useBuilds(name)
  // Task and step choices come from everything in the chosen run, whatever else is filtered.
  const scope = useQuery({
    queryKey: [...keys.logs(name), { run: values.run || undefined }],
    queryFn: () => api.logs({ project: name, run: values.run || undefined }),
  })
  const oneKind = values.kinds.length === 1 ? values.kinds[0] : undefined
  const filter = {
    run: values.run || undefined,
    task: values.task ? Number(values.task) : undefined,
    step: values.step || undefined,
    kind: oneKind,
  }
  const entries = useQuery({
    queryKey: [...keys.logs(name), filter],
    queryFn: () => api.logs({ project: name, ...filter }),
  })

  const shown = (entries.data ?? []).filter((e) => !values.kinds.length || values.kinds.includes(e.kind))
  const all = scope.data ?? []
  const tasks = [...new Set(all.flatMap((e) => (e.task === null ? [] : [e.task])))].sort((a, b) => a - b)
  const steps = [...new Set(all.flatMap((e) => (e.step ? [e.step] : [])))].sort()

  function select(next: string) {
    update({ log: next, id: "" })
    viewer.current?.scrollIntoView?.({ behavior: "smooth", block: "start" })
  }
  function refresh() {
    void entries.refetch()
    void scope.refetch()
  }

  return (
    <section data-project={name} className="stackg" aria-label="Logs">
      <LogFilters
        values={values} runs={runs.data ?? []} tasks={tasks} steps={steps}
        onChange={(p) => update(p)}
        onClear={() => update({ run: "", task: "", step: "", kinds: [] })}
      >
        <button type="button" className="btn btn-secondary btn-sm" onClick={refresh}>
          {entries.isFetching ? <Wheel /> : <Icon name="arrows-clockwise" />}
          {entries.isFetching ? "Refreshing" : "Refresh"}
        </button>
      </LogFilters>
      <div className="console">
        <div ref={list} className="min-w-0">
          {entries.error ? (
            <ErrorState error={entries.error} onRetry={refresh} />
          ) : !entries.data ? (
            <div className="lglist"><p className="loading help" style={{ padding: 16 }}>Loading logs…</p></div>
          ) : (
            <LogList entries={shown} selected={id} onSelect={select} />
          )}
        </div>
        <div ref={viewer} className="min-w-0">
          <LogViewer project={name} id={id} />
        </div>
      </div>
    </section>
  )
}
