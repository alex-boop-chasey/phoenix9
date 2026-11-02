// The only place the web app talks to the server. Paths are relative to the page (path-prefix safe).
import type {
  CreateForm, EditBody, EventsRecent, ExplainView, Gate, GateAction, GateAnswer, GithubRepos, GlobalView,
  DeployStatus, Info, Job, UpdateStatus, KeyInput, KeyRow, LibraryStep, LogEntry, LogText, NameCheck, Overrides, PlanView, Preset,
  Profile, Project, ProjectQueryResult, ProjectRow, ChangelogLine, BuildRow, RunDetail, Service, ServicesView, KeysAudit, SettingsView,
  SpecFile, StartRunBody, Template, ImportCandidate, ImportResult, RemoveResult, ChatStartResult,
} from "@/lib/types"

/** An error from the server or the network, with a plain-English message. */
export class ApiError extends Error {
  status: number
  body: unknown
  constructor(status: number, message: string, body: unknown = null) {
    super(message)
    this.name = "ApiError"
    this.status = status
    this.body = body
  }
}

const NOT_ANSWERING = "Phoenix is not answering."

/** The api/ address next to the page (keeps any /proxy/<port>/ prefix; never "/api"). */
export function apiBase(): URL {
  return new URL("api/", location.href.split("#")[0])
}

type Params = Record<string, string | number | boolean | null | undefined>

function urlFor(path: string, params?: Params): string {
  const url = new URL(path.replace(/^\/+/, ""), apiBase())
  for (const [key, value] of Object.entries(params ?? {})) {
    if (value !== undefined && value !== null && value !== "") url.searchParams.set(key, String(value))
  }
  return url.toString()
}

async function send<T>(url: string, init: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(url, init)
  } catch {
    throw new ApiError(0, NOT_ANSWERING)
  }
  let body: unknown = null
  try {
    body = await res.json()
  } catch {
    body = null
  }
  const parsed = body as { ok?: boolean; data?: T; message?: string } | null
  if (!res.ok || !parsed || parsed.ok !== true) {
    const message = parsed && typeof parsed.message === "string" && parsed.message ? parsed.message : NOT_ANSWERING
    throw new ApiError(res.status, message, body)
  }
  return parsed.data as T
}

/** GET a path under api/ and return its `data`. */
export function get<T>(path: string, params?: Params): Promise<T> {
  return send<T>(urlFor(path, params), { method: "GET" })
}

/** POST a JSON body to a path under api/ and return its `data`. */
export function post<T>(path: string, body: unknown = {}): Promise<T> {
  return send<T>(urlFor(path), {
    method: "POST",
    headers: { "X-Phoenix": "1", "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
}

/** The address for an EventSource (all projects, or one). */
export function eventsUrl(project?: string): string {
  return urlFor("events", { project })
}

const e = encodeURIComponent

export const api = {
  info: () => get<Info>("info"),
  projects: () => get<ProjectRow[]>("projects"),
  searchProjects: (params: Record<string, string>) => get<ProjectQueryResult>("projects", params),
  importCandidates: () => get<ImportCandidate[]>("import/candidates"),
  checkName: (name: string) => get<NameCheck>("projects/check-name", { name }),
  project: (name: string) => get<Project>(`projects/${e(name)}`),
  changelog: (name: string, limit = 20) => get<ChangelogLine[]>(`projects/${e(name)}/changelog`, { limit }),
  keys: (name: string) => get<KeyRow[]>(`projects/${e(name)}/keys`),
  settings: (name: string) => get<SettingsView>(`projects/${e(name)}/settings`),
  explain: (name: string) => get<ExplainView>(`projects/${e(name)}/explain`),
  specs: (name: string) => get<SpecFile[]>(`projects/${e(name)}/specs`),
  builds: (name: string) => get<BuildRow[]>(`projects/${e(name)}/runs`),
  run: (project: string, runId: string) => get<RunDetail>(`runs/${e(project)}/${e(runId)}`),
  gates: (project?: string) => get<Gate[]>("gates", { project }),
  librarySteps: () => get<{ steps: LibraryStep[]; problems: string[] }>("library/steps"),
  libraryProfiles: () => get<{ profiles: Profile[]; problems: string[] }>("library/profiles"),
  libraryPresets: () => get<{ presets: Preset[] }>("library/presets"),
  libraryTemplates: () => get<Template[]>("library/templates"),
  libraryServices: () => get<{ services: Service[]; problems: string[] }>("library/services"),
  githubRepos: () => get<GithubRepos>("github/repos"),
  global: () => get<GlobalView>("global"),
  services: () => get<ServicesView>("services"),
  keysAudit: () => get<KeysAudit>("keys/audit"),
  update: (refresh = false) => get<UpdateStatus>("update", { refresh: refresh ? 1 : undefined }),
  deploys: (name: string) => get<DeployStatus>(`projects/${e(name)}/deploys`),
  job: (id: string) => get<Job>(`jobs/${e(id)}`),
  eventsRecent: (params: { project?: string; after?: number; limit?: number }) =>
    get<EventsRecent>("events/recent", params),
  logs: (params: { project: string; run?: string; task?: number; step?: string; kind?: string }) =>
    get<LogEntry[]>("logs", params),
  readLog: (project: string, id: string) => get<LogText>("logs/read", { project, id }),

  removeProject: (name: string) => post<RemoveResult>(`projects/${e(name)}/remove`, { confirm: true }),
  importProject: (target: string) => post<ImportResult>("import", { target }),
  chatStart: (name: string) => post<ChatStartResult>(`projects/${e(name)}/chat/start`, {}),
  createProject: (form: CreateForm) => post<{ job: string }>("projects", form),
  editProject: (name: string, body: EditBody) => post<Project>(`projects/${e(name)}/edit`, body),
  saveKeys: (name: string, rows: KeyInput[]) => post<KeyRow[]>(`projects/${e(name)}/keys/save`, { rows }),
  revealKey: (name: string, key: string) =>
    post<{ name: string; value: string }>(`projects/${e(name)}/keys/reveal`, { name: key }),
  removeKey: (name: string, key: string) => post<KeyRow[]>(`projects/${e(name)}/keys/remove`, { name: key }),
  setSettings: (name: string, set: Record<string, unknown>) =>
    post<SettingsView>(`projects/${e(name)}/settings`, { set }),
  setPreset: (name: string, preset: string) =>
    post<SettingsView>(`projects/${e(name)}/settings/preset`, { preset }),
  checkSettings: (name: string) => post<SettingsView>(`projects/${e(name)}/settings/check`, {}),
  plan: (name: string, overrides: Overrides) => post<PlanView>(`projects/${e(name)}/plan`, { overrides }),
  saveDefaults: (name: string, overrides: Overrides) =>
    post<{ project: string }>(`projects/${e(name)}/defaults`, { overrides }),
  startRun: (name: string, body: StartRunBody) =>
    post<{ run_id: string; project: string; status: string }>(`projects/${e(name)}/runs`, body),
  stopRun: (project: string, runId: string) =>
    post<{ run_id: string; status: string; containers_removed: number }>(
      `runs/${e(project)}/${e(runId)}/stop`,
      { confirm: true },
    ),
  answerGate: (id: string, action: GateAction, note = "") =>
    post<GateAnswer>(`gates/${e(id)}/answer`, { action, note }),
}
