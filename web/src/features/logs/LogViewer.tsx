import { useEffect, useRef } from "react"
import { useQuery } from "@tanstack/react-query"

import { CopyButton } from "@/components/CopyButton"
import { ErrorState } from "@/components/ErrorState"
import { Icon } from "@/components/Icon"
import { Wheel } from "@/components/Indicator"
import { api } from "@/lib/api"

import { DiffView } from "./DiffView"
import { kindInfo } from "./LogFilters"

/** The open log: header with kind tag, title and Copy, then the text (newest at the bottom, diffs coloured). */
export function LogViewer({ project, id }: { project: string; id: string }) {
  // Not under the "logs" key, so live events refetch the list but not the open text.
  const q = useQuery({ queryKey: ["logtext", project, id], queryFn: () => api.readLog(project, id), enabled: !!id })
  const box = useRef<HTMLDivElement>(null)
  const text = q.data?.text

  useEffect(() => {
    if (box.current) box.current.scrollTop = box.current.scrollHeight
  }, [text])

  const log = q.data
  return (
    <div className="reader" aria-live="polite">
      {!id ? (
        <p className="loading">Pick a log to read it.</p>
      ) : q.error ? (
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      ) : !log ? (
        <div className="loading" data-testid="log-loading"><Wheel className="wheel-lg" />Loading log…</div>
      ) : (
        <>
          <div className="reader-h">
            <span className="tag"><Icon name={kindInfo(log.kind).icon} />{kindInfo(log.kind).label}</span>
            <b>{log.title}</b>
            {log.truncated && <span className="help">Showing the last 2 MB</span>}
            <span style={{ marginLeft: "auto" }}><CopyButton text={log.text} /></span>
          </div>
          <div className="reader-body" ref={box}>
            {log.is_diff ? <DiffView text={log.text} /> : <pre>{log.text}</pre>}
          </div>
        </>
      )}
    </div>
  )
}
