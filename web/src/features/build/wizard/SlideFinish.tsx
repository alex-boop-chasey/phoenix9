// Slide 6: what happens after the tasks: merge (auto or ask), deploy, notifications.
import { MERGE } from "@/features/settings/BuildSection"

import { Choices, SwitchRow } from "./Choice"
import { deployerChosen, mergeLocked, type MergeMode } from "./model"
import type { SlideProps } from "./Wizard"

/** Merge, deploy and notifications. */
export function SlideFinish({ project, state, dispatch, baseline }: SlideProps) {
  const a = state.answers
  const locked = mergeLocked(project)
  const canDeploy = deployerChosen(baseline?.settings.deploy)
  return (
    <div className="stackg">
      <span className="lbl">Merge</span>
      <Choices
        name="wz-merge" label="Merge" value={a.merge} disabled={locked}
        onChange={(v) => dispatch({ type: "merge", value: v as MergeMode })}
        options={MERGE.map((o) => ({ value: o.value, label: o.label, help: o.help }))}
      />
      {locked && <p className="small">Phoenix's own project always asks before merging.</p>}
      <span className="lbl" style={{ marginTop: 8 }}>After the build</span>
      <div className="rail choices">
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
    </div>
  )
}
