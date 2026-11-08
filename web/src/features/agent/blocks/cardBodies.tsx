import type { ReactElement } from "react"

import { BuildsBody } from "./bodies/BuildsBody"
import { GatesBody } from "./bodies/GatesBody"
import { ProjectsBody } from "./bodies/ProjectsBody"
import { RunBody } from "./bodies/RunBody"

// The body components of cards by type; tasks 15-17 add real ones, until then a plain JSON view is shown.

export interface CardBodyProps { type: string; data: unknown }

/** A plain JSON view of a card's data. */
export function JsonBody({ data }: CardBodyProps) {
  return <pre className="ag-code mono" data-testid="card-json"><code>{JSON.stringify(data, null, 2)}</code></pre>
}

/** Body components by card type; a type not listed uses JsonBody. */
export const CARD_BODIES: Record<string, (props: CardBodyProps) => ReactElement> = {
  projects: ProjectsBody,
  gates: GatesBody,
  run: RunBody,
  builds: BuildsBody,
}
