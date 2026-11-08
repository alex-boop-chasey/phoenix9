// Placeholder for the choice reply block; a later task fills it in.
import type { BlockProps } from "@/features/agent/blocks/types"

/** Shows a checked choice block (placeholder). */
export function ChoiceBlock({ json, frozen = false }: BlockProps) {
  return <div className="ag-block ag-block-choice" data-testid="block-choice" data-frozen={frozen ? "true" : undefined}><pre className="ag-code mono"><code>{json}</code></pre></div>
}
