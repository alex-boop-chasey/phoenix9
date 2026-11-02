import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/lib/utils"
import { Slot } from "radix-ui"

const badgeVariants = cva("badge [&>svg]:pointer-events-none", {
  variants: {
    variant: {
      default: "b-run",
      secondary: "b-info",
      ok: "b-ok",
      bad: "b-bad",
      destructive: "b-bad",
      running: "b-run",
      info: "b-info",
      need: "b-need",
      outline: "",
      ghost: "border-transparent",
      link: "text-accent-text underline-offset-4 [a&]:hover:underline",
    },
  },
  defaultVariants: {
    variant: "default",
  },
})

function Badge({
  className,
  variant = "default",
  asChild = false,
  ...props
}: React.ComponentProps<"span"> &
  VariantProps<typeof badgeVariants> & { asChild?: boolean }) {
  const Comp = asChild ? Slot.Root : "span"

  return (
    <Comp
      data-slot="badge"
      data-variant={variant}
      className={cn(badgeVariants({ variant }), className)}
      {...props}
    />
  )
}

export { Badge, badgeVariants }
