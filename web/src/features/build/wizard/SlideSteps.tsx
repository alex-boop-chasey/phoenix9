// Slide 3: the step rail with switches; changing one makes the preset Custom, and reasons and errors show.
import { Icon } from "@/components/Icon"
import { InfoBlock } from "@/components/InfoBlock"
import { Skeleton } from "@/components/ui/skeleton"
import { Tag } from "@/components/Tag"
import { useLibrarySteps } from "@/lib/queries"
import { cn } from "@/lib/utils"

import { GROUP_TITLES, planInOrder, presetLabel, shownOn, stepNote } from "./model"
import type { SlideProps } from "./Wizard"

/** The editable step rail. */
export function SlideSteps({ state, dispatch, plan, presets }: SlideProps) {
  const a = state.answers
  const library = useLibrarySteps()
  if (!plan) return <Skeleton className="h-40 w-full" />
  const description = (name: string) => library.data?.steps.find((s) => s.name === name)?.description ?? ""
  const forced = plan.steps.filter((s) => !s.on && s.reason.startsWith("needs "))
  const always = planInOrder(plan.steps).flatMap((g) => g.steps.filter((s) => s.default === "always"))
  return (
    <div className="stackg">
      <p className="small">
        Preset: <b>{presetLabel(a, presets)}</b>
        {a.preset === "custom" ? " (your own mix of steps)" : " (changing a step makes the preset Custom)"}
      </p>
      {plan.errors.length > 0 && (
        <InfoBlock tone="bad">
          <b>These steps can't run together</b>
          <ul className="list-disc pl-4">{plan.errors.map((e) => <li key={e}>{e}</li>)}</ul>
        </InfoBlock>
      )}
      {forced.length > 0 && (
        <InfoBlock>
          <b>Switched off by another step</b>
          <ul className="list-disc pl-4">{forced.map((s) => <li key={s.name}>{s.title}: {s.reason}</li>)}</ul>
        </InfoBlock>
      )}
      {always.length > 0 && (
        <section className="always" aria-label="Always runs">
          <h3>Always runs</h3>
          <ul>
            {always.map((s) => (
              <li key={s.name} data-step={s.name}>
                <b>{s.title}</b>
                {description(s.name) && <small>{description(s.name)}</small>}
              </li>
            ))}
          </ul>
        </section>
      )}
      <div className="rail">
        {planInOrder(plan.steps.filter((s) => s.default !== "always")).map((g) => g.steps.length > 0 && (
          <section key={g.group} aria-label={GROUP_TITLES[g.group]} className="contents">
            <h3 className="rail-h">{g.title}</h3>
            {g.steps.map((s) => {
              const forcedOff = !s.on && s.reason.startsWith("needs ")
              const briefLock = s.name === "planner" && a.source === "brief"
              const on = shownOn(s, a)
              const note = stepNote(s, a, plan.steps)
              const id = `wz-step-${s.name}`
              return (
                <label key={s.name} htmlFor={id} data-step={s.name} className={cn("rrow", forcedOff && "off")}>
                  <span className="node" style={{ width: 12, height: 12, marginLeft: 5 }} />
                  <span className="rt">
                    <b>
                      <Icon name={s.kind === "ai" ? "sparkle" : "terminal"} size="sm" />{s.title}
                      <Tag>{s.kind === "ai" ? "AI" : s.kind}</Tag>
                      {!!s.safety && <Tag tone="safety"><Icon name="shield-check" />Safety</Tag>}
                    </b>
                    {description(s.name) && <small>{description(s.name)}</small>}
                    {note && (forcedOff ? <span className="reason"><Icon name="warning-circle" size="xs" />{note}</span> : <span className="note">{note}</span>)}
                  </span>
                  <span className="rr">
                    <input
                      id={id} type="checkbox" role="switch" className="switch" aria-label={s.title}
                      checked={on} disabled={forcedOff || briefLock}
                      onChange={(e) => dispatch({ type: "step", name: s.name, on: e.target.checked })}
                    />
                  </span>
                </label>
              )
            })}
          </section>
        ))}
      </div>
    </div>
  )
}
