// The Deploy card on a project's Overview: deployer, live address, last deploy and a Deploy now button.
import { useQueryClient } from "@tanstack/react-query"
import { useEffect, useState } from "react"
import { toast } from "sonner"

import { ConfirmDialog } from "@/components/ConfirmDialog"
import { Icon } from "@/components/Icon"
import { post } from "@/lib/api"
import { useDeploys, useJob } from "@/lib/queries"
import type { DeployRecord } from "@/lib/types"

/** One plain line about the last deploy. */
function lastLine(r: DeployRecord): string {
  const commit = r.commit ? r.commit.slice(0, 7) : "latest"
  const result = r.ok ? "ok" : r.rolled_back ? `rolled back: ${r.reason}` : `failed: ${r.reason}`
  return `${r.at} · ${commit} · ${result}`
}

/** The result line of a finished deploy job. */
function resultLine(status: string, message: string, url?: string): string {
  if (status === "done") return url ? `Deployed to ${url}.` : "Deployed."
  return message || "The deploy failed."
}

/** Deploy card for a project whose deployer is not "none". */
export function DeployCard({ name }: { name: string }) {
  const { data } = useDeploys(name)
  const qc = useQueryClient()
  const [confirm, setConfirm] = useState(false)
  const [jobId, setJobId] = useState("")
  const [starting, setStarting] = useState(false)
  const job = useJob(jobId).data
  const running = starting || (!!jobId && (!job || job.status === "running"))

  const finished = !!jobId && !!job && job.status !== "running"
  useEffect(() => {
    if (finished) void qc.invalidateQueries({ queryKey: ["deploys", name] })
  }, [finished, name, qc])

  if (!data || data.deployer.name === "none") return null
  const { deployer, recent } = data
  const last = recent[0]

  async function start() {
    setStarting(true)
    try {
      const out = await post<{ job: string }>(`projects/${encodeURIComponent(name)}/deploy`, { yes: true })
      setJobId(out.job)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "The deploy did not start.")
    } finally {
      setStarting(false)
    }
  }

  return (
    <section className="card stackg" aria-label="Deploy">
      <h2 className="h3"><Icon name="rocket-launch" /> Deploy</h2>
      <div className="stackg" style={{ gap: 8, fontSize: 14 }}>
        <p>Deployer: {deployer.title}</p>
        {!deployer.supported ? (
          <p className="text-muted-foreground">{deployer.title} is not yet supported.</p>
        ) : (
          <>
            <p>
              Live address:{" "}
              {data.live_url ? (
                <a href={data.live_url} target="_blank" rel="noreferrer">
                  {data.live_url}
                </a>
              ) : (
                <span className="text-muted-foreground">not deployed yet</span>
              )}
            </p>
            <p>Last deploy: {last ? lastLine(last) : <span className="text-muted-foreground">none yet</span>}</p>
            <div>
              <button type="button" className="btn btn-primary" disabled={running} onClick={() => setConfirm(true)}>Deploy now</button>
            </div>
            {running && <p role="status">Deploying…</p>}
            {job && job.status !== "running" && (
              <p role="status" className={job.status === "failed" ? "text-destructive" : undefined}>
                {resultLine(job.status, job.message, job.result?.url)}
              </p>
            )}
          </>
        )}
        <ConfirmDialog
          open={confirm}
          onOpenChange={setConfirm}
          title="Deploy now?"
          body={`This puts the main code of ${name} live with ${deployer.title}. If the health check fails it is rolled back.`}
          confirmLabel="Deploy now"
          onConfirm={() => {
            setConfirm(false)
            void start()
          }}
        />
      </div>
    </section>
  )
}
