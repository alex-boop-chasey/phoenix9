// The home page: every project on the server, with search, an owner filter and live status.
import { FolderOpen } from "lucide-react"
import { useMemo } from "react"
import { Link, useSearchParams } from "react-router"

import { EmptyState } from "@/components/EmptyState"
import { ErrorState } from "@/components/ErrorState"
import { PageHeader } from "@/components/PageHeader"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { ProjectCards } from "@/features/projects/ProjectCards"
import { ProjectsFilters } from "@/features/projects/ProjectsFilters"
import { ProjectsTable } from "@/features/projects/ProjectsTable"
import { ALL_OWNERS, filterRows, ownersOf, sortRows } from "@/features/projects/rows"
import { useIsDesktop } from "@/features/projects/useIsDesktop"
import { useLiveEvents } from "@/lib/live"
import { useProjects } from "@/lib/queries"

function CreateButton() {
  return (
    <Button asChild>
      <Link to="/new">Create new project</Link>
    </Button>
  )
}

/** The Projects page. */
export default function ProjectsPage() {
  const query = useProjects()
  const desktop = useIsDesktop()
  const [params, setParams] = useSearchParams()
  // Live: project.*, run.*, task.* and gate.* events refresh the list (see invalidateForEvent); it also polls every 10 s.
  useLiveEvents()

  const q = params.get("q") ?? ""
  const owner = params.get("owner") ?? ALL_OWNERS
  const setFilter = (key: "q" | "owner", value: string) => {
    const next = new URLSearchParams(params)
    if (value === "" || (key === "owner" && value === ALL_OWNERS)) next.delete(key)
    else next.set(key, value)
    setParams(next, { replace: true })
  }

  const all = useMemo(() => sortRows(query.data ?? []), [query.data])
  const owners = useMemo(() => ownersOf(all), [all])
  const shown = useMemo(() => filterRows(all, q, owner), [all, q, owner])

  return (
    <main>
      <PageHeader title="Projects" description="Every project on this server." actions={<CreateButton />} />
      {query.isPending ? (
        <div className="flex flex-col gap-2" aria-label="Loading projects">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-14 w-full" />
          ))}
        </div>
      ) : query.isError ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : all.length === 0 ? (
        <EmptyState icon={FolderOpen} title="No projects yet" line="Create your first project to get started." action={<CreateButton />} />
      ) : (
        <div className="flex flex-col gap-3">
          <ProjectsFilters
            q={q} owner={owner} owners={owners}
            onQ={(v) => setFilter("q", v)} onOwner={(v) => setFilter("owner", v)}
          />
          <p className="text-sm text-muted-foreground">
            {shown.length} of {all.length} projects
          </p>
          {shown.length === 0 ? (
            <EmptyState
              icon={FolderOpen}
              title="No projects match"
              action={
                <Button variant="outline" onClick={() => setParams({}, { replace: true })}>
                  Clear filters
                </Button>
              }
            />
          ) : desktop ? (
            <ProjectsTable rows={shown} />
          ) : (
            <ProjectCards rows={shown} />
          )}
        </div>
      )}
    </main>
  )
}
