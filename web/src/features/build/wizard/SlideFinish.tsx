// Slide 6: what happens after the tasks: merge (auto or ask), deploy, notifications.
import { Label } from "@/components/ui/label"
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group"
import { Switch } from "@/components/ui/switch"
import { MERGE } from "@/features/settings/BuildSection"

import { deployerChosen, mergeLocked, type MergeMode } from "./model"
import type { SlideProps } from "./Wizard"

/** One labelled switch row with a help line. */
function SwitchRow({ id, label, help, checked, disabled, onChange }: {
  id: string; label: string; help: string; checked: boolean; disabled?: boolean; onChange: (on: boolean) => void
}) {
  return (
    <div className="flex items-start gap-3">
      <span className="flex min-h-11 min-w-11 items-center justify-center">
        <Switch id={id} aria-label={label} checked={checked} disabled={disabled} onCheckedChange={onChange} />
      </span>
      <Label htmlFor={id} className="flex-col items-start gap-0 pt-2.5 font-normal">
        <span className="font-medium">{label}</span>
        <span className="text-sm text-muted-foreground">{help}</span>
      </Label>
    </div>
  )
}

/** Merge, deploy and notifications. */
export function SlideFinish({ project, state, dispatch, baseline }: SlideProps) {
  const a = state.answers
  const locked = mergeLocked(project)
  const canDeploy = deployerChosen(baseline?.settings.deploy)
  return (
    <div className="space-y-6">
      <section className="space-y-2" aria-label="Merge">
        <h3 className="font-semibold">Merge</h3>
        <RadioGroup
          value={a.merge} disabled={locked} aria-label="Merge"
          onValueChange={(v) => dispatch({ type: "merge", value: v as MergeMode })}
        >
          {MERGE.map((o) => (
            <div key={o.value} className="flex items-start gap-2">
              <RadioGroupItem value={o.value} id={`wz-mg-${o.value}`} className="mt-1" aria-label={o.label} />
              <Label htmlFor={`wz-mg-${o.value}`} className="flex-col items-start gap-0 font-normal">
                <span className="font-medium">{o.label}</span>
                <span className="text-sm text-muted-foreground">{o.help}</span>
              </Label>
            </div>
          ))}
        </RadioGroup>
        {locked && <p className="text-sm text-muted-foreground">Phoenix's own project always asks before merging.</p>}
      </section>
      <SwitchRow
        id="wz-deploy" label="Deploy" checked={canDeploy && a.deploy} disabled={!canDeploy}
        help={canDeploy ? "Deploy after a successful merge." : "Deployers come later."}
        onChange={(on) => dispatch({ type: "deploy", on })}
      />
      <SwitchRow
        id="wz-notify" label="Notifications" checked={a.steps.notify ?? true}
        help="Send a message when the build finishes or needs you."
        onChange={(on) => dispatch({ type: "notify", on })}
      />
    </div>
  )
}
