// Slide 1: build from a spec in the project's notes, or from a brief the Planner turns into a spec.
import { Icon } from "@/components/Icon"
import { Textarea } from "@/components/ui/textarea"

import { Choices } from "./Choice"
import type { SlideProps } from "./Wizard"

/** Spec or brief, then the spec list (from the real specs API) or the brief box. */
export function SlideWhat({ state, dispatch, specs }: SlideProps) {
  const a = state.answers
  const sorted = [...specs].sort((x, y) => y.modified.localeCompare(x.modified))
  return (
    <div className="stackg">
      <span className="lbl">What should this build work from?</span>
      <Choices
        name="wz-source" label="What to build" value={a.source}
        onChange={(v) => dispatch({ type: "source", source: v as "spec" | "brief" })}
        options={[
          { value: "spec", label: "Use a spec", help: "Build from a spec file in the project's notes/specs folder." },
          { value: "brief", label: "Write a brief for the Planner", help: "The Planner turns your brief into a spec; you approve it before building." },
        ]}
      />
      {a.source === "spec" ? (
        sorted.length ? (
          <>
            <span className="lbl" style={{ marginTop: 8 }}>Choose a spec</span>
            <Choices
              name="wz-spec" label="Spec" value={a.spec} onChange={(path) => dispatch({ type: "spec", path })}
              options={sorted.map((s) => ({
                value: s.path, label: s.title, icon: <Icon name="file-text" size="sm" />,
                help: <span className="mono">{s.path} · {s.modified.slice(0, 10)}</span>,
              }))}
            />
          </>
        ) : (
          <p className="small">No specs yet. Put one in the project's notes/specs folder, or write a brief instead.</p>
        )
      ) : (
        <div className="field" style={{ marginTop: 8 }}>
          <label htmlFor="wz-brief">Brief</label>
          <Textarea
            id="wz-brief" rows={5} value={a.brief} placeholder="What should be built?"
            onChange={(e) => dispatch({ type: "brief", text: e.target.value })}
          />
          <span className="help">The Planner stays switched on for this build.</span>
        </div>
      )}
    </div>
  )
}
