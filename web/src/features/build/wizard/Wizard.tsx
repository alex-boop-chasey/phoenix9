// The build wizard: seven Next/Back slides over one reducer, then Submit (remember defaults, start the run).
import { useEffect, useMemo, useReducer, useRef, useState, type ComponentType, type Dispatch } from "react"

import { ErrorState } from "@/components/ErrorState"
import { Button } from "@/components/ui/button"
import { Icon } from "@/components/Icon"
import { Skeleton } from "@/components/ui/skeleton"
import { sameValue } from "@/features/settings/dotted"
import { useSaveDefaults, useStartRun } from "@/lib/queries"
import type { LibraryStep, PlanView, Preset, SettingsView, SpecFile } from "@/lib/types"

import {
  SLIDE_COUNT, SLIDE_TITLES, aiCards, canSubmit, presetLabel, shownOn, initialAnswers, reduce, startBody, startState, toOverrides, validateSlide,
  type Action, type WizardState,
} from "./model"
import { SlideFailures } from "./SlideFailures"
import { SlideFinish } from "./SlideFinish"
import { SlideModels } from "./SlideModels"
import { SlidePreset } from "./SlidePreset"
import { SlideReview } from "./SlideReview"
import { SlideSteps } from "./SlideSteps"
import { SlideWhat } from "./SlideWhat"
import { PLAN_DEBOUNCE_MS, useDebounced, usePlanFor, useWizardData } from "./useWizardData"

/** What every slide gets: the state, a way to change it, and the loaded data. */
export interface SlideProps {
  project: string
  state: WizardState
  dispatch: Dispatch<Action>
  /** The effective plan for the current answers (debounced). */
  plan: PlanView | undefined
  /** The plan for the chosen preset with no edits. */
  baseline: PlanView | undefined
  presets: Preset[]
  specs: SpecFile[]
}

const SLIDES: ComponentType<SlideProps>[] = [
  SlideWhat, SlidePreset, SlideSteps, SlideModels, SlideFailures, SlideFinish, SlideReview,
]

interface Props {
  name: string
  /** Slide to open on (from a deep link); 1 by default. */
  startSlide?: number
  onCancel: () => void
  onStarted: (runId: string) => void
}

/** Loads what the wizard needs, then shows it. */
export function Wizard(props: Props) {
  const data = useWizardData(props.name)
  if (data.error) return <ErrorState error={data.error} onRetry={data.retry} />
  if (!data.ready || !data.settings) return <Skeleton className="h-64 w-full" />
  return <WizardForm {...props} settings={data.settings} presets={data.presets} steps={data.steps} specs={data.specs} />
}

function WizardForm({
  name, startSlide = 1, onCancel, onStarted, settings, presets, steps, specs,
}: Props & { settings: SettingsView; presets: Preset[]; steps: LibraryStep[]; specs: SpecFile[] }) {
  const base = useMemo(() => ({ project: name, steps }), [name, steps])
  const [state, dispatch] = useReducer(
    (s: WizardState, a: Action) => reduce(s, a, base),
    undefined,
    () => ({ ...startState(initialAnswers(settings, presets, steps)), slide: startSlide, seen: startSlide }),
  )
  const a = state.answers
  const basePreset = a.preset === "custom" ? (a.basedOn ?? "quick") : a.preset
  const baseline = usePlanFor(name, { preset: basePreset })
  const overrides = useMemo(() => toOverrides(a, { ...base, baseline: baseline.data }), [a, base, baseline.data])
  const debounced = useDebounced(overrides, PLAN_DEBOUNCE_MS)
  const plan = usePlanFor(name, debounced)
  const saveDefaults = useSaveDefaults(name)
  const startRun = useStartRun(name)
  const [busy, setBusy] = useState(false)
  const top = useRef<HTMLDivElement>(null)
  const heading = useRef<HTMLHeadingElement>(null)
  const shownSlide = useRef(state.slide)

  // Every step change lands on the progress header (below the sticky header) with focus on the step title.
  useEffect(() => {
    if (shownSlide.current === state.slide) return
    shownSlide.current = state.slide
    top.current?.scrollIntoView?.({ block: "start" })
    heading.current?.focus({ preventScroll: true })
  }, [state.slide])

  const problems = validateSlide(state.slide, a, plan.data)
  // On the Steps slide, Next waits until the step list matches the latest switches (no slipping past an error).
  const updating = state.slide === 3 && (!sameValue(debounced, overrides) || plan.isFetching)
  const last = state.slide === SLIDE_COUNT
  const Slide = SLIDES[state.slide - 1]!

  async function submit() {
    setBusy(true)
    const final = toOverrides(a, { ...base, baseline: baseline.data })
    try {
      if (state.remember) await saveDefaults.mutateAsync(final)
      const started = await startRun.mutateAsync(startBody(a, final))
      onStarted(started.run_id)
    } catch (err) {
      dispatch({ type: "error", message: err instanceof Error && err.message ? err.message : "Something went wrong." })
    } finally {
      setBusy(false)
    }
  }

  const outline = outlineNotes(state, plan.data, presets, specs)
  const showProblem = state.slide !== 3 && problems.length > 0

  return (
    <>
      <div className="wiz" ref={top}>
        <ol className="outline" aria-label="Build wizard steps">
          {SLIDE_TITLES.map((title, i) => {
            const n = i + 1
            const reachable = n <= state.seen
            return (
              <li key={title}>
                <button
                  type="button" className={n < state.slide ? "done" : ""} data-slide={n}
                  aria-current={n === state.slide ? "step" : undefined} disabled={!reachable || busy}
                  onClick={() => dispatch({ type: "goto", slide: n })}
                >
                  <span className="num">{n < state.slide ? <Icon name="check" size="xs" /> : n}</span>
                  <b>{title}</b>
                  {reachable && outline[i] && <small>{outline[i]}</small>}
                </button>
              </li>
            )
          })}
        </ol>
        <div className="wmain">
        <div className="wprog" data-testid="wizard-progress">
          <p className="small">Step {state.slide} of {SLIDE_COUNT}<span className="wp-title"> · {SLIDE_TITLES[state.slide - 1]}</span></p>
          <div className="wbar" role="progressbar" aria-label="Wizard progress" aria-valuemin={1} aria-valuemax={SLIDE_COUNT} aria-valuenow={state.slide}>
            {SLIDE_TITLES.map((title, i) => (
              <span key={title} className={i + 1 < state.slide ? "done" : i + 1 === state.slide ? "now" : ""} />
            ))}
          </div>
        </div>
        <section className="canvas" aria-label="Build wizard">
          <div className="canvas-h">
            <div>
              <h2 className="h2" ref={heading} tabIndex={-1}>{SLIDE_TITLES[state.slide - 1]}</h2>
            </div>
            <span className="area"><Icon name="hammer" />Build</span>
          </div>
          <Slide
            project={name} state={state} dispatch={dispatch} plan={plan.data} baseline={baseline.data}
            presets={presets} specs={specs}
          />
        </section>
        </div>
      </div>
      <div className="wdock">
        <Button variant="ghost" onClick={onCancel}>Cancel</Button>
        <span className="prob" aria-live="polite">
          {showProblem && <><Icon name="info" size="sm" /><span role="status">{problems.join(" ")}</span></>}
        </span>
        <Button variant="secondary" disabled={state.slide === 1 || busy} onClick={() => dispatch({ type: "back" })}>
          <Icon name="arrow-left" />Back
        </Button>
        {last ? (
          <Button disabled={busy || !canSubmit(a, plan.data, baseline.data)} onClick={() => void submit()}>
            {busy ? <span className="wheel" aria-hidden /> : <Icon name="rocket-launch" />}
            Start build
          </Button>
        ) : (
          <Button disabled={problems.length > 0 || updating} onClick={() => dispatch({ type: "next" })}>
            Next<Icon name="arrow-right" />
          </Button>
        )}
      </div>
    </>
  )
}

/** The short line under each outline step once it has been seen. */
function outlineNotes(state: WizardState, plan: PlanView | undefined, presets: Preset[], specs: SpecFile[]): string[] {
  const a = state.answers
  const off = plan ? plan.steps.filter((s) => !shownOn(s, a)).length : 0
  const on = plan ? plan.steps.length - off : 0
  const ai = plan ? aiCards(plan.steps, a).length : 0
  const spec = specs.find((s) => s.path === a.spec)?.title
  return [
    a.source === "brief" ? "A brief for the Planner" : (spec ?? ""),
    presetLabel(a, presets),
    plan ? `${on} steps, ${off} off` : "",
    plan ? `${ai} AI steps` : "",
    Number.isNaN(a.maxTries) ? "" : `${a.maxTries} tries`,
    a.merge === "ask" ? "Ask before merging" : "Merge automatically",
    "",
  ]
}
