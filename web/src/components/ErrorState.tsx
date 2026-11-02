import { AlertTriangle } from "lucide-react"

import { Button } from "@/components/ui/button"

/** A plain error message with a "Try again" button (never a stack or JSON). */
export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message = error instanceof Error && error.message ? error.message : "Something went wrong."
  return (
    <div role="alert" className="flex flex-col items-center gap-2 rounded-lg border border-destructive/40 p-8 text-center">
      <AlertTriangle className="size-8 text-destructive" aria-hidden />
      <p className="text-sm">{message}</p>
      {onRetry && (
        <Button variant="outline" size="sm" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  )
}
