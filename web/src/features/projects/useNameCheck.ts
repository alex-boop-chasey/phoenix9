// Checks a new project name: locally first, then with the server after a short pause.
import { useEffect, useState } from "react"

import { api } from "@/lib/api"
import type { NameCheck } from "@/lib/types"
import { NAME_RE } from "@/features/projects/formModel"

export function useNameCheck(name: string, enabled: boolean): { message: string; ok: boolean } {
  const [result, setResult] = useState<{ name: string; check: NameCheck } | null>(null)
  const localBad = !!name && !NAME_RE.test(name)
  useEffect(() => {
    if (!enabled || !name || localBad) return
    const timer = setTimeout(() => {
      api.checkName(name).then((check) => setResult({ name, check })).catch(() => setResult(null))
    }, 300)
    return () => clearTimeout(timer)
  }, [name, enabled, localBad])
  if (localBad) {
    return { ok: false, message: "Use lowercase letters, digits and dashes, starting with a letter or digit (41 characters at most)." }
  }
  if (result && result.name === name) return result.check
  return { ok: false, message: "" }
}
