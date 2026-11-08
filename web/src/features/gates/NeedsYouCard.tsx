import { Loader2 } from "lucide-react"
import { useEffect, useState } from "react"
import { Link } from "react-router"

import { ConfirmDialog } from "@/components/ConfirmDialog"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Icon } from "@/components/Icon"
import { Textarea } from "@/components/ui/textarea"
import { ApiError } from "@/lib/api"
import { useAnswerGate } from "@/lib/queries"
import type { Gate, GateAction } from "@/lib/types"
import { cn } from "@/lib/utils"

const LABEL: Record<string, string> = {
  approve: "Approve",
  back: "Send back with a note",
  skip: "Skip task",
  stop: "Stop run",
  acknowledged: "Acknowledged",
  done: "Done, keys pasted",
  defer: "Build without it for now",
}

const KNOWN: GateAction[] = ["approve", "back", "skip", "stop", "acknowledged"]

/** The label for an action: the known one, else the action's own name. */
const labelOf = (action: GateAction) => LABEL[action] ?? action

const ESCALATION_HELP =
  "Fix it, then press Acknowledged; the task runs once more."
const DEFER_HELP =
  "\"Build without it for now\" carries on and builds the site so it still works without these keys. Phoenix shows \"Waiting for keys\" until you save them; the next build then switches the service on."
const DELEGATED_HELP =
  "A Claude session in the project's folder is working on it; it will answer this itself if it fixes it."
const DELEGATED_FLAG = "delegated to project chat"   // the backend flag (failmodes.DELEGATE_FLAG); keep in step

/** An amber card that shows one open question for Alex, with the buttons that answer it. */
export function NeedsYouCard({ gate, compact = false, reviewHref }: { gate: Gate; compact?: boolean; reviewHref?: string }) {
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
  const extra = gate.actions.filter((a) => !KNOWN.includes(a))
  const shown = [...order.filter(offers), ...extra]

  const button = (action: GateAction) => {
    const label = labelOf(action)
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
    body = <p role="status" className="font-semibold">Answered: Phoenix is carrying on</p>
  } else if (already) {
    body = <p role="status" className="font-semibold">Someone already answered this.</p>
  } else {
    body = (
      <>
        {gate.why && <p className="text-sm">{gate.why}</p>}
        {gate.flags.length > 0 && (
          <div className="flags">
            {gate.flags.map((f) => (
              <span key={f} className={f === DELEGATED_FLAG ? "badge b-info" : "badge b-bad"}>
                <Icon name={f === DELEGATED_FLAG ? "info" : "shield-check"} />{f}
              </span>
            ))}
          </div>
        )}
        {escalation && <p className="text-sm text-muted-foreground">{ESCALATION_HELP}</p>}
        {offers("defer") && <p className="text-sm text-muted-foreground">{DEFER_HELP}</p>}
        {gate.flags.includes(DELEGATED_FLAG) && <p className="text-sm text-muted-foreground">{DELEGATED_HELP}</p>}
        {gate.links.length > 0 && (
          <div className="links">
            {gate.links.map((l) => (
              <a key={l.doc ?? l.url} href={l.doc ? `#/doc?path=${encodeURIComponent(l.doc)}` : l.url}
                 {...(l.doc ? {} : { target: "_blank", rel: "noreferrer" })}>
                <Icon name="git-pull-request" size="sm" />{l.label}
              </a>
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
        {reviewHref && gate.kind === "merge" ? (
          <div className="acts">
            <Link className="btn btn-primary" to={reviewHref}><Icon name="git-merge" />Review and merge</Link>
          </div>
        ) : (
          <div className="acts">{shown.map(button)}</div>
        )}
      </>
    )
  }

  return (
    <article className={cn("need", compact && "need-compact")} aria-label={`Needs you: ${gate.title}`}>
      <div className="need-bar">
        <Icon name="bell-ringing" />Needs you<span className="sp">{where(gate)}</span>
      </div>
      <div className="need-b">
        <p className="h3 need-title">{gate.title}</p>
        {body}
      </div>
      <ConfirmDialog
        open={confirmStop}
        onOpenChange={setConfirmStop}
        title="Stop this run?"
        body="Stop this run? Its unfinished work and branch are thrown away."
        confirmLabel="Stop run"
        destructive
        onConfirm={() => send("stop")}
      />
    </article>
  )
}

/** Where a question comes from, in words: the task and step, else the kind of question. */
function where(gate: Gate): string {
  const parts = [gate.task != null ? `Task ${gate.task}` : null, gate.step ? `${stepName(gate.step)} step` : null]
  const found = parts.filter(Boolean).join(" · ")
  if (found) return found
  return gate.kind === "merge" ? "Merge step" : gate.kind === "plan" ? "Plan" : gate.kind === "deploy" ? "Deploy" : "Build"
}

/** "builder" -> "Builder". */
function stepName(step: string): string {
  return step.charAt(0).toUpperCase() + step.slice(1)
}
