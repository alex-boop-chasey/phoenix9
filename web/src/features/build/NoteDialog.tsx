// "Send a note" on the running task: a small dialog that adds a note to the task's file; the next attempt reads it.
import { useState } from "react"

import { Icon } from "@/components/Icon"
import { Wheel } from "@/components/Indicator"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Textarea } from "@/components/ui/textarea"
import { useNoteRun } from "@/lib/queries"

export const MAX_NOTE = 2000

/** The "Send a note" button for one task, and the dialog it opens. */
export function NoteButton({ runId, task }: { runId: string; task: number }) {
  const [open, setOpen] = useState(false)
  const [text, setText] = useState("")
  const [sent, setSent] = useState(false)
  const note = useNoteRun()
  const trimmed = text.trim()
  const problem = trimmed.length > MAX_NOTE ? `That is ${trimmed.length} characters; the most is ${MAX_NOTE}.` : null
  const change = (next: boolean) => {
    setOpen(next)
    if (next) {
      setText("")
      setSent(false)
      note.reset()
    }
  }
  const send = () =>
    note.mutate({ runId, task, text: trimmed }, { onSuccess: () => { setSent(true); setText("") } })
  return (
    <>
      <Button variant="secondary" size="sm" onClick={() => change(true)} data-note-task={task}>
        <Icon name="pencil-simple" />
        Send a note
      </Button>
      <Dialog open={open} onOpenChange={change}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Send a note</DialogTitle>
            <DialogDescription>
              Task {task}'s next attempt reads this note. It is kept in the task file under Fix notes.
            </DialogDescription>
          </DialogHeader>
          {sent ? (
            <p role="status" className="small">Note saved. The next attempt will read it.</p>
          ) : (
            <Textarea
              aria-label="Note" rows={5} value={text} onChange={(e) => setText(e.target.value)}
              placeholder="What should the next attempt know?"
            />
          )}
          {problem && <p role="alert" className="small">{problem}</p>}
          {note.error && <Alert variant="destructive"><AlertDescription>{note.error.message}</AlertDescription></Alert>}
          <DialogFooter>
            <Button variant="secondary" onClick={() => change(false)}>{sent ? "Close" : "Cancel"}</Button>
            {!sent && (
              <Button disabled={!trimmed || !!problem || note.isPending} onClick={send}>
                {note.isPending && <Wheel />}
                Send note
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
