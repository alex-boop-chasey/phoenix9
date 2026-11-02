// The live list of creation steps, one line each, with a spinner, tick or cross.
import { Check, Loader2, X } from "lucide-react"

import type { JobStep } from "@/lib/types"

/** One line per step so far; the list grows as the server reports each step. */
export function CreateProgress({ steps }: { steps: JobStep[] }) {
  return (
    <ul className="space-y-2" aria-label="Progress" aria-live="polite">
      {steps.length === 0 && <li className="text-sm text-muted-foreground">Starting…</li>}
      {steps.map((s, i) => (
        <li key={i} className="flex items-center gap-2 text-sm" data-status={s.status}>
          {s.status === "running" && <Loader2 className="size-4 animate-spin text-blue-500" data-testid="spinner" aria-label="Working" />}
          {s.status === "done" && <Check className="size-4 text-green-500" aria-label="Done" />}
          {s.status === "failed" && <X className="size-4 text-red-500" aria-label="Failed" />}
          <span>{s.label}</span>
        </li>
      ))}
    </ul>
  )
}
