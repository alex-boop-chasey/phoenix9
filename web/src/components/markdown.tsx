// Small safe markdown for agent text: builds React elements only, never HTML strings.
import type { ReactNode } from "react"

const SAFE_LINK = /^(https?:|mailto:)/i
const INLINE = /`([^`\n]+)`|\*\*([^*\n]+)\*\*|\*([^*\n]+)\*|\[([^\]\n]+)\]\(([^)\s]+)\)/g

/** Turn one line of text into inline elements (code, bold, italic, safe links). */
export function renderInline(text: string, keyBase = "i"): ReactNode[] {
  const out: ReactNode[] = []
  let last = 0
  let n = 0
  for (const m of text.matchAll(INLINE)) {
    const at = m.index ?? 0
    if (at > last) out.push(text.slice(last, at))
    const key = `${keyBase}-${n++}`
    if (m[1] !== undefined) out.push(<code key={key} className="mono">{m[1]}</code>)
    else if (m[2] !== undefined) out.push(<strong key={key}>{renderInline(m[2], key)}</strong>)
    else if (m[3] !== undefined) out.push(<em key={key}>{renderInline(m[3], key)}</em>)
    else if (SAFE_LINK.test(m[5] ?? "")) {
      out.push(<a key={key} href={m[5]} target="_blank" rel="noopener noreferrer">{renderInline(m[4] ?? "", key)}</a>)
    } else out.push(m[0])
    last = at + m[0].length
  }
  if (last < text.length) out.push(text.slice(last))
  return out
}

const BULLET = /^\s*[-*+]\s+(.*)$/
const NUMBER = /^\s*\d+[.)]\s+(.*)$/
const HEADING = /^#{1,6}\s+(.*)$/
const FENCE = /^\s*```/

/** Render markdown text as React elements; anything unsupported stays plain text. */
export function Markdown({ text }: { text: string }) {
  const lines = text.replace(/\r\n?/g, "\n").split("\n")
  const at = (n: number) => lines[n] ?? ""
  const blocks: ReactNode[] = []
  let i = 0
  while (i < lines.length) {
    const line = at(i)
    const key = `b${blocks.length}`
    if (!line.trim()) { i++; continue }
    if (FENCE.test(line)) {
      const code: string[] = []
      i++
      while (i < lines.length && !FENCE.test(at(i))) code.push(at(i++))
      i++
      blocks.push(<pre key={key} className="ag-code mono"><code>{code.join("\n")}</code></pre>)
      continue
    }
    const head = HEADING.exec(line)
    if (head) { blocks.push(<h3 key={key} className="ag-h">{renderInline(head[1] ?? "", key)}</h3>); i++; continue }
    const kind = BULLET.test(line) ? BULLET : NUMBER.test(line) ? NUMBER : null
    if (kind) {
      const items: ReactNode[] = []
      while (i < lines.length && kind.test(at(i))) {
        items.push(<li key={items.length}>{renderInline(kind.exec(at(i))?.[1] ?? "", `${key}-${items.length}`)}</li>)
        i++
      }
      blocks.push(kind === BULLET ? <ul key={key}>{items}</ul> : <ol key={key}>{items}</ol>)
      continue
    }
    const para: string[] = []
    while (i < lines.length && at(i).trim() && !FENCE.test(at(i)) && !HEADING.test(at(i)) && !BULLET.test(at(i)) && !NUMBER.test(at(i))) para.push(at(i++))
    const kids: ReactNode[] = []
    para.forEach((p, n) => {
      if (n) kids.push(<br key={`br${n}`} />)
      kids.push(...renderInline(p, `${key}-${n}`))
    })
    blocks.push(<p key={key}>{kids}</p>)
  }
  return <div className="ag-md">{blocks}</div>
}
