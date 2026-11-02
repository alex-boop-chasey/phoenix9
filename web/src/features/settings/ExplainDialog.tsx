// A dialog with the resolver's plain-English step list for a project.
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { useExplain } from "@/lib/queries"

/** Shows the effective step list as readable lines, indentation kept. */
export function ExplainDialog({
  name, open, onOpenChange,
}: { name: string; open: boolean; onOpenChange: (open: boolean) => void }) {
  const explain = useExplain(name, open)
  const lines = (explain.data?.text ?? "").split("\n").filter((l) => l.trim())
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>The effective step list</DialogTitle>
          <DialogDescription>What the next build would run, and the settings that differ from the defaults.</DialogDescription>
        </DialogHeader>
        {explain.isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
        {explain.error && <p className="text-sm text-destructive">{explain.error.message}</p>}
        <ul className="space-y-1 text-sm">
          {lines.map((line, i) => <li key={i} className="whitespace-pre-wrap break-words">{line}</li>)}
        </ul>
      </DialogContent>
    </Dialog>
  )
}
