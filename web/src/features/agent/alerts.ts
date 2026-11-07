// Alerts for a closed Phoenix agent panel: a toast and an unread count when the agent replies.
import { useEffect, useRef, useState } from "react"
import { toast } from "sonner"

import { useAgentMessages, useAgentStream } from "@/features/agent/useAgent"

/** Keep the live stream running and count the agent's replies that arrive while the panel is closed. */
export function useAgentAlerts(open: boolean, show: () => void): number {
  const thread = useAgentMessages().data
  const [unread, setUnread] = useState(0)
  const seen = useRef<{ session: string | null; line: number } | null>(null)
  const showRef = useRef(show)
  showRef.current = show
  useAgentStream(true)

  useEffect(() => {
    if (!thread) return
    const lines = thread.items.filter((i) => i.type === "agent").map((i) => i.line)
    const top = Math.max(0, ...lines)
    const before = seen.current
    seen.current = { session: thread.session_id, line: top }
    if (!before) return
    const base = before.session === thread.session_id ? before.line : 0
    const fresh = lines.filter((n) => n > base).length
    if (fresh > 0 && !open) {
      setUnread((n) => n + fresh)
      toast("Phoenix agent replied", { action: { label: "Open", onClick: () => showRef.current() } })
    }
  }, [thread, open])

  useEffect(() => {
    if (open) setUnread(0)
  }, [open])

  return unread
}
