// The card for a list_projects result: one line per project, drawn from typed data.
export interface ProjectCardData { name: string; state?: string }

/** A small list of projects with their state in plain words. */
export function ProjectCards({ projects }: { projects: ProjectCardData[] }) {
  return (
    <section className="card" aria-label="Projects" data-testid="project-cards">
      <h3>Projects</h3>
      <ul>
        {projects.map((p) => (
          <li key={p.name}>{String(p.name)}{p.state ? ` — ${String(p.state)}` : ""}</li>
        ))}
      </ul>
    </section>
  )
}
