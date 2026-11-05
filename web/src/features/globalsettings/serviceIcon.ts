// The icon for each service row.
import type { IconName } from "@/components/Icon"

const ICONS: Record<string, IconName> = {
  claude: "sparkle", cloudflare: "cloud", github: "github-logo", supabase: "hard-drives", resend: "plugs-connected",
  sentry: "warning-octagon", stripe: "coins", telegram: "telegram-logo",
}

/** The icon for a service (a plug for any the dashboard does not know). */
export function serviceIcon(name: string): IconName {
  return ICONS[name] ?? "plugs"
}

