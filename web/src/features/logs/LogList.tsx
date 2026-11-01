import { Badge } from "@/components/ui/badge"
import { RelativeTime } from "@/components/RelativeTime"
import type { LogEntry } from "@/lib/types"
import { cn } from "@/lib/utils"

import { taskLabel } from "./LogFilters"

/** "run · task · attempt · step" in muted words. */
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
  if (!entries.length) return <p className="p-4 text-sm text-muted-foreground">No logs match these filters.</p>
  return (
    <ul className="flex flex-col gap-1">
      {entries.map((e) => (
        <li key={e.id}>
          <button type="button" onClick={() => onSelect(e.id)} aria-current={e.id === selected}
            className={cn("w-full rounded-md border p-2 text-left text-sm hover:bg-accent", e.id === selected && "border-primary bg-accent")}>
            <div className="flex items-center gap-2">
              <span className="min-w-0 flex-1 truncate font-medium">{e.title}</span>
              <Badge variant="secondary">{e.kind}</Badge>
            </div>
            <div className="mt-0.5 truncate text-xs text-muted-foreground">{where(e)}</div>
            <div className="text-xs text-muted-foreground">{size(e.size)} · <RelativeTime iso={e.modified} /></div>
          </button>
        </li>
      ))}
    </ul>
  )
}
