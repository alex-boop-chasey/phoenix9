import { useCallback, useSyncExternalStore } from "react"

/** Theme choice: dark by default, remembered in localStorage when it is available. */
export type Theme = "dark" | "light"

const KEY = "phoenix9-theme"
const listeners = new Set<() => void>()
let current: Theme | null = null

/** Read the saved theme; falls back to dark when storage is missing or throws. */
export function readTheme(): Theme {
  try {
    return localStorage.getItem(KEY) === "light" ? "light" : "dark"
  } catch {
    return "dark"
  }
}

/** Put the theme on the page: data-theme on <html> (the CSS tokens read it) plus the "dark" class. */
export function applyTheme(theme: Theme) {
  document.documentElement.dataset.theme = theme
  document.documentElement.classList.toggle("dark", theme === "dark")
}

/** Current theme (reads storage the first time). */
export function getTheme(): Theme {
  current ??= readTheme()
  return current
}

/** Set, apply and remember the theme; storage failures are ignored. */
export function setTheme(theme: Theme) {
  current = theme
  applyTheme(theme)
  try {
    localStorage.setItem(KEY, theme)
  } catch {
    // no storage: the choice lasts until the page closes
  }
  listeners.forEach((fn) => fn())
}

/** Switch between dark and light. */
export function toggleTheme() {
  setTheme(getTheme() === "dark" ? "light" : "dark")
}

/** Forget the in-memory choice so the next read goes to storage (used by tests). */
export function resetThemeCache() {
  current = null
}

function subscribe(fn: () => void) {
  listeners.add(fn)
  return () => listeners.delete(fn)
}

/** React hook: the current theme and a toggle. */
export function useTheme() {
  const theme = useSyncExternalStore(subscribe, getTheme)
  const toggle = useCallback(() => toggleTheme(), [])
  return { theme, toggle }
}
