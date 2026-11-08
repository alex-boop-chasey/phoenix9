// The one check for links the panel opens from agent-driven content: web addresses only.

/** The url when it is an absolute http or https address, else null (no javascript:, data: or relative links). */
export function safeUrl(url: string | undefined | null): string | null {
  return typeof url === "string" && /^https?:\/\//i.test(url) ? url : null
}
