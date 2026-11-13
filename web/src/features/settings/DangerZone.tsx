/** The red "Danger zone" at the bottom of a project's Settings tab: Remove from Phoenix, and Delete project entirely. */
import { useState } from "react"
import { useNavigate } from "react-router"
import { toast } from "sonner"

import { ConfirmDialog } from "@/components/ConfirmDialog"
import { Icon } from "@/components/Icon"
import { Wheel } from "@/components/Indicator"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { formatBytes } from "@/lib/format"
import { useDeletePlan, useDeleteProject, useDeleteRepo, useProject, useRefreshProjects, useRemoveProject } from "@/lib/queries"
import type { DeleteLink, DeletePlan, DeleteResult, Project } from "@/lib/types"

export const PROTECTED_PROJECTS = ["phoenix9", "home"]

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`

/** The help line under Delete project entirely: says whether the GitHub repo goes (from project.json only). */
export function deleteHelp(project: Project | undefined): string {
  if (!project) return "Removes the folder, builds and keys; the next step says whether the GitHub repo goes."
  const repo = project.repo_owner ? `${project.repo_owner}/${project.repo_name}` : null
  if (!repo) return "Removes the folder, builds and keys."
  if (project.repo_made_by_phoenix) return `Removes the folder, builds, keys and the GitHub repo ${repo} (Phoenix made it).`
  return `Removes the folder, builds and keys. Your GitHub repo ${repo} is kept: Phoenix did not create it.`
}

/** The list of live deployments, each with its links. */
function StillLive({ items }: { items: DeleteLink[] }) {
  if (!items.length) return null
  return (
    <div data-testid="still-live">
      <b>Still live, take it down yourself:</b>
      <ul>
        {items.map((d) => (
          <li key={d.target}>
            {d.target}
            {d.links.map((l) => <span key={l}> · <a href={l} target="_blank" rel="noreferrer">{l}</a></span>)}
          </li>
        ))}
      </ul>
    </div>
  )
}

/** The dry run in plain words: everything that will go. */
function PlanView({ plan }: { plan: DeletePlan }) {
  return (
    <div className="stackg" aria-label="What will be deleted">
      <p>This cannot be undone. A safety copy is written to <code>{plan.safety_copy}</code> first, and kept for {plan.keep_days ?? 30} days.</p>
      <ul>
        <li>Folder <code>{plan.folder}</code> ({formatBytes(plan.size)})</li>
        <li>
          {plan.repo ? <>GitHub repo <code>{plan.repo}</code></> : "No GitHub repo"}
          {plan.repo && plan.repo_delete ? (
            <span className="help" data-testid="repo-verdict">
              {plan.repo_delete.delete ? " (will be deleted)" : ` (kept: ${plan.repo_delete.reason ?? plan.repo_delete.why})`}
            </span>
          ) : null}
        </li>
        <li>
          {plan.open_prs.length ? plural(plan.open_prs.length, "open merge request", "open merge requests") : "No open merge requests"}
          {plan.open_prs.map((p) => <span key={p.number}> · <a href={p.url} target="_blank" rel="noreferrer">#{p.number} {p.title}</a></span>)}
          {plan.open_prs_note ? <span className="help"> ({plan.open_prs_note})</span> : null}
        </li>
        <li>{plan.unpushed ? `${plural(plan.unpushed, "commit", "commits")} never pushed` : "No commits waiting to be pushed"}</li>
        {plan.unsaved_edits ? <li>{plural(plan.unsaved_edits, "unsaved edit", "unsaved edits")} (never committed; kept in the safety copy)</li> : null}
        <li>{plural(plan.runs.count, "Phoenix build", "Phoenix builds")} of history</li>
        <li>
          {plan.keys.length ? `Saved project keys: ${plan.keys.join(", ")}` : "No saved project keys"}
          {plan.keys_note ? <b data-testid="keys-note"> {plan.keys_note}</b> : null}
        </li>
        <li>The chat connection ({plan.chat.unit})</li>
      </ul>
      <StillLive items={plan.deployments} />
    </div>
  )
}

/** What happened: the safety copy, anything not done, and live deployments. */
function ResultView({ result, onRepo, retrying }: { result: DeleteResult; onRepo: () => void; retrying: boolean }) {
  const githubFailed = result.steps.some((s) => s.step === "GitHub repo" && !s.ok)
  return (
    <div className="stackg" aria-label="Result">
      <p>Safety copy: <code>{result.backup}</code></p>
      <ul>
        {result.steps.map((s) => <li key={s.step}>{s.kept ? "Kept" : s.ok ? "Done" : "Not done"}: {s.step}. {s.words}</li>)}
      </ul>
      {result.not_done.length > 0 && (
        <div role="alert">
          <b>Not done:</b>
          <ul>{result.not_done.map((n) => <li key={n.what}>{n.what}. {n.how}</li>)}</ul>
        </div>
      )}
      {githubFailed && (
        <button type="button" className="btn btn-secondary" disabled={retrying} onClick={onRepo}>
          {retrying ? <><Wheel />Deleting…</> : "Delete repo"}
        </button>
      )}
      <StillLive items={result.still_live ?? []} />
    </div>
  )
}

/** The Delete project entirely dialog: dry run, type the name, progress, result. */
function DeleteDialog({ name, onClose }: { name: string; onClose: (deleted: boolean) => void }) {
  const plan = useDeletePlan(name)
  const del = useDeleteProject()
  const repo = useDeleteRepo()
  const [typed, setTyped] = useState("")
  const [result, setResult] = useState<DeleteResult | null>(null)
  const refused = (plan.data?.refusals.length ?? 0) > 0
  const ready = !!plan.data && !refused && typed === name && !del.isPending

  const run = () => del.mutate({ name, confirm: typed }, { onSuccess: setResult })
  const retry = () => repo.mutate(name, {
    onSuccess: (r) => setResult((old) => old && {
      ...old,
      steps: old.steps.map((s) => (s.step === "GitHub repo" ? (r.steps[0] ?? s) : s)),
      not_done: r.not_done,
    }),
    onError: (err) => toast.error(err.message),
  })

  return (
    <Dialog open onOpenChange={(open) => { if (!open && !del.isPending) onClose(!!result) }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Delete {name} entirely</DialogTitle>
          <DialogDescription>Everything below goes. Live deployments are never touched.</DialogDescription>
        </DialogHeader>
        {result ? <ResultView result={result} onRepo={retry} retrying={repo.isPending} /> : (
          <>
            {plan.isPending && <p><Wheel />Working out what would go…</p>}
            {plan.error && <div className="blk-info" role="alert"><Icon name="warning-circle" /><span>{plan.error.message}</span></div>}
            {plan.data && <PlanView plan={plan.data} />}
            {refused && (
              <div className="blk-info" role="alert" aria-label="Refused">
                <Icon name="warning-circle" />
                <ul>{plan.data!.refusals.map((r) => <li key={r}>{r}</li>)}</ul>
              </div>
            )}
            {del.isPending && <p role="status"><Wheel />Deleting… making the safety copy, then removing each part. Please wait.</p>}
            {del.error && <div className="blk-info" role="alert"><Icon name="warning-circle" /><span>{del.error.message}</span></div>}
            {plan.data && !refused && (
              <div className="field">
                <label className="lbl" htmlFor="dz-confirm">Type {name} to confirm</label>
                <input className="input mono" id="dz-confirm" value={typed} autoComplete="off" disabled={del.isPending}
                  onChange={(e) => setTyped(e.target.value)} />
              </div>
            )}
          </>
        )}
        <DialogFooter>
          {result ? (
            <button type="button" className="btn btn-primary" onClick={() => onClose(true)}>Close</button>
          ) : (
            <>
              <button type="button" className="btn btn-ghost" disabled={del.isPending} onClick={() => onClose(false)}>Cancel</button>
              <button type="button" className="btn btn-destructive" disabled={!ready} onClick={run}>Delete project entirely</button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** The Danger zone section; hidden for phoenix9 and home. */
export function DangerZone({ name }: { name: string }) {
  const [asking, setAsking] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const remove = useRemoveProject()
  const refresh = useRefreshProjects()
  const navigate = useNavigate()
  const project = useProject(PROTECTED_PROJECTS.includes(name) ? "" : name)
  if (PROTECTED_PROJECTS.includes(name)) return null

  const confirmRemove = () => {
    setAsking(false)
    remove.mutate(name, {
      onSuccess: () => { refresh(); toast.success(`${name} removed from Phoenix`); navigate("/") },
      onError: (err) => toast.error(err.message),
    })
  }
  const closeDelete = (deleted: boolean) => {
    setDeleting(false)
    if (deleted) { refresh(); navigate("/") }
  }

  return (
    <div className="sect" id="sec-danger" role="region" aria-label="Danger zone" style={{ border: "1px solid var(--danger, #dc2626)", borderRadius: 8, padding: 16 }}>
      <div className="sect-h"><h2 className="h2" style={{ color: "var(--danger, #dc2626)" }}>Danger zone</h2></div>
      <div className="srow two">
        <span className="help">Remove from Phoenix keeps every file; Import brings it back.</span>
        <button type="button" className="btn btn-secondary" disabled={remove.isPending} onClick={() => setAsking(true)}>Remove from Phoenix</button>
      </div>
      <div className="srow two">
        <span className="help" data-testid="delete-help">{deleteHelp(project.data)} A safety copy is kept for 30 days.</span>
        <button type="button" className="btn btn-destructive" onClick={() => setDeleting(true)}>Delete project entirely…</button>
      </div>
      <ConfirmDialog open={asking} onOpenChange={setAsking} title={`Remove ${name} from Phoenix?`} confirmLabel="Remove"
        body="Phoenix stops listing it. Every file is kept, and Import brings it back." onConfirm={confirmRemove} />
      {deleting && <DeleteDialog name={name} onClose={closeDelete} />}
    </div>
  )
}
