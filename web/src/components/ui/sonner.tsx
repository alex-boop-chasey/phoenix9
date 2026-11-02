"use client"

import { Icon } from "@/components/Icon"
import { Wheel } from "@/components/Indicator"
import { useTheme } from "@/lib/theme"
import { Toaster as Sonner, type ToasterProps } from "sonner"

/** Toasts in the mockup look: coloured left edge, an icon, and always a close button. */
const Toaster = ({ ...props }: ToasterProps) => {
  const { theme } = useTheme()

  return (
    <Sonner
      theme={theme as ToasterProps["theme"]}
      className="toaster group"
      closeButton
      icons={{
        success: <Icon name="check-circle" />,
        info: <Icon name="info" />,
        warning: <Icon name="warning" />,
        error: <Icon name="warning-octagon" />,
        loading: <Wheel />,
      }}
      toastOptions={{
        classNames: {
          toast: "phx-toast",
          closeButton: "phx-toast-x",
        },
      }}
      style={
        {
          "--normal-bg": "var(--surface)",
          "--normal-text": "var(--text)",
          "--normal-border": "var(--line-strong)",
          "--success-bg": "var(--surface)",
          "--success-text": "var(--text)",
          "--success-border": "var(--line-strong)",
          "--error-bg": "var(--surface)",
          "--error-text": "var(--text)",
          "--error-border": "var(--line-strong)",
          "--info-bg": "var(--surface)",
          "--info-text": "var(--text)",
          "--info-border": "var(--line-strong)",
          "--warning-bg": "var(--surface)",
          "--warning-text": "var(--text)",
          "--warning-border": "var(--line-strong)",
          "--border-radius": "var(--r-md)",
        } as React.CSSProperties
      }
      {...props}
    />
  )
}

export { Toaster }
