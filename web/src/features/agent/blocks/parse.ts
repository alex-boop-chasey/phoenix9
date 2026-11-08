// Splits agent markdown into text parts and reply-block parts (fenced blocks tagged phoenix-*).

export type BlockKind = "card" | "choice" | "confirm" | "nav"

export interface TextPart { type: "text"; text: string }
export interface BlockPart {
  type: "block"
  tag: string
  /** Null when the tag is not one of the four known kinds. */
  kind: BlockKind | null
  json: string
  /** The plain line that follows the block (empty when there is none). */
  fallback: string
}
export type Part = TextPart | BlockPart

const KINDS: Record<string, BlockKind> = {
  "phoenix-card": "card",
  "phoenix-choice": "choice",
  "phoenix-confirm": "confirm",
  "phoenix-nav": "nav",
}

const OPEN = /^\s*(`{3,})\s*([^\s`]*)/
const closes = (line: string, ticks: string) => new RegExp(`^\\s*\`{${ticks.length},}\\s*$`).test(line)

/** The block kind for a fence tag, or null when unknown. */
export function kindOf(tag: string): BlockKind | null {
  return KINDS[tag] ?? null
}

/** Split agent markdown into text parts and block parts; a block's fallback is the next non-empty line. */
export function parseBlocks(markdown: string): Part[] {
  const lines = markdown.replace(/\r\n?/g, "\n").split("\n")
  const parts: Part[] = []
  let text: string[] = []
  const flush = () => {
    if (text.some((l) => l.trim())) parts.push({ type: "text", text: text.join("\n") })
    text = []
  }
  let i = 0
  while (i < lines.length) {
    const line = lines[i] ?? ""
    const open = OPEN.exec(line)
    if (!open) { text.push(line); i++; continue }
    const ticks = open[1] ?? "```"
    const tag = open[2] ?? ""
    let end = i + 1
    while (end < lines.length && !closes(lines[end] ?? "", ticks)) end++
    const closed = end < lines.length
    if (!tag.startsWith("phoenix-") || !closed) {
      // Ordinary code (or an unclosed fence): keep it as text for the markdown renderer.
      text.push(...lines.slice(i, closed ? end + 1 : lines.length))
      i = closed ? end + 1 : lines.length
      continue
    }
    flush()
    const json = lines.slice(i + 1, end).join("\n")
    i = end + 1
    let next = i
    while (next < lines.length && !(lines[next] ?? "").trim()) next++
    const cand = lines[next] ?? ""
    let fallback = ""
    if (next < lines.length && !OPEN.test(cand)) { fallback = cand.trim(); i = next + 1 }
    parts.push({ type: "block", tag, kind: kindOf(tag), json, fallback })
  }
  flush()
  return parts
}
