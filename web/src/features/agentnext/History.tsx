// The list of earlier conversations, newest first, beside the conversation on the full-screen agent; clicking one opens it.
import type { ThreadInfo } from "./runtime"

/** Say when a conversation was last used, in plain words. */
function lastUsed(seconds: number): string {
  return seconds ? new Date(seconds * 1000).toLocaleString() : "not yet"
}

/** The history list; the open conversation is marked. New conversation is in the panel's header. */
export function History(props: { threads: ThreadInfo[]; current: string; onOpen: (id: string) => void }) {
  return (
    <nav className="ag-side" aria-label="Conversations">
      {!props.threads.length && <p className="ag-menu-note">No earlier conversations.</p>}
      <ul>
        {props.threads.map((t) => (
          <li key={t.id}>
            <button
              type="button"
              className="ag-thread"
              aria-current={t.id === props.current ? "true" : undefined}
              onClick={() => props.onOpen(t.id)}
            >
              <span>{t.title || "New conversation"}</span>
              <span className="ag-when">Last used {lastUsed(t.last_used)}</span>
            </button>
          </li>
        ))}
      </ul>
    </nav>
  )
}
