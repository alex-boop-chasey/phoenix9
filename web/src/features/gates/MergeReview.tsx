import { Loader2 } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"

import { ConfirmDialog } from "@/components/ConfirmDialog"
import { Icon } from "@/components/Icon"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { NeedsYouCard } from "@/features/gates/NeedsYouCard"
import { useAnswerGate, useGateReview } from "@/lib/queries"
import type { Gate, GateAction, ReviewFile } from "@/lib/types"

/** A diff line's class: hunk header, added, removed or plain. */
function lineClass(line: string): "h" | "a" | "d" | "c" {
  if (line.startsWith("@@")) return "h"
  if (line.startsWith("+")) return "a"
  if (line.startsWith("-")) return "d"
  return "c"
}

/** The readable lines of one file's diff (the git header lines are left out). */
function diffLines(diff: string): string[] {
  const lines = diff.split("\n")
  const start = lines.findIndex((l) => l.startsWith("@@"))
  const body = start >= 0 ? lines.slice(start) : []
  return body.filter((l, i) => l !== "" || i < body.length - 1)
}

function FileRow({ file }: { file: ReviewFile }) {
  const lines = diffLines(file.diff)
  return (
    <details>
      <summary>
        <Icon name="caret-right" size="sm" className="car" />
        <span className="fn">
          {file.path}
          {file.safety && <> <span className="tag t-safety"><Icon name="shield-check" />Safety</span></>}
        </span>
        <span className="st">
          <span className="add">+{file.added}</span>
          <span className="del">−{file.removed}</span>
        </span>
      </summary>
      <pre className="diff">
        {lines.length === 0 ? (
          <span className="c">{file.binary ? "Binary file" : "No text changes to show"}</span>
        ) : (
          lines.map((l, i) => {
            const c = lineClass(l)
            return <span key={i} className={c}>{c === "h" ? l : l.slice(1)}</span>
          })
        )}
      </pre>
    </details>
  )
}

/** The merge review inside the Merge step: summary, facts, changed files and the three answers. */
export function MergeReview({ gate }: { gate: Gate }) {
  const review = useGateReview(gate.id)
  const answer = useAnswerGate(gate.project)
  const [noting, setNoting] = useState(false)
  const [note, setNote] = useState("")
  const [confirmSkip, setConfirmSkip] = useState(false)
  const [pressed, setPressed] = useState<GateAction | null>(null)
  const [done, setDone] = useState<GateAction | null>(null)
  const [error, setError] = useState("")

  if (review.isError) return <NeedsYouCard gate={gate} compact />
  const r = review.data
  if (!r) return <p className="small" role="status">Loading the review…</p>

  const send = (action: GateAction, text = "") => {
    setPressed(action)
    setError("")
    answer.mutate(
      { id: gate.id, action, note: text },
      {
        onSuccess: () => {
          setDone(action)
          if (action === "approve") toast.success("Merged into main", { description: `${r.title.replace(/^Merge |\?$/g, "")} is on main.` })
          else if (action === "back") toast.success("Sent back", { description: "Your note was posted on the merge request." })
          else toast.info("Not merged", { description: "The branch is kept." })
        },
        onError: (err) => setError(err instanceof Error && err.message ? err.message : "Something went wrong."),
        onSettled: () => setPressed(null),
      },
    )
  }

  const busy = answer.isPending
  const retried = r.tasks.retried.map((t) => `task ${t.number}`).join(", ")
  const suiteOk = r.full_suite.status === "passed"
  const suiteBad = r.full_suite.status === "failed"
  const tasksOk = r.tasks.passed === r.tasks.total

  if (done) {
    const text = done === "approve" ? "Merged into main" : done === "back" ? "Sent back" : "Not merged"
    return <p role="status" className={done === "approve" ? "review-done" : "small"}>
      {done === "approve" && <Icon name="check-circle" />}{text}
    </p>
  }

  return (
    <div className="review" aria-label="Review the merge">
      <div>
        <h3 className="h3" style={{ fontSize: 20 }}>{r.title}</h3>
        {r.summary && <p className="muted" style={{ marginTop: 6, maxWidth: "72ch", whiteSpace: "pre-line" }}>{r.summary}</p>}
      </div>
      <div className="facts">
        <div className={`fact ${tasksOk ? "ok" : "bad"}`}>
          <span>Tasks</span>
          <b><Icon name="check-circle" />{r.tasks.passed} of {r.tasks.total} passed</b>
          {retried && <span>{retried} needed a retry</span>}
        </div>
        <div className={`fact ${suiteOk ? "ok" : suiteBad ? "bad" : ""}`}>
          <span>Full suite</span>
          <b><Icon name="check-circle" />{suiteOk ? "Passed" : suiteBad ? "Failed" : r.full_suite.status}</b>
          {r.full_suite.note && <span>{r.full_suite.note}</span>}
        </div>
        <div className={`fact ${r.safety.flag ? "bad" : "ok"}`}>
          <span>Safety</span>
          <b><Icon name="shield-check" />{r.safety.flag ? "Changes safety code" : "No safety code changed"}</b>
          {r.safety.flag && <span>{r.safety.files.join(", ")}</span>}
        </div>
      </div>
      <div className="stackg" style={{ gap: 8 }}>
        <div className="row" style={{ justifyContent: "space-between" }}>
          <b className="lbl">Changed files ({r.files.length})</b>
          <span className="mono small"><span className="add">+{r.added}</span> <span className="del">−{r.removed}</span></span>
        </div>
        <div className="files">{r.files.map((f) => <FileRow key={f.path} file={f} />)}</div>
      </div>
      {noting && (
        <div className="note">
          <label className="lbl" htmlFor={`note-${gate.id}`}>Note for the builder</label>
          <Textarea id={`note-${gate.id}`} placeholder="What should change?" value={note} onChange={(e) => setNote(e.target.value)} disabled={busy} />
          <div className="row">
            <Button variant="secondary" disabled={busy || !note.trim()} onClick={() => send("back", note.trim())}>
              {pressed === "back" && <Loader2 className="animate-spin" aria-hidden />}Send back note
            </Button>
            <Button variant="ghost" disabled={busy} onClick={() => setNoting(false)}>Cancel</Button>
          </div>
        </div>
      )}
      {error && <p role="alert" className="small" style={{ color: "var(--bad)" }}>{error}</p>}
      <div className="acts">
        <Button disabled={busy} onClick={() => send("approve")}>
          {pressed === "approve" ? <Loader2 className="animate-spin" aria-hidden /> : <Icon name="git-merge" />}
          {pressed === "approve" ? "Merging…" : "Approve & merge"}
        </Button>
        <Button variant="secondary" disabled={busy} onClick={() => setNoting(true)}>Send back</Button>
        <Button variant="ghost" disabled={busy} onClick={() => setConfirmSkip(true)}>Don't merge</Button>
        {r.merge_request && (
          <a className="end" href={r.merge_request} target="_blank" rel="noreferrer">
            <Icon name="git-pull-request" size="sm" /> Merge request on GitHub
          </a>
        )}
      </div>
      <ConfirmDialog
        open={confirmSkip}
        onOpenChange={setConfirmSkip}
        title="Don't merge this build?"
        body="The work stays on its branch. Nothing goes into main."
        confirmLabel="Don't merge"
        destructive
        onConfirm={() => send("skip")}
      />
    </div>
  )
}
