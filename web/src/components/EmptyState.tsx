import type { LucideIcon } from "lucide-react"
import type { ReactNode } from "react"

/** A centred "nothing here yet" message with an icon and an optional action. */
export function EmptyState({
  icon: Icon,
  title,
  line,
  action,
}: {
  icon: LucideIcon
  title: string
  line?: string
  action?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed p-8 text-center">
      <Icon className="size-8 text-muted-foreground" aria-hidden />
      <h2 className="text-base font-medium">{title}</h2>
      {line && <p className="text-sm text-muted-foreground">{line}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  )
}
