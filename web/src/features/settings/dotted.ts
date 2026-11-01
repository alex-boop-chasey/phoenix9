// Small helpers for dotted settings keys ("steps.builder.model") and comma lists.

/** Read a nested value by dotted path, or undefined. */
export function getPath(obj: unknown, path: string): unknown {
  let node: unknown = obj
  for (const part of path.split(".")) {
    if (node === null || typeof node !== "object") return undefined
    node = (node as Record<string, unknown>)[part]
  }
  return node
}

/** Split "a, b" into ["a","b"], dropping blanks. */
export const parseList = (text: string): string[] => text.split(",").map((x) => x.trim()).filter(Boolean)

/** Join a list for a text box. */
export const listText = (v: unknown): string => (Array.isArray(v) ? v.join(", ") : "")

/** Whether two settings values are the same (lists and scalars). */
export const sameValue = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)
