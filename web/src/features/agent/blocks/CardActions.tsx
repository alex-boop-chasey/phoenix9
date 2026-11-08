// The buttons under a card: they come only from Phoenix's /api/cards answer, never from the model's block.
import { useState } from "react"

import { ConfirmDialog } from "@/components/ConfirmDialog"
import { Button } from "@/components/ui/button"
import { navigateKeepingPanel } from "@/features/agent/navigate"
import { post, get } from "@/lib/api"
import { routeHash } from "@/lib/routes"
import { safeUrl } from "@/lib/safeUrl"

export interface CardAction {
  label: string
  kind: "link" | "route" | "op"
  href?: string
  route?: { to: string; params?: Record<string, unknown> }
  op?: { method: string; path: string; body?: unknown }
  confirm?: string
  danger?: boolean
}

interface Props {
  actions: CardAction[]
  /** Posts the one note to the agent after a button succeeded. */
  onNote: (text: string) => void
}

function errorText(err: unknown): string {
  return err instanceof Error && err.message ? err.message : "it did not work"
}

/** Run an op the way the dashboard does (the route table of the API, who=dashboard is the browser's own way). */
async function runOp(op: NonNullable<CardAction["op"]>): Promise<void> {
  const path = op.path.replace(/^\/?api\//, "").replace(/^\//, "")
  const method = op.method.toUpperCase()
  if (method === "GET") await get(path)
  else if (method === "POST") await post(path, op.body ?? {})
  else throw new Error(`cannot send ${method}`)
}

/** The buttons of a card, with the shared confirm dialog and a short result line. */
export function CardActions({ actions, onNote }: Props) {
  const [pending, setPending] = useState<CardAction | null>(null)
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null)

  if (actions.length === 0) return null

  async function perform(action: CardAction) {
    setBusy(true)
    try {
      await runOp(action.op!)
      setResult({ ok: true, text: `${action.label}: done` })
      onNote(`[Phoenix panel · button] ${action.label} done`)
    } catch (err) {
      setResult({ ok: false, text: `${action.label} failed: ${errorText(err)}` })
    } finally {
      setBusy(false)
    }
  }

  function click(action: CardAction) {
    if (action.kind === "route" && action.route) {
      const hash = routeHash(action.route.to, action.route.params ?? {})
      if (hash) navigateKeepingPanel(hash)
    } else if (action.kind === "op" && action.op) {
      if (action.confirm) setPending(action)
      else void perform(action)
    }
  }

  return (
    <div className="ag-card-actions" data-testid="card-actions">
      <div className="flex flex-wrap gap-2">
        {actions.map((a, i) => a.kind === "link" ? (safeUrl(a.href) ? (
          <Button key={i} asChild variant="outline" size="sm">
            <a href={safeUrl(a.href)!} target="_blank" rel="noopener">{a.label}</a>
          </Button>
        ) : null) : (
          <Button key={i} type="button" variant={a.danger ? "destructive" : "outline"} size="sm" disabled={busy} onClick={() => click(a)}>
            {a.label}
          </Button>
        ))}
      </div>
      {result && <p role="status" className={result.ok ? "muted" : "text-destructive"} data-testid="card-result">{result.text}</p>}
      <ConfirmDialog
        open={pending !== null}
        onOpenChange={(open) => { if (!open) setPending(null) }}
        title={pending?.label ?? ""}
        body={pending?.confirm ?? ""}
        confirmLabel={pending?.label ?? "Confirm"}
        destructive={pending?.danger}
        onConfirm={() => { const a = pending; setPending(null); if (a) void perform(a) }}
      />
    </div>
  )
}
