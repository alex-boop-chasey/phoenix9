// Slide 2: Simple / Quick / Full / Custom, with the effective step list for the current answers under them.
import { Label } from "@/components/ui/label"
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group"
import { Skeleton } from "@/components/ui/skeleton"
import { StepToggleList } from "@/features/settings/StepToggleList"

import { presetLabel, shownStepValues } from "./model"
import type { SlideProps } from "./Wizard"

/** Preset cards and the read-only step list they lead to. */
export function SlidePreset({ state, dispatch, plan, presets }: SlideProps) {
  const a = state.answers
  return (
    <div className="space-y-6">
      <RadioGroup
        value={a.preset} aria-label="Preset" className="grid gap-3 md:grid-cols-2"
        onValueChange={(v) => {
          const p = presets.find((x) => x.name === v)
          if (p) dispatch({ type: "preset", preset: p })
        }}
      >
        {presets.map((p) => (
          <Label
            key={p.name} htmlFor={`wz-preset-${p.name}`}
            className="flex cursor-pointer items-start gap-3 rounded-lg border p-3 font-normal has-[[data-state=checked]]:border-primary"
          >
            <RadioGroupItem value={p.name} id={`wz-preset-${p.name}`} className="mt-1" aria-label={p.title} />
            <span className="flex min-w-0 flex-col gap-0.5">
              <span className="font-medium">{p.title}</span>
              <span className="text-sm text-muted-foreground">{p.description}</span>
            </span>
          </Label>
        ))}
      </RadioGroup>
      {a.preset === "custom" && <p className="text-sm text-muted-foreground">Preset: {presetLabel(a, presets)}</p>}
      <section className="space-y-2" aria-label="Effective steps">
        <h3 className="font-semibold">These steps will run</h3>
        {plan ? (
          <StepToggleList steps={plan.steps} values={shownStepValues(plan.steps, a)} onChange={() => {}} readOnly />
        ) : (
          <Skeleton className="h-40 w-full" />
        )}
      </section>
    </div>
  )
}
