import { Check, Copy } from "lucide-react"
import { useState } from "react"

import { Button } from "@/components/ui/button"

/** A small button that copies `text` to the clipboard. */
export function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [done, setDone] = useState(false)
  async function copy() {
    try {
      await navigator.clipboard.writeText(text)
      setDone(true)
      setTimeout(() => setDone(false), 1500)
    } catch {
      setDone(false)
    }
  }
  return (
    <Button variant="ghost" size="sm" onClick={copy} aria-label={label}>
      {done ? <Check /> : <Copy />}
      {done ? "Copied" : label}
    </Button>
  )
}
