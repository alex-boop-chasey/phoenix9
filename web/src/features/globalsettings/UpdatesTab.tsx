// Phoenix settings > Updates: the update panel plus the update history.
import { UpdateHistory } from "@/features/updates/UpdateHistory"
import { UpdatePanel } from "@/features/updates/UpdatePanel"

/** The Updates panel. */
export function UpdatesTab() {
  return (
    <div className="gpanel" data-gp="updates">
      <UpdatePanel />
      <UpdateHistory />
    </div>
  )
}
