// The home page: every project on the server, with search, filters, the Add project menu and live status.
import { useCallback, useMemo, useEffect, useRef, useState } from "react"
import { Link, useNavigate } from "react-router"
import { toast } from "sonner"

import { Icon } from "@/components/Icon"
import { ErrorState } from "@/components/ErrorState"
import { Skeleton } from "@/components/ui/skeleton"
import { AddProjectMenu } from "@/features/projects/AddProjectMenu"
import { ProjectRowCard } from "@/features/projects/ProjectRowCard"
import { ProjectsFilters } from "@/features/projects/ProjectsFilters"
import { RemoveDialog } from "@/features/projects/RemoveDialogs"
import { ownersOf } from "@/features/projects/rows"
import { apiParams, useProjectQuery, withKnownOwner } from "@/features/projects/useProjectQuery"
import { useLiveEvents } from "@/lib/live"
import { useProjects, useProjectSearch, useRefreshProjects, useRemoveProject } from "@/lib/queries"
import type { ProjectRow } from "@/lib/types"

const FADE_MS = 220

/** The Projects page. */
export default function ProjectsPage() {
  const { query: asked, update, clear } = useProjectQuery()
  const all = useProjects()
  const owners = useMemo(() => ownersOf(all.data ?? []), [all.data])
  const query = all.data ? withKnownOwner(asked, owners) : asked
  const found = useProjectSearch(apiParams(query))
  const remove = useRemoveProject()
  const refresh = useRefreshProjects()
  const navigate = useNavigate()
  const search = useRef<HTMLInputElement>(null)
  const [asking, setAsking] = useState<string | null>(null)
  const [gone, setGone] = useState<string[]>([])
  // Live: project.*, run.*, task.* and gate.* events refresh the list; it also polls every 10 s.
  useLiveEvents()

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName
      if (e.key !== "/" || tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || e.ctrlKey || e.metaKey) return
      e.preventDefault()
      search.current?.focus()
    }
    document.addEventListener("keydown", onKey)
    return () => document.removeEventListener("keydown", onKey)
  }, [])

  const confirmRemove = (name: string) => {
    setAsking(null)
    remove.mutate(name, {
      onSuccess: () => {
        setGone((g) => [...g, name])
        setTimeout(() => { refresh(); setGone((g) => g.filter((n) => n !== name)) }, FADE_MS)
        toast.success(`${name} removed from Phoenix`, {
          description: "Bring it back any time with Import.",
          action: { label: "Import", onClick: () => navigate("/import") },
        })
      },
      onError: (err) => toast.error(err.message),
    })
  }

  // Stable callbacks (they take the project name) so the memoised rows only re-render when their row changes.
  const askRemove = useCallback((name: string) => setAsking(name), [])
  const card = (row: ProjectRow) => (
    <ProjectRowCard key={row.name} row={row} gone={gone.includes(row.name)} onRemove={askRemove} />
  )

  const body = () => {
    if (!all.data || !found.data) {
      const error = all.error ?? found.error
      if (error) return <ErrorState error={error} onRetry={() => { void all.refetch(); void found.refetch() }} />
      return (
        <div className="plist" aria-label="Loading projects">
          {[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-20 w-full" />)}
        </div>
      )
    }
    const { top, rest, total } = found.data
    const totalAll = all.data.length
    if (totalAll === 0) {
      return (
        <div className="empty">
          <span className="ec"><Icon name="folder-open" /></span>
          <b className="h3">No projects yet</b>
          <p className="small">Create your first project to get started.</p>
          <Link className="btn btn-primary" to="/new"><Icon name="plus" />Create new project</Link>
        </div>
      )
    }
    const countText = total === totalAll ? `${total} project${total === 1 ? "" : "s"}` : `${total} of ${totalAll} projects`
    return (
      <>
        <ProjectsFilters ref={search} query={query} countText={countText} onChange={update} />
        {total === 0 ? (
          <div className="empty">
            <span className="ec"><Icon name="magnifying-glass" /></span>
            <b className="h3">No projects match</b>
            <p className="small">Try another word or clear the filters.</p>
            <button type="button" className="btn btn-secondary" onClick={clear}>Clear filters</button>
          </div>
        ) : (
          <div className="plist">{[...top, ...rest].map(card)}</div>
        )}
      </>
    )
  }

  return (
    <main>
      <div className="title-row">
        <div><h1 className="h1">Projects</h1><p className="lead">Every project on this server.</p></div>
        <AddProjectMenu />
      </div>
      {body()}
      <RemoveDialog name={asking} onCancel={() => setAsking(null)} onConfirm={confirmRemove} />
    </main>
  )
}
