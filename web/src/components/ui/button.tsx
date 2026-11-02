import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/lib/utils"
import { Slot } from "radix-ui"

const buttonVariants = cva("btn [&_svg]:pointer-events-none", {
  variants: {
    variant: {
      default: "btn-primary",
      primary: "btn-primary",
      secondary: "btn-secondary",
      outline: "btn-secondary",
      ghost: "btn-ghost",
      danger: "btn-danger",
      destructive: "btn-danger-fill",
      "danger-fill": "btn-danger-fill",
      link: "h-auto border-0 px-0 text-accent-text underline-offset-4 hover:underline",
    },
    size: {
      default: "",
      sm: "btn-sm",
      xs: "btn-sm",
      lg: "",
      icon: "btn-icon",
      "icon-sm": "btn-sm btn-icon",
      "icon-xs": "btn-sm btn-icon",
      "icon-lg": "btn-icon",
    },
  },
  defaultVariants: {
    variant: "default",
    size: "default",
  },
})

function Button({
  className,
  variant = "default",
  size = "default",
  asChild = false,
  ...props
}: React.ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean
  }) {
  const Comp = asChild ? Slot.Root : "button"

  return (
    <Comp
      data-slot="button"
      data-variant={variant}
      data-size={size}
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  )
}

export { Button, buttonVariants }
