// Reference material: files and links saved in the project's notes/reference folder, given to every build.
import { useCallback, useEffect, useId, useRef, useState, type DragEvent } from "react"

import { Icon } from "@/components/Icon"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { api, ApiError } from "@/lib/api"
import { formatBytes } from "@/lib/format"
import type { ReferenceView } from "@/lib/types"

export const ALLOWED_EXTENSIONS =
  ".txt .md .css .scss .json .js .ts .html .svg .png .jpg .jpeg .webp .gif .pdf .csv .yaml .yml .toml"

interface Upload {
  id: number
  name: string
  size: number
  state: "saving" | "refused"
  message?: string
}

const errorText = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong. Please try again.")

function toBase64(buf: ArrayBuffer): string {
  const bytes = new Uint8Array(buf)
  let out = ""
  for (let i = 0; i < bytes.length; i += 0x8000) out += String.fromCharCode(...bytes.subarray(i, i + 0x8000))
  return btoa(out)
}

const readBuffer = (file: File): Promise<ArrayBuffer> =>
  typeof file.arrayBuffer === "function"
    ? file.arrayBuffer()
    : new Promise((resolve, reject) => {
        const r = new FileReader()
        r.onload = () => resolve(r.result as ArrayBuffer)
        r.onerror = () => reject(r.error)
        r.readAsArrayBuffer(file)
      })

const readText = (file: File): Promise<string> =>
  typeof file.text === "function"
    ? file.text()
    : new Promise((resolve, reject) => {
        const r = new FileReader()
        r.onload = () => resolve(String(r.result))
        r.onerror = () => reject(r.error)
        r.readAsText(file)
      })

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`

/** One line saying what the build will get. */
export function summaryLine(files: number, links: number): string {
  if (!files && !links) return "No reference material yet. Optional."
  return `${plural(files, "file")} and ${plural(links, "link")} will be given to the build`
}

/** The Reference material card: upload files, add links; saved straight away. */
export function ReferenceCard({ project }: { project: string }) {
  const uid = useId()
  const fileInput = useRef<HTMLInputElement>(null)
  const linksInput = useRef<HTMLInputElement>(null)
  const nextId = useRef(1)
  const [view, setView] = useState<ReferenceView | null>(null)
  const [loadError, setLoadError] = useState("")
  const [uploads, setUploads] = useState<Upload[]>([])
  const [paste, setPaste] = useState("")
  const [linkBusy, setLinkBusy] = useState(false)
  const [linkError, setLinkError] = useState("")
  const [removeError, setRemoveError] = useState("")
  const [dragging, setDragging] = useState(false)

  const refresh = useCallback(async () => {
    try {
      setView(await api.reference(project))
      setLoadError("")
    } catch (e) {
      setLoadError(errorText(e))
    }
  }, [project])

  useEffect(() => { void refresh() }, [refresh])

  const patch = (id: number, change: Partial<Upload>) =>
    setUploads((list) => list.map((u) => (u.id === id ? { ...u, ...change } : u)))

  async function uploadOne(file: File) {
    const id = nextId.current++
    setUploads((list) => [...list, { id, name: file.name, size: file.size, state: "saving" }])
    try {
      await api.addReferenceFile(project, file.name, toBase64(await readBuffer(file)))
      setUploads((list) => list.filter((u) => u.id !== id))
    } catch (e) {
      patch(id, { state: "refused", message: errorText(e) })
    }
    await refresh()
  }

  async function uploadAll(files: File[]) {
    for (const f of files) await uploadOne(f)
  }

  const onPick = (list: FileList | null) => {
    const files = Array.from(list ?? [])
    if (fileInput.current) fileInput.current.value = ""
    void uploadAll(files)
  }

  const onDrop = (ev: DragEvent) => {
    ev.preventDefault()
    setDragging(false)
    void uploadAll(Array.from(ev.dataTransfer.files))
  }

  async function removeFile(name: string) {
    setRemoveError("")
    try {
      await api.removeReferenceFile(project, name)
    } catch (e) {
      setRemoveError(errorText(e))
    }
    await refresh()
  }

  async function removeLink(url: string) {
    setRemoveError("")
    try {
      await api.removeReferenceLink(project, url)
    } catch (e) {
      setRemoveError(errorText(e))
    }
    await refresh()
  }

  async function addLinks(text: string, clear: boolean) {
    setLinkBusy(true)
    setLinkError("")
    try {
      await api.addReferenceLinks(project, text)
      if (clear) setPaste("")
    } catch (e) {
      setLinkError(errorText(e))
    }
    setLinkBusy(false)
    await refresh()
  }

  async function onLinksFile(list: FileList | null) {
    const file = list?.[0]
    if (linksInput.current) linksInput.current.value = ""
    if (file) await addLinks(await readText(file), false)
  }

  const files = view?.files.filter((f) => f.kind !== "links") ?? []
  const links = view?.links ?? []

  return (
    <section className="stackg" aria-label="Reference material" data-card="Reference material" style={{ marginTop: 8 }}>
      <span className="lbl">Reference material</span>
      <span className="help">
        Style sheets, design tokens, notes, images or links the build should look at. Optional. They are only read, never run.
      </span>

      <div
        className="field"
        onDragOver={(ev) => { ev.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        data-testid="reference-drop"
        style={{
          border: "1px dashed var(--border, currentColor)", borderRadius: 8, padding: 12,
          opacity: dragging ? 0.7 : 1, display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center",
        }}
      >
        <Icon name="file-text" size="sm" />
        <span className="small">Drop files here, or</span>
        <Button type="button" variant="secondary" size="sm" onClick={() => fileInput.current?.click()}>Choose files</Button>
        <input
          ref={fileInput} type="file" multiple hidden accept={ALLOWED_EXTENSIONS.split(" ").join(",")}
          aria-label="Reference files" onChange={(ev) => onPick(ev.target.files)}
        />
      </div>

      {uploads.length > 0 && (
        <ul className="stackg" aria-label="Uploading">
          {uploads.map((u) => (
            <li key={u.id} className="small" role={u.state === "refused" ? "alert" : undefined}>
              <span className="mono">{u.name}</span> ({formatBytes(u.size)}){" "}
              {u.state === "saving" ? "Saving…" : <>Not saved: {u.message}{" "}
                <Button type="button" variant="ghost" size="sm" aria-label={`Dismiss ${u.name}`}
                  onClick={() => setUploads((l) => l.filter((x) => x.id !== u.id))}>Dismiss</Button></>}
            </li>
          ))}
        </ul>
      )}

      {files.length > 0 && (
        <ul className="stackg" aria-label="Saved files">
          {files.map((f) => (
            <li key={f.name} className="small" style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              <span className="mono" style={{ overflowWrap: "anywhere" }}>{f.name}</span>
              <span>{formatBytes(f.size)}</span>
              <Button type="button" variant="ghost" size="sm" aria-label={`Remove ${f.name}`} onClick={() => void removeFile(f.name)}>Remove</Button>
            </li>
          ))}
        </ul>
      )}

      <div className="field">
        <label htmlFor={`${uid}-links`}>Paste links, one per line (add a note after | if you like)</label>
        <Textarea id={`${uid}-links`} rows={3} value={paste} onChange={(e) => setPaste(e.target.value)} placeholder="https://example.com/brand | our brand guide" />
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <Button type="button" variant="secondary" size="sm" disabled={linkBusy || !paste.trim()} onClick={() => void addLinks(paste, true)}>Add</Button>
          <Button type="button" variant="secondary" size="sm" disabled={linkBusy} onClick={() => linksInput.current?.click()}>Choose a .txt of links</Button>
          <input
            ref={linksInput} type="file" accept=".txt,text/plain" hidden aria-label="Links file"
            onChange={(ev) => void onLinksFile(ev.target.files)}
          />
        </div>
        {linkError && <span className="help" role="alert">{linkError}</span>}
      </div>

      {links.length > 0 && (
        <ul className="stackg" aria-label="Saved links">
          {links.map((l) => (
            <li key={l.url} className="small" style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              <span className="mono" style={{ overflowWrap: "anywhere" }}>{l.url}</span>
              {l.note && <span>{l.note}</span>}
              <Button type="button" variant="ghost" size="sm" aria-label={`Remove ${l.url}`} onClick={() => void removeLink(l.url)}>Remove</Button>
            </li>
          ))}
        </ul>
      )}

      {removeError && <span className="help" role="alert">{removeError}</span>}
      {loadError && <span className="help" role="alert">{loadError}</span>}
      <p className="small" aria-live="polite">{view ? summaryLine(files.length, links.length) : "Loading reference material…"}</p>
    </section>
  )
}
