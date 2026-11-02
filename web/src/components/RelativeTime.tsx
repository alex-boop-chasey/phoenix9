import { relativeTime } from "@/lib/format"

/** A time in words ("5 minutes ago"); the full time shows on hover. */
export function RelativeTime({ iso }: { iso: string | null | undefined }) {
  if (!iso) return <span className="text-muted-foreground">-</span>
  return (
    <time dateTime={iso} title={iso}>
      {relativeTime(iso) || iso}
    </time>
  )
}
