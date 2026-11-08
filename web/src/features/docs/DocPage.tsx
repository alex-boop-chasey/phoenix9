import { useQuery } from "@tanstack/react-query"
import { useSearchParams } from "react-router"

import { ErrorState } from "@/components/ErrorState"
import { Skeleton } from "@/components/ui/skeleton"
import { Markdown } from "@/features/agent/markdown"
import { get } from "@/lib/api"

import { docDownloadUrl } from "./docUrl"

export interface DocShown {
  id: string
  title: string
  text: string
}

/** The page at #/doc?path=<id>: one document, read from Phoenix and shown as clean text. */
export default function DocPage() {
  const [params] = useSearchParams()
  const id = params.get("path") ?? ""
  const q = useQuery({
    queryKey: ["doc", id],
    queryFn: () => get<DocShown>("docs/show", { id }),
    enabled: !!id,
    retry: false,
  })
  if (!id) return <ErrorState error={new Error("No document was asked for.")} />
  if (q.error) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />
  if (!q.data) return <Skeleton className="h-24 w-full" />
  const doc = q.data
  return (
    <article className="stackg mx-auto max-w-3xl min-w-0" style={{ gap: 16 }} aria-label={doc.title}>
      <header className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="h2 break-words">{doc.title}</h1>
        <a className="btn btn-outline" href={docDownloadUrl(doc.id)} download>Download</a>
      </header>
      <div className="min-w-0 break-words"><Markdown text={doc.text} /></div>
    </article>
  )
}

