/** The Settings tab: a section index on the left, the Project section, then the Build section. */
import { useEffect, useState } from "react"
import { useSearchParams } from "react-router"

import { Icon } from "@/components/Icon"
import { BuildSection } from "@/features/settings/BuildSection"
import { scrollToAndHighlight } from "@/lib/focus"
import { DangerZone } from "@/features/settings/DangerZone"
import { ProjectSection } from "@/features/settings/ProjectSection"

const SECTIONS: { id: string; label: string; icon: "sliders-horizontal" | "hammer"; links: [string, string][] }[] = [
  { id: "sec-project", label: "Project", icon: "sliders-horizontal", links: [["s-repo", "Repo and kind"], ["s-svc", "Services"], ["s-keys", "Project keys"]] },
  { id: "sec-build", label: "Build", icon: "hammer", links: [["s-preset", "Preset"], ["s-fail", "Failures"], ["s-merge", "Merge and deploy"]] },
]

/** Scroll to a part of the page and flash an outline around it. */
function jump(id: string) {
  scrollToAndHighlight(document.getElementById(id))
}

/** The settings row that holds a dotted key such as "deploy.mode" (a row listing "deploy" holds all of its sub-keys). */
export function rowForKey(key: string): HTMLElement | null {
  for (const row of document.querySelectorAll<HTMLElement>("[data-settings]")) {
    const held = row.dataset.settings!.split(" ")
    if (held.some((k) => key === k || key.startsWith(`${k}.`))) return row
  }
  return null
}

const SECTION_ID: Record<string, string> = { project: "sec-project", build: "sec-build" }
const WAIT_MS = 100
const WAIT_TRIES = 50

/** Open the section and scroll to the setting named in the address; waits while the settings are still loading. */
function useAddressTarget(onOpen: (sectionId: string) => void) {
  const [params] = useSearchParams()
  const section = SECTION_ID[params.get("section") ?? ""] ?? null
  const key = params.get("key")
  useEffect(() => {
    if (!section && !key) return
    let tries = 0
    let stop = () => {}
    const timer = setInterval(() => {
      const el = key ? rowForKey(key) : document.getElementById(section!)
      if (!el && ++tries < WAIT_TRIES) return
      clearInterval(timer)
      if (!el) return
      const sect = el.id.startsWith("sec-") ? el.id : el.closest<HTMLElement>(".sect")?.id
      if (sect) onOpen(sect)
      stop = scrollToAndHighlight(el)
    }, WAIT_MS)
    return () => { clearInterval(timer); stop() }
  }, [section, key]) // eslint-disable-line react-hooks/exhaustive-deps
}

export function SettingsTab({ name }: { name: string }) {
  const [current, setCurrent] = useState("sec-project")
  useAddressTarget(setCurrent)
  const go = (id: string, section: string) => { setCurrent(section); jump(id) }
  return (
    <section data-project={name} className="idx-wrap" aria-label="Project settings">
      <nav className="sidx" aria-label="Settings sections">
        {SECTIONS.map((s) => (
          <div key={s.id} style={{ display: "contents" }}>
            <button type="button" aria-current={current === s.id} onClick={() => go(s.id, s.id)}>
              <Icon name={s.icon} />{s.label}
            </button>
            {s.links.map(([id, label]) => (
              <a key={id} href={`#${id}`} onClick={(e) => { e.preventDefault(); go(id, s.id) }}>{label}</a>
            ))}
          </div>
        ))}
      </nav>
      <div className="stackg" style={{ gap: 32 }}>
        <ProjectSection name={name} />
        <BuildSection name={name} />
        <DangerZone name={name} />
      </div>
    </section>
  )
}
