// The Project half of the Settings tab: description, repo, profile, services and the project keys.
import { useEffect, useState } from "react"
import { toast } from "sonner"

import { ConfirmDialog } from "@/components/ConfirmDialog"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { KeysForm } from "@/features/keys/KeysForm"
import { ProjectForm } from "@/features/projects/ProjectForm"
import { emptyForm, type FormValues } from "@/features/projects/formModel"
import { sameValue } from "@/features/settings/dotted"
import { useEditProject, useProject } from "@/lib/queries"
import type { EditBody, Project } from "@/lib/types"

const fromProject = (p: Project): FormValues => ({
  ...emptyForm, name: p.name, description: p.description, repo: p.repo, profile: p.profile, services: p.services,
})

/** The edit body with only the fields that differ from the saved project. */
export function changedFields(p: Project, v: FormValues): EditBody {
  const body: EditBody = {}
  if (v.description !== p.description) body.description = v.description
  if (v.repo.trim() !== p.repo) body.repo = v.repo.trim()
  if (v.profile !== p.profile) body.profile = v.profile
  if (!sameValue([...v.services].sort(), [...p.services].sort())) body.services = v.services
  return body
}

/** Project fields with their own Save, then the project keys. */
export function ProjectSection({ name }: { name: string }) {
  const project = useProject(name)
  const edit = useEditProject(name)
  const [value, setValue] = useState<FormValues | null>(null)
  const [asking, setAsking] = useState(false)
  const [error, setError] = useState("")

  useEffect(() => {
    if (project.data && !value) setValue(fromProject(project.data))
  }, [project.data, value])

  if (!project.data || !value) return null
  const body = changedFields(project.data, value)
  const dirty = Object.keys(body).length > 0
  const risky = body.repo !== undefined || body.profile !== undefined

  function save(confirm: boolean) {
    setError("")
    edit.mutate(confirm ? { ...body, confirm: true } : body, {
      onSuccess: (fresh) => { setValue(fromProject(fresh)); toast.success("Saved") },
      onError: (err) => setError(err.message),
    })
  }

  return (
    <Card>
      <CardHeader><CardTitle>Project</CardTitle></CardHeader>
      <CardContent className="space-y-6">
        <ProjectForm mode="edit" value={value} onChange={setValue} />
        {error && <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>}
        <div className="flex items-center gap-3">
          <Button disabled={!dirty || edit.isPending} onClick={() => (risky ? setAsking(true) : save(false))}>
            Save project
          </Button>
          {dirty && <span className="text-sm text-muted-foreground">Unsaved changes</span>}
        </div>
        <ConfirmDialog
          open={asking} onOpenChange={setAsking} title="Change the repo/profile?"
          body="Change the repo/profile? The next build uses the new one."
          confirmLabel="Change it" onConfirm={() => save(true)}
        />
        <div className="space-y-2 border-t pt-4">
          <h3 className="font-semibold">Project keys</h3>
          <KeysForm mode="saved" project={name} />
          <p className="text-sm text-muted-foreground">Changes are picked up by the next build and the next chat restart.</p>
        </div>
      </CardContent>
    </Card>
  )
}
