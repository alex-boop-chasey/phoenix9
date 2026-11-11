// Maps a tool's component name to our React components; all text is drawn as plain text from typed data.
import type { ReactNode } from "react"

import { ChoiceCard, choiceAskFrom } from "./choicecard"
import { EnvUploadCard, envAskFrom } from "./envcard"
import { FlowCard, flowFrom } from "./flowcard"
import { JobCard, PlanCheckCard, SpecsCard, jobFrom, planCheckFrom, specsFrom } from "./guidedcards"
import { KeyInputCard, keyAskFrom } from "./keycard"
import { SearchResultsCard, searchFrom } from "./searchcard"

/** Card data for one project, as the Phoenix pack sends it. */
export interface ProjectCardData { name: string; status: string; last_used: string; link?: string }

/** One tool call as the panel tracks it: running until its result arrives. */
export interface ToolCallItem { toolCallId: string; toolName: string; running: boolean; component?: string; data?: unknown }

function isText(v: unknown): v is string { return typeof v === "string" }

/** Pick out the projects that fit the card shape; null when the data does not fit. */
export function projectsFrom(data: unknown): ProjectCardData[] | null {
  const list = (data as { projects?: unknown } | null | undefined)?.projects
  if (!Array.isArray(list)) return null
  const out: ProjectCardData[] = []
  for (const p of list) {
    if (!p || typeof p !== "object") return null
    const { name, status, last_used, link } = p as Record<string, unknown>
    if (!isText(name)) return null
    out.push({ name, status: isText(status) ? status : "", last_used: isText(last_used) ? last_used : "", link: isText(link) ? link : undefined })
  }
  return out
}

function openHash(link: string) {
  window.location.hash = link.startsWith("#") ? link : `#${link}`
}

/** One project: name, status, last used; a click opens it. */
export function MiniProjectCard({ project, onOpen }: { project: ProjectCardData; onOpen?: (p: ProjectCardData) => void }) {
  const open = () => (onOpen ? onOpen(project) : openHash(project.link || `#/p/${project.name}`))
  return (
    <button type="button" className="card w-full text-left" data-testid="mini-project-card" onClick={open}>
      <strong>{project.name}</strong>
      <span className="block text-sm">{project.status || "unknown"}</span>
      <span className="block text-xs text-muted-foreground">Last used: {project.last_used || "not yet"}</span>
    </button>
  )
}

/** A list of project cards. */
export function ProjectCards({ projects, onOpen }: { projects: ProjectCardData[]; onOpen?: (p: ProjectCardData) => void }) {
  return (
    <section className="flex flex-col gap-2" aria-label="Projects" data-testid="project-cards">
      {projects.map((p) => <MiniProjectCard key={p.name} project={p} onOpen={onOpen} />)}
    </section>
  )
}

/** Card data for a build that was started or changed. */
export interface BuildCardData { project: string; run_id: string; status: string; started: string; link?: string }
/** Card data for one run. */
export interface RunCardData { run_id: string; title: string; status: string; current_step: string; tasks_done: number; tasks_total: number; link?: string }
/** One task of a run. */
export interface TaskRow { number: number; title: string; status: string }

function isObject(v: unknown): v is Record<string, unknown> { return !!v && typeof v === "object" && !Array.isArray(v) }
function count(v: unknown): number { return typeof v === "number" && Number.isFinite(v) ? v : 0 }

/** The build card data when it fits (project and run id are text), else null. */
export function buildFrom(data: unknown): BuildCardData | null {
  const b = isObject(data) ? data.build : null
  if (!isObject(b) || !isText(b.project) || !isText(b.run_id)) return null
  return { project: b.project, run_id: b.run_id, status: isText(b.status) ? b.status : "", started: isText(b.started) ? b.started : "", link: isText(b.link) ? b.link : undefined }
}

/** One run's card data when it fits (a run id is text), else null. */
export function runFrom(r: unknown): RunCardData | null {
  if (!isObject(r) || !isText(r.run_id)) return null
  const t = (v: unknown) => (isText(v) ? v : "")
  return { run_id: r.run_id, title: t(r.title), status: t(r.status), current_step: t(r.current_step), tasks_done: count(r.tasks_done), tasks_total: count(r.tasks_total), link: isText(r.link) ? r.link : undefined }
}

/** The task rows when every one fits (a number and a title), else null. */
export function tasksFrom(data: unknown): TaskRow[] | null {
  const list = isObject(data) ? data.tasks : null
  if (!Array.isArray(list)) return null
  const out: TaskRow[] = []
  for (const t of list) {
    if (!isObject(t) || typeof t.number !== "number" || !isText(t.title)) return null
    out.push({ number: t.number, title: t.title, status: isText(t.status) ? t.status : "" })
  }
  return out
}

/** A build that was started or changed: project, run, status, started; a click opens it. */
export function BuildCard({ build }: { build: BuildCardData }) {
  return (
    <button type="button" className="card w-full text-left" data-testid="build-card" onClick={() => openHash(build.link || `#/p/${build.project}/build`)}>
      <strong>{build.project}</strong>
      <span className="block text-sm">Build {build.run_id}: {build.status || "unknown"}</span>
      <span className="block text-xs text-muted-foreground">Started: {build.started || "not yet"}</span>
    </button>
  )
}

/** One run: title, status, current step, tasks done of total; a click opens it. */
export function RunCard({ run }: { run: RunCardData }) {
  return (
    <button type="button" className="card w-full text-left" data-testid="run-card" onClick={() => run.link && openHash(run.link)}>
      <strong>{run.title || run.run_id}</strong>
      <span className="block text-sm">{run.status || "unknown"}</span>
      {run.current_step ? <span className="block text-xs">Now: {run.current_step}</span> : null}
      <span className="block text-xs text-muted-foreground">{run.tasks_done} of {run.tasks_total} tasks done</span>
    </button>
  )
}

/** A run's tasks: number, title and status each. */
export function TaskListCard({ tasks }: { tasks: TaskRow[] }) {
  return (
    <ol className="flex flex-col gap-1" aria-label="Tasks" data-testid="task-list-card">
      {tasks.map((t) => <li key={t.number}>Task {t.number}: {t.title} - {t.status || "unknown"}</li>)}
    </ol>
  )
}

/** Card data for settings: name/value rows, a plain explanation and a link to the settings page. */
export interface SettingsCardData { project: string; rows: { name: string; value: string }[]; explanation: string; note: string; problems: string[]; link?: string }
/** Card data for key names: names and status only. */
export interface KeyNamesCardData { project: string; keys: { name: string; status: string }[]; link?: string }
/** Card data for the updater. */
export interface UpdateCardData { installed: string; newest: string; queued: boolean; link?: string }

/** Settings card data when it fits (a project name and a list of rows), else null. */
export function settingsFrom(data: unknown): SettingsCardData | null {
  if (!isObject(data) || !isText(data.project) || !Array.isArray(data.rows)) return null
  const rows: { name: string; value: string }[] = []
  for (const r of data.rows) {
    if (!isObject(r) || !isText(r.name)) return null
    rows.push({ name: r.name, value: isText(r.value) ? r.value : "" })
  }
  const problems = Array.isArray(data.problems) ? data.problems.filter(isText) : []
  return { project: data.project, rows, explanation: isText(data.explanation) ? data.explanation : "", note: isText(data.note) ? data.note : "", problems, link: isText(data.link) ? data.link : undefined }
}

/** Key names card data; only the name and a set/missing status are read, so no other field can be drawn. */
export function keyNamesFrom(data: unknown): KeyNamesCardData | null {
  if (!isObject(data) || !isText(data.project) || !Array.isArray(data.keys)) return null
  const keys: { name: string; status: string }[] = []
  for (const k of data.keys) {
    if (!isObject(k) || !isText(k.name)) return null
    keys.push({ name: k.name, status: k.status === "set" ? "set" : "missing" })
  }
  return { project: data.project, keys, link: isText(data.link) ? data.link : undefined }
}

/** Update card data when it fits (versions are text), else null. */
export function updateFrom(data: unknown): UpdateCardData | null {
  if (!isObject(data) || !isText(data.installed) || !isText(data.newest)) return null
  return { installed: data.installed, newest: data.newest, queued: data.queued === true, link: isText(data.link) ? data.link : undefined }
}

/** A project's settings: each name and value, the plain explanation and a link to the settings page. */
export function SettingsCard({ settings }: { settings: SettingsCardData }) {
  return (
    <section className="card flex flex-col gap-1" aria-label="Settings" data-testid="settings-card">
      <strong>Settings for {settings.project}</strong>
      {settings.note ? <span className="block text-sm">{settings.note}</span> : null}
      {settings.problems.map((p, i) => <span key={i} className="block text-sm">{p}</span>)}
      <ul>{settings.rows.map((r) => <li key={r.name}>{r.name}: {r.value}</li>)}</ul>
      {settings.explanation ? <p className="text-sm">{settings.explanation}</p> : null}
      <a className="text-xs underline" href={settings.link || `#/p/${settings.project}/settings`}>Open the settings page</a>
    </section>
  )
}

/** A project's key names and whether each is set or missing; never a value. */
export function KeyNamesCard({ keys }: { keys: KeyNamesCardData }) {
  return (
    <section className="card flex flex-col gap-1" aria-label="Keys" data-testid="key-names-card">
      <strong>Keys for {keys.project}</strong>
      {keys.keys.length ? <ul>{keys.keys.map((k) => <li key={k.name}>{k.name}: {k.status}</li>)}</ul> : <span className="text-sm">No keys yet.</span>}
    </section>
  )
}

/** The updater: installed version, newest version and whether an install is queued. */
export function UpdateCard({ update }: { update: UpdateCardData }) {
  return (
    <section className="card flex flex-col gap-1" aria-label="Update" data-testid="update-card">
      <span className="block text-sm">Installed: {update.installed || "unknown"}</span>
      <span className="block text-sm">Newest: {update.newest || "unknown"}</span>
      <span className="block text-xs">{update.queued ? "An install is queued." : "No install is queued."}</span>
      <a className="text-xs underline" href={update.link || "#/settings?section=updates"}>Open the updates page</a>
    </section>
  )
}

/** One repair button: its label, the control it leads to and that control's inputs. */
export interface RepairOption { label: string; tool: string; inputs: Record<string, unknown> }
/** Card data for "what happened" to a stopped run. */
export interface WhatHappenedData { project: string; run_id: string; cause: string; tried: string[]; suggestion: string; options: RepairOption[] }

/** What-happened data when it fits (a cause and well-formed options), else null. */
export function whatHappenedFrom(data: unknown): WhatHappenedData | null {
  if (!isObject(data) || !isText(data.cause) || !data.cause || !Array.isArray(data.options)) return null
  const options: RepairOption[] = []
  for (const o of data.options) {
    if (!isObject(o) || !isText(o.label) || !o.label || !isText(o.tool) || !o.tool || !isObject(o.inputs)) return null
    options.push({ label: o.label, tool: o.tool, inputs: o.inputs })
  }
  const tried = Array.isArray(data.tried) ? data.tried.filter(isText) : []
  return { project: isText(data.project) ? data.project : "", run_id: isText(data.run_id) ? data.run_id : "", cause: data.cause, tried, suggestion: isText(data.suggestion) ? data.suggestion : "", options }
}

/** The fixed chat message a button sends: ask the agent to use that control with those inputs. */
export function optionMessage(o: RepairOption): string {
  return `Please do this: ${o.label}. Use the ${o.tool} control with these inputs: ${JSON.stringify(o.inputs)}`
}

/** What happened to a run: the cause, what was tried, the suggestion and one button per option. */
export function WhatHappenedCard({ data, onSend }: { data: WhatHappenedData; onSend?: (message: string) => void }) {
  return (
    <section className="card flex flex-col gap-2" aria-label="What happened" data-testid="what-happened-card">
      <strong>What happened{data.run_id ? ` to ${data.run_id}` : ""}</strong>
      <p className="text-sm">{data.cause}</p>
      {data.tried.length ? <ul aria-label="What was tried">{data.tried.map((t, i) => <li key={i}>{t}</li>)}</ul> : null}
      {data.suggestion ? <p className="text-sm">Suggestion: {data.suggestion}</p> : null}
      <div className="flex flex-wrap gap-2">
        {data.options.map((o, i) => <button key={i} type="button" className="btn" onClick={() => onSend?.(optionMessage(o))}>{o.label}</button>)}
      </div>
    </section>
  )
}

/** Card data for a task's tries: the task and one plain line per try. */
export interface TriesCardData { run_id: string; task: string; status: string; max_tries: number | null; tries: string[] }
/** Card data for a step's AI session excerpt: where it came from and the quoted text. */
export interface SessionCardData { source: string; text: string }

/** Tries data when it fits (a list of lines), else null. */
export function triesFrom(data: unknown): TriesCardData | null {
  if (!isObject(data) || !Array.isArray(data.tries)) return null
  const title = isText(data.title) ? data.title : ""
  const num = typeof data.task === "number" ? `Task ${data.task}` : ""
  return { run_id: isText(data.run_id) ? data.run_id : "", task: [num, title].filter(Boolean).join(": "), status: isText(data.status) ? data.status : "", max_tries: typeof data.max_tries === "number" ? data.max_tries : null, tries: data.tries.filter(isText) }
}

/** Session data when the wrapped excerpt (quoted.data is text) fits, else null. */
export function sessionFrom(data: unknown): SessionCardData | null {
  const q = isObject(data) ? data.quoted : null
  if (!isObject(q) || !isText(q.data)) return null
  return { source: isText(q.quoted_from) ? q.quoted_from : "", text: q.data }
}

/** A task's tries, one line per try. */
export function TriesCard({ data }: { data: TriesCardData }) {
  return (
    <section className="card flex flex-col gap-1" aria-label="Tries" data-testid="tries-card">
      <strong>{data.task || "Tries"}{data.status ? ` - ${data.status}` : ""}</strong>
      {data.max_tries !== null ? <span className="text-xs">Up to {data.max_tries} tries</span> : null}
      {data.tries.length ? <ul>{data.tries.map((t, i) => <li key={i}>{t}</li>)}</ul> : <span className="text-sm">No tries yet.</span>}
    </section>
  )
}

/** A step's AI session excerpt, shown as quoted text. */
export function SessionCard({ data }: { data: SessionCardData }) {
  return (
    <figure className="card flex flex-col gap-1" aria-label="Session excerpt" data-testid="session-card">
      {data.source ? <figcaption className="text-xs">From {data.source}</figcaption> : null}
      <blockquote className="whitespace-pre-wrap text-sm">{data.text}</blockquote>
    </figure>
  )
}

/** What shows when a card's data does not fit its shape. */
function Fallback({ tool }: { tool: string }) {
  return <p data-testid="card-fallback">Used {tool}, but the result could not be shown.</p>
}

/** The cards we can draw, chosen by component name. */
export const COMPONENTS: Record<string, (props: { data: unknown; tool: string; callId?: string; onOpen?: (p: ProjectCardData) => void; onSend?: (message: string) => void }) => ReactNode> = {
  project_cards: ({ data, tool, onOpen }) => {
    const projects = projectsFrom(data)
    return projects ? <ProjectCards projects={projects} onOpen={onOpen} /> : <Fallback tool={tool} />
  },
  BuildCard: ({ data, tool }) => {
    const build = buildFrom(data)
    return build ? <BuildCard build={build} /> : <Fallback tool={tool} />
  },
  RunCard: ({ data, tool }) => {
    const run = runFrom(isObject(data) ? data.run : null)
    const tasks = tasksFrom(data)
    if (!run) return <Fallback tool={tool} />
    return <div className="flex flex-col gap-2"><RunCard run={run} />{tasks && tasks.length ? <TaskListCard tasks={tasks} /> : null}</div>
  },
  RunCards: ({ data, tool }) => {
    const list = isObject(data) ? data.runs : null
    const runs = Array.isArray(list) ? list.map(runFrom) : null
    if (!runs || runs.some((r) => !r)) return <Fallback tool={tool} />
    return <section className="flex flex-col gap-2" aria-label="Builds" data-testid="run-cards">{runs.map((r) => <RunCard key={r!.run_id} run={r!} />)}</section>
  },
  TaskListCard: ({ data, tool }) => {
    const tasks = tasksFrom(data)
    return tasks ? <TaskListCard tasks={tasks} /> : <Fallback tool={tool} />
  },
  run_card: (props) => (buildFrom(props.data) ? COMPONENTS.BuildCard!(props) : COMPONENTS.RunCard!(props)),
  task_list_card: (props) => COMPONENTS.TaskListCard!(props),
  settings_card: ({ data, tool }) => {
    const settings = settingsFrom(data)
    return settings ? <SettingsCard settings={settings} /> : <Fallback tool={tool} />
  },
  SettingsCard: (props) => COMPONENTS.settings_card!(props),
  keys_card: ({ data, tool }) => {
    const keys = keyNamesFrom(data)
    return keys ? <KeyNamesCard keys={keys} /> : <Fallback tool={tool} />
  },
  KeyNamesCard: (props) => COMPONENTS.keys_card!(props),
  update_card: ({ data, tool }) => {
    const update = updateFrom(data)
    return update ? <UpdateCard update={update} /> : <Fallback tool={tool} />
  },
  UpdateCard: (props) => COMPONENTS.update_card!(props),
  WhatHappenedCard: ({ data, onSend }) => {
    const d = whatHappenedFrom(data)
    return d ? <WhatHappenedCard data={d} onSend={onSend} /> : null
  },
  tries_card: ({ data, tool }) => {
    const d = triesFrom(data)
    return d ? <TriesCard data={d} /> : <Fallback tool={tool} />
  },
  session_card: ({ data, tool }) => {
    const d = sessionFrom(data)
    return d ? <SessionCard data={d} /> : <Fallback tool={tool} />
  },
  SearchResultsCard: ({ data }) => {
    const rows = searchFrom(data)
    return rows ? <SearchResultsCard rows={rows} /> : null
  },
  KeyInputCard: ({ data, tool, callId }) => {
    const ask = keyAskFrom(data)
    return ask && callId ? <KeyInputCard ask={ask} callId={callId} /> : <Fallback tool={tool} />
  },
  ChoiceCard: ({ data, tool, callId }) => {
    const ask = choiceAskFrom(data)
    return ask && callId ? <ChoiceCard ask={ask} callId={callId} /> : <Fallback tool={tool} />
  },
  FlowCard: ({ data, onSend }) => {
    const d = flowFrom(data)
    return d ? <FlowCard card={d} onSend={onSend} /> : null
  },
  PlanCheckCard: ({ data, tool }) => {
    const d = planCheckFrom(data)
    return d ? <PlanCheckCard data={d} /> : <Fallback tool={tool} />
  },
  SpecsCard: ({ data, tool }) => {
    const d = specsFrom(data)
    return d ? <SpecsCard data={d} /> : <Fallback tool={tool} />
  },
  JobCard: ({ data, tool }) => {
    const d = jobFrom(data)
    return d ? <JobCard data={d} /> : <Fallback tool={tool} />
  },
  EnvUploadCard: ({ data, tool, callId }) => {
    const ask = envAskFrom(data)
    return ask && callId ? <EnvUploadCard ask={ask} callId={callId} /> : <Fallback tool={tool} />
  },
}

/** One tool call: running state, then its card, or a plain "Used <tool>" line. */
export function ToolCall({ call, onOpen }: { call: ToolCallItem; onOpen?: (p: ProjectCardData) => void }) {
  if (call.running) return <p data-testid="tool-running" aria-busy="true">Running {call.toolName}…</p>
  const Draw = call.component ? COMPONENTS[call.component] : undefined
  if (!Draw) return <p data-testid="tool-used">Used {call.toolName}</p>
  return <>{Draw({ data: call.data, tool: call.toolName, callId: call.toolCallId, onOpen })}</>
}
