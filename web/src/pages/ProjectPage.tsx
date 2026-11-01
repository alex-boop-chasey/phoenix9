import { SearchX } from "lucide-react"
import { Link, Navigate, useNavigate, useParams } from "react-router"

import { EmptyState } from "@/components/EmptyState"
import { ErrorState } from "@/components/ErrorState"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { BuildTab } from "@/features/build/BuildTab"
import { LogsTab } from "@/features/logs/LogsTab"
import { OverviewTab } from "@/features/overview/OverviewTab"
import { SettingsTab } from "@/features/settings/SettingsTab"
import { ApiError } from "@/lib/api"
import { useProject } from "@/lib/queries"

const TABS = ["overview", "build", "logs", "settings"] as const

const linkClass = "text-primary underline-offset-4 hover:underline"

/** A project's page: header with links, and the Overview, Build, Logs and Settings tabs. */
export default function ProjectPage() {
  const { name = "", tab } = useParams()
  const navigate = useNavigate()
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
    <main className="flex flex-col gap-4">
      <div className="min-w-0">
        <h1 className="truncate text-2xl font-semibold">{row.name}</h1>
        {row.description && <p className="truncate text-sm text-muted-foreground">{row.description}</p>}
        <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-sm">
          {row.repo_url && <a href={row.repo_url} target="_blank" rel="noreferrer" className={linkClass}>Repo</a>}
          {row.chat.url && <a href={row.chat.url} target="_blank" rel="noreferrer" className={linkClass}>Chat</a>}
          {row.vscode_url && (
            <a href={row.vscode_url} target="_blank" rel="noreferrer" className={linkClass}>Open in VS Code</a>
          )}
        </div>
      </div>
      <Tabs value={tab} onValueChange={(t) => navigate(`/p/${encodeURIComponent(name)}/${t}`)}>
        <div className="max-w-full overflow-x-auto">
          <TabsList>
            {TABS.map((t) => (
              <TabsTrigger key={t} value={t} className="capitalize">{t}</TabsTrigger>
            ))}
          </TabsList>
        </div>
        <TabsContent value="overview"><OverviewTab name={name} /></TabsContent>
        <TabsContent value="build"><BuildTab name={name} /></TabsContent>
        <TabsContent value="logs"><LogsTab name={name} /></TabsContent>
        <TabsContent value="settings"><SettingsTab name={name} /></TabsContent>
      </Tabs>
    </main>
  )
}
