import { ICONS, type IconName } from "@/components/iconSprite"
import { cn } from "@/lib/utils"

export type { IconName }

const SIZES = { xs: "xs", sm: "sm", md: "", lg: "lg" } as const

/** A Phosphor Duotone icon by name, drawn from the artwork bundled in this app (no network). */
export function Icon({ name, size = "md", className, title }: {
  name: IconName
  size?: keyof typeof SIZES
  className?: string
  title?: string
}) {
  const art = ICONS[name]
  return (
    <svg
      className={cn("i", SIZES[size], className)}
      viewBox="0 0 256 256"
      data-icon={name}
      role={title ? "img" : undefined}
      aria-label={title}
      aria-hidden={title ? undefined : true}
      dangerouslySetInnerHTML={{ __html: art }}
    />
  )
}
