// New project: the order sheet on the left, the receipt "What Phoenix will make" on the right.
import { useCallback, useEffect, useRef, useState } from "react"
import { useNavigate } from "react-router"
import { toast } from "sonner"

import { Icon } from "@/components/Icon"
import { CreateProgress } from "@/features/projects/CreateProgress"
import { OrderSheet } from "@/features/projects/OrderSheet"
import { emptyForm, newRepoApplies, sourceComplete, toCreateForm, type FormValues } from "@/features/projects/formModel"
import { useCreateProject, useGithubRepos, useJob, useLibraryProfiles, useLibraryTemplates } from "@/lib/queries"
import type { RowsSummary } from "@/features/keys/KeysForm"
import type { KeyInput } from "@/lib/types"

interface Missing {
  text: string
  target: string
  focus: string
}

/** What is still missing before Create can run (the first one is shown as a link). */
function missingOf(v: FormValues, nameOk: boolean, pending: boolean): Missing[] {
  const out: Missing[] = []
  if (!nameOk) out.push({ text: "Choose a name that is free.", target: "np-step-name", focus: "pf-name" })
  if (!sourceComplete(v)) {
    const what = v.source === "repo" ? "Choose the GitHub repo." : v.source === "template" ? "Choose a template." : "Type the folder path."
    out.push({ text: what, target: "np-step-source", focus: v.source === "code" ? "pf-path" : "" })
  }
  if (pending) out.push({ text: "Press Save under Project keys before creating.", target: "np-step-keys", focus: "" })
  return out
}

function jump(m: Missing) {
  const step = document.getElementById(m.target)
  step?.scrollIntoView({ behavior: "smooth", block: "center" })
  const field = m.focus ? document.getElementById(m.focus) : step?.querySelector<HTMLElement>("input, button")
  field?.focus({ preventScroll: true })
}

function Receipt({ v, summary, github }: { v: FormValues; summary: RowsSummary; github: boolean }) {
  const templates = useLibraryTemplates()
  const profiles = useLibraryProfiles()
  const code =
    v.source === "empty" ? "A blank folder"
      : v.source === "repo" ? (v.repo ? `Copy of ${v.repo}` : "Copy of a GitHub repo")
        : v.source === "template" ? `${templates.data?.find((t) => t.name === v.template)?.title ?? (v.template || "A template")} template`
          : (v.path ? `Code in ${v.path}` : "Code already on this server")
  const kind = v.profile ? (profiles.data?.profiles.find((p) => p.name === v.profile)?.title ?? v.profile) : "Worked out later"
  const newRepo = github && newRepoApplies(v.source) && v.newRepo
  const { total, needValue } = summary
  return (
    <dl>
      <dt>Folder</dt><dd className="mono">{v.name ? `/srv/projects/${v.name}` : "—"}</dd>
      <dt>Code</dt><dd>{code}</dd>
      <dt>Kind</dt><dd>{kind}</dd>
      <dt>Repo</dt>
      <dd className="mono">{newRepo ? `${v.owner}/${v.name || "…"} (new)` : v.source === "repo" && v.repo ? v.repo : "none"}</dd>
      <dt>Services</dt><dd>{v.services.length ? v.services.join(", ") : "none"}</dd>
      <dt>Keys</dt>
      <dd>{total === 0 ? "none" : `${total} ${total === 1 ? "row" : "rows"}${needValue ? ` (${needValue} need a value)` : ""}`}</dd>
    </dl>
  )
}

/** The New project page. */
export default function NewProjectPage() {
  const [values, setValues] = useState<FormValues>(emptyForm)
  const [nameOk, setNameOk] = useState(false)
  const [keyRows, setKeyRows] = useState<KeyInput[]>([])
  const [pending, setPending] = useState(false)
  const [summary, setSummary] = useState<RowsSummary>({ total: 0, needValue: 0 })
  const [jobId, setJobId] = useState("")
  const [error, setError] = useState("")
  const create = useCreateProject()
  const github = useGithubRepos()
  const job = useJob(jobId)
  const toasted = useRef("")
  const navigate = useNavigate()

  const onRows = useCallback((rows: KeyInput[], p: boolean, s: RowsSummary) => { setKeyRows(rows); setPending(p); setSummary(s) }, [])

  const j = job.data
  const started = !!jobId
  const done = started && j?.status === "done"
  const failed = started && j?.status === "failed"
  const name = j?.project || values.name

  useEffect(() => {
    if (done && toasted.current !== jobId) {
      toasted.current = jobId
      toast.success(`Project ${name} created`, { description: "Start the first build when you are ready." })
      void navigate(`/p/${encodeURIComponent(name)}/overview`, { replace: true })
    }
  }, [done, jobId, name, navigate])

  const missing = missingOf(values, nameOk, pending)
  const ready = missing.length === 0 && !create.isPending && !started

  function submit() {
    setError("")
    create.mutate(toCreateForm(values, keyRows, !!github.data?.connected), {
      onSuccess: (r) => setJobId(r.job),
      onError: (e) => setError(e.message),
    })
  }

  const creating = started && !failed
  return (
    <>
      {creating && (
      <main>
        <div className="title-row">
          <div>
            <h1 className="h1">{done ? `${name} is ready` : `Creating ${name}…`}</h1>
            <p className="lead">{done ? "Opening the project…" : "Phoenix is setting up the folder and repo. This takes a moment."}</p>
          </div>
          <span className="area"><Icon name="plus-circle" />Create</span>
        </div>
        <section className="card stackg" aria-label="Creating the project">
          <CreateProgress steps={j?.steps ?? []} />
        </section>
      </main>
      )}
      <main hidden={creating}>
      <div className="title-row">
        <div>
          <h1 className="h1">New project</h1>
          <p className="lead">Fill in the sheet; the receipt on the right shows what Phoenix will make.</p>
        </div>
        <span className="area"><Icon name="plus-circle" />Create</span>
      </div>
      <form className="order" onSubmit={(e) => { e.preventDefault(); if (ready) submit() }}>
        <fieldset style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}>
          <OrderSheet value={values} onChange={setValues} onNameOk={setNameOk} onRows={onRows} />
        </fieldset>
        <aside className="receipt" aria-label="What Phoenix will make">
          <div className="receipt-h"><h2 className="h2" style={{ fontSize: 22 }}>What Phoenix will make</h2></div>
          {failed && j ? (
            <div className="receipt-f" style={{ borderTop: 0 }}>
              <p className="lbl">Could not make {name}</p>
              <CreateProgress steps={j.steps} />
              <div role="alert" className="stackg">
                <p className="reason">{j.message || "Creating the project failed."}</p>
                <p className="small">Nothing was left half-made.</p>
                <button type="button" className="btn btn-secondary" onClick={() => setJobId("")}>Back to the form</button>
              </div>
            </div>
          ) : (
            <>
              <Receipt v={values} summary={summary} github={!!github.data?.connected} />
              <div className="receipt-f">
                {error && <p className="reason" role="alert">{error}</p>}
                <p className="small" id="rcUnmet" style={{ display: "flex", gap: 6, alignItems: "center", color: missing.length ? undefined : "var(--ok)" }}>
                  <Icon name={missing.length ? "info" : "check-circle"} size="sm" />
                  {missing.length
                    ? <a href={`#${missing[0]!.target}`} onClick={(e) => { e.preventDefault(); jump(missing[0]!) }}>{missing[0]!.text}</a>
                    : <span>Ready to create.</span>}
                </p>
                <button type="submit" className="btn btn-primary" disabled={!ready} aria-describedby="rcUnmet" style={{ width: "100%" }}>
                  <Icon name="plus-circle" />Create project
                </button>
              </div>
            </>
          )}
        </aside>
      </form>
    </main>
    </>
  )
}
