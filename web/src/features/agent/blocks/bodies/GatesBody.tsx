// Body of the gates card: the open questions as the same Needs-you cards the dashboard shows.
import { NeedsYouCard } from "@/features/gates/NeedsYouCard"
import type { Gate } from "@/lib/types"

import type { CardBodyProps } from "../cardBodies"

/** The Needs-you cards of a gates card; read-only (no answer buttons) when the card is frozen. */
export function GatesBody({ data, frozen = false }: CardBodyProps) {
  const gates = (Array.isArray(data) ? data : []) as Gate[]
  if (gates.length === 0) return <p className="muted" data-testid="gates-empty">Nothing is waiting for you.</p>
  return (
    <div className="flex flex-col gap-3" data-testid="card-gates">
      {gates.map((g) => (
        <NeedsYouCard key={g.id} gate={g} compact readOnly={frozen} reviewHref={`/p/${encodeURIComponent(g.project)}/build?run=${encodeURIComponent(g.run)}`} />
      ))}
    </div>
  )
}
