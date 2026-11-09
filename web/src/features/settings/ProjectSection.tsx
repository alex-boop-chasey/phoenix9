// The Project half of the Settings tab: description, repo, services and the project keys.
import { useEffect, useState } from "react"
import { toast } from "sonner"

import { ConfirmDialog } from "@/components/ConfirmDialog"
import { Icon } from "@/components/Icon"
import { Wheel } from "@/components/Indicator"
import { KeysForm } from "@/features/keys/KeysForm"
import { SERVICE_ICON } from "@/features/projects/OrderSheet"
import { emptyForm, type FormValues } from "@/features/projects/formModel"
import { sameValue } from "@/features/settings/dotted"
import { useEditProject, useLibraryServices, useProject } from "@/lib/queries"
import type { EditBody, Project, SetUpService } from "@/lib/types"

const fromProject = (p: Project): FormValues => ({
  ...emptyForm, name: p.name, description: p.description, repo: p.repo, profile: p.profile, services: p.services,
})

/** The edit body with only the fields that differ from the saved project. */
export function changedFields(p: Project, v: FormValues): EditBody {
  const body: EditBody = {}
  if (v.description !== p.description) body.description = v.description
  if (v.repo.trim() !== p.repo) body.repo = v.repo.trim()
  if (!sameValue([...v.services].sort(), [...p.services].sort())) body.services = v.services
  return body
}

/** A row of the settings page: a label on the left, the control on the right. */
export function SettingsRow({ id, keys, label, labelFor, two = true, children }: {
  id?: string; keys?: string[]; label: string; labelFor?: string; two?: boolean; children: React.ReactNode
}) {
  return (
    <div className={two ? "srow two" : "srow"} id={id} data-settings={keys?.join(" ")}>
      {labelFor ? <label className="lbl" htmlFor={labelFor}>{label}</label> : <span className="lbl">{label}</span>}
      {children}
    </div>
  )
}

/** "Supabase · 31 October · by the “Setup wizard” build" per service; just the name when nothing more is known. */
export function setUpLine(done: SetUpService[], titleOf: (n: string) => string): string {
  if (!done.length) return "nothing yet"
  return done.map((e) => {
    const day = e.at && !Number.isNaN(Date.parse(e.at)) ? new Date(e.at).toLocaleDateString("en-GB", { day: "numeric", month: "long" }) : ""
    return [titleOf(e.name), day, e.run_name ? `by the “${e.run_name}” build` : ""].filter(Boolean).join(" · ")
  }).join(", ")
}

/** The sticky "Unsaved changes" bar with Discard and Save. */
export function SaveBar({ label, busy, onDiscard, onSave }: { label: string; busy: boolean; onDiscard: () => void; onSave: () => void }) {
  return (
    <div className="savebar" role="region" aria-label="Unsaved changes">
      <span className="unsaved"><i />Unsaved changes</span>
      <button type="button" className="btn btn-ghost" onClick={onDiscard}>Discard</button>
      <button type="button" className="btn btn-primary" disabled={busy} onClick={onSave}>
        {busy ? <><Wheel />Saving…</> : label}
      </button>
    </div>
  )
}

/** Project fields, then the project keys; edits wait for the Save bar. */
export function ProjectSection({ name }: { name: string }) {
  const project = useProject(name)
  const edit = useEditProject(name)
  const library = useLibraryServices()
  const [value, setValue] = useState<FormValues | null>(null)
  const [asking, setAsking] = useState(false)
  const [error, setError] = useState("")
  const [open, setOpen] = useState<"repo" | "services" | null>(null)

  useEffect(() => {
    if (project.data && !value) setValue(fromProject(project.data))
  }, [project.data, value])

  if (!project.data || !value) return null
  const saved = project.data
  const set = (patch: Partial<FormValues>) => setValue({ ...value, ...patch })
  const toggle = (which: "repo" | "services") => setOpen(open === which ? null : which)
  const body = changedFields(saved, value)
  const dirty = Object.keys(body).length > 0
  const risky = body.repo !== undefined

  function save(confirm: boolean) {
    setError("")
    edit.mutate(confirm ? { ...body, confirm: true } : body, {
      onSuccess: (fresh) => { setValue(fromProject(fresh)); setOpen(null); toast.success("Project saved") },
      onError: (err) => setError(err.message),
    })
  }

  const serviceList = library.data?.services ?? []
  const titleOf = (n: string) => serviceList.find((s) => s.name === n)?.title ?? n

  return (
    <div className="sect" id="sec-project">
      <div className="sect-h">
        <h2 className="h2">Project</h2>
        <span className="area"><Icon name="sliders-horizontal" />Setup</span>
      </div>
      <SettingsRow keys={["name"]} label="Name" labelFor="st-name">
        <input className="input mono" id="st-name" value={value.name} readOnly />
      </SettingsRow>
      <SettingsRow keys={["description"]} label="Description" labelFor="st-desc">
        <div className="field">
          <textarea className="textarea" id="st-desc" value={value.description} onChange={(e) => set({ description: e.target.value })} />
          <span className="help">A few lines. They go into the project's CLAUDE.md.</span>
        </div>
      </SettingsRow>

      <SettingsRow keys={["repo"]} id="s-repo" label="GitHub repo">
        <div>
          <div className="swap">
            <span className="ico"><Icon name="github-logo" /></span>
            <span className="t"><b className="mono">{value.repo || "No repo yet"}</b><span>{value.repo ? "Code is kept here" : "Add one to push the code"}</span></span>
            <button type="button" className="btn btn-secondary btn-sm" aria-expanded={open === "repo"} onClick={() => toggle("repo")}>Change</button>
          </div>
          {open === "repo" && (
            <div className="swap-panel">
              <input className="input mono" aria-label="GitHub repo" placeholder="owner/name" value={value.repo} autoComplete="off"
                onChange={(e) => set({ repo: e.target.value })} />
            </div>
          )}
        </div>
      </SettingsRow>

      <SettingsRow keys={["services"]} id="s-svc" label="Services">
        <div>
          <div className="swap">
            <div className="chips" style={{ flex: 1 }}>
              {value.services.length === 0 && <span className="help">None chosen</span>}
              {value.services.map((n) => (
                <span key={n} className="chip"><Icon name={SERVICE_ICON[n] ?? "plugs"} />{titleOf(n)}</span>
              ))}
            </div>
            <button type="button" className="btn btn-secondary btn-sm" aria-expanded={open === "services"} onClick={() => toggle("services")}>Change</button>
            <div className="sofar">
              <Icon name="check-circle" size="sm" className="text-ok" />
              Set up so far: {setUpLine(project.data.setup?.services_set_up ?? [], titleOf)}
            </div>
          </div>
          {open === "services" && (
            <div className="swap-panel" role="group" aria-label="Services">
              {serviceList.map((s) => {
                const on = value.services.includes(s.name)
                return (
                  <button key={s.name} type="button" className="mini" aria-pressed={on} aria-selected={on}
                    onClick={() => set({ services: on ? value.services.filter((x) => x !== s.name) : [...value.services, s.name] })}>
                    <span className="ico"><Icon name={SERVICE_ICON[s.name] ?? "plugs"} /></span>
                    <span className="t"><b>{s.title}</b></span>
                    <Icon name="check" className="tick" />
                  </button>
                )
              })}
            </div>
          )}
        </div>
      </SettingsRow>

      <SettingsRow id="s-keys" label="Project keys" two={false}>
        <span className="help">Changes are picked up by the next build.</span>
        <KeysForm mode="saved" project={name} />
      </SettingsRow>

      {error && <div className="blk-info" role="alert"><Icon name="warning-circle" /><span>{error}</span></div>}
      {dirty && (
        <SaveBar
          label="Save project" busy={edit.isPending}
          onDiscard={() => { setValue(fromProject(saved)); setOpen(null); setError("") }}
          onSave={() => (risky ? setAsking(true) : save(false))}
        />
      )}
      <ConfirmDialog
        open={asking} onOpenChange={setAsking} title="Change the repo?"
        body="Change the repo? The next build uses the new one."
        confirmLabel="Change it" onConfirm={() => save(true)}
      />
    </div>
  )
}
