// A dialog that browses folders under the projects folder and hands back the one picked.
import { useState } from "react"

import { ErrorState } from "@/components/ErrorState"
import { Icon } from "@/components/Icon"
import { Skeleton } from "@/components/ui/skeleton"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from "@/components/ui/dialog"
import { useFolders } from "@/lib/queries"

function Browser({ start, onPick, onClose }: { start: string; onPick: (path: string) => void; onClose: () => void }) {
  const [path, setPath] = useState(start)
  const list = useFolders(path)
  // A typed path that is not browsable falls back to the projects folder.
  const lost = list.isError && path !== ""
  const body = () => {
    if (list.isPending) return <Skeleton className="h-24 w-full" aria-label="Loading" />
    if (list.isError) return lost ? (
      <p className="small">That folder can't be opened. <button type="button" className="btn btn-secondary btn-sm" onClick={() => setPath("")}>Back to the projects folder</button></p>
    ) : <ErrorState error={list.error} onRetry={() => void list.refetch()} />
    return (
      <div className="stackg" data-testid="folder-list">
        {list.data.parent && (
          <button type="button" className="btn btn-secondary btn-sm" onClick={() => setPath(list.data.parent ?? "")}>
            <Icon name="arrow-left" />Up one folder
          </button>
        )}
        {list.data.folders.length === 0 ? <p className="small">No folders in here.</p> : list.data.folders.map((f) => (
          <button key={f.path} type="button" className="btn btn-secondary" style={{ justifyContent: "flex-start", minHeight: 44 }} onClick={() => setPath(f.path)}>
            <Icon name="folder-simple" /><span className="mono">{f.name}</span>
          </button>
        ))}
      </div>
    )
  }
  return (
    <>
      <DialogTitle>Choose a folder</DialogTitle>
      <DialogDescription>Only folders inside the projects folder can be picked.</DialogDescription>
      <p className="small mono" data-testid="folder-here">{list.data?.path ?? path}</p>
      {body()}
      <DialogFooter>
        <button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button>
        <button type="button" className="btn btn-primary" disabled={!list.data || list.data.path === list.data.root}
          onClick={() => list.data && onPick(list.data.path)}>Use this folder</button>
      </DialogFooter>
    </>
  )
}

/** The Choose a folder dialog; mounted fresh each time it opens so it starts where the path box points. */
export function FolderPicker({ open, start, onClose, onPick }: {
  open: boolean; start: string; onClose: () => void; onPick: (path: string) => void
}) {
  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent>{open && <Browser start={start} onPick={onPick} onClose={onClose} />}</DialogContent>
    </Dialog>
  )
}
