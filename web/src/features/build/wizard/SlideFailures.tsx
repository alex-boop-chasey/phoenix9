// Slide 5: how many tries a task gets, and what happens when it still fails.
import { ON_FAILURE } from "@/features/settings/BuildSection"

import { Choices } from "./Choice"
import type { OnFailure } from "./model"
import type { SlideProps } from "./Wizard"

/** Retries and the on-failure mode, each mode explained. */
export function SlideFailures({ state, dispatch }: SlideProps) {
  const a = state.answers
  return (
    <div className="stackg">
      <div className="field" style={{ maxWidth: 220 }}>
        <label htmlFor="wz-max-tries">Tries per task (1 to 10)</label>
        <input
          id="wz-max-tries" className="input" type="number" min={1} max={10} step={1}
          value={Number.isNaN(a.maxTries) ? "" : String(a.maxTries)}
          onChange={(e) => dispatch({ type: "maxTries", value: e.target.value === "" ? Number.NaN : Number(e.target.value) })}
        />
      </div>
      <span className="lbl" style={{ marginTop: 8 }}>When a task still fails</span>
      <Choices
        name="wz-failure" label="On failure" value={a.onFailure}
        onChange={(v) => dispatch({ type: "onFailure", value: v as OnFailure })}
        options={ON_FAILURE.map((o) => ({ value: o.value, label: o.label, help: o.help }))}
      />
    </div>
  )
}
