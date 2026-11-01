import { Link } from "react-router"

import { StatusBadge } from "@/components/StatusBadge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { NeedsYouCard } from "@/features/gates/NeedsYouCard"
import { ChatLink, RepoLink } from "@/features/projects/parts"
import { runText } from "@/features/projects/rows"
import { useBuilds, useChangelog, useGates, useProject } from "@/lib/queries"
import { useLiveEvents } from "@/lib/live"
import { DeployCard } from "@/features/deploy/DeployCard"
import { UpdatePanel } from "@/features/updates/UpdatePanel"

/** The Overview tab: open questions, about, current build and recent changes. */
export function OverviewTab({ name }: { name: string }) {
  useLiveEvents(name)
  const project = useProject(name)
  const gates = useGates(name)
  const builds = useBuilds(name)
  const changes = useChangelog(name, 10)
  const row = project.data
  const open = (gates.data ?? []).filter((g) => g.project === name && !g.answered)
  const run = row?.run ?? null
  const title = run ? builds.data?.find((b) => b.run_id === run.run_id)?.title : undefined
  const recent = [...(changes.data ?? [])].reverse()

  return (
    <div className="flex flex-col gap-4">
      {open.map((g) => (
        <NeedsYouCard key={g.id} gate={g} />
      ))}
      <Card>
        <CardHeader><CardTitle>About</CardTitle></CardHeader>
        <CardContent className="flex flex-col gap-2 text-sm">
          <p>{row?.description || <span className="text-muted-foreground">No description.</span>}</p>
          {row && (
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
              <span>Repo: <RepoLink row={row} /></span>
              <span>Chat: <ChatLink row={row} /></span>
              {row.vscode_url && (
                <Button asChild size="sm" variant="outline">
                  <a href={row.vscode_url} target="_blank" rel="noreferrer">Open in VS Code</a>
                </Button>
              )}
            </div>
          )}
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>Current build</CardTitle></CardHeader>
        <CardContent className="flex flex-col gap-2 text-sm">
          {row && run ? (
            <>
              {title && <p className="font-medium">{title}</p>}
              <div className="flex flex-wrap items-center gap-2">
                <span>{runText(row)}</span>
                <StatusBadge status={run.status} />
              </div>
              <Link to={`/p/${encodeURIComponent(name)}/build`} className="text-primary underline-offset-4 hover:underline">
                Open the Build tab
              </Link>
            </>
          ) : (
            <p className="text-muted-foreground">No build running.</p>
          )}
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>Recent changes</CardTitle></CardHeader>
        <CardContent>
          {recent.length === 0 ? (
            <p className="text-sm text-muted-foreground">No changes recorded yet.</p>
          ) : (
            <ul className="flex flex-col gap-2 text-sm">
              {recent.map((c, i) => (
                <li key={i} className="flex flex-wrap gap-x-2">
                  <span className="text-muted-foreground">{[c.date, c.who].filter(Boolean).join(" · ")}</span>
                  <span>{c.text}</span>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
      <DeployCard name={name} />
      {name === "phoenix9" && <UpdatePanel />}
    </div>
  )
}
