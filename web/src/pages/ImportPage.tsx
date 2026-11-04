// The Import page: bring back a removed project, import a folder Phoenix doesn't list, or type a folder path.
import { useState } from "react"
import { toast } from "sonner"

import { ErrorState } from "@/components/ErrorState"
import { Icon } from "@/components/Icon"
import { Wheel } from "@/components/Indicator"
import { FolderPicker } from "@/features/projects/FolderPicker"
import { Skeleton } from "@/components/ui/skeleton"
import { useImportCandidates, useImportProject, useRefreshProjects } from "@/lib/queries"
import type { ImportCandidate } from "@/lib/types"

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]

function removedOn(iso: string | null): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso ?? "")
  return m ? `removed on ${Number(m[3])} ${MONTHS[Number(m[2]) - 1]}` : "removed earlier"
}

function CandidateCard({ c, busy, onImport }: { c: ImportCandidate; busy: boolean; onImport: () => void }) {
  const second = `${c.repo ?? "No repo"} · ${c.kind === "removed" ? removedOn(c.removed_on) : "not in Phoenix yet"}`
  return (
    <div className="card card-dashed" data-candidate={c.name}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <b className="mono" style={{ fontSize: 15 }}>{c.name}</b>
        <button type="button" className="btn btn-secondary btn-sm" disabled={busy} onClick={onImport}>
          {busy ? <><Wheel />Importing</> : <><Icon name="download-simple" />Import</>}
        </button>
      </div>
      <p className="small mono">{c.path}</p>
      <p className="small">{second}</p>
    </div>
  )
}

/** The Import page. */
export default function ImportPage() {
  const list = useImportCandidates()
  const importer = useImportProject()
  const refresh = useRefreshProjects()
  const [busy, setBusy] = useState<string | null>(null)
  const [path, setPath] = useState("")
  const [choosing, setChoosing] = useState(false)

  const run = (target: string, after?: () => void) => {
    setBusy(target)
    importer.mutate(target, {
      onSuccess: (r) => { toast.success(`${r.name} imported`); refresh(); after?.() },
      onError: (err) => toast.error(err.message),
      onSettled: () => setBusy(null),
    })
  }

  const section = (title: string, items: ImportCandidate[]) => (
    <>
      <h2 className="h3">{title} ({items.length})</h2>
      {items.length === 0 ? <p className="small">Nothing here.</p> : (
        <div className="g2">
          {items.map((c) => <CandidateCard key={c.path} c={c} busy={busy === c.name} onImport={() => run(c.name)} />)}
        </div>
      )}
    </>
  )

  const body = () => {
    if (list.isPending) return <Skeleton className="h-24 w-full" aria-label="Loading" />
    if (list.isError) return <ErrorState error={list.error} onRetry={() => void list.refetch()} />
    return (
      <>
        {section("Removed earlier", list.data.filter((c) => c.kind === "removed"))}
        {section("Not in Phoenix yet", list.data.filter((c) => c.kind === "folder"))}
      </>
    )
  }

  return (
    <main>
      <div className="title-row">
        <div><h1 className="h1">Import a project</h1><p className="lead">Bring back a removed project, or a folder Phoenix doesn't list yet.</p></div>
      </div>
      <div className="stackg">
        {body()}
        <form
          className="card" style={{ marginTop: 8 }}
          onSubmit={(e) => { e.preventDefault(); if (path.trim()) run(path.trim(), () => setPath("")) }}
        >
          <h2 className="h3" style={{ marginBottom: 10 }}>Or pick a folder yourself</h2>
          <div className="row">
            <div className="field" style={{ flex: "1 1 260px" }}>
              <label htmlFor="impPath">Folder</label>
              <input className="input mono" id="impPath" placeholder="/srv/projects/…" value={path} onChange={(e) => setPath(e.target.value)} />
            </div>
            <button type="button" className="btn btn-secondary" style={{ alignSelf: "flex-end" }} onClick={() => setChoosing(true)}>
              <Icon name="folder-open" />Choose a folder
            </button>
            <button type="submit" className="btn btn-primary" style={{ alignSelf: "flex-end" }} disabled={!path.trim() || busy !== null}>
              <Icon name="download-simple" />Import
            </button>
          </div>
        </form>
        <FolderPicker open={choosing} start={path.trim()} onClose={() => setChoosing(false)} onPick={(p) => { setPath(p); setChoosing(false) }} />
      </div>
    </main>
  )
}
