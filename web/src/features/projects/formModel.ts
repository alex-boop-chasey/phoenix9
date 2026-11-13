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
  /** A ready-made starter picked under Framework (only with an Empty source). */
  framework: string
  path: string
  profile: string
  newRepo: boolean
  owner: string
  services: string[]
}

export const emptyForm: FormValues = {
  name: "", description: "", source: "empty", repo: "", template: "", framework: "", path: "", profile: "",
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

/** Whether the Framework picker is used: only an empty project scaffolds a starter. */
export const frameworkApplies = (source: SourceKind) => source === "empty"

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
  if (v.source === "empty" && v.framework) {
    source.kind = "template"
    source.template = v.framework
  }
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

/** The New project wizard's slides, in order, with the note shown under each in the outline. */
export const NEW_SLIDES = [
  { title: "Name and source", note: "Name, code and repo" },
  { title: "Type and services", note: "What it is and what it uses" },
  { title: "Keys", note: "Values the project needs" },
] as const

/** Something still missing, the slide it is on, and where to send the cursor. */
export interface Missing {
  slide: number
  text: string
  target: string
  focus: string
}

/** What is still missing on one slide of the New project wizard (empty when Next can go on). */
export function slideMissing(n: number, v: FormValues, nameOk: boolean, pending: boolean): Missing[] {
  const out: Missing[] = []
  if (n === 1) {
    if (!nameOk) out.push({ slide: 1, text: "Choose a name that is free.", target: "np-step-name", focus: "pf-name" })
    if (!sourceComplete(v)) {
      const what = v.source === "repo" ? "Choose the GitHub repo." : v.source === "template" ? "Type the GitHub template, owner/name." : "Type the folder path."
      out.push({ slide: 1, text: what, target: "np-step-source", focus: v.source === "code" ? "pf-path" : "" })
    }
  }
  if (n === 2 && !v.profile) out.push({ slide: 2, text: "Choose a type.", target: "np-step-services", focus: "" })
  if (n === 3 && pending) out.push({ slide: 3, text: "Press Save under Project keys before creating.", target: "np-step-keys", focus: "" })
  return out
}

/** Everything still missing before Create can run, slide by slide. */
export function allMissing(v: FormValues, nameOk: boolean, pending: boolean): Missing[] {
  return NEW_SLIDES.flatMap((_, i) => slideMissing(i + 1, v, nameOk, pending))
}
