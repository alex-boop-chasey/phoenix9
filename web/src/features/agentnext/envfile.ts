// Reads a .env file's text into rows; secret unless the name is clearly public (backlog O45).

/** One name and value from a .env file, and whether it is kept secret. */
export interface EnvRow { name: string; value: string; secret: boolean }

const NAME = /^[A-Za-z_][A-Za-z0-9_]*$/

/** True when the name is clearly public: a public prefix, an _URL or _ID ending, or a port or flag name. */
export function isPublicName(name: string): boolean {
  const n = name.toUpperCase()
  if (n.startsWith("PUBLIC_") || n.startsWith("NEXT_PUBLIC_")) return true
  if (n.endsWith("_URL") || n.endsWith("_ID")) return true
  if (n === "PORT" || n.endsWith("_PORT")) return true
  return n.endsWith("_ENABLED") || n.endsWith("_DISABLED") || n.endsWith("_FLAG") || n.startsWith("ENABLE_") || n.startsWith("DISABLE_")
}

/** Take matching single or double quotes off a value. */
function unquote(v: string): string {
  if (v.length >= 2 && (v[0] === '"' || v[0] === "'") && v[v.length - 1] === v[0]) return v.slice(1, -1)
  return v
}

/** Parse .env text: skip blanks and comments, optional `export`, split at the first =, last repeat of a name wins. */
export function parseEnv(text: string): EnvRow[] {
  const rows = new Map<string, EnvRow>()
  for (const raw of text.split(/\r?\n/)) {
    let line = raw.trim()
    if (!line || line.startsWith("#")) continue
    if (/^export\s+/.test(line)) line = line.replace(/^export\s+/, "")
    const eq = line.indexOf("=")
    if (eq < 0) continue
    const name = line.slice(0, eq).trim()
    if (!NAME.test(name)) continue
    rows.set(name, { name, value: unquote(line.slice(eq + 1).trim()), secret: !isPublicName(name) })
  }
  return [...rows.values()]
}
