import { useEffect, useRef } from "react"

import { CopyButton } from "@/components/CopyButton"
import { ErrorState } from "@/components/ErrorState"
import { Badge } from "@/components/ui/badge"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Skeleton } from "@/components/ui/skeleton"
import { api } from "@/lib/api"
import { useQuery } from "@tanstack/react-query"

import { DiffView } from "./DiffView"

/** The open log: title bar with Copy, then the text (newest at the bottom, diffs coloured). */
export function LogViewer({ project, id }: { project: string; id: string }) {
  // Not under the "logs" key, so live events refetch the list but not the open text.
  const q = useQuery({ queryKey: ["logtext", project, id], queryFn: () => api.readLog(project, id), enabled: !!id })
  const box = useRef<HTMLDivElement>(null)
  const text = q.data?.text

  useEffect(() => {
    const view = box.current?.querySelector("[data-slot=scroll-area-viewport]")
    if (view) view.scrollTop = view.scrollHeight
  }, [text])

  if (!id) return <p className="p-4 text-sm text-muted-foreground">Pick a log to read it.</p>
  if (q.error) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />
  const log = q.data
  if (!log) return <Skeleton data-testid="log-loading" className="h-64 w-full" />
  return (
    <div className="flex min-w-0 flex-col rounded-md border">
      <div className="flex flex-wrap items-center gap-2 border-b p-2">
        <Badge variant="secondary">{log.kind}</Badge>
        <span className="min-w-0 flex-1 truncate text-sm font-medium">{log.title}</span>
        {log.truncated && <span className="text-xs text-muted-foreground">Showing the last 2 MB</span>}
        <CopyButton text={log.text} />
      </div>
      <div ref={box}>
        <ScrollArea className="h-[60vh] [&>[data-slot=scroll-area-viewport]>div]:!block">
          <div className="p-3">
            {log.is_diff ? (
              <DiffView text={log.text} />
            ) : (
              <pre className="font-mono text-xs whitespace-pre-wrap break-words">{log.text}</pre>
            )}
          </div>
        </ScrollArea>
      </div>
    </div>
  )
}
