/** Small helpers that turn numbers into plain words. */

/** Bytes as "1.5 MB"; null/undefined as a dash. */
export function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null || !Number.isFinite(bytes)) return "-"
  if (bytes < 1024) return `${bytes} B`
  const units = ["KB", "MB", "GB", "TB"]
  let value = bytes / 1024
  let i = 0
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024
    i++
  }
  return `${value >= 10 ? Math.round(value) : value.toFixed(1)} ${units[i]}`
}

/** Seconds as "45s", "14 min", "2 h 5 min" or "5 days". */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return "-"
  const total = Math.round(seconds)
  if (total < 60) return `${total}s`
  const minutes = Math.floor(total / 60)
  if (minutes < 60) return `${minutes} min`
  const hours = Math.floor(minutes / 60)
  if (hours >= 24) {
    const days = Math.floor(hours / 24)
    return `${days} day${days === 1 ? "" : "s"}`
  }
  const rest = minutes % 60
  return rest ? `${hours} h ${rest} min` : `${hours} h`
}

/** Dollars as "$1.23"; null/undefined as a dash. */
export function formatCost(usd: number | null | undefined): string {
  if (usd == null || !Number.isFinite(usd)) return "-"
  return `$${usd.toFixed(2)}`
}

/** An ISO time as words like "5 minutes ago". */
export function relativeTime(iso: string, now: number = Date.now()): string {
  const then = Date.parse(iso)
  if (Number.isNaN(then)) return ""
  const secs = Math.round((now - then) / 1000)
  if (secs < 45) return "just now"
  const mins = Math.round(secs / 60)
  if (mins < 60) return `${mins} minute${mins === 1 ? "" : "s"} ago`
  const hours = Math.round(mins / 60)
  if (hours < 24) return `${hours} hour${hours === 1 ? "" : "s"} ago`
  const days = Math.round(hours / 24)
  return `${days} day${days === 1 ? "" : "s"} ago`
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

function clock(d: Date): string {
  const h = d.getHours() % 12 || 12
  return `${h}:${String(d.getMinutes()).padStart(2, "0")} ${d.getHours() < 12 ? "am" : "pm"}`
}

/** An ISO time in local time: "3:42 pm" today, "9 Nov, 3:42 pm" this year, "9 Nov 2025, 3:42 pm" before; "" when unknown. */
export function shortWhen(iso: string | null | undefined, now: Date = new Date()): string {
  const d = iso ? new Date(iso) : null
  if (!d || Number.isNaN(d.getTime())) return ""
  const day = `${d.getDate()} ${MONTHS[d.getMonth()]}`
  if (d.getFullYear() !== now.getFullYear()) return `${day} ${d.getFullYear()}, ${clock(d)}`
  if (d.getMonth() === now.getMonth() && d.getDate() === now.getDate()) return clock(d)
  return `${day}, ${clock(d)}`
}

/** An ISO time in full local words, e.g. "Monday 9 November 2026, 3:42 pm"; "" when unknown. */
export function fullWhen(iso: string | null | undefined): string {
  const d = iso ? new Date(iso) : null
  if (!d || Number.isNaN(d.getTime())) return ""
  const date = d.toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long", year: "numeric" })
  return `${date.replace(",", "")}, ${clock(d)}`
}
