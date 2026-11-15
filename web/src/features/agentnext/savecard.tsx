// The save-attachment card: Alex presses Save to put a file he attached into a project's reference documents;
// the bytes go from the agent service to Phoenix as Alex, and the agent only hears saved, cancelled or refused.
import { useState } from "react"

import { Icon } from "@/components/Icon"
import { ALLOWED_EXTENSIONS } from "@/features/reference/ReferenceCard"
import { api, ApiError } from "@/lib/api"
import { sizeWords, toBase64 } from "./attach"
import { Mark, NeedsYou, cardClass } from "./cardparts"
import { answerBrowser } from "./choicecard"
import { attachmentUrl } from "./runtime"

/** Phoenix's reference limits (phoenix9/reference.py): 5 MB a file, names of at most 100 characters. */
export const REFERENCE_MAX_FILE = 5 * 1024 * 1024
const MAX_NAME = 100
export const TOO_BIG = "This file is too big for reference documents (at most 5 MB)."
export const WRONG_TYPE = "Files of this type can't be saved as reference documents."
const NO_NAME = "This file's name has nothing usable in it, so it can't be saved as a reference document."
const FAILED = "The file could not be saved. Please try again in the project's settings."

type Reason = "too-big" | "wrong-type" | "exists" | "other"

/** What the agent offered: the file (shown to Alex only), its conversation and the project. */
export interface SaveAsk {
  attachmentId: string
  project: string
  thread: string
  file: { name: string; mime: string; size: number }
}

/** Pick out a save offer that fits the shape; null when it does not. */
export function saveAskFrom(data: unknown): SaveAsk | null {
  const d = (data ?? {}) as Record<string, unknown>
  const f = (d.file ?? {}) as Record<string, unknown>
  if (typeof d.attachment_id !== "string" || typeof d.project !== "string" || !d.project) return null
  if (typeof f.name !== "string" || typeof f.mime !== "string" || typeof f.size !== "number" || typeof f.thread_id !== "string") return null
  return { attachmentId: d.attachment_id, project: d.project, thread: f.thread_id, file: { name: f.name, mime: f.mime, size: f.size } }
}

/** The file name as Phoenix will keep it (the same cleaning as phoenix9/reference.py clean_name), or why it can't be. */
export function referenceName(filename: string): { name: string } | { reason: Reason; words: string } {
  let base = (filename.split(/[\\/]/).pop() ?? "").replace(/ /g, "-")
  base = base.replace(/[^A-Za-z0-9._-]/g, "").replace(/\.{2,}/g, ".").replace(/^\.+/, "")
  const dot = base.lastIndexOf(".")
  let stem = dot >= 0 ? base.slice(0, dot) : base
  const tail = dot >= 0 ? base.slice(dot + 1) : ""
  const ext = tail ? `.${tail.toLowerCase()}` : ""
  if (!ALLOWED_EXTENSIONS.split(" ").includes(ext)) return { reason: "wrong-type", words: WRONG_TYPE }
  stem = stem.replace(/^\.+|\.+$/g, "")
  if (!stem) return { reason: "other", words: NO_NAME }
  return { name: stem.slice(0, MAX_NAME - ext.length) + ext }
}

/** Why the file can't go into reference documents at all, or null when it may. */
function blockedBy(ask: SaveAsk): { reason: Reason; words: string } | null {
  if (ask.file.size > REFERENCE_MAX_FILE) return { reason: "too-big", words: TOO_BIG }
  const named = referenceName(ask.file.name)
  return "reason" in named ? named : null
}

type Phase = "open" | "saving" | "exists" | "saved" | "cancelled" | "refused"

/** The file, its size and "Save into <project>'s reference documents?" with Save and Cancel (Replace when it exists). */
export function SaveAttachmentCard({ ask, callId }: { ask: SaveAsk; callId: string }) {
  const [phase, setPhase] = useState<Phase>("open")
  const [words, setWords] = useState("")
  const blocked = blockedBy(ask)
  const named = referenceName(ask.file.name)
  const name = "name" in named ? named.name : ask.file.name
  const href = attachmentUrl(ask.thread, ask.attachmentId)

  const tell = async (result: { status: "saved" | "cancelled" | "refused"; reason?: Reason }) => {
    try { await answerBrowser(callId, result) } catch { /* the run times out on its own */ }
  }
  const refuse = async (reason: Reason, text: string) => {
    setWords(text)
    setPhase("refused")
    await tell({ status: "refused", reason })
  }
  const send = async (replace: boolean) => {
    setPhase("saving")
    try {
      const res = await fetch(href, { headers: { "X-Phoenix": "1" } })
      if (!res.ok) return await refuse("other", FAILED)
      await api.addReferenceFile(ask.project, name, await toBase64(await res.blob()), replace)
    } catch (err) {
      return await refuse(err instanceof ApiError && /too big/.test(err.message) ? "too-big" : "other",
        err instanceof ApiError ? err.message : FAILED)
    }
    setPhase("saved")
    await tell({ status: "saved" })
  }
  const save = async () => {
    if (blocked) return
    setPhase("saving")
    try {
      const view = await api.reference(ask.project)
      if (view.files.some((f) => f.name === name)) { setPhase("exists"); return }
    } catch (err) {
      return await refuse("other", err instanceof ApiError ? err.message : FAILED)
    }
    await send(false)
  }
  const cancel = async () => {
    if (blocked) return await refuse(blocked.reason, blocked.words)
    setPhase("cancelled")
    await tell(phase === "exists" ? { status: "cancelled", reason: "exists" } : { status: "cancelled" })
  }

  const waiting = phase === "open" || phase === "saving" || phase === "exists"
  return (
    <section className={cardClass(waiting)} aria-label="Save a file into reference documents" data-testid="save-attachment-card">
      <h3 className="ag-card-h">Save a file for {ask.project}{waiting ? <NeedsYou /> : null}</h3>
      <div className="ag-card-b">
        {ask.file.mime.startsWith("image/")
          ? <a className="ag-thumb" href={href} target="_blank" rel="noopener noreferrer" title={ask.file.name}>
              <img src={href} alt={ask.file.name} loading="lazy" />
            </a>
          : <span className="ag-file-chip"><Icon name="file-text" size="sm" /><span className="ag-file-name">{ask.file.name}</span></span>}
        <p className="ag-quiet">{ask.file.name} · {sizeWords(ask.file.size)}</p>
        {waiting && phase !== "exists" && <p>Save into {ask.project}'s reference documents?</p>}
        {phase === "exists" && <p>{ask.project} already has a reference document called {name}. Replace it?</p>}
        {waiting && blocked && <p role="status" className="ag-result"><Mark ok={false} /><span>{blocked.words}</span></p>}
        {phase === "saved" && <p className="ag-result"><Mark ok /><span>Saved into {ask.project}'s reference documents.</span></p>}
        {phase === "cancelled" && <p className="ag-quiet">Cancelled.</p>}
        {phase === "refused" && <p role="alert" className="ag-result"><Mark ok={false} /><span>Not saved. {words}</span></p>}
      </div>
      {waiting && (
        <div className="ag-card-f">
          <button type="button" className="btn btn-ghost" disabled={phase === "saving"} onClick={() => void cancel()}>Cancel</button>
          {phase === "exists"
            ? <button type="button" className="btn btn-primary" onClick={() => void send(true)}>Replace</button>
            : <button type="button" className="btn btn-primary" disabled={phase === "saving" || blocked !== null} onClick={() => void save()}>Save</button>}
        </div>
      )}
    </section>
  )
}
