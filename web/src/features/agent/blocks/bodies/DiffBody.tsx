// Body of the diff card: the same diff view as the Logs tab, with a count per file.
import { DiffView } from "@/features/logs/DiffView"

import type { CardBodyProps } from "../cardBodies"

interface DiffFile { name: string; added: number; removed: number; lines: string[] }

/** The files of a diff card. */
export function DiffBody({ data }: CardBodyProps) {
  const d = (data ?? {}) as { files?: DiffFile[]; truncated?: boolean }
  const files = Array.isArray(d.files) ? d.files : []
  if (files.length === 0) return <p className="muted" data-testid="diff-empty">No changes.</p>
  return (
    <div className="flex flex-col gap-2" data-testid="card-diff">
      <ul className="m-0 list-none p-0 text-sm">
        {files.map((f, i) => (
          <li key={i} className="mono">{f.name} <span className="text-ok">+{f.added}</span> <span className="text-bad">-{f.removed}</span></li>
        ))}
      </ul>
      {d.truncated ? <p className="muted" data-testid="diff-truncated">The diff is cut short.</p> : null}
      <div className="ag-code mono max-h-80 overflow-auto" tabIndex={0}>
        <DiffView text={files.flatMap((f) => f.lines).join("\n")} />
      </div>
    </div>
  )
}
