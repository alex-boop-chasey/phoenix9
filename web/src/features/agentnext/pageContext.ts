// What page Alex is on, as the small context the agent is told with each message, and the chip's plain words.

const SAFE = /^[A-Za-z0-9/_.-]{1,80}$/

/** The page, project and run Alex has open (each only when known and safe to send). */
export interface PageParts { page?: string; project?: string; run?: string }

/** Where Alex is: the context keys plus a plain label for the chip. */
export interface PageContext {
  context: PageParts
  folder: string
  selected?: string
}

const TOP_PAGES: Record<string, string> = { "/": "projects", "/new": "new", "/import": "import", "/styles": "styles", "/settings": "settings" }

/** Work out the page, project and run from a router location. */
export function readPageContext(pathname: string, search: string): PageContext {
  const context: PageParts = {}
  const m = /^\/p\/([^/]+)(?:\/([^/]+))?\/?$/.exec(pathname)
  if (m) {
    const name = decodeURIComponent(m[1] ?? "")
    context.project = name
    context.page = m[2] ? `project/${m[2]}` : "project"
  } else {
    const top = TOP_PAGES[pathname.replace(/(.)\/$/, "$1")] as string | undefined
    if (top) context.page = top
  }
  if (context.page && !SAFE.test(context.page)) delete context.page
  const run = new URLSearchParams(search).get("run")
  if (run && SAFE.test(run)) context.run = run
  return { context, folder: context.project ?? "Phoenix", selected: context.run }
}

const PAGE_WORDS: Record<string, string> = {
  projects: "the project list", new: "a new project", import: "importing a project", styles: "the style reference", settings: "Phoenix settings",
}

/** The chip's line, e.g. "Looking at: demo-site, build 20261110-0900". */
export function lookingAt(parts: PageParts): string {
  const bits: string[] = []
  if (parts.project && SAFE.test(parts.project)) bits.push(parts.project)
  else if (parts.page && PAGE_WORDS[parts.page]) bits.push(PAGE_WORDS[parts.page]!)
  if (parts.run) bits.push(`build ${parts.run}`)
  return `Looking at: ${bits.length ? bits.join(", ") : "Phoenix"}`
}

/** The context to send with a message: only the safe parts, or nothing when none are known. */
export function contextToSend(parts: PageParts): PageParts | undefined {
  const out: PageParts = {}
  for (const key of ["page", "project", "run"] as const) {
    const v = parts[key]
    if (v && SAFE.test(v)) out[key] = v
  }
  return Object.keys(out).length ? out : undefined
}
