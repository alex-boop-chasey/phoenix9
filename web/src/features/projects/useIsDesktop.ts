// True when the window is at least Tailwind's md width (768 px); follows window resizes.
import { useEffect, useState } from "react"

const QUERY = "(min-width: 768px)"

function matches(): boolean {
  return typeof window.matchMedia === "function" ? window.matchMedia(QUERY).matches : true
}

/** Whether to show the desktop table (true) or the phone cards (false). */
export function useIsDesktop(): boolean {
  const [desktop, setDesktop] = useState(matches)
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return
    const list = window.matchMedia(QUERY)
    const onChange = () => setDesktop(list.matches)
    onChange()
    list.addEventListener?.("change", onChange)
    return () => list.removeEventListener?.("change", onChange)
  }, [])
  return desktop
}
