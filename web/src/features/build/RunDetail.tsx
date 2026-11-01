import { Link } from "react-router"

import { ErrorState } from "@/components/ErrorState"
import { RelativeTime } from "@/components/RelativeTime"
import { StatusBadge } from "@/components/StatusBadge"
import { Skeleton } from "@/components/ui/skeleton"
import { NeedsYouCard } from "@/features/gates/NeedsYouCard"
import { useBuilds, useRun } from "@/lib/queries"

import { resultText } from "./parts"
import { StepList, gatesShownInSteps } from "./StepList"

/** One build: its result, any open questions, the read-only step list and a link to its logs. */
export function RunDetail({ name, runId }: { name: string; runId: string }) {
  const run = useRun(name, runId)
  const builds = useBuilds(name)
  const base = `/p/${encodeURIComponent(name)}`
  const back = <Link to={`${base}/build`} className="text-sm text-primary hover:underline">← All builds</Link>

  if (run.error) return <div className="flex flex-col gap-3">{back}<ErrorState error={run.error} onRetry={() => void run.refetch()} /></div>
  const d = run.data
  if (!d) return <div className="flex flex-col gap-3">{back}<Skeleton className="h-24 w-full" /></div>

  const row = builds.data?.find((b) => b.run_id === runId)
  const tasks = Object.values(d.tasks)
  const failed = tasks.filter((t) => t.status === "failed").length
  const result = resultText(d.status, tasks.length, failed, d.current?.task)
  const cost = row?.cost || (d.usage.cost_usd != null ? `$${d.usage.cost_usd.toFixed(2)}` : "-")
  const inSteps = gatesShownInSteps(d)
  const others = d.gates.filter((g) => !g.answered && !inSteps.has(g.id))

  return (
    <div className="flex flex-col gap-4">
      {back}
      <header className="flex flex-col gap-1">
        <h2 className="text-xl font-semibold">{d.title || d.run_id}</h2>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
          <span>Preset: {d.preset}</span>
          <span className="inline-flex items-center gap-2"><StatusBadge status={d.status} />{result}</span>
          <span>Started: <RelativeTime iso={row?.started || d.created} /></span>
          <span>Duration: {row?.duration || "-"}</span>
          <span>Cost: {cost}</span>
        </div>
      </header>
      {others.map((g) => <NeedsYouCard key={g.id} gate={g} />)}
      <StepList run={d} />
      <Link to={`${base}/logs?run=${encodeURIComponent(runId)}`} className="text-primary hover:underline">
        See this build's logs
      </Link>
    </div>
  )
}
