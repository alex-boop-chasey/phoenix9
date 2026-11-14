// Follow the agent's `ui.go` events: move the dashboard while the Agent panel is open, ignore them when it is closed.
import { useCallback, useState } from "react"

import { navigateKeepingPanel } from "@/lib/navigate"
import type { PhoenixEvent } from "@/lib/types"

/** The last move the agent made: where it went and the hash shown just before. */
export interface UiMove { label: string; from: string }

/** Returns the last move (or null), the event handler for `useLiveEvents`, and a Back action. */
export function useUiGo(open: boolean) {
  const [moved, setMoved] = useState<UiMove | null>(null)

  const onEvent = useCallback((ev: PhoenixEvent) => {
    if (ev.type !== "ui.go" || !open) return
    const hash = ev.data?.hash
    if (typeof hash !== "string" || !hash.startsWith("#/")) return
    const from = window.location.hash
    navigateKeepingPanel(hash)
    setMoved({ label: typeof ev.data.label === "string" && ev.data.label ? ev.data.label : "another page", from })
  }, [open])

  const back = useCallback(() => {
    if (moved) navigateKeepingPanel(moved.from || "#/")
    setMoved(null)
  }, [moved])

  return { moved, onEvent, back }
}
