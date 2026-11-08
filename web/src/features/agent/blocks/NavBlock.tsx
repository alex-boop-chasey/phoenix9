// The nav reply block: a row of buttons that move the dashboard while the panel stays open.
import { Button } from "@/components/ui/button"
import type { BlockProps } from "@/features/agent/blocks/types"
import { navigateKeepingPanel } from "@/features/agent/navigate"

interface NavLink { hash: string; label: string }

function linksOf(resolved: unknown): NavLink[] {
  const list = (resolved as { links?: unknown } | null | undefined)?.links
  if (!Array.isArray(list)) return []
  return list.filter((l): l is NavLink => !!l && typeof l.hash === "string" && l.hash.startsWith("#/") && typeof l.label === "string")
}

/** Shows the resolved links of a checked nav block as buttons; dropped links are left out. */
export function NavBlock({ resolved, frozen = false }: BlockProps) {
  const links = linksOf(resolved)
  if (!links.length) return null
  return (
    <div className="ag-block ag-block-nav ag-nav" data-testid="block-nav" data-frozen={frozen ? "true" : undefined} role="group" aria-label="Links">
      {links.map((l, i) => (
        <Button key={i} type="button" variant="outline" size="sm" disabled={frozen} onClick={() => navigateKeepingPanel(l.hash)}>{l.label}</Button>
      ))}
    </div>
  )
}
