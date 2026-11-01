// New project: the form, the project keys, and the live progress while it is created.
import { useCallback, useEffect, useRef, useState } from "react"
import { Link, useNavigate } from "react-router"
import { toast } from "sonner"

import { PageHeader } from "@/components/PageHeader"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { CreateProgress } from "@/features/projects/CreateProgress"
import { ProjectForm } from "@/features/projects/ProjectForm"
import { emptyForm, sourceComplete, toCreateForm, type FormValues } from "@/features/projects/formModel"
import { KeysForm } from "@/features/keys/KeysForm"
import { useCreateProject, useGithubRepos, useJob } from "@/lib/queries"
import type { KeyInput } from "@/lib/types"

/** The New project page. */
export default function NewProjectPage() {
  const navigate = useNavigate()
  const [values, setValues] = useState<FormValues>(emptyForm)
  const [nameOk, setNameOk] = useState(false)
  const [keyRows, setKeyRows] = useState<KeyInput[]>([])
  const [pending, setPending] = useState(false)
  const [jobId, setJobId] = useState("")
  const [error, setError] = useState("")
  const create = useCreateProject()
  const github = useGithubRepos()
  const job = useJob(jobId)
  const handled = useRef("")

  const onRows = useCallback((rows: KeyInput[], p: boolean) => { setKeyRows(rows); setPending(p) }, [])

  const j = job.data
  useEffect(() => {
    if (!j || handled.current === j.id + j.status) return
    if (j.status === "done") {
      handled.current = j.id + j.status
      toast.success(`Project ${j.project || values.name} created`)
      void navigate(`/p/${j.project || values.name}/overview`)
    }
  }, [j, navigate, values.name])

  const ready = nameOk && sourceComplete(values) && !pending && !create.isPending

  function submit() {
    setError("")
    create.mutate(toCreateForm(values, keyRows, !!github.data?.connected), {
      onSuccess: (r) => setJobId(r.job.id),
      onError: (e) => setError(e.message),
    })
  }

  const failed = j?.status === "failed"
  const showProgress = !!jobId && !!j

  return (
    <main className="mx-auto max-w-2xl space-y-4">
      <Link to="/" className="text-sm text-muted-foreground hover:underline">← Projects</Link>
      <PageHeader title="New project" />
      {showProgress ? (
        <section className="space-y-4">
          <CreateProgress steps={j.steps} />
          {failed && (
            <>
              <Alert variant="destructive">
                <AlertDescription>
                  <p>{j.message || "Creating the project failed."}</p>
                  <p>Nothing was left half-made.</p>
                </AlertDescription>
              </Alert>
              <Button type="button" className="w-full sm:w-auto" onClick={() => { setJobId(""); handled.current = "" }}>
                Back to the form
              </Button>
            </>
          )}
        </section>
      ) : (
        <form className="space-y-6" onSubmit={(e) => { e.preventDefault(); if (ready) submit() }}>
          {error && <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>}
          <ProjectForm mode="create" value={values} onChange={setValues} onNameOk={setNameOk} />
          <section className="space-y-3">
            <h2 className="text-lg font-semibold">Project keys</h2>
            <KeysForm mode="local" onRowsChange={onRows} />
            {pending && <p className="text-xs text-muted-foreground">Save the key rows before creating.</p>}
          </section>
          <Button type="submit" disabled={!ready} className="w-full sm:w-auto">Create</Button>
        </form>
      )}
    </main>
  )
}
