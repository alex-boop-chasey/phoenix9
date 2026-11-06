// The two Remove dialogs: "Remove … from Phoenix?" and the "can't be removed" notice for phoenix9.
import { Icon } from "@/components/Icon"
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog"

/** Confirm removing a project, or explain why phoenix9 cannot be removed. */
export function RemoveDialog({ name, onCancel, onConfirm }: { name: string | null; onCancel: () => void; onConfirm: (name: string) => void }) {
  const locked = name === "phoenix9"
  return (
    <AlertDialog open={name !== null} onOpenChange={(o) => { if (!o) onCancel() }}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <div className="dlg-h">
            <span className={locked ? "ico info" : "ico"}><Icon name={locked ? "lock" : "trash"} size="lg" /></span>
            <AlertDialogTitle>{locked ? "phoenix9 can't be removed" : `Remove ${name} from Phoenix?`}</AlertDialogTitle>
          </div>
          <AlertDialogDescription>
            {locked
              ? "Phoenix's own project can't be removed from Phoenix."
              : "Its folder, notes, code, repo and keys stay exactly where they are. It disappears from Phoenix's list. You can bring it back with Import."}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <div className="dlg-f">
          <AlertDialogCancel className="btn btn-secondary">{locked ? "Close" : "Cancel"}</AlertDialogCancel>
          {!locked && name && (
            <AlertDialogAction className="btn btn-danger-fill" onClick={() => onConfirm(name)}>
              <Icon name="trash" />Remove from Phoenix
            </AlertDialogAction>
          )}
        </div>
      </AlertDialogContent>
    </AlertDialog>
  )
}
