// The report card: the daily report as plain text with its date.

/** The daily report as the Phoenix pack sends it. */
export interface Report { date: string; text: string }

function isObject(v: unknown): v is Record<string, unknown> { return !!v && typeof v === "object" && !Array.isArray(v) }
function isText(v: unknown): v is string { return typeof v === "string" }

/** The text, whether it came plain or wrapped as quoted data. */
function textOf(v: unknown): string | null {
  if (isText(v)) return v
  return isObject(v) && isText(v.data) ? v.data : null
}

/** The report when it has text (and a date that is text), else null. */
export function reportFrom(data: unknown): Report | null {
  if (!isObject(data)) return null
  const text = textOf(data.text)
  if (text === null || (data.date !== undefined && !isText(data.date))) return null
  return { date: isText(data.date) ? data.date : "", text }
}

/** The report text, kept as plain text with its line breaks. */
export function ReportCard({ report }: { report: Report }) {
  return (
    <section className="card flex flex-col gap-1" aria-label="Daily report" data-testid="report-card">
      {report.date ? <strong>{report.date}</strong> : null}
      <p className="whitespace-pre-wrap text-sm">{report.text}</p>
    </section>
  )
}
