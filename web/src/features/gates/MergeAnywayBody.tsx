/** The "are you sure?" text before merging a run that is not clean: the list of what went wrong. */
export function MergeAnywayBody({ warnings }: { warnings: string[] }) {
  return (
    <>
      <p>This run is not clean:</p>
      <ul className="list-disc pl-5" aria-label="What went wrong">
        {warnings.map((w) => <li key={w}>{w}</li>)}
      </ul>
      <p>Merging puts this work into main as it is.</p>
    </>
  )
}
