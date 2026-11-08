// Props shared by the reply block components.

export interface BlockProps {
  /** The block's JSON text, already checked by /api/blocks/check. */
  json: string
  /** What the check resolved (nav links, etc.). */
  resolved?: unknown
  /** True in items older than the latest conversation divider: no buttons. */
  frozen?: boolean
}
