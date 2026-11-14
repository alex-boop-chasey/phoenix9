// New project: a three-slide wizard (Back/Next, Create on the last) beside the receipt "What Phoenix will make".
import { useCallback, useEffect, useRef, useState } from "react"
import { useNavigate } from "react-router"
import { toast } from "sonner"

import { Icon } from "@/components/Icon"
import { CreateProgress } from "@/features/projects/CreateProgress"
import { OrderSheet } from "@/features/projects/OrderSheet"
import { Button } from "@/components/ui/button"
import {
  NEW_SLIDES, allMissing, emptyForm, newRepoApplies, slideMissing, toCreateForm, type FormValues, type Missing,
} from "@/features/projects/formModel"
import { useCreateProject, useGithubRepos, useJob, useLibraryProfiles, useLibraryTemplates } from "@/lib/queries"
import type { RowsSummary } from "@/features/keys/KeysForm"
import type { KeyInput } from "@/lib/types"

/** Scroll to the part of a slide that is missing something and put the cursor there. */
function focusMissing(m: Missing) {
  const step = document.getElementById(m.target)
  step?.scrollIntoView?.({ behavior: "smooth", block: "center" })
  const field = m.focus ? document.getElementById(m.focus) : step?.querySelector<HTMLElement>("input, button")
  field?.focus({ preventScroll: true })
}

function Receipt({ v, summary, github }: { v: FormValues; summary: RowsSummary; github: boolean }) {
  const templates = useLibraryTemplates()
  const profiles = useLibraryProfiles()
  const framework = templates.data?.find((t) => t.name === v.framework)?.title ?? v.framework
  const code =
    v.source === "empty" ? (v.framework ? `${framework} starter` : "A blank folder")
      : v.source === "repo" ? (v.repo ? `Copy of ${v.repo}` : "Copy of a GitHub repo")
        : v.source === "template" ? `${v.template || "A GitHub"} template`
          : (v.path ? `Code in ${v.path}` : "Code already on this server")
  const kind = v.profile ? (profiles.data?.profiles.find((p) => p.name === v.profile)?.title ?? v.profile) : "Not chosen yet"
  const newRepo = github && newRepoApplies(v.source) && v.newRepo
  const { total, needValue } = summary
  return (
    <dl>
      <dt>Folder</dt><dd className="mono">{v.name ? `/srv/projects/${v.name}` : "—"}</dd>
      <dt>Code</dt><dd>{code}</dd>
      <dt>Type</dt><dd>{kind}</dd>
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

  const [slide, setSlide] = useState(1)
  const [seen, setSeen] = useState(1)
  const [focusOn, setFocusOn] = useState<Missing | null>(null)
  const top = useRef<HTMLDivElement>(null)
  const heading = useRef<HTMLHeadingElement>(null)
  const shownSlide = useRef(slide)
  const last = slide === NEW_SLIDES.length
  const problems = last ? allMissing(values, nameOk, pending) : slideMissing(slide, values, nameOk, pending)
  const ready = last && problems.length === 0 && !create.isPending && !started

  function go(n: number) {
    setSlide(n)
    setSeen((s) => Math.max(s, n))
  }

  /** Open the slide that is missing something and point at the field. */
  function jump(m: Missing) {
    if (m.slide === slide) focusMissing(m)
    else { go(m.slide); setFocusOn(m) }
  }

  // Every slide change lands on the progress line with focus on the slide title (or on the missing field).
  useEffect(() => {
    if (shownSlide.current === slide) return
    shownSlide.current = slide
    top.current?.scrollIntoView?.({ block: "start" })
    if (focusOn) { focusMissing(focusOn); setFocusOn(null) } else heading.current?.focus({ preventScroll: true })
  }, [slide, focusOn])

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
          <p className="lead">Three short steps; the card beside them shows what Phoenix will make.</p>
        </div>
        <span className="area"><Icon name="plus-circle" />Create</span>
      </div>
      <form onSubmit={(e) => { e.preventDefault(); if (ready) submit(); else if (!last && !problems.length) go(slide + 1) }}>
        <div className="order">
          <div className="wiz np-wiz" ref={top}>
            <ol className="outline" aria-label="New project steps">
              {NEW_SLIDES.map((s, i) => {
                const n = i + 1
                return (
                  <li key={s.title}>
                    <button
                      type="button" className={n < slide ? "done" : ""} data-slide={n}
                      aria-current={n === slide ? "step" : undefined} disabled={n > seen || started}
                      onClick={() => go(n)}
                    >
                      <span className="num">{n < slide ? <Icon name="check" size="xs" /> : n}</span>
                      <b>{s.title}</b>
                      <small>{s.note}</small>
                    </button>
                  </li>
                )
              })}
            </ol>
            <div className="wmain">
              <div className="wprog" data-testid="np-progress">
                <p className="small">Step {slide} of {NEW_SLIDES.length}<span className="wp-title"> · {NEW_SLIDES[slide - 1]!.title}</span></p>
                <div className="wbar" role="progressbar" aria-label="New project progress" aria-valuemin={1} aria-valuemax={NEW_SLIDES.length} aria-valuenow={slide}>
                  {NEW_SLIDES.map((s, i) => (
                    <span key={s.title} className={i + 1 < slide ? "done" : i + 1 === slide ? "now" : ""} />
                  ))}
                </div>
              </div>
              <section className="canvas" aria-label="New project">
                <div className="canvas-h">
                  <h2 className="h2" ref={heading} tabIndex={-1}>{NEW_SLIDES[slide - 1]!.title}</h2>
                </div>
                <fieldset style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}>
                  <OrderSheet value={values} slide={slide} onChange={setValues} onNameOk={setNameOk} onRows={onRows} />
                </fieldset>
              </section>
            </div>
          </div>
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
                {error && <div className="receipt-f"><p className="reason" role="alert">{error}</p></div>}
              </>
            )}
          </aside>
        </div>
        <div className="wdock np-dock">
          <span className="prob" id="rcUnmet" aria-live="polite">
            <Icon name={problems.length ? "info" : "check-circle"} size="sm" />
            {problems.length
              ? <a href={`#${problems[0]!.target}`} onClick={(e) => { e.preventDefault(); jump(problems[0]!) }}>{problems[0]!.text}</a>
              : <span>{last ? "Ready to create." : "This step is done."}</span>}
          </span>
          <Button type="button" variant="secondary" disabled={slide === 1 || started} onClick={() => go(slide - 1)}>
            <Icon name="arrow-left" />Back
          </Button>
          {last ? (
            <Button type="submit" disabled={!ready} aria-describedby="rcUnmet">
              <Icon name="plus-circle" />Create project
            </Button>
          ) : (
            <Button type="button" disabled={problems.length > 0} aria-describedby="rcUnmet" onClick={() => go(slide + 1)}>
              Next<Icon name="arrow-right" />
            </Button>
          )}
        </div>
      </form>
    </main>
    </>
  )
}
