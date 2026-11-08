import type { ReactElement } from "react"

import { BuildsBody } from "./bodies/BuildsBody"
import { ChartBody } from "./bodies/ChartBody"
import { DiffBody } from "./bodies/DiffBody"
import { GatesBody } from "./bodies/GatesBody"
import { LogBody } from "./bodies/LogBody"
import { ProjectsBody } from "./bodies/ProjectsBody"
import { PrsBody } from "./bodies/PrsBody"
import { RunBody } from "./bodies/RunBody"
import { SettingsPreviewBody } from "./bodies/SettingsPreviewBody"
import { TableBody } from "./bodies/TableBody"
import { UpdateBody } from "./bodies/UpdateBody"

// The body components of cards by type; tasks 15-17 add real ones, until then a plain JSON view is shown.

export interface CardBodyProps { type: string; data: unknown; /** True for a card in an older conversation: show it read-only. */ frozen?: boolean }

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
  prs: PrsBody,
  log: LogBody,
  diff: DiffBody,
  update: UpdateBody,
  "settings-preview": SettingsPreviewBody,
  table: TableBody,
  chart: ChartBody,
}
