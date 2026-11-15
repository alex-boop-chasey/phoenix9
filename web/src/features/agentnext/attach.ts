// Files Alex attaches to a message: which ones may go, shrinking pictures in the browser, and sending them to the
// agent service (which checks everything again; these checks only save a pointless upload).

/** The file picker's list: pictures (phones also offer the camera), PDFs and plain text files. */
export const ACCEPT = "image/*,application/pdf,.txt,.md,.csv,.json,.yaml,.yml,.toml,.log"
export const MAX_FILE = 10 * 1024 * 1024
export const MAX_PER_MESSAGE = 5
/** Pictures are shrunk so their longest side is at most this many pixels. */
export const MAX_SIDE = 1568
export const JPEG_QUALITY = 0.85

export const TOO_BIG = "That file is too big to attach (at most 10 MB)."
export const TOO_MANY = "At most 5 files can go with one message."
export const EMPTY = "That file is empty."
export const WRONG_TYPE = "Files of that type can't be attached. Attach a picture (PNG, JPEG, WebP or GIF), a PDF or a text file (txt, md, csv, json, yaml, toml, log)."
const FAILED = "The file could not be attached. Try again."

const IMAGES = ["image/png", "image/jpeg", "image/webp", "image/gif"]
const TEXT_TYPES = ["text/plain", "text/markdown", "text/csv", "application/json"]
const TEXT_ENDINGS = [".txt", ".md", ".csv", ".json", ".yaml", ".yml", ".toml", ".log"]

/** A file sent with a message, as the service describes it. */
export interface AttachmentInfo { id: string; name: string; mime: string; size: number }

/** What kind of file it is by its type or name: a picture, a PDF, text, or null when it can't be attached. */
export function kindOf(file: { name: string; type: string }): "image" | "pdf" | "text" | null {
  const type = file.type.toLowerCase()
  const name = file.name.toLowerCase()
  if (IMAGES.includes(type)) return "image"
  if (type === "application/pdf" || name.endsWith(".pdf")) return "pdf"
  if (TEXT_TYPES.includes(type) || TEXT_ENDINGS.some((end) => name.endsWith(end))) return "text"
  if (!type && /\.(png|jpe?g|webp|gif)$/.test(name)) return "image"
  return null
}

/** The plain refusal for a file before it is sent (wrong type, empty, too big, one too many), or null. */
export function checkFile(file: { name: string; type: string; size: number }, alreadyAttached: number): string | null {
  if (alreadyAttached >= MAX_PER_MESSAGE) return TOO_MANY
  if (!kindOf(file)) return WRONG_TYPE
  if (file.size === 0) return EMPTY
  if (file.size > MAX_FILE) return TOO_BIG
  return null
}

/** The size a picture is drawn at: the longest side at most `max`, the shape kept, never made bigger. */
export function fitSize(width: number, height: number, max = MAX_SIDE): { width: number; height: number } {
  const side = Math.max(width, height)
  if (side <= max || side <= 0) return { width, height }
  const scale = max / side
  return { width: Math.max(1, Math.round(width * scale)), height: Math.max(1, Math.round(height * scale)) }
}

/** The type a shrunk picture is saved as: PNG only when it has see-through parts, else JPEG; null leaves it (GIFs). */
export function outputType(type: string, transparent: boolean): "image/png" | "image/jpeg" | null {
  if (type === "image/gif") return null
  return type === "image/png" && transparent ? "image/png" : "image/jpeg"
}

/** Whether a picture should be redrawn: too big, or a PNG (screenshots get much smaller as JPEG). GIFs never. */
export function needsRedraw(type: string, width: number, height: number): boolean {
  if (type === "image/gif" || !IMAGES.includes(type)) return false
  return Math.max(width, height) > MAX_SIDE || type === "image/png"
}

/** The file name after a change of type (photo.png -> photo.jpg). */
export function renamed(name: string, type: string): string {
  const end = type === "image/png" ? ".png" : ".jpg"
  const base = name.replace(/\.[^./\\]*$/, "")
  return (base || "picture") + end
}

/** True when any pixel of RGBA data is not fully opaque. */
export function hasTransparency(rgba: ArrayLike<number>): boolean {
  for (let i = 3; i < rgba.length; i += 4) if (rgba[i]! < 255) return true
  return false
}

/** Short size words: "512 bytes", "340 KB", "1.2 MB". */
export function sizeWords(bytes: number): string {
  if (bytes < 1024) return `${bytes} bytes`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

/** Shrink a picture in the browser (canvas); any other file, a GIF, or a browser that can't draw it is kept as it is. */
export async function shrinkImage(file: File): Promise<File> {
  if (kindOf(file) !== "image" || typeof createImageBitmap !== "function") return file
  try {
    const bitmap = await createImageBitmap(file)
    if (!needsRedraw(file.type, bitmap.width, bitmap.height)) return file
    const { width, height } = fitSize(bitmap.width, bitmap.height)
    const canvas = document.createElement("canvas")
    canvas.width = width
    canvas.height = height
    const ctx = canvas.getContext("2d")
    if (!ctx) return file
    ctx.drawImage(bitmap, 0, 0, width, height)
    const type = outputType(file.type, file.type === "image/png" && hasTransparency(ctx.getImageData(0, 0, width, height).data))
    if (!type) return file
    const blob = await new Promise<Blob | null>((done) => canvas.toBlob(done, type, type === "image/jpeg" ? JPEG_QUALITY : undefined))
    if (!blob || (blob.size >= file.size && width === bitmap.width)) return file
    return new File([blob], type === file.type ? file.name : renamed(file.name, type), { type })
  } catch {
    return file
  }
}

/** The file's bytes in base64 (what the service's upload takes). */
export async function toBase64(file: Blob): Promise<string> {
  const bytes = new Uint8Array(await file.arrayBuffer())
  let out = ""
  for (let i = 0; i < bytes.length; i += 0x8000) out += String.fromCharCode(...bytes.subarray(i, i + 0x8000))
  return btoa(out)
}

/** The plain words of a refused upload: the service's `error`, Phoenix's `message`, or a general line. */
export function refusalWords(body: unknown): string {
  const b = body as { error?: unknown; message?: unknown } | null
  if (b && typeof b.error === "string" && /^[A-Z]/.test(b.error)) return b.error
  if (b && typeof b.message === "string" && b.message) return b.message
  return FAILED
}

/** Send one file to the conversation; its description, or the plain refusal. */
export async function uploadAttachment(url: string, file: File): Promise<AttachmentInfo | { error: string }> {
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "X-Phoenix": "1", "Content-Type": "application/json" },
      body: JSON.stringify({ name: file.name, mime: file.type, data_base64: await toBase64(file) }),
    })
    const body = await res.json().catch(() => null)
    return res.ok && body && typeof body.id === "string" ? (body as AttachmentInfo) : { error: refusalWords(body) }
  } catch {
    return { error: FAILED }
  }
}

/** The attachments a stored `user_message` carries (only well-formed ones). */
export function attachmentsOf(value: unknown): AttachmentInfo[] {
  const list = (value as { attachments?: unknown } | null)?.attachments
  if (!Array.isArray(list)) return []
  return list.filter((a): a is AttachmentInfo =>
    !!a && typeof a.id === "string" && typeof a.name === "string" && typeof a.mime === "string" && typeof a.size === "number")
}
