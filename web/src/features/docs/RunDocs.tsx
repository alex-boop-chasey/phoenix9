import { useQuery } from "@tanstack/react-query"

import { get } from "@/lib/api"

import { DocButtons } from "./DocButtons"

interface DocRow {
  id: string
  title: string
  size: number
}

/** View/Download buttons for a run's plan and summary documents (nothing when it has none). */
export function RunDocs({ runId }: { runId: string }) {
  const q = useQuery({ queryKey: ["docs", runId], queryFn: () => get<DocRow[]>("docs/list", { run: runId }), retry: false })
  const shown = (q.data ?? []).filter((d) => /\/(plan|summary)\.md$/.test(d.id))
  if (!shown.length) return null
  return (
    <div className="stackg" style={{ gap: 6 }} data-testid="run-docs">
      {shown.map((d) => (
        <div key={d.id} className="flex flex-wrap items-center gap-2">
          <span className="small">{d.title}</span>
          <DocButtons id={d.id} label={d.title} />
        </div>
      ))}
    </div>
  )
}
