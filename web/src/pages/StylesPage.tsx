import { useMemo } from "react"
import { toast } from "sonner"

import { Icon, type IconName } from "@/components/Icon"
import { ICONS } from "@/components/iconSprite"
import { Indicator, Wheel } from "@/components/Indicator"
import { useTheme } from "@/lib/theme"

const TOKENS: [string, string][] = [
  ["--bg-page", "Page"], ["--bg-dash", "Dashboard well"], ["--surface", "Cards"], ["--surface-2", "Raised"],
  ["--line", "Lines"], ["--text", "Text"], ["--text-2", "Text, quiet"], ["--accent", "Electric blue"],
  ["--attn", "Needs you (orange)"], ["--ok", "Passed"], ["--bad", "Failed"], ["--info", "Pending, idle"],
]

const ICON_NAMES = Object.keys(ICONS) as IconName[]

/** Read each token's live value in both themes (the other theme is switched on for an instant, then put back). */
function readTokens(): Record<string, { dark: string; light: string }> {
  const root = document.documentElement
  const was = root.dataset.theme
  const read = (theme: string) => {
    root.dataset.theme = theme
    const cs = getComputedStyle(root)
    return Object.fromEntries(TOKENS.map(([t]) => [t, cs.getPropertyValue(t).trim()]))
  }
  const dark = read("dark")
  const light = read("light")
  if (was) root.dataset.theme = was
  else delete root.dataset.theme
  return Object.fromEntries(TOKENS.map(([t]) => [t, { dark: dark[t] ?? "", light: light[t] ?? "" }]))
}

function Board({ title, note, children, className }: { title: string; note?: string; children: React.ReactNode; className?: string }) {
  return (
    <section className="board">
      <div className="board-h"><h2 className="h2">{title}</h2>{note && <span className="sp small">{note}</span>}</div>
      <div className={`board-b ${className ?? ""}`}>{children}</div>
    </section>
  )
}

function Swatches() {
  const { theme } = useTheme()
  const values = useMemo(readTokens, [theme])
  return (
    <>
      {TOKENS.map(([token, name]) => (
        <div className="swt" key={token}>
          <i style={{ "--v": `var(${token})` } as React.CSSProperties} />
          <div><b>{name}</b><code>{token}</code><code>dark {values[token]?.dark}</code><code>light {values[token]?.light}</code></div>
        </div>
      ))}
    </>
  )
}

const AREAS = [
  ["Pick one", "Choice tiles, dot top-right", "Swap card + “Change” → mini cards", "Rail radio rows", "Select in a ledger cell"],
  ["Pick several", "Tiles with a corner tick", "Swap card with chips → checkbox mini cards", "Rail rows with on/off switches", "Checklist ledger table"],
  ["Repo / long list", "Chooser dialog with search", "Swap card → dropdown with search", "Rail list with search above", "Ledger table, radio column"],
  ["Folder / file", "Path box", "—", "Spec files as a rail list", "—"],
  ["Keys", "Dashed draft rows", "Saved table with Reveal / Remove", "—", "Sealed vault per service"],
  ["Services", "Service tiles with connection dot", "Swap card + “Set up so far”", "One switch row “Needs: …”", "Registry rows, Connect / Disconnect"],
  ["Models", "—", "—", "Model lane with numbered fallbacks", "Model grid: step × model, then, then"],
  ["Steps on/off", "—", "—", "The step rail", "—"],
]

/** The Style reference page: colours, type, status, buttons, inputs, the four rich-input dialects and the icons. */
export default function StylesPage() {
  return (
    <div className="stackg" style={{ gap: 20 }}>
      <div className="title-row">
        <div>
          <h1 className="h1" id="t-styles">Style reference</h1>
          <p className="lead">The shared materials. Simple inputs look the same everywhere; rich inputs change shape per settings area.</p>
        </div>
      </div>
      <Board title="Colours" note="Live values, dark and light" className="swatches"><Swatches /></Board>
      <div className="g2">
        <Board title="Type" className="stackg">
          <div><span className="h1">Page title</span><p className="small mono">Big Shoulders Display 800 · 40 · all caps</p></div>
          <div><span className="h2">Section heading</span><p className="small mono">Big Shoulders Display 700 · 26</p></div>
          <div><span className="h3">Card title</span><p className="small mono">Figtree 600 · 17</p></div>
          <div><p>Body text reads at fifteen pixels with generous line height.</p><p className="small mono">Figtree 400 · 15/24</p></div>
          <div><span className="mono">RESEND_API_KEY · /srv/projects · $1.67</span><p className="small mono">IBM Plex Mono · names, paths, money</p></div>
        </Board>
        <Board title="Status" className="stackg">
          <div className="row">
            <Indicator kind="passed" />Passed<Indicator kind="failed" />Failed<Indicator kind="pending" />Pending
            <Indicator kind="running" />Running<Indicator kind="needs-you" />Needs you
          </div>
          <div className="row">
            <span className="badge b-need"><Icon name="bell-ringing" />Needs you</span>
            <span className="badge b-run"><Wheel />Running task 2 of 4</span>
            <span className="badge b-bad"><Icon name="x-circle" />Failed</span>
            <span className="badge b-ok"><Icon name="check-circle" />Passed</span>
            <span className="badge b-info"><Icon name="circle-dashed" />Idle</span>
          </div>
          <div className="blk-info bad"><Icon name="warning-octagon" /><span>Orange means only “Needs you”. Red means failed. Blue means a button, a link, a highlight or something running.</span></div>
          <div className="row">
            <button type="button" className="btn btn-primary">Primary</button>
            <button type="button" className="btn btn-secondary">Secondary</button>
            <button type="button" className="btn btn-ghost">Ghost</button>
            <button type="button" className="btn btn-danger">Danger</button>
            <button type="button" className="btn btn-primary" disabled>Disabled</button>
          </div>
          <div className="row">
            <Wheel /><span className="small">Loading spinner</span>
            <button type="button" className="btn btn-primary" onClick={() => toast.success("Build settings saved", { description: "Every toast has an X and fades after a few seconds." })}>Show a toast</button>
          </div>
        </Board>
      </div>
      <Board title="Simple inputs" note="Identical in every area" className="g2">
        <div className="field"><label htmlFor="sx1">Text box</label><input className="input" id="sx1" placeholder="Type here" /><span className="help">Help line under every control.</span></div>
        <div className="field"><label htmlFor="sx2">Number</label><input className="input" id="sx2" inputMode="numeric" defaultValue="3" /></div>
        <div className="stackg">
          <label className="check"><input type="checkbox" id="sx3" defaultChecked />Plain checkbox</label>
          <label className="sw-line" htmlFor="sx4"><input type="checkbox" className="switch" id="sx4" defaultChecked />Plain switch</label>
        </div>
      </Board>
      <Board title="Rich inputs by area" note="The shape tells you which settings you are in" className="stackg">
        <div className="areas4">
          <div><span className="area"><Icon name="plus-circle" />Create · open tiles</span>
            <div className="tiles" style={{ gridTemplateColumns: "1fr 1fr" }}>
              <label className="tile"><input type="radio" name="ex1" id="ex1a" defaultChecked aria-label="Web app" /><span className="mark-r" /><b>Web app</b></label>
              <label className="tile"><input type="radio" name="ex1" id="ex1b" aria-label="Mobile" /><span className="mark-r" /><b>Mobile</b></label>
            </div></div>
          <div><span className="area"><Icon name="sliders-horizontal" />Setup · swap card</span>
            <div className="swap"><span className="ico"><Icon name="globe" /></span><span className="t"><b>Web app</b><span>Sites and apps</span></span><button type="button" className="btn btn-secondary btn-sm">Change</button></div></div>
          <div><span className="area"><Icon name="hammer" />Build · rows on a rail</span>
            <div className="rail">
              <label className="rrow"><input type="radio" name="ex3" id="ex3a" defaultChecked aria-label="Web app" /><span className="node" /><span className="rt"><b>Web app</b></span></label>
              <label className="rrow"><input type="radio" name="ex3" id="ex3b" aria-label="Mobile app" /><span className="node" /><span className="rt"><b>Mobile app</b></span></label>
            </div></div>
          <div><span className="area"><Icon name="gear" />Phoenix · ledger row</span>
            <div className="lrow" style={{ padding: "8px 0", gridTemplateColumns: "minmax(0,1fr) auto" }}>
              <b>Kind</b><label className="sr" htmlFor="ex4">Kind</label>
              <select className="select" id="ex4" style={{ width: "auto" }}><option>Web app</option><option>Mobile app</option></select>
            </div></div>
        </div>
        <div className="tscroll"><table className="rtable">
          <thead><tr><th>Input</th><th>Create (New project)</th><th>Setup (project Settings)</th><th>Build (wizard, build settings)</th><th>Phoenix (global settings)</th></tr></thead>
          <tbody>{AREAS.map(([what, ...cells]) => <tr key={what}><th>{what}</th>{cells.map((c, i) => <td key={i}>{c}</td>)}</tr>)}</tbody>
        </table></div>
      </Board>
      <Board title="Icons" note="Phosphor Duotone, bundled" className="icons">
        {ICON_NAMES.map((n) => <figure key={n}><Icon name={n} size="lg" /><figcaption>{n}</figcaption></figure>)}
      </Board>
    </div>
  )
}
