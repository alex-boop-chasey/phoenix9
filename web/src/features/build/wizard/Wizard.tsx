// The build wizard: seven Next/Back slides over one reducer, then Submit (remember defaults, start the run).
import { Loader2 } from "lucide-react"
import { useMemo, useReducer, useState, type ComponentType, type Dispatch } from "react"

import { ErrorState } from "@/components/ErrorState"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { sameValue } from "@/features/settings/dotted"
import { useSaveDefaults, useStartRun } from "@/lib/queries"
import type { LibraryStep, PlanView, Preset, SettingsView, SpecFile } from "@/lib/types"

import {
  SLIDE_COUNT, SLIDE_TITLES, canSubmit, initialAnswers, reduce, startBody, startState, toOverrides, validateSlide,
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
  name, onCancel, onStarted, settings, presets, steps, specs,
}: Props & { settings: SettingsView; presets: Preset[]; steps: LibraryStep[]; specs: SpecFile[] }) {
  const base = useMemo(() => ({ project: name, steps }), [name, steps])
  const [state, dispatch] = useReducer(
    (s: WizardState, a: Action) => reduce(s, a, base),
    undefined,
    () => startState(initialAnswers(settings, presets, steps)),
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

  return (
    <Card aria-label="Build wizard">
      <CardHeader className="gap-1">
        <p className="text-sm text-muted-foreground">Step {state.slide} of {SLIDE_COUNT}</p>
        <CardTitle className="text-xl"><h2>{SLIDE_TITLES[state.slide - 1]}</h2></CardTitle>
      </CardHeader>
      <CardContent className="min-w-0">
        <Slide
          project={name} state={state} dispatch={dispatch} plan={plan.data} baseline={baseline.data}
          presets={presets} specs={specs}
        />
        {state.slide !== 3 && problems.length > 0 && (
          <p className="mt-4 text-sm text-muted-foreground" role="status">{problems.join(" ")}</p>
        )}
      </CardContent>
      <CardFooter className="flex flex-wrap items-center justify-between gap-2">
        <Button variant="ghost" onClick={onCancel}>Cancel</Button>
        <div className="flex gap-2">
          <Button variant="outline" disabled={state.slide === 1 || busy} onClick={() => dispatch({ type: "back" })}>Back</Button>
          {last ? (
            <Button disabled={busy || !canSubmit(a, plan.data, baseline.data)} onClick={() => void submit()}>
              {busy && <Loader2 className="animate-spin" aria-hidden />}
              Submit
            </Button>
          ) : (
            <Button disabled={problems.length > 0 || updating} onClick={() => dispatch({ type: "next" })}>Next</Button>
          )}
        </div>
      </CardFooter>
    </Card>
  )
}
