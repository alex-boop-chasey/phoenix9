// The values of the project form, and how they turn into the create request.
import type { CreateForm, KeyInput } from "@/lib/types"

export type SourceKind = "empty" | "repo" | "template" | "code"

export interface FormValues {
  name: string
  /** Not asked on New project; project Settings edits it. */
  description: string
  source: SourceKind
  repo: string
  template: string
  path: string
  profile: string
  newRepo: boolean
  owner: string
  services: string[]
}

export const emptyForm: FormValues = {
  name: "", description: "", source: "empty", repo: "", template: "", path: "", profile: "web",
  newRepo: true, owner: "", services: [],
}

export const NAME_RE = /^[a-z0-9][a-z0-9-]{0,40}$/
export const PROFILES = ["web", "mobile", "desktop", "python-script", "research", "platform"]

const OWNER_KEY = "phoenix9.newRepoOwner"

/** The owner picked last time, or "" (localStorage may be unavailable). */
export function rememberedOwner(): string {
  try {
    return localStorage.getItem(OWNER_KEY) ?? ""
  } catch {
    return ""
  }
}

/** Remember the chosen owner for next time. */
export function rememberOwner(owner: string) {
  try {
    localStorage.setItem(OWNER_KEY, owner)
  } catch {
    // ignore: remembering is only a convenience
  }
}

/** Whether the source part of the form is filled in. */
export function sourceComplete(v: FormValues): boolean {
  if (v.source === "repo") return !!v.repo
  if (v.source === "template") return !!v.template.trim()
  if (v.source === "code") return !!v.path.trim()
  return true
}

/** Whether a new GitHub repo can be asked for with this source. */
export const newRepoApplies = (source: SourceKind) => source === "empty" || source === "template"

/** Build the documented create body. */
export function toCreateForm(v: FormValues, keys: KeyInput[], githubConnected: boolean): CreateForm {
  const source: CreateForm["source"] = { kind: v.source }
  if (v.source === "repo") source.repo = v.repo
  if (v.source === "template") source.template = v.template.trim()
  if (v.source === "code") source.path = v.path.trim()
  const on = githubConnected && newRepoApplies(v.source) && v.newRepo
  return {
    name: v.name, description: v.description, source, profile: v.profile,
    new_repo: on ? { on: true, owner: v.owner } : { on: false, owner: "" },
    services: v.services, keys,
  }
}
