import { docDownloadUrl, docViewHref } from "./docUrl"

/** View (new tab) and Download buttons for one document id. */
export function DocButtons({ id, label }: { id: string; label?: string }) {
  const what = label ?? id
  return (
    <span className="inline-flex flex-wrap gap-2" data-testid="doc-buttons">
      <a className="btn btn-outline" href={docViewHref(id)} target="_blank" rel="noopener" aria-label={`View ${what}`}>
        View
      </a>
      <a className="btn btn-outline" href={docDownloadUrl(id)} download aria-label={`Download ${what}`}>
        Download
      </a>
    </span>
  )
}
