// Placeholder for the confirm reply block; a later task fills it in.
import type { BlockProps } from "@/features/agent/blocks/types"

/** Shows a checked confirm block (placeholder). */
export function ConfirmBlock({ json, frozen = false }: BlockProps) {
  return <div className="ag-block ag-block-confirm" data-testid="block-confirm" data-frozen={frozen ? "true" : undefined}><pre className="ag-code mono"><code>{json}</code></pre></div>
}
