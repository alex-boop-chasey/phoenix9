// What the wizard loads from the server: settings, presets, library steps, specs, and plans for overrides.
import { keepPreviousData, useQuery } from "@tanstack/react-query"
import { useEffect, useState } from "react"

import { api } from "@/lib/api"
import { keys, useLibraryPresets, useLibrarySteps, useSettings, useSpecs } from "@/lib/queries"
import type { Overrides } from "@/lib/types"

export const PLAN_DEBOUNCE_MS = 300

/** The value, but only after it has stopped changing for `ms`. */
export function useDebounced<T>(value: T, ms: number): T {
  const [shown, setShown] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setShown(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return shown
}

/** POST /plan for these overrides (cached per overrides; the previous plan stays shown while loading). */
export function usePlanFor(name: string, overrides: Overrides | null) {
  return useQuery({
    queryKey: [...keys.plan(name), "wizard", JSON.stringify(overrides)],
    queryFn: () => api.plan(name, overrides ?? {}),
    enabled: !!name && overrides !== null,
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  })
}

/** Everything the wizard needs before it can show slide 1. */
export function useWizardData(name: string) {
  const settings = useSettings(name)
  const presets = useLibraryPresets()
  const steps = useLibrarySteps()
  const specs = useSpecs(name)
  const all = [settings, presets, steps, specs]
  const error = all.find((q) => q.error)?.error ?? null
  const ready = !!(settings.data && presets.data && steps.data && specs.data)
  return {
    error, ready,
    retry: () => all.forEach((q) => void q.refetch()),
    settings: settings.data, presets: presets.data?.presets ?? [], steps: steps.data?.steps ?? [], specs: specs.data ?? [],
  }
}
