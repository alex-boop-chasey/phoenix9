import { useSearchParams } from "react-router"

import { ErrorState } from "@/components/ErrorState"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"
import { useLiveEvents } from "@/lib/live"
import { useBuilds } from "@/lib/queries"

import { BuildList } from "./BuildList"
import { RunDetail } from "./RunDetail"

/** The Build tab: previous builds, or one build's step list when `run` is in the address. */
export function BuildTab({ name }: { name: string }) {
  const [params] = useSearchParams()
  const builds = useBuilds(name)
  useLiveEvents(name)
  const runId = params.get("run")
  if (runId) return <RunDetail name={name} runId={runId} />

  return (
    <section className="flex flex-col gap-4" data-project={name}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-semibold">Builds</h2>
        <TooltipProvider>
          <Tooltip>
            <TooltipTrigger asChild>
              <span tabIndex={0}>
                <Button disabled>Start new build</Button>
              </span>
            </TooltipTrigger>
            <TooltipContent>The build wizard is coming next.</TooltipContent>
          </Tooltip>
        </TooltipProvider>
      </div>
      {builds.error ? (
        <ErrorState error={builds.error} onRetry={() => void builds.refetch()} />
      ) : builds.data ? (
        <BuildList name={name} rows={builds.data} />
      ) : (
        <Skeleton className="h-24 w-full" />
      )}
    </section>
  )
}
