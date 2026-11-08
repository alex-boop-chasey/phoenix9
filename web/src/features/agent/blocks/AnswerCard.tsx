// The card reply block: fetches the live card from Phoenix, shows it, keeps it fresh and offers its buttons.
import { useQuery } from "@tanstack/react-query"
import { useCallback, useEffect, useRef } from "react"

import { CARD_BODIES, JsonBody } from "@/features/agent/blocks/cardBodies"
import { CardActions, type CardAction } from "@/features/agent/blocks/CardActions"
import type { BlockProps } from "@/features/agent/blocks/types"
import { useSendToAgent } from "@/features/agent/useAgent"
import { get } from "@/lib/api"
import { useLiveEvents } from "@/lib/live"
import type { PhoenixEvent } from "@/lib/types"

export interface CardWatch { projects: string[]; runs: string[]; types: string[]; poll_s?: number }
export interface CardAnswer {
  type: string; title: string; data: unknown; actions: CardAction[]; watch: CardWatch; inline: boolean
}
interface Resolved { type: string; query?: Record<string, unknown>; title?: string | null }

const DEBOUNCE_MS = 500

/** True when an event is one this card watches (an empty list means any). */
export function matchesWatch(watch: CardWatch | undefined, ev: { type: string; project?: string | null; run?: string | null }): boolean {
  if (!watch || ev.type === "command" || ev.type === "ui.go") return false
  const { projects = [], runs = [], types = [] } = watch
  if (projects.length && !(ev.project && projects.includes(ev.project))) return false
  if (runs.length && !(ev.run && runs.includes(ev.run))) return false
  if (types.length && !types.some((t) => ev.type.startsWith(t))) return false
  return true
}

function resolvedOf(json: string, resolved: unknown): Resolved | null {
  const r = resolved as Resolved | null | undefined
  if (r && typeof r.type === "string") return r
  try {
    const obj = JSON.parse(json) as Resolved
    return typeof obj.type === "string" ? obj : null
  } catch {
    return null
  }
}

/** Shows a checked card block with live data and its buttons. */
export function AnswerCard({ json, resolved, frozen = false }: BlockProps) {
  const card = resolvedOf(json, resolved)
  const query = useQuery({
    queryKey: ["agent", "card", card?.type, JSON.stringify(card?.query ?? {}), card?.title ?? ""],
    enabled: card !== null,
    queryFn: () => get<CardAnswer>("cards", {
      type: card!.type, query: JSON.stringify(card!.query ?? {}), title: card!.title ?? undefined,
    }),
    staleTime: frozen ? Infinity : 0,
    refetchOnWindowFocus: false,
    retry: false,
    refetchInterval: (q) => {
      const s = q.state.data?.watch?.poll_s
      return !frozen && s ? s * 1000 : false
    },
  })
  const watch = query.data?.watch
  const refetch = query.refetch
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  useEffect(() => () => clearTimeout(timer.current), [])

  const onEvent = useCallback((ev: PhoenixEvent) => {
    if (frozen || !matchesWatch(watch, ev)) return
    clearTimeout(timer.current)
    timer.current = setTimeout(() => void refetch(), DEBOUNCE_MS)
  }, [frozen, watch, refetch])
  useLiveEvents(undefined, onEvent)

  const send = useSendToAgent()
  const note = useCallback((text: string) => send.mutate({ text }), [send])

  const data = query.data
  const Body = (data && CARD_BODIES[data.type]) || JsonBody
  return (
    <div className="ag-block ag-block-card" data-testid="block-card" data-frozen={frozen ? "true" : undefined}>
      <div className="ag-card-title">{data?.title ?? card?.title ?? card?.type ?? "Card"}</div>
      {query.isPending && card && <p className="muted" aria-busy="true" data-testid="card-loading">Loading…</p>}
      {query.isError && (
        <p className="text-destructive" role="alert" data-testid="card-error">
          Could not load this card: {query.error instanceof Error ? query.error.message : "unknown error"}
        </p>
      )}
      {data && <Body type={data.type} data={data.data} frozen={frozen} />}
      {data && !frozen && <CardActions actions={data.actions ?? []} onNote={note} />}
    </div>
  )
}
