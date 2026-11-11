// Cards for the guided flows: the plan check, the specs and the creation job; plain text from typed data only.

function isObject(v: unknown): v is Record<string, unknown> { return !!v && typeof v === "object" && !Array.isArray(v) }
function isText(v: unknown): v is string { return typeof v === "string" }
function texts(v: unknown): string[] { return Array.isArray(v) ? v.filter(isText) : [] }

/** Plan check data: each group's steps, any errors and whether it is fine. */
export interface PlanCheckData { project: string; groups: { name: string; steps: string[] }[]; errors: string[]; ok: boolean }
/** Specs data: each spec's name, title and whether it can be built directly. */
export interface SpecsData { project: string; specs: { name: string; title: string; task_format: boolean }[] }
/** Job data: kind, project, status, each step with its status, and the message. */
export interface JobData { job: string; kind: string; project: string; status: string; steps: { label: string; status: string }[]; message: string }

/** Plan check data when it fits (groups is an object of lists), else null. */
export function planCheckFrom(data: unknown): PlanCheckData | null {
  if (!isObject(data) || !isObject(data.groups)) return null
  const groups: { name: string; steps: string[] }[] = []
  for (const [name, steps] of Object.entries(data.groups)) {
    if (!Array.isArray(steps)) return null
    groups.push({ name, steps: steps.filter(isText) })
  }
  const errors = texts(data.errors)
  return { project: isText(data.project) ? data.project : "", groups, errors, ok: errors.length === 0 }
}

/** Specs data when it fits (a list of specs with names), else null. */
export function specsFrom(data: unknown): SpecsData | null {
  if (!isObject(data) || !Array.isArray(data.specs)) return null
  const specs: SpecsData["specs"] = []
  for (const s of data.specs) {
    if (!isObject(s) || !isText(s.name) || !s.name) return null
    specs.push({ name: s.name, title: isText(s.title) ? s.title : "", task_format: s.task_format === true })
  }
  return { project: isText(data.project) ? data.project : "", specs }
}

/** Job data when it fits (a status and well-formed steps), else null. */
export function jobFrom(data: unknown): JobData | null {
  if (!isObject(data) || !isText(data.status) || !Array.isArray(data.steps)) return null
  const steps: JobData["steps"] = []
  for (const s of data.steps) {
    if (!isObject(s) || !isText(s.label)) return null
    steps.push({ label: s.label, status: isText(s.status) ? s.status : "" })
  }
  const t = (v: unknown) => (isText(v) ? v : "")
  return { job: t(data.job), kind: t(data.kind), project: t(data.project), status: data.status, steps, message: t(data.message) }
}

/** The plan check: each group's steps and any errors, in plain words. */
export function PlanCheckCard({ data }: { data: PlanCheckData }) {
  return (
    <section className="card flex flex-col gap-1" aria-label="Plan check" data-testid="plan-check-card">
      <strong>Plan check{data.project ? ` for ${data.project}` : ""}</strong>
      <span className="text-sm">{data.ok ? "The plan is fine." : "The plan has problems."}</span>
      {data.groups.map((g) => (
        <div key={g.name}>
          <span className="block text-sm">{g.name}: {g.steps.length} {g.steps.length === 1 ? "step" : "steps"}</span>
          <ul>{g.steps.map((s, i) => <li key={i}>{s}</li>)}</ul>
        </div>
      ))}
      {data.errors.length ? <ul aria-label="Errors">{data.errors.map((e, i) => <li key={i}>Problem: {e}</li>)}</ul> : null}
    </section>
  )
}

/** The specs of a project, and which can be built directly. */
export function SpecsCard({ data }: { data: SpecsData }) {
  return (
    <section className="card flex flex-col gap-1" aria-label="Specs" data-testid="specs-card">
      <strong>Specs{data.project ? ` for ${data.project}` : ""}</strong>
      {data.specs.length ? (
        <ul>{data.specs.map((s) => (
          <li key={s.name}>{s.title ? `${s.name}: ${s.title}` : s.name} - {s.task_format ? "can be built directly" : "needs a plan first"}</li>
        ))}</ul>
      ) : <span className="text-sm">No specs yet.</span>}
    </section>
  )
}

/** A creation job: each step with its status, then "Done" or the failure message. */
export function JobCard({ data }: { data: JobData }) {
  const failed = data.status === "failed" || data.status === "error"
  const done = data.status === "done" || data.status === "ok"
  return (
    <section className="card flex flex-col gap-1" aria-label="Job" data-testid="job-card">
      <strong>{data.kind || "Job"}{data.project ? ` for ${data.project}` : ""}</strong>
      <ul>{data.steps.map((s, i) => <li key={i}>{s.label}: {s.status || "waiting"}</li>)}</ul>
      {failed ? <span className="text-sm" data-testid="job-result">Failed: {data.message || "no reason given"}</span>
        : done ? <span className="text-sm" data-testid="job-result">Done</span>
        : <span className="text-sm" data-testid="job-result">Status: {data.status}</span>}
    </section>
  )
}
