// One reply block: checks it once with Phoenix, then shows the matching component or the fallback text.
import { useEffect, useState } from "react"

import { AnswerCard } from "@/features/agent/blocks/AnswerCard"
import { ChoiceBlock } from "@/features/agent/blocks/ChoiceBlock"
import { ConfirmBlock } from "@/features/agent/blocks/ConfirmBlock"
import { NavBlock } from "@/features/agent/blocks/NavBlock"
import type { BlockPart } from "@/features/agent/blocks/parse"
import { post } from "@/lib/api"

interface CheckResult { ok: boolean; reason: string | null; resolved: unknown }

const cache = new Map<string, Promise<CheckResult>>()

/** Forget every cached check (for tests). */
export function clearBlockCache(): void {
  cache.clear()
}

function checkBlock(kind: string, json: string): Promise<CheckResult> {
  const key = `${kind}\n${json}`
  let hit = cache.get(key)
  if (!hit) {
    hit = post<CheckResult>("blocks/check", { kind, json }).catch((err: unknown) => {
      cache.delete(key)
      return { ok: false, reason: err instanceof Error && err.message ? err.message : "the check failed", resolved: null }
    })
    cache.set(key, hit)
  }
  return hit
}

function asOf(at?: string): string {
  const d = at ? new Date(at) : null
  if (!d || Number.isNaN(d.getTime())) return "as of an earlier conversation"
  return `as of ${d.toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hour12: false })}`
}

function Failed({ fallback, reason }: { fallback: string; reason: string }) {
  return (
    <div className="ag-block-failed" data-testid="block-failed">
      {fallback && <p>{fallback}</p>}
      <p className="ag-block-reason muted">block could not be shown: {reason}</p>
    </div>
  )
}

/** Check a block once and show it, or its fallback line with a grey reason when it cannot be shown. */
export function BlockView({ part, frozen = false, at, later }: { part: BlockPart; frozen?: boolean; at?: string; later?: string[] }) {
  const { kind, json, fallback } = part
  const [result, setResult] = useState<CheckResult | null>(null)

  useEffect(() => {
    let live = true
    setResult(null)
    if (kind) void checkBlock(kind, json).then((r) => { if (live) setResult(r) })
    return () => { live = false }
  }, [kind, json])

  if (!kind) return <Failed fallback={fallback} reason={`unknown block type ${part.tag}`} />
  if (!result) return <div className="ag-block-wait muted" aria-busy="true" data-testid="block-wait">{fallback}</div>
  if (!result.ok) return <Failed fallback={fallback} reason={result.reason ?? "the check failed"} />

  const props = { json, resolved: result.resolved, frozen, later }
  const body = kind === "card" ? <AnswerCard {...props} /> : kind === "choice" ? <ChoiceBlock {...props} />
    : kind === "confirm" ? <ConfirmBlock {...props} /> : <NavBlock {...props} />
  return (
    <div className="ag-block-wrap" data-testid="block-view">
      {body}
      {frozen && <div className="ag-block-asof muted">{asOf(at)}</div>}
    </div>
  )
}
