import type { ReactNode } from "react"

import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Wheel } from "@/components/Indicator"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { buttonVariants } from "@/components/ui/button"
import { cn } from "@/lib/utils"

/** A "are you sure?" dialog with a title, a body and a confirm button.
 * With `stayOpen` the confirm button leaves the dialog open (the caller closes it on success), shows a wheel
 * while `pending` and the server's refusal in `error`. */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  body,
  confirmLabel,
  destructive = false,
  onConfirm,
  stayOpen = false,
  pending = false,
  error = null,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  body: ReactNode
  confirmLabel: string
  destructive?: boolean
  onConfirm: () => void
  stayOpen?: boolean
  pending?: boolean
  error?: string | null
}) {
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription asChild>
            <div>{body}</div>
          </AlertDialogDescription>
        </AlertDialogHeader>
        {error && <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>}
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction
            className={cn(destructive && buttonVariants({ variant: "destructive" }))}
            disabled={pending}
            onClick={(ev) => {
              if (stayOpen) ev.preventDefault()
              if (!pending) onConfirm()
            }}
          >
            {pending && <Wheel />}
            {confirmLabel}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
