// Placeholder for the card reply block; a later task fills it in.
import type { BlockProps } from "@/features/agent/blocks/types"

/** Shows a checked card block (placeholder). */
export function AnswerCard({ json, frozen = false }: BlockProps) {
  return <div className="ag-block ag-block-card" data-testid="block-card" data-frozen={frozen ? "true" : undefined}><pre className="ag-code mono"><code>{json}</code></pre></div>
}
