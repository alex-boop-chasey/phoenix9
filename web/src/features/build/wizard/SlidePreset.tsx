// Slide 2: Simple / Quick / Full / Custom, with the "These steps will run" rail computed from the shared step state.
import { InfoBlock } from "@/components/InfoBlock"
import { Skeleton } from "@/components/ui/skeleton"

import { Choices } from "./Choice"
import { runSummary } from "./model"
import type { SlideProps } from "./Wizard"

/** Preset choices and the live list of what will run. */
export function SlidePreset({ state, dispatch, plan, presets }: SlideProps) {
  const a = state.answers
  const sum = plan ? runSummary(plan.steps, a, presets) : null
  return (
    <div className="stackg">
      <span className="lbl">Preset</span>
      <Choices
        name="wz-preset" label="Preset" value={a.preset}
        onChange={(v) => {
          const p = presets.find((x) => x.name === v)
          if (p) dispatch({ type: "preset", preset: p })
        }}
        options={presets.map((p) => ({ value: p.name, label: p.title, help: p.description }))}
      />
      <span className="lbl" style={{ marginTop: 8 }}>These steps will run</span>
      {sum ? (
        <div className="rail" role="list" aria-label="Effective steps">
          {sum.groups.map((g) => (
            <div className="rrow dot on locked" role="listitem" key={g.group} data-group={g.group}>
              <span className="node" />
              <span className="rt"><b>{g.names.join(" · ")}</b><small>{g.title}</small></span>
            </div>
          ))}
          {sum.off.names.length > 0 && (
            <div className="rrow dot locked" role="listitem" data-off>
              <span className="node" />
              <span className="rt"><b style={{ color: "var(--text-3)" }}>{sum.off.names.join(" · ")}</b><small>{sum.off.note}</small></span>
            </div>
          )}
          {sum.customHint && (
            <InfoBlock tone="tip" className="mt-2">
              <span>Custom: switch each step on or off on the next page, Steps.</span>
            </InfoBlock>
          )}
        </div>
      ) : (
        <Skeleton className="h-40 w-full" />
      )}
    </div>
  )
}
