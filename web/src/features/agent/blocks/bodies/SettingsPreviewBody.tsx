// Body of the settings-preview card: before and after for each proposed setting.
import type { CardBodyProps } from "../cardBodies"
import { InlineFooter } from "./Footer"

interface Row { key: string; before: unknown; after: unknown; ok: boolean; reason?: string | null }

function show(value: unknown): string {
  if (value === null || value === undefined) return "(not set)"
  return typeof value === "string" ? value : JSON.stringify(value)
}

/** Before/after rows of a settings change, with the reason under rows that are not ok. */
export function SettingsPreviewBody({ data }: CardBodyProps) {
  const d = (data ?? {}) as { rows?: Row[]; footer?: string }
  const rows = Array.isArray(d.rows) ? d.rows : []
  return (
    <div data-testid="card-settings-preview">
      <ul className="flex flex-col gap-2">
        {rows.map((r) => (
          <li key={r.key} data-ok={r.ok ? "true" : "false"}>
            <div className="mono break-all font-medium">{r.key}</div>
            <div className="flex flex-wrap items-center gap-x-2 text-sm">
              <span className="muted line-through" data-testid="before">{show(r.before)}</span>
              <span aria-hidden="true">→</span>
              <span className="rounded bg-accent px-1 font-semibold" data-testid="after">{show(r.after)}</span>
            </div>
            {!r.ok && <p className="text-destructive text-sm" data-testid="reason">{r.reason || "Not allowed."}</p>}
          </li>
        ))}
      </ul>
      <InlineFooter text={d.footer} />
    </div>
  )
}
