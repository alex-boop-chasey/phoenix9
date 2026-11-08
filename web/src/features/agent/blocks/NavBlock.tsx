// Placeholder for the nav reply block; a later task fills it in.
import type { BlockProps } from "@/features/agent/blocks/types"

/** Shows a checked nav block (placeholder). */
export function NavBlock({ json, frozen = false }: BlockProps) {
  return <div className="ag-block ag-block-nav" data-testid="block-nav" data-frozen={frozen ? "true" : undefined}><pre className="ag-code mono"><code>{json}</code></pre></div>
}
