// Slide 1: build from a spec in the project's notes, or from a brief the Planner turns into a spec.
import { Label } from "@/components/ui/label"
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"

import type { SlideProps } from "./Wizard"

/** Spec or brief. */
export function SlideWhat({ state, dispatch, specs }: SlideProps) {
  const a = state.answers
  const sorted = [...specs].sort((x, y) => y.modified.localeCompare(x.modified))
  return (
    <div className="space-y-4">
      <RadioGroup
        value={a.source} aria-label="What to build"
        onValueChange={(v) => dispatch({ type: "source", source: v as "spec" | "brief" })}
      >
        <div className="flex items-center gap-2">
          <RadioGroupItem value="spec" id="wz-src-spec" />
          <Label htmlFor="wz-src-spec">Use a spec</Label>
        </div>
        <div className="flex items-center gap-2">
          <RadioGroupItem value="brief" id="wz-src-brief" />
          <Label htmlFor="wz-src-brief">Write a brief for the Planner</Label>
        </div>
      </RadioGroup>

      {a.source === "spec" ? (
        sorted.length ? (
          <div className="space-y-1">
            <Label htmlFor="wz-spec">Spec</Label>
            <Select value={a.spec} onValueChange={(v) => dispatch({ type: "spec", path: v })}>
              <SelectTrigger id="wz-spec" aria-label="Spec" className="w-full max-w-full md:w-96">
                <SelectValue placeholder="Choose a spec" />
              </SelectTrigger>
              <SelectContent>
                {sorted.map((s) => (
                  <SelectItem key={s.path} value={s.path}>{`${s.title} (${s.path})`}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            No specs yet. Put one in the project's notes/specs folder, or write a brief instead.
          </p>
        )
      ) : (
        <div className="space-y-1">
          <Label htmlFor="wz-brief">Brief</Label>
          <Textarea
            id="wz-brief" rows={5} value={a.brief} placeholder="What should be built?"
            onChange={(e) => dispatch({ type: "brief", text: e.target.value })}
          />
          <p className="text-sm text-muted-foreground">
            The Planner turns your brief into a spec; you approve it before building.
          </p>
        </div>
      )}
    </div>
  )
}
