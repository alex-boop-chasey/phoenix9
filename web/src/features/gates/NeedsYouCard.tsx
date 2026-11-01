import { Loader2 } from "lucide-react"
import { useEffect, useState } from "react"

import { ConfirmDialog } from "@/components/ConfirmDialog"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Textarea } from "@/components/ui/textarea"
import { ApiError } from "@/lib/api"
import { useAnswerGate } from "@/lib/queries"
import type { Gate, GateAction } from "@/lib/types"
import { cn } from "@/lib/utils"

const LABEL: Record<GateAction, string> = {
  approve: "Approve",
  back: "Send back with a note",
  skip: "Skip task",
  stop: "Stop run",
  acknowledged: "Acknowledged",
}

const ESCALATION_HELP =
  "Fix it (for example with the project's chat), then press Acknowledged; the task runs once more."
const DELEGATED_HELP =
  "The project's chat is working on it; it will answer this itself if it fixes it."
const DELEGATED_FLAG = "delegated to project chat"

/** An amber card that shows one open question for Alex, with the buttons that answer it. */
export function NeedsYouCard({ gate, compact = false }: { gate: Gate; compact?: boolean }) {
  const answer = useAnswerGate(gate.project)
  const [pressed, setPressed] = useState<GateAction | null>(null)
  const [noting, setNoting] = useState(false)
  const [note, setNote] = useState("")
  const [confirmStop, setConfirmStop] = useState(false)
  const [done, setDone] = useState<GateAction | null>(null)
  const [gone, setGone] = useState(false)
  const [already, setAlready] = useState(false)
  const [error, setError] = useState("")

  useEffect(() => {
    if (!done) return
    const t = setTimeout(() => setGone(true), 2000)
    return () => clearTimeout(t)
  }, [done])

  if (gone) return null

  const send = (action: GateAction, text = "") => {
    setPressed(action)
    setError("")
    answer.mutate(
      { id: gate.id, action, note: text },
      {
        onSuccess: () => setDone(action),
        onError: (err) => {
          if (err instanceof ApiError && err.status === 409) setAlready(true)
          else setError(err instanceof Error && err.message ? err.message : "Something went wrong.")
        },
        onSettled: () => setPressed(null),
      },
    )
  }

  const busy = answer.isPending
  const escalation = gate.kind === "escalation"
  const offers = (a: GateAction) => gate.actions.includes(a)
  const primary: GateAction = escalation ? "acknowledged" : "approve"
  const order: GateAction[] = escalation
    ? ["acknowledged", "skip", "stop"]
    : ["approve", "back", "skip", "stop", "acknowledged"]
  const shown = order.filter(offers)

  const button = (action: GateAction) => {
    const label = LABEL[action]
    const spin = pressed === action && <Loader2 className="animate-spin" aria-hidden />
    if (action === "back") {
      return (
        <Button key={action} variant="outline" size={compact ? "sm" : "default"} disabled={busy} onClick={() => setNoting(true)}>
          {label}
        </Button>
      )
    }
    return (
      <Button
        key={action}
        size={compact ? "sm" : "default"}
        variant={action === primary ? "default" : action === "stop" ? "destructive" : "outline"}
        disabled={busy}
        onClick={() => (action === "stop" ? setConfirmStop(true) : send(action))}
      >
        {spin}
        {label}
      </Button>
    )
  }

  let body
  if (done) {
    body = <p role="status" className="text-sm font-medium">Answered: {LABEL[done]}</p>
  } else if (already) {
    body = <p role="status" className="text-sm font-medium">Someone already answered this.</p>
  } else {
    body = (
      <>
        {gate.why && <p className="text-sm">{gate.why}</p>}
        {(gate.task != null || gate.step) && (
          <p className="text-xs text-muted-foreground">
            {[gate.task != null ? `Task ${gate.task}` : null, gate.step ? stepName(gate.step) : null]
              .filter(Boolean)
              .join(" · ")}
          </p>
        )}
        {gate.flags.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {gate.flags.map((f) => (
              <Badge key={f} variant={f === DELEGATED_FLAG ? "secondary" : "destructive"}>
                {f}
              </Badge>
            ))}
          </div>
        )}
        {escalation && <p className="text-sm text-muted-foreground">{ESCALATION_HELP}</p>}
        {gate.flags.includes(DELEGATED_FLAG) && <p className="text-sm text-muted-foreground">{DELEGATED_HELP}</p>}
        {gate.links.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {gate.links.map((l) => (
              <Button key={l.url} asChild variant="link" size="sm" className="h-auto p-0">
                <a href={l.url} target="_blank" rel="noreferrer">{l.label}</a>
              </Button>
            ))}
          </div>
        )}
        {noting && (
          <div className="flex flex-col gap-2">
            <Textarea
              aria-label="Note for the builder"
              placeholder="What should change?"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              disabled={busy}
            />
            <div className="flex gap-2">
              <Button size="sm" disabled={busy || !note.trim()} onClick={() => send("back", note.trim())}>
                {pressed === "back" && <Loader2 className="animate-spin" aria-hidden />}
                Send back
              </Button>
              <Button size="sm" variant="ghost" disabled={busy} onClick={() => setNoting(false)}>
                Cancel
              </Button>
            </div>
          </div>
        )}
        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        <div className="flex flex-wrap gap-2">{shown.map(button)}</div>
      </>
    )
  }

  return (
    <Card className={cn("border-amber-500/50 border-l-4 border-l-amber-500", compact && "gap-2 py-3 text-sm")}>
      <CardHeader className={compact ? "px-3" : undefined}>
        <CardTitle className={compact ? "text-base" : undefined}>Needs you: {gate.title}</CardTitle>
      </CardHeader>
      <CardContent className={cn("flex flex-col gap-3", compact && "px-3")}>{body}</CardContent>
      <ConfirmDialog
        open={confirmStop}
        onOpenChange={setConfirmStop}
        title="Stop this run?"
        body="Stop this run? Work done so far stays on its branch."
        confirmLabel="Stop run"
        destructive
        onConfirm={() => send("stop")}
      />
    </Card>
  )
}

/** "builder" -> "Builder". */
function stepName(step: string): string {
  return step.charAt(0).toUpperCase() + step.slice(1)
}
