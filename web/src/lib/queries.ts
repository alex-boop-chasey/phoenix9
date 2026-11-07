// react-query hooks with stable keys, and mutations that refresh the right keys.
import { keepPreviousData, useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query"
import { useCallback } from "react"

import { api } from "@/lib/api"
import type {
  CreateForm, EditBody, GateAction, KeyInput, Overrides, StartRunBody,
} from "@/lib/types"

/** Whether the event stream is connected ("live") or we are polling; set by useLiveEvents, read by refreshMs(). */
export const liveMode: { current: "live" | "polling" } = { current: "polling" }

/** How often the project lists refetch: 30 s when live events arrive, 10 s when only polling. */
export function refreshMs(): number {
  return liveMode.current === "live" ? 30_000 : 10_000
}

const REFRESH_MS = 10_000

export const keys = {
  info: () => ["info"] as const,
  projects: () => ["projects"] as const,
  project: (name: string) => ["project", name] as const,
  builds: (name: string) => ["builds", name] as const,
  run: (project: string, runId: string) => ["run", project, runId] as const,
  gates: (project?: string) => (project ? (["gates", project] as const) : (["gates"] as const)),
  settings: (name: string) => ["settings", name] as const,
  explain: (name: string) => ["explain", name] as const,
  plan: (name: string) => ["plan", name] as const,
  keyRows: (name: string) => ["keys", name] as const,
  specs: (name: string) => ["specs", name] as const,
  changelog: (name: string) => ["changelog", name] as const,
  logs: (project: string) => ["logs", project] as const,
  chat: (name: string) => ["chat", name] as const,
  global: () => ["global"] as const,
  services: () => ["services"] as const,
  github: () => ["github"] as const,
  job: (id: string) => ["job", id] as const,
  library: (kind: string) => ["library", kind] as const,
}

/** Refresh everything that could show this project (used after a change to it). */
export function invalidateProject(qc: QueryClient, name: string) {
  for (const key of [
    keys.projects(), keys.project(name), keys.builds(name), keys.gates(), keys.settings(name),
    keys.explain(name), keys.plan(name), keys.keyRows(name), keys.specs(name), keys.changelog(name),
  ]) {
    void qc.invalidateQueries({ queryKey: key })
  }
}

export const useInfo = () => useQuery({ queryKey: keys.info(), queryFn: api.info, staleTime: 60_000 })
export const useUpdate = (enabled = true) =>
  useQuery({ queryKey: ["update"], queryFn: () => api.update(), enabled })
export const useDeploys = (name: string, enabled = true) =>
  useQuery({ queryKey: ["deploys", name], queryFn: () => api.deploys(name), enabled: !!name && enabled })
export const useProjects = () =>
  useQuery({ queryKey: keys.projects(), queryFn: api.projects, refetchInterval: () => refreshMs() })
export const useProjectSearch = (params: Record<string, string>) =>
  useQuery({ queryKey: [...keys.projects(), "search", params], queryFn: () => api.searchProjects(params), refetchInterval: () => refreshMs(), placeholderData: keepPreviousData })
/** The sub-folders of a folder under the projects folder (empty path = the projects folder). */
export const useFolders = (path: string) =>
  useQuery({ queryKey: ["folders", path], queryFn: () => api.folders(path), retry: false })

export const useImportCandidates = () =>
  useQuery({ queryKey: ["import-candidates"], queryFn: api.importCandidates })
export const useProject = (name: string) =>
  useQuery({ queryKey: keys.project(name), queryFn: () => api.project(name), enabled: !!name })
export const useBuilds = (name: string) =>
  useQuery({ queryKey: keys.builds(name), queryFn: () => api.builds(name), enabled: !!name })
const RUN_POLL_MS = 4000
const LIVE_RUN = ["queued", "running", "waiting"]

/** One run's detail; refetched every 4 s while it is queued, running or waiting. */
export const useRun = (project: string, runId: string) =>
  useQuery({
    queryKey: keys.run(project, runId),
    queryFn: () => api.run(project, runId),
    enabled: !!project && !!runId,
    refetchInterval: (q) => (LIVE_RUN.includes(q.state.data?.status ?? "") ? RUN_POLL_MS : false),
  })
export const useGates = (project?: string) =>
  useQuery({ queryKey: keys.gates(project), queryFn: () => api.gates(project), refetchInterval: REFRESH_MS })
export const useSettings = (name: string) =>
  useQuery({ queryKey: keys.settings(name), queryFn: () => api.settings(name), enabled: !!name })
export const useExplain = (name: string, enabled = true) =>
  useQuery({ queryKey: keys.explain(name), queryFn: () => api.explain(name), enabled: !!name && enabled })
export const usePlanRows = (name: string) =>
  useQuery({ queryKey: keys.plan(name), queryFn: () => api.plan(name, {}), enabled: !!name })
export const useKeyRows = (name: string) =>
  useQuery({ queryKey: keys.keyRows(name), queryFn: () => api.keys(name), enabled: !!name })
export const useSpecs = (name: string) =>
  useQuery({ queryKey: keys.specs(name), queryFn: () => api.specs(name), enabled: !!name })
export const useChangelog = (name: string, limit = 20) =>
  useQuery({ queryKey: [...keys.changelog(name), limit], queryFn: () => api.changelog(name, limit), enabled: !!name })
export const useLogs = (project: string, filter: { run?: string; task?: number; step?: string; kind?: string } = {}) =>
  useQuery({ queryKey: [...keys.logs(project), filter], queryFn: () => api.logs({ project, ...filter }), enabled: !!project })
export const useGlobal = () => useQuery({ queryKey: keys.global(), queryFn: api.global })
export const useKeysAudit = (enabled = true) =>
  useQuery({ queryKey: ["keys-audit"], queryFn: api.keysAudit, enabled })
export const useGlobalServices = () => useQuery({ queryKey: ["global-services"], queryFn: api.globalServices })
export const useDoctor = () =>
  useQuery({ queryKey: ["doctor"], queryFn: () => api.doctor("quick"), staleTime: 5 * 60_000 })
export const useUpdateHistory = () => useQuery({ queryKey: ["update-history"], queryFn: api.updateHistory })
export const useServices = () => useQuery({ queryKey: keys.services(), queryFn: api.services })
export const useGithubRepos = (enabled = true) =>
  useQuery({ queryKey: keys.github(), queryFn: api.githubRepos, enabled })
export const useJob = (id: string) =>
  useQuery({
    queryKey: keys.job(id),
    queryFn: () => api.job(id),
    enabled: !!id,
    refetchInterval: (q) => (q.state.data && q.state.data.status !== "running" ? false : 1000),
  })
export const useLibrarySteps = () => useQuery({ queryKey: keys.library("steps"), queryFn: api.librarySteps })
export const useLibraryProfiles = () => useQuery({ queryKey: keys.library("profiles"), queryFn: api.libraryProfiles })
export const useLibraryPresets = () => useQuery({ queryKey: keys.library("presets"), queryFn: api.libraryPresets })
export const useLibraryTemplates = () => useQuery({ queryKey: keys.library("templates"), queryFn: api.libraryTemplates })
export const useLibraryTools = () => useQuery({ queryKey: keys.library("tools"), queryFn: api.libraryTools })
export const useLibraryServices = (enabled = true) =>
  useQuery({ queryKey: keys.library("services"), queryFn: api.libraryServices, enabled })

/** Remove a project from Phoenix (the page refreshes the lists itself, after the row fades out). */
export function useRemoveProject() {
  return useMutation({ mutationFn: (name: string) => api.removeProject(name) })
}

/** The dry run for deleting a project entirely (only fetched while `enabled`). */
export const useDeletePlan = (name: string, enabled = true) =>
  useQuery({ queryKey: ["delete-plan", name], queryFn: () => api.deletePlan(name), enabled, gcTime: 0 })

/** Delete a project entirely; `confirm` is the project's name typed again. */
export function useDeleteProject() {
  return useMutation({ mutationFn: (v: { name: string; confirm: string }) => api.deleteProject(v.name, v.confirm) })
}

/** Retry only the GitHub repo delete of a deleted project. */
export function useDeleteRepo() {
  return useMutation({ mutationFn: (name: string) => api.deleteRepo(name) })
}

/** A function (stable between renders) that refreshes the project lists and the import lists. */
export function useRefreshProjects() {
  const qc = useQueryClient()
  return useCallback(() => {
    void qc.invalidateQueries({ queryKey: keys.projects() })
    void qc.invalidateQueries({ queryKey: ["import-candidates"] })
  }, [qc])
}

/** Import a removed project or a folder; the lists refresh afterwards. */
export function useImportProject() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (target: string) => api.importProject(target),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.projects() })
      void qc.invalidateQueries({ queryKey: ["import-candidates"] })
    },
  })
}

export function useCreateProject() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (form: CreateForm) => api.createProject(form),
    onSuccess: () => void qc.invalidateQueries({ queryKey: keys.projects() }),
  })
}

export function useEditProject(name: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: EditBody) => api.editProject(name, body),
    onSuccess: () => invalidateProject(qc, name),
  })
}

export function useSaveKeys(name: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (rows: KeyInput[]) => api.saveKeys(name, rows),
    onSuccess: () => void qc.invalidateQueries({ queryKey: keys.keyRows(name) }),
  })
}

export function useRemoveKey(name: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (key: string) => api.removeKey(name, key),
    onSuccess: () => void qc.invalidateQueries({ queryKey: keys.keyRows(name) }),
  })
}

export function useRevealKey(name: string) {
  return useMutation({ mutationFn: (key: string) => api.revealKey(name, key) })
}

export function useSetSettings(name: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (set: Record<string, unknown>) => api.setSettings(name, set),
    onSuccess: () => invalidateProject(qc, name),
  })
}

export function useSetPreset(name: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (preset: string) => api.setPreset(name, preset),
    onSuccess: () => invalidateProject(qc, name),
  })
}

export function useCheckSettings(name: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api.checkSettings(name),
    onSuccess: () => void qc.invalidateQueries({ queryKey: keys.settings(name) }),
  })
}

export function usePlan(name: string) {
  return useMutation({ mutationFn: (overrides: Overrides) => api.plan(name, overrides) })
}

export function useSaveDefaults(name: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (overrides: Overrides) => api.saveDefaults(name, overrides),
    onSuccess: () => invalidateProject(qc, name),
  })
}

export function useStartRun(name: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: StartRunBody) => api.startRun(name, body),
    onSuccess: () => invalidateProject(qc, name),
  })
}

export function useStopRun(project: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (runId: string) => api.stopRun(project, runId),
    onSuccess: (_d, runId) => {
      invalidateProject(qc, project)
      void qc.invalidateQueries({ queryKey: keys.run(project, runId) })
    },
  })
}

export function useDiscardRun(project: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ runId, force = false }: { runId: string; force?: boolean }) =>
      api.discardRun(project, runId, force),
    onSuccess: (_d, { runId }) => {
      invalidateProject(qc, project)
      void qc.invalidateQueries({ queryKey: keys.run(project, runId) })
    },
  })
}

export const useGateReview = (id: string) =>
  useQuery({ queryKey: ["gate-review", id], queryFn: () => api.gateReview(id), staleTime: 30_000 })

export function useAnswerGate(project?: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (v: { id: string; action: GateAction; note?: string }) => api.answerGate(v.id, v.action, v.note ?? ""),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.gates() })
      void qc.invalidateQueries({ queryKey: keys.projects() })
      if (project) invalidateProject(qc, project)
      void qc.invalidateQueries({ queryKey: ["run"] })
    },
  })
}

/** The chat state of one project. */
export const useChat = (name: string) =>
  useQuery({ queryKey: keys.chat(name), queryFn: () => api.getChat(name), enabled: !!name })

/** Open (start or wake) a project's chat, then refresh the projects list. */
export function useOpenChat() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (name: string) => api.openChat(name),
    onSettled: (_data, _err, name) => {
      void qc.invalidateQueries({ queryKey: keys.projects() })
      void qc.invalidateQueries({ queryKey: keys.chat(name) })
    },
  })
}
