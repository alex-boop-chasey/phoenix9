// The list of earlier conversations, newest first; clicking one opens it.
import { Button } from "@/components/ui/button"
import type { ThreadInfo } from "./runtime"

/** Say when a conversation was last used, in plain words. */
function lastUsed(seconds: number): string {
  return seconds ? new Date(seconds * 1000).toLocaleString() : "not yet"
}

/** The history list with New conversation on top. */
export function History(props: { threads: ThreadInfo[]; current: string; onOpen: (id: string) => void; onNew: () => void }) {
  return (
    <nav className="flex flex-col gap-2" aria-label="Conversations">
      <Button variant="secondary" onClick={props.onNew}>New conversation</Button>
      <ul className="flex flex-col gap-1">
        {props.threads.map((t) => (
          <li key={t.id}>
            <button
              type="button"
              className="w-full rounded-md px-2 py-1 text-left hover:bg-muted"
              aria-current={t.id === props.current ? "true" : undefined}
              onClick={() => props.onOpen(t.id)}
            >
              <span className="block text-sm">{t.title || "New conversation"}</span>
              <span className="block text-xs text-muted-foreground">Last used {lastUsed(t.last_used)}</span>
            </button>
          </li>
        ))}
      </ul>
    </nav>
  )
}
