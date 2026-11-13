import { Icon } from "@/components/Icon"
import { RelativeTime } from "@/components/RelativeTime"
import type { LogEntry } from "@/lib/types"

import { kindInfo, taskLabel } from "./LogFilters"

/** "build · task · attempt · step" in muted words. */
function where(e: LogEntry): string {
  const bits = [e.run]
  if (e.task !== null) bits.push(taskLabel(e.task))
  if (e.attempt !== null) bits.push(`attempt ${e.attempt}`)
  if (e.step) bits.push(e.step)
  return bits.join(" · ")
}

const size = (n: number) => (n >= 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)} MB` : n >= 1024 ? `${Math.round(n / 1024)} KB` : `${n} B`)

/** The entries that match the filters; click one to open it. */
export function LogList({
  entries, selected, onSelect,
}: {
  entries: LogEntry[]
  selected: string
  onSelect: (id: string) => void
}) {
  if (!entries.length) return <p className="help" style={{ padding: 16 }}>No logs match these filters.</p>
  return (
    <div className="lglist" role="listbox" aria-label="Logs">
      {entries.map((e) => {
        const info = kindInfo(e.kind)
        return (
          <button key={e.id} type="button" className="lgi" role="option" aria-selected={e.id === selected} onClick={() => onSelect(e.id)}>
            <b>{e.title}</b>
            <span className="k"><Icon name={info.icon} />{info.label}</span>
            <small>{where(e)}</small>
            <small>{size(e.size)} · <RelativeTime iso={e.modified} /></small>
          </button>
        )
      })}
    </div>
  )
}
