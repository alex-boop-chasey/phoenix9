/** The Settings tab: the Project section and the Build section, each with its own Save. */
import { BuildSection } from "@/features/settings/BuildSection"
import { ProjectSection } from "@/features/settings/ProjectSection"

export function SettingsTab({ name }: { name: string }) {
  return (
    <section data-project={name} className="space-y-6">
      <ProjectSection name={name} />
      <BuildSection name={name} />
    </section>
  )
}
