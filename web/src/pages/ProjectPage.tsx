import { SearchX } from "lucide-react"
import { Link, Navigate, useParams } from "react-router"

import { EmptyState } from "@/components/EmptyState"
import { ErrorState } from "@/components/ErrorState"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { BuildTab } from "@/features/build/BuildTab"
import { LogsTab } from "@/features/logs/LogsTab"
import { OverviewTab } from "@/features/overview/OverviewTab"
import { SettingsTab } from "@/features/settings/SettingsTab"
import { ApiError } from "@/lib/api"
import { useProject } from "@/lib/queries"

import { ProjectHeader, TABS } from "./ProjectHeader"

/** A project's page: header with links, and the Overview, Build, Logs and Settings tabs. */
export default function ProjectPage() {
  const { name = "", tab } = useParams()
  const project = useProject(name)

  if (!tab || !(TABS as readonly string[]).includes(tab)) {
    return <Navigate to={`/p/${name}/overview`} replace />
  }
  const err = project.error
  if (err instanceof ApiError && err.status === 404) {
    return (
      <EmptyState
        icon={SearchX}
        title={`No project called ${name}`}
        action={<Button asChild variant="outline"><Link to="/">Back to projects</Link></Button>}
      />
    )
  }
  if (err) return <ErrorState error={err} onRetry={() => void project.refetch()} />
  const row = project.data
  if (!row) return <Skeleton className="h-16 w-full" />

  return (
    <main className="flex flex-col">
      <ProjectHeader row={row} />
      {tab === "overview" && <OverviewTab name={name} />}
      {tab === "build" && <BuildTab name={name} />}
      {tab === "logs" && <LogsTab name={name} />}
      {tab === "settings" && <SettingsTab name={name} />}
    </main>
  )
}
