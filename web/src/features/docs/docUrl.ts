import { apiBase } from "@/lib/api"

/** The page address (hash form) that shows one document. */
export function docViewHref(id: string): string {
  return `#/doc?path=${encodeURIComponent(id)}`
}

/** The server address that downloads one document. */
export function docDownloadUrl(id: string): string {
  const url = new URL("docs/download", apiBase())
  url.searchParams.set("id", id)
  return url.toString()
}
