// The search box and the Owner dropdown above the projects list.
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"

import { ALL_OWNERS, NO_REPO } from "./rows"

/** Search input plus Owner select; the parent keeps the values in the URL. */
export function ProjectsFilters({
  q, owner, owners, onQ, onOwner,
}: {
  q: string
  owner: string
  owners: string[]
  onQ: (q: string) => void
  onOwner: (owner: string) => void
}) {
  return (
    <div className="flex flex-col gap-2 sm:flex-row">
      <Input
        type="search"
        placeholder="Search projects"
        aria-label="Search projects"
        value={q}
        onChange={(e) => onQ(e.target.value)}
        className="sm:max-w-xs"
      />
      <Select value={owner} onValueChange={onOwner}>
        <SelectTrigger aria-label="Owner" className="w-full sm:w-56">
          <SelectValue placeholder="Owner" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ALL_OWNERS}>All owners</SelectItem>
          {owners.map((o) => (
            <SelectItem key={o} value={o}>
              {o}
            </SelectItem>
          ))}
          <SelectItem value={NO_REPO}>No repo</SelectItem>
        </SelectContent>
      </Select>
    </div>
  )
}
