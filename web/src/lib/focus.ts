// Scroll to a part of the page and give it a short glow (no scroll animation when the person prefers reduced motion).
import { useEffect } from "react"

export const GLOW_MS = 2000

/** Scroll the element into view and glow it for 2 s; returns a function that stops the glow early. */
/** The id of the dashboard's one page scroller (the main content area; the header and sidebar never scroll). */
export const PAGE_SCROLLER_ID = "page"

/** Scroll the page (the main content area) back to its top. */
export function scrollPageTop(): void {
  const el = document.getElementById(PAGE_SCROLLER_ID)
  if (el) el.scrollTop = 0
  else window.scrollTo?.(0, 0)
}

export function scrollToAndHighlight(el: Element | null, className = "focus-glow"): () => void {
  if (!el) return () => {}
  const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false
  el.scrollIntoView?.({ behavior: reduce ? "auto" : "smooth", block: "center" })
  el.classList.add(className)
  const t = setTimeout(() => el.classList.remove(className), GLOW_MS)
  return () => {
    clearTimeout(t)
    el.classList.remove(className)
  }
}

/** Once `ready` and `id` is set, scroll to the element with that id and glow it; unknown ids are ignored. */
export function useScrollToId(id: string | null | undefined, ready = true, className?: string): void {
  useEffect(() => {
    if (!id || !ready) return
    return scrollToAndHighlight(document.getElementById(id), className)
  }, [id, ready, className])
}
