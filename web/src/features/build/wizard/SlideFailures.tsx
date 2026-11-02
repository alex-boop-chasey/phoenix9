// Slide 5: how many tries a task gets, and what happens when it still fails.
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group"

import { ON_FAILURE } from "@/features/settings/BuildSection"

import type { OnFailure } from "./model"
import type { SlideProps } from "./Wizard"

/** Retries and the on-failure mode, each mode explained. */
export function SlideFailures({ state, dispatch }: SlideProps) {
  const a = state.answers
  return (
    <div className="space-y-6">
      <div className="space-y-1">
        <Label htmlFor="wz-max-tries">Tries per task (1 to 10)</Label>
        <Input
          id="wz-max-tries" type="number" min={1} max={10} step={1} className="w-24"
          value={Number.isNaN(a.maxTries) ? "" : String(a.maxTries)}
          onChange={(e) => dispatch({ type: "maxTries", value: e.target.value === "" ? Number.NaN : Number(e.target.value) })}
        />
      </div>
      <section className="space-y-2" aria-label="When a task still fails">
        <h3 className="font-semibold">When a task still fails</h3>
        <RadioGroup
          value={a.onFailure} aria-label="On failure"
          onValueChange={(v) => dispatch({ type: "onFailure", value: v as OnFailure })}
        >
          {ON_FAILURE.map((o) => (
            <div key={o.value} className="flex items-start gap-2">
              <RadioGroupItem value={o.value} id={`wz-of-${o.value}`} className="mt-1" aria-label={o.label} />
              <Label htmlFor={`wz-of-${o.value}`} className="flex-col items-start gap-0 font-normal">
                <span className="font-medium">{o.label}</span>
                <span className="text-sm text-muted-foreground">{o.help}</span>
              </Label>
            </div>
          ))}
        </RadioGroup>
      </section>
    </div>
  )
}
