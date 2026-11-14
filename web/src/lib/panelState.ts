// Remembered Agent drawer settings (open, wide) and the phone-width check; every storage access is guarded.
import { useEffect, useState } from "react"

const OPEN_KEY = "phoenix.agent.open"
const WIDE_KEY = "phoenix.agent.wide"
const PHONE_QUERY = "(max-width: 719px)"

/** Read a remembered yes/no flag; false when storage is missing or throws. */
export function readFlag(key: string): boolean {
  try {
    return window.localStorage.getItem(key) === "1"
  } catch {
    return false
  }
}

/** Remember a yes/no flag; silently does nothing when storage throws. */
export function writeFlag(key: string, value: boolean) {
  try {
    window.localStorage.setItem(key, value ? "1" : "0")
  } catch {
    /* storage is off: the setting just is not remembered */
  }
}

/** Whether the panel was open last time. */
export const readOpen = () => readFlag(OPEN_KEY)
/** Remember whether the panel is open. */
export const writeOpen = (open: boolean) => writeFlag(OPEN_KEY, open)
/** Whether the panel was wide last time. */
export const readWide = () => readFlag(WIDE_KEY)
/** Remember whether the panel is wide. */
export const writeWide = (wide: boolean) => writeFlag(WIDE_KEY, wide)

/** True while the window is phone width (under 720 px); follows resizes. */
export function usePhoneWidth(): boolean {
  const query = () => window.matchMedia?.(PHONE_QUERY)
  const [phone, setPhone] = useState(() => query()?.matches ?? false)
  useEffect(() => {
    const mq = query()
    if (!mq) return
    const on = () => setPhone(mq.matches)
    on()
    mq.addEventListener?.("change", on)
    return () => mq.removeEventListener?.("change", on)
  }, [])
  return phone
}
