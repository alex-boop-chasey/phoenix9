// The wizard's answers and slide, kept per project in localStorage for a day, so leaving the Build tab
// (or a refused start) never loses them. Storage may be unavailable: every call is wrapped and optional.
import type { SpecFile } from "@/lib/types"

import { SLIDE_COUNT, chooseSpec, type WizardState } from "./model"

export const SAVED_MAX_AGE_MS = 24 * 60 * 60 * 1000
const key = (project: string) => `phoenix9.wizard.${project}`

type Saved = Pick<WizardState, "slide" | "seen" | "answers" | "remember">

/** Keep the wizard's state for this project (the error line is not kept). */
export function saveWizard(project: string, state: WizardState, now = Date.now()) {
  try {
    const { slide, seen, answers, remember } = state
    localStorage.setItem(key(project), JSON.stringify({ at: now, state: { slide, seen, answers, remember } }))
  } catch {
    // ignore: keeping the wizard is only a convenience
  }
}

/** Forget the kept wizard (a build started, Cancel, or Start over). */
export function clearWizard(project: string) {
  try {
    localStorage.removeItem(key(project))
  } catch {
    // ignore
  }
}

/**
 * The kept wizard state, or null when there is none, it is older than a day, or it is unreadable.
 * A kept spec that no longer exists is dropped (the rest stays) and the wizard opens on the spec picker.
 */
export function loadWizard(project: string, specs: SpecFile[], now = Date.now()): Saved | null {
  try {
    const raw = localStorage.getItem(key(project))
    if (!raw) return null
    const data = JSON.parse(raw) as { at?: number; state?: Saved }
    const s = data.state
    if (typeof data.at !== "number" || now - data.at > SAVED_MAX_AGE_MS || !s || typeof s.answers !== "object"
      || !s.answers || typeof s.answers.steps !== "object") {
      clearWizard(project)
      return null
    }
    const slide = Number.isInteger(s.slide) ? Math.min(Math.max(s.slide, 1), SLIDE_COUNT) : 1
    const seen = Number.isInteger(s.seen) ? Math.min(Math.max(s.seen, slide), SLIDE_COUNT) : slide
    let answers = s.answers
    if (answers.spec && !specs.some((f) => f.path === answers.spec)) {
      answers = chooseSpec(answers, "", false)
      return { slide: 1, seen, answers, remember: !!s.remember }
    }
    return { slide, seen, answers, remember: !!s.remember }
  } catch {
    return null
  }
}
