// Reads the text of a .env file into key rows (pure; the file itself is never sent or stored).

const NAME_RE = /^[A-Za-z_][A-Za-z0-9_]*$/
const PUBLIC_PREFIXES = ["PUBLIC_", "NEXT_PUBLIC_", "VITE_", "EXPO_PUBLIC_"]

/** One key read from a .env file. */
export interface EnvEntry {
  name: string
  value: string
  secret: boolean
}

/** The keys read from a file and how many lines were not KEY=value. */
export interface EnvParse {
  entries: EnvEntry[]
  skipped: number
}

/** True only for names (or values) that are clearly safe to show; everything else is secret. */
export function isPublicKey(name: string, value: string): boolean {
  const n = name.toUpperCase()
  if (n === "PORT") return true
  if (PUBLIC_PREFIXES.some((p) => n.startsWith(p))) return true
  if (n.endsWith("_URL")) return true
  if (n.endsWith("_ID") && !n.endsWith("_SECRET_ID")) return true
  const v = value.trim().toLowerCase()
  return v === "true" || v === "false"
}

/** Drop one pair of matching single or double quotes around a value. */
function unquote(value: string): string {
  const v = value.trim()
  if (v.length >= 2 && (v[0] === '"' || v[0] === "'") && v.at(-1) === v[0]) return v.slice(1, -1)
  return v
}

/** Parse .env text: skip blanks and # comments, allow `export `, strip quotes; a later repeat of a name wins. */
export function parseEnvFile(text: string): EnvParse {
  const byName = new Map<string, EnvEntry>()
  let skipped = 0
  for (const raw of text.replace(/^﻿/, "").split(/\r\n|\r|\n/)) {
    const line = raw.trim()
    if (!line || line.startsWith("#")) continue
    const body = line.replace(/^export\s+/, "")
    const eq = body.indexOf("=")
    const name = eq < 0 ? "" : body.slice(0, eq).trim()
    if (!NAME_RE.test(name)) {
      skipped += 1
      continue
    }
    const value = unquote(body.slice(eq + 1))
    byName.delete(name)
    byName.set(name, { name, value, secret: !isPublicKey(name, value) })
  }
  return { entries: [...byName.values()], skipped }
}

/** The plain-English note for lines that were not KEY=value ("" when none). */
export function skippedNote(skipped: number): string {
  if (!skipped) return ""
  return skipped === 1 ? "1 line was skipped: not KEY=value" : `${skipped} lines were skipped: not KEY=value`
}
