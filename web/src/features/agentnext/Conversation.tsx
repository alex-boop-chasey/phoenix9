// One conversation with the agent: the chat, cards, approvals, Stop and the message box that stays at the bottom
// (with files attached by the paperclip, by pasting or by dropping them on the conversation).
import {
  useEffect, useMemo, useRef, useState, type ClipboardEvent, type DragEvent, type KeyboardEvent, type ReactNode, type SyntheticEvent,
} from "react"
import { useNavigate } from "react-router"

import { Icon } from "@/components/Icon"
import { ApprovalCard, SuggestionChips, makeGoTo } from "./approval"
import {
  ACCEPT, MAX_FILE, TOO_BIG, checkFile, kindOf, shrinkImage, sizeWords, uploadAttachment, type AttachmentInfo,
} from "./attach"
import { COMPONENTS } from "./components"
import { FlowLine, flowFrom } from "./flowcard"
import type { PageParts } from "./pageContext"
import {
  AssistantRuntimeProvider, ComposerPrimitive, ThreadPrimitive, attachmentUrl, attachmentsUrl, olderFlowSteps, useAgentNextRuntime,
  type CardItem, type ChatLine, type Frame,
} from "./runtime"
import { WorkingLine } from "./WorkingLine"

/** A message sent while the agent was still writing: it waits its turn on the service. */
export interface QueuedMessage { runId: string; text: string; thread: string; queued: boolean; attachments?: AttachmentInfo[] }

/** A file chosen for the next message: uploading until the service gives it an id (`info`). */
interface Chosen { key: number; name: string; size: number; image: boolean; preview?: string; info?: AttachmentInfo }

/** The files that went with a message: pictures as small thumbnails, other files as chips; each opens in a new tab. */
function SentFiles({ thread, files }: { thread: string; files?: AttachmentInfo[] }) {
  if (!files?.length || !thread) return null
  return (
    <span className="ag-sent-files">
      {files.map((f) => {
        const href = attachmentUrl(thread, f.id)
        return f.mime.startsWith("image/")
          ? <a key={f.id} className="ag-thumb" href={href} target="_blank" rel="noopener noreferrer" title={f.name}>
              <img src={href} alt={f.name} loading="lazy" />
            </a>
          : <a key={f.id} className="ag-file-chip" href={href} target="_blank" rel="noopener noreferrer">
              <Icon name="file-text" size="sm" /><span className="ag-file-name">{f.name}</span>
            </a>
      })}
    </span>
  )
}

/** One typed card, drawn from its data. */
function Card({ card, older, onSend }: { card: CardItem; older?: boolean; onSend?: (message: string) => void }) {
  if (older) {
    const flow = flowFrom(card.data)
    return flow ? <FlowLine card={flow} /> : null
  }
  const Draw = COMPONENTS[card.component]
  return Draw ? <>{Draw({ data: card.data, tool: card.component, callId: card.toolCallId, onSend })}</> : null
}

/** One earlier line: Alex's or the model's words, or a quiet note (what was done on its own, Phoenix's outcome). */
function Line({ line, thread }: { line: ChatLine; thread: string }) {
  if (line.role === "note") return <p data-role="note" className="ag-note" role="note">{line.text}</p>
  return line.attachments?.length
    ? <p data-role={line.role}><SentFiles thread={thread} files={line.attachments} />{line.text}</p>
    : <p data-role={line.role}>{line.text}</p>
}

/** True when what is dragged over the conversation holds files. */
const dragsFiles = (e: DragEvent) => Array.from(e.dataTransfer?.types ?? []).includes("Files")

/** What a conversation shows and does; everything after `onRunEnd` is for the drawer and may be left out. */
export interface ConversationProps {
  thread: string
  earlier: ChatLine[]
  earlierCards: CardItem[]
  follow?: { frames: Frame[] }
  onRunEnd: () => void
  /** Show the "Agent" heading (the drawer has its own). */
  heading?: boolean
  /** What Alex has open, sent with every message. */
  context?: PageParts
  /** The small "Looking at" chip shown inside the message box, above the text. */
  chip?: ReactNode
  /** A short line shown just above the message box (the allowance). */
  notice?: ReactNode
  /** Where go_to moves the dashboard (default: the router). */
  goTo?: (path: string) => void
  /** Messages waiting their turn, shown as "Queued". */
  queued?: QueuedMessage[]
  /** Turns on sending while the agent writes; called with each message the service took. */
  onQueued?: (item: QueuedMessage) => void
  /** Called when Alex presses Stop (the service drops the queue). */
  onStopped?: () => void
  /** Called once the conversation has a service id (a new chat gets one with its first message). */
  onThread?: (id: string) => void
  /** A message to send as soon as the conversation shows (once per key). */
  pending?: { key: number; text: string }
  onPendingSent?: (key: number) => void
  /** Called when an approval card starts waiting for Alex. */
  onApprovalWaiting?: () => void
  /** The allowance is low: say quietly that files use more of it while files are attached. */
  allowanceLow?: boolean
}

/** One conversation: the chat, cards, approvals, Stop and the message box. */
export function Conversation(props: ConversationProps) {
  const { thread, earlier, earlierCards, follow, onRunEnd, heading = true, context, chip, notice, goTo, queued = [], onQueued, onStopped, onThread, pending, onPendingSent, onApprovalWaiting, allowanceLow } = props
  const navigate = useNavigate()
  const browserHandler = useMemo(() => makeGoTo(goTo ?? ((hash) => navigate(hash))), [goTo, navigate])
  const { runtime, agent, side } = useAgentNextRuntime(browserHandler, thread, follow)
  agent.context = context

  const allCards = useMemo(() => [...earlierCards, ...side.cards], [earlierCards, side.cards])
  const older = useMemo(() => olderFlowSteps(allCards), [allCards])
  // While the newest flow card is active it has its own Cancel button, so cancel chips are left out.
  const flowActive = useMemo(() => {
    const newest = [...allCards].reverse().map((c) => (c.component === "FlowCard" ? flowFrom(c.data) : null)).find(Boolean)
    return newest?.status === "active"
  }, [allCards])
  // Calls that drew a card show the card instead; the rest are this turn's steps.
  const steps = useMemo(() => (side.calls ?? []).filter((c) => !c.component), [side.calls])

  const [wasRunning, setWasRunning] = useState(false)
  useEffect(() => {
    if (side.running) setWasRunning(true)
    else if (wasRunning) { setWasRunning(false); onRunEnd() }
  }, [side.running, wasRunning, onRunEnd])

  const waiting = side.approvals.filter((a) => a.decision === "pending").length
  const waitingBefore = useRef(waiting)
  useEffect(() => {
    if (waiting > waitingBefore.current) onApprovalWaiting?.()
    waitingBefore.current = waiting
  }, [waiting, onApprovalWaiting])

  useEffect(() => {
    if (side.thread) onThread?.(side.thread)
  }, [side.thread, onThread])

  const say = (text: string) => runtime.thread.append({ role: "user", content: [{ type: "text", text }] })
  const queueing = !!onQueued && side.running

  /** Send a message while the agent writes: the service queues it, or says plainly why not. */
  const sendQueued = async (text: string, files: AttachmentInfo[] = []) => {
    const got = await agent.send(text, files)
    if (!("error" in got)) {
      const item: QueuedMessage = { runId: got.run_id, text, thread: agent.serviceThread, queued: got.queued }
      onQueued?.(files.length ? { ...item, attachments: files } : item)
    }
  }

  // Files chosen for the next message; each is uploaded at once and shows as a chip until the message goes.
  const [chosen, setChosen] = useState<Chosen[]>([])
  const chosenRef = useRef<Chosen[]>([])
  const nextKey = useRef(0)
  const [fileNote, setFileNote] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)
  const dragDepth = useRef(0)
  const picker = useRef<HTMLInputElement>(null)
  const change = (fn: (list: Chosen[]) => Chosen[]) => {
    chosenRef.current = fn(chosenRef.current)
    setChosen(chosenRef.current)
  }
  const drop = (key: number) => change((list) => list.filter((c) => {
    if (c.key === key && c.preview) URL.revokeObjectURL(c.preview)
    return c.key !== key
  }))
  const upload = async (key: number, file: File) => {
    const small = await shrinkImage(file)
    let got: AttachmentInfo | { error: string }
    if (small.size > MAX_FILE) got = { error: TOO_BIG }
    else {
      try { got = await uploadAttachment(attachmentsUrl(await agent.serviceThreadId()), small) }
      catch { got = { error: "The agent isn't available right now." } }
    }
    if (!chosenRef.current.some((c) => c.key === key)) return   // removed while it was uploading
    if ("error" in got) {
      setFileNote(got.error)
      drop(key)
    } else {
      const info = got
      change((list) => list.map((c) => (c.key === key ? { ...c, info, name: info.name, size: info.size } : c)))
    }
  }
  const addFiles = (files: File[]) => {
    setFileNote(null)
    let count = chosenRef.current.length
    for (const file of files) {
      const why = checkFile(file, count)
      if (why) { setFileNote(why); continue }
      count++
      const key = ++nextKey.current
      const image = kindOf(file) === "image"
      const preview = image && typeof URL.createObjectURL === "function" ? URL.createObjectURL(file) : undefined
      change((list) => [...list, { key, name: file.name, size: file.size, image, preview }])
      void upload(key, file)
    }
  }
  const uploading = chosen.some((c) => !c.info)

  // While the agent writes, Enter and Send go to the queue; with files attached, Send takes them along.
  const takeForQueue = (e: SyntheticEvent) => {
    const withFiles = chosenRef.current.length > 0
    if (!queueing && !withFiles) return
    e.preventDefault()
    e.stopPropagation()
    if (chosenRef.current.some((c) => !c.info)) return   // Send waits until every file is uploaded
    const files = chosenRef.current.flatMap((c) => (c.info ? [c.info] : []))
    const text = runtime.thread.composer.getState().text.trim()
    if (!text && !files.length) return
    runtime.thread.composer.setText("")
    change((list) => { list.forEach((c) => c.preview && URL.revokeObjectURL(c.preview)); return [] })
    setFileNote(null)
    if (queueing) void sendQueued(text, files)
    else {
      agent.attachNext(files)
      void say(text)
    }
  }
  const onPaste = (e: ClipboardEvent) => {
    const files = Array.from(e.clipboardData?.files ?? [])
    if (!files.length) return
    e.preventDefault()
    addFiles(files)
  }
  const onDragEnter = (e: DragEvent) => {
    if (!dragsFiles(e)) return
    e.preventDefault()
    dragDepth.current++
    setDragging(true)
  }
  const onDragOver = (e: DragEvent) => {
    if (dragsFiles(e)) e.preventDefault()
  }
  const onDragLeave = () => {
    dragDepth.current = Math.max(0, dragDepth.current - 1)
    if (!dragDepth.current) setDragging(false)
  }
  const onDrop = (e: DragEvent) => {
    if (!dragsFiles(e) && !e.dataTransfer?.files?.length) return
    e.preventDefault()
    dragDepth.current = 0
    setDragging(false)
    addFiles(Array.from(e.dataTransfer.files))
  }
  const serviceThread = side.thread ?? thread
  const userIds = (): string[] => runtime.thread.getState().messages.filter((m) => m.role === "user").map((m) => m.id)
  const onKeyDownCapture = (e: KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) takeForQueue(e)
  }

  const sentKey = useRef<number | null>(null)
  useEffect(() => {
    if (!pending || sentKey.current === pending.key) return
    sentKey.current = pending.key
    if (onQueued && side.running) void sendQueued(pending.text)
    else say(pending.text)
    onPendingSent?.(pending.key)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pending])

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <div
        className={`ag-conv${dragging ? " ag-drop" : ""}`} data-testid="agent-conversation"
        onDragEnter={onDragEnter} onDragOver={onDragOver} onDragLeave={onDragLeave} onDrop={onDrop}
      >
      <div className="ag-scroll">
        {heading && <h1>Agent</h1>}
        {[...earlier, ...(side.caught ?? [])].map((l) => <Line key={l.id} line={l} thread={serviceThread} />)}
        <ThreadPrimitive.Root>
          <ThreadPrimitive.Viewport className="flex flex-col gap-2">
            <ThreadPrimitive.Messages>
              {({ message }) => (
                <p data-role={message.role}>
                  {message.role === "user" && <SentFiles thread={serviceThread} files={side.sentFiles?.[userIds().indexOf(message.id)]} />}
                  {message.content.map((part, i) => (part.type === "text" ? <span key={i}>{part.text}</span> : null))}
                </p>
              )}
            </ThreadPrimitive.Messages>
          </ThreadPrimitive.Viewport>
        </ThreadPrimitive.Root>
        {(side.notes ?? []).map((l) => <Line key={l.id} line={l} thread={serviceThread} />)}
        <WorkingLine calls={steps} running={side.running} />
        {allCards.map((c) => <Card key={c.toolCallId} card={c} older={older.has(c.toolCallId)} onSend={say} />)}
        {side.approvals.map((a) => (
          <ApprovalCard key={a.approvalId} item={a} onDecide={(d, confirm) => agent.decide(a.approvalId, d, confirm)} />
        ))}
        <SuggestionChips actions={side.suggestions} onSend={say} flowActive={flowActive} />
        {queued.length > 0 && (
          <ul className="flex flex-col gap-1" aria-label="Waiting to be answered" data-testid="agent-queued">
            {queued.map((q) => (
              <li key={q.runId} data-role="user" className="text-muted-foreground">
                <span className="badge b-info">Queued</span> {q.text}
                {q.attachments?.length ? <span className="ag-note"> {q.attachments.map((f) => f.name).join(", ")}</span> : null}
              </li>
            ))}
          </ul>
        )}
        {side.refused && <p role="alert">{side.refused}</p>}
      </div>
      <div className="ag-comp">
        {notice}
        {allowanceLow && chosen.length > 0 && (
          <p role="status" className="ag-allow" data-testid="files-allowance">Files use more of this month's allowance.</p>
        )}
        {fileNote && <p role="status" className="ag-allow" data-testid="file-refused">{fileNote}</p>}
        <div onKeyDownCapture={onKeyDownCapture} onSubmitCapture={takeForQueue} onPasteCapture={onPaste}>
          <ComposerPrimitive.Root className="ag-field">
            {chip}
            {chosen.length > 0 && (
              <ul className="ag-files" aria-label="Attached files">
                {chosen.map((c) => (
                  <li key={c.key} className="ag-file-chip" data-state={c.info ? "ready" : "uploading"}>
                    {c.image && c.preview ? <img className="ag-file-thumb" src={c.preview} alt="" /> : <Icon name="file-text" size="sm" />}
                    <span className="ag-file-name">{c.name}</span>
                    <span className="ag-file-size">{c.info ? sizeWords(c.size) : "Uploading…"}</span>
                    <button type="button" className="ag-file-x" aria-label={`Remove ${c.name}`} title={`Remove ${c.name}`} onClick={() => drop(c.key)}>
                      <Icon name="x" size="xs" />
                    </button>
                  </li>
                ))}
              </ul>
            )}
            <div className="ag-row">
              <button type="button" className="btn btn-ghost btn-icon" aria-label="Attach files" title="Attach files" onClick={() => picker.current?.click()}>
                <Icon name="paperclip" />
              </button>
              <input
                ref={picker} type="file" multiple accept={ACCEPT} hidden tabIndex={-1} aria-hidden="true" data-testid="attach-input"
                onChange={(e) => { addFiles(Array.from(e.target.files ?? [])); e.target.value = "" }}
              />
              <ComposerPrimitive.Input
                className="ag-input" placeholder="Ask the agent" aria-label="Message" minRows={1} maxRows={6}
                autoComplete="off" autoCorrect="on" enterKeyHint="send"
              />
              {side.running && (
                <button type="button" className="btn btn-ghost btn-icon" aria-label="Stop" title="Stop" onClick={() => { onStopped?.(); void agent.stop() }}>
                  <Icon name="stop" />
                </button>
              )}
              {queueing || chosen.length > 0
                ? <button type="submit" className="btn btn-primary btn-icon" aria-label="Send" title="Send" disabled={uploading}><Icon name="paper-plane" /></button>
                : <ComposerPrimitive.Send asChild>
                    <button type="submit" className="btn btn-primary btn-icon" aria-label="Send" title="Send"><Icon name="paper-plane" /></button>
                  </ComposerPrimitive.Send>}
            </div>
          </ComposerPrimitive.Root>
        </div>
      </div>
      </div>
    </AssistantRuntimeProvider>
  )
}
