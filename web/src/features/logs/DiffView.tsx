import { cn } from "@/lib/utils"

export type DiffLineKind = "file" | "meta" | "hunk" | "add" | "del" | "plain"

/** Decide how one diff line should look. */
export function diffLineKind(line: string): DiffLineKind {
  if (line.startsWith("diff --git")) return "file"
  if (line.startsWith("+++") || line.startsWith("---")) return "meta"
  if (line.startsWith("@@")) return "hunk"
  if (line.startsWith("+")) return "add"
  if (line.startsWith("-")) return "del"
  return "plain"
}

/** True when the text has real diff markers (a file header or a hunk header). */
export function looksLikeDiff(text: string): boolean {
  return text.split("\n").some((l) => l.startsWith("diff --git") || l.startsWith("@@"))
}

const LINE_CLASS: Record<DiffLineKind, string> = {
  file: "mt-3 border-t border-line pt-2 font-bold first:mt-0 first:border-t-0 first:pt-0",
  meta: "font-bold",
  hunk: "bg-info/10 text-info",
  add: "bg-ok/15 text-ok",
  del: "bg-bad/15 text-bad",
  plain: "",
}

/** Shows a diff with added lines green, removed lines red and headers picked out; plain text stays plain. */
export function DiffView({ text }: { text: string }) {
  if (!looksLikeDiff(text)) {
    return <pre>{text}</pre>
  }
  return (
    <div data-testid="diff" className="difft whitespace-pre-wrap break-words">
      {text.split("\n").map((line, i) => {
        const kind = diffLineKind(line)
        return (
          <div key={i} data-line={kind} className={cn("px-1", LINE_CLASS[kind])}>
            {line || " "}
          </div>
        )
      })}
    </div>
  )
}
