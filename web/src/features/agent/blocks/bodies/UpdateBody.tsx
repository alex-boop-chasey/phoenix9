// Body of the update card: installed and available version and the updater's state.
import type { UpdateStatus } from "@/lib/types"

import type { CardBodyProps } from "../cardBodies"

/** One plain sentence about the updater's state. */
function statusText(s: UpdateStatus): string {
  if (!s.supported) return "Updates are not supported here."
  if (s.running) return "An update is running."
  if (s.update_available) return "An update is available."
  return "Up to date."
}

/** Current and available version of an update card. */
export function UpdateBody({ data }: CardBodyProps) {
  const s = data as UpdateStatus | null
  if (!s || typeof s !== "object") return <p className="muted">No update information.</p>
  return (
    <dl className="m-0 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1" data-testid="card-update">
      <dt className="muted">Current</dt>
      <dd className="m-0" data-testid="update-current">{s.installed?.tag ?? "not installed"}</dd>
      <dt className="muted">Available</dt>
      <dd className="m-0" data-testid="update-available">{s.update_available && s.newest ? s.newest : "none"}</dd>
      <dt className="muted">Status</dt>
      <dd className="m-0" data-testid="update-status">{statusText(s)}</dd>
    </dl>
  )
}
