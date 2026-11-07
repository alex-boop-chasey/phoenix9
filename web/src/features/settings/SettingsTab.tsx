/** The Settings tab: a section index on the left, the Project section, then the Build section. */
import { useState } from "react"

import { Icon } from "@/components/Icon"
import { BuildSection } from "@/features/settings/BuildSection"
import { DangerZone } from "@/features/settings/DangerZone"
import { ProjectSection } from "@/features/settings/ProjectSection"

const SECTIONS: { id: string; label: string; icon: "sliders-horizontal" | "hammer"; links: [string, string][] }[] = [
  { id: "sec-project", label: "Project", icon: "sliders-horizontal", links: [["s-repo", "Repo and kind"], ["s-svc", "Services"], ["s-keys", "Project keys"]] },
  { id: "sec-build", label: "Build", icon: "hammer", links: [["s-preset", "Preset"], ["s-fail", "Failures"], ["s-merge", "Merge and deploy"]] },
]

/** Scroll to a part of the page and flash a blue outline around it. */
function jump(id: string) {
  const el = document.getElementById(id)
  if (!el) return
  const calm = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches
  el.scrollIntoView?.({ behavior: calm ? "auto" : "smooth", block: "center" })
  el.animate?.([{ boxShadow: "0 0 0 2px var(--accent)" }, { boxShadow: "0 0 0 0 transparent" }], { duration: 1500 })
}

export function SettingsTab({ name }: { name: string }) {
  const [current, setCurrent] = useState("sec-project")
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
