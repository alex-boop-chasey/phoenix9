import { useQuery } from "@tanstack/react-query"
import { ChevronDown, RefreshCw } from "lucide-react"
import { useRef, useState } from "react"
import { useSearchParams } from "react-router"

import { ErrorState } from "@/components/ErrorState"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { api } from "@/lib/api"
import { useLiveEvents } from "@/lib/live"
import { keys, useBuilds } from "@/lib/queries"
import { cn } from "@/lib/utils"

import { LogFilters, type LogFilterValues } from "./LogFilters"
import { LogList } from "./LogList"
import { LogViewer } from "./LogViewer"

/** The Logs tab: filters, the matching entries, and the selected log as plain text. */
export function LogsTab({ name }: { name: string }) {
  const [params, setParams] = useSearchParams()
  const [open, setOpen] = useState(false)
  const viewer = useRef<HTMLDivElement>(null)
  const list = useRef<HTMLDivElement>(null)
  useLiveEvents(name)

  const values: LogFilterValues = {
    run: params.get("run") ?? "",
    task: params.get("task") ?? "",
    step: params.get("step") ?? "",
    kinds: (params.get("kind") ?? "").split(",").filter(Boolean),
  }
  const id = params.get("id") ?? ""

  function update(patch: Partial<LogFilterValues & { id: string }>) {
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
    update({ id: next })
    viewer.current?.scrollIntoView?.({ behavior: "smooth", block: "start" })
  }
  function refresh() {
    void entries.refetch()
    void scope.refetch()
  }

  return (
    <section data-project={name} className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Logs</h2>
        <Button variant="outline" size="sm" onClick={refresh}><RefreshCw /> Refresh</Button>
      </div>
      <div className="grid gap-4 lg:grid-cols-[16rem_20rem_minmax(0,1fr)]">
        <div>
          <Button variant="outline" size="sm" className="lg:hidden" aria-expanded={open} onClick={() => setOpen(!open)}>
            Filters <ChevronDown className={cn(open && "rotate-180")} />
          </Button>
          <div className={cn("mt-2 lg:mt-0 lg:block", open ? "block" : "hidden")}>
            <LogFilters
              values={values} runs={runs.data ?? []} tasks={tasks} steps={steps}
              onChange={(p) => update(p)}
              onClear={() => update({ run: "", task: "", step: "", kinds: [] })}
            />
          </div>
        </div>
        <div ref={list} className="min-w-0 lg:max-h-[70vh] lg:overflow-y-auto">
          {entries.error ? (
            <ErrorState error={entries.error} onRetry={refresh} />
          ) : !entries.data ? (
            <Skeleton className="h-32 w-full" />
          ) : (
            <LogList entries={shown} selected={id} onSelect={select} />
          )}
        </div>
        <div ref={viewer} className="min-w-0">
          {id && (
            <Button variant="ghost" size="sm" className="mb-2 lg:hidden" onClick={() => {
              list.current?.scrollIntoView?.({ behavior: "smooth", block: "start" })
            }}>
              Back to list
            </Button>
          )}
          <LogViewer project={name} id={id} />
        </div>
      </div>
    </section>
  )
}
