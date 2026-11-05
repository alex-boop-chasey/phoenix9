# Phoenix 9 dashboard: merged design plan (round 2, 2026-11-01)

The buildable design for the phase 5 restyle. Self-contained: a builder needs only this file, the inventory
(`../2026-11-01-ui-inventory.md`, for the exact data behind each id) and the Ember Forge reference.
Base: **Designer A** (structure, conventions, one control shape per area). Details from **Designer B**. Fixes and
decisions from the critic (`critic.md`). Source markers: **[A]**, **[B]**, **[A+B]** (both agreed), **[new]** (critic).

Element ids (PJ-04, WZ-12 ...) are the inventory's. Section 8 proves every id is placed.

---

## 0. The idea in one table

One forge, one set of materials (tokens, simple inputs, buttons, toasts). Every page has its own floor plan so Alex
knows where he is before reading. Conventions decide **where** things are; Ember decides **how they look**. [A+B]

| Page | Floor plan (its unique structure) | From |
| --- | --- | --- |
| Projects | **Switchboard**: Needs-you shelf, then a dense grid of low cards | A |
| New project | **Order sheet**: numbered form left, sticky "What Phoenix will make" receipt right | A |
| Import | **Ghost shelf**: dashed cards of folders you can bring back, path bar below | B (order A) |
| Project: Overview | **Repo home**: wide main column plus a fixed About sidebar | B |
| Project: Build list | **Ledger**: table grouped Today / This week / Earlier, task bar in each row | A + B |
| Project: one build | **Pipeline**: vertical rail of step nodes in bands, sticky summary right | A (+ B dot strip) |
| Project: wizard | **Outline and canvas**: slide outline with answers left, slide right, dock below | B |
| Project: Logs | **Console**: filter toolbar, list and reader side by side, darker surface | A + B |
| Project: Settings | **Settings index**: left index, one section per view, sticky save bar | A + B |
| Phoenix settings | **Control room**: health strip, then a mosaic of status boards | A |
| Styles | **Specimen sheet**: topic tabs, specimens, "Areas side by side" | A + B |

Four settings areas, four rich-input dialects (section 2): **Create = open tiles**, **Setup = swap cards**, **Build =
rows on a rail**, **Phoenix = ledger rows and sealed vaults**. Simple inputs and buttons never change. [A, B's swap card]

Rules:
1. Conventions first, character second (cog top-right, primary action top-right, tabs under the title, green good,
   red failed, amber needs a person, blue busy, grey quiet). [A+B]
2. Colour is never the only signal: every status has an icon and a word; "needs you" also has a hatched spine. [B]
3. One thing, one place, one icon: repo, VS Code, chat always in that order, as one joined dock. [B]
4. Needs you beats everything: first on every page it appears on, counted on the header bell. [A+B]
5. Every disabled thing says why, printed on the page (tooltip only as a bonus). [B]
6. Motion answers a hand; at most four things move by themselves. [A]

---

## 1. Design system

### 1.1 Colour tokens [A names, Ember values, critic fixes marked *]

Code uses semantic tokens only. Ember's names (`--ember`, `--molten`, `--amber`) stay as aliases of
`--accent`, `--accent-2`, `--accent-3` for the reference HTML. Contrast ratios are computed (critic section 3).

| Token | Dark | Light | Use |
| --- | --- | --- | --- |
| `--bg-page` | #0D1117 | #F4EEE6 | header, outer margins |
| `--bg-dash` | #161B22 | #EBE2D6 | the **well**: the dashboard area holding every page (spec: different from the page) |
| `--bg-console` | #0D1117 | #FFFBF6 | Logs page well and log reader |
| `--surface` | #1C2229 | #FFFBF6 | cards, tiles, boards, dialogs, popovers |
| `--surface-2` | #232A32 | #F6EEE3 | hover, raised inner areas, selected rows |
| `--surface-3` | #2B333C | #EEE3D5 | pressed, progress tracks |
| `--input-bg` | #0D1117 | #FFFFFF | simple input fill (inset) |
| `--line` | #30363D | #E0D3C2 | dividers, card borders |
| `--line-strong` | #444D57 | #CDBBA6 | card hover border, decorative outlines |
| `--input-border` * | #6E7681 (4.12:1) | #948068 (3.79:1) | borders of every input, switch track off, checkbox (WCAG 1.4.11) |
| `--text` | #E6EDF3 | #1E1713 | body, titles, badge words |
| `--text-2` | #A3AEB9 (7.1:1) | #5B4D42 (7.9:1) | help lines, secondary |
| `--text-3` * | #7D8792 | #7A6A5C | placeholders and timestamps on surfaces/inputs only (never meaning alone) |
| `--accent` | #2E8BFF | #D2470C | selected borders, running, icons, heat |
| `--accent-fill` * | #2E8BFF | #C2410C | primary button fill (light: white text 5.18:1) |
| `--accent-ink` | #03101F (5.7:1) | #FFFFFF | text on `--accent-fill` |
| `--accent-text` * | #4FA9FF | #B23A08 (4.68:1 on well) | links, text in accent |
| `--accent-2` | #4FA9FF | #E2620F | hover, heat middle |
| `--accent-3` | #7DD8FF | #A86400 | "Live" dot, highlights (dark only for focus) |
| `--focus` * | #7DD8FF (10.8:1) | #B23A08 | 2 px focus ring, 2 px offset |
| `--ok` | #5DBFA6 | #23806B | passed, connected, healthy |
| `--attn` * | #E3B341 (8.2:1) | #7A4F00 (6.9:1) | Needs you, waiting for you, unsaved dot, caution |
| `--attn-soft` * | rgba(227,179,65,.14) | #FFF1C2 (solid) | Needs-you fill, warning block fill |
| `--attn-edge` * | rgba(227,179,65,.45) | #B8860B (3.16:1) | Needs-you border, hatch stripes |
| `--bad` | #EF5A43 | #C0341F | failed text/icons, danger outline |
| `--bad-fill` * | #C93A26 | #C0341F | filled danger button (white text 5.1:1 / 5.6:1) |
| `--info` | #A9AECB | #4D6578 | queued, paused, stopped, skipped, info blocks |
| `--{ok,bad,info,accent}-soft` | tone at 12-15% | tone at 9-10% | badge and block fills |
| `--{tone}-edge` | tone at 45% | tone at 40% | badge and block borders |
| `--heat` | #1450C8 to #2E8BFF to #7DD8FF sweep | #C2360A to #D2470C to #A86400 sweep | running bars, wire loader, Agent drawer edge |
| `--hatch` [B] | `repeating-linear-gradient(135deg, var(--attn-edge) 0 3px, transparent 3px 6px)` over `--attn-soft` | same | the "a person is needed" pattern; only ever for Needs you / Waiting for you |

Badge words are always in `--text`; the tone lives in icon, fill and border (critic issue 7). [new]

**Well rule** [A]: header and margins on `--bg-page`; every page sits in one well (`--bg-dash`, 1 px `--line`, radius
14 on the top corners, full height). Cards float on it in `--surface` with `shadow-1`. Logs switches its well to
`--bg-console`. Phone: well is full bleed, no radius.

### 1.2 Type scale [A, case rule new]

Big Shoulders Display (h1, h2, wordmark, version trio numerals), Figtree (everything else), IBM Plex Mono (names in
code form, ids, paths, versions, cost, durations, key names, logs). Self-hosted. Changing numbers use `tabular-nums`.

| Role | Font | Size / line (phone) | Weight | Case |
| --- | --- | --- | --- | --- |
| h1 | Big Shoulders | 40/42 (30/32) | 800 | **uppercase by CSS only** (one per page; source text sentence case) |
| h2 | Big Shoulders | 26/30 (22/26) | 700 | sentence case |
| h3 | Figtree | 17/24 | 600 | sentence case (card and tile titles, task headings) |
| stat | Big Shoulders | 28/28 tabular | 700 | version trio, big counts |
| p | Figtree | 15/24 | 400 | body, max 68 characters a line |
| label | Figtree | 14/20 | 600 | field labels, row titles, button text |
| small | Figtree | 13/20 | 400 | help lines, descriptions, table cells |
| micro | Figtree | 12/16 | 500 | badges, tags, toast meta |
| mono | Plex Mono | 13/20 (12 in tables, logs) | 400 | `demo-site`, `RESEND_API_KEY`, `v9.1`, `$1.67` |

No other all-caps anywhere (Ember's eyebrow label is dropped). h3 is Figtree, not the condensed face, so dense lists
stay readable. [new]

### 1.3 Spacing, radii, borders, shadows [A]

- Spacing (4 px base): 2, 4, 8, 12, 16, 20, 24, 32, 40, 56. Card padding 12; tile/board padding 20 (16 phone); gap 16
  (12 in the Projects grid); section gap 32; page gutter 16 phone / 24 tablet / 32 desktop; content max 1200.
- Radii: xs 4 (tags, kbd), sm 6 (inputs, buttons, menu rows), md 10 (cards, info blocks, mini cards), lg 14 (boards,
  dialogs, popovers, the well), pill 999 (badges, chips, switches). A child never has a larger radius than its parent.
- Borders: 1 px `--line`; inputs 1 px `--input-border`; **highlighted border** 1 px tone edge plus a 3 px solid tone bar
  on the left (info blocks) [A]; **status spine** 4 px on the left edge of cards and list rows: solid tone, or
  `--hatch` for needs you [B]. **Dashed** 1 px `--input-border` = "not saved yet / not in Phoenix yet" everywhere. [A+B]
- Shadows: Ember `shadow-1` (resting), `shadow-2` (hover, popovers), `shadow-3` (dialogs, drawer); `glow` for the
  selected tile. Light theme keeps Ember's warm brown shadows.

### 1.4 Motion [A]

| Token | Value | Use |
| --- | --- | --- |
| `--dur-fast` | 120 ms | hover, press, switch thumb |
| `--dur-base` | 200 ms | popover open, tab underline slide, inline reveal, toast in |
| `--dur-slow` | 320 ms | drawer, dialog, sheet, bar fill |
| `--ease-out` | cubic-bezier(.2,.8,.2,1) | default |
| `--ease-drawer` | cubic-bezier(.32,.72,0,1) | drawer and sheets |

Only four things move by themselves: (1) the running spinner/arc, (2) the heat sweep on a running bar or the wire
loader, (3) one 2 s glow pulse when a Needs-you card arrives, (4) the Agent flame breathing while it works. Nothing
animates in on page load. One celebration only: on project create success the heat bar fills across the well once.
Never move something under Alex's pointer or focus (Projects re-sort waits). [B]
`prefers-reduced-motion`: spinners become a static half ring plus the word, sweeps and pulses stop, sheets fade in one
frame, check marks appear without drawing.

### 1.5 Components

Every component has default, hover, focus-visible, pressed, disabled. **Disabled** = 45% opacity, no hover, and the
reason printed beside it (help line, or the dock/bar), linked with `aria-describedby`; tooltip optional. [B]
Touch targets 44 px on phone; dense desktop icon buttons 32 px (above the 24 px minimum).

**Buttons** [A+B] (height 40, phone 44, compact 32 desktop only; radius 6; label 14/20 600; `Verb object`, sentence
case, 2-4 words; never "OK" or "Submit"):

| Variant | Look | Use |
| --- | --- | --- |
| Primary | `--accent-fill`, `--accent-ink`; hover `--accent-2` with a soft glow; pressed inset | the one main action of a view, max one per view (Needs-you cards included) |
| Secondary | `--surface-2`, 1 px `--input-border`; hover border `--accent` | Back, Refresh, Reset to preset, Send back with a note, Import |
| Ghost | transparent, `--text-2`; hover `--surface-2` | Cancel, Copy, Clear filters, Discard |
| Danger | outline `--bad` on transparent; filled `--bad-fill` + white only as a dialog's confirm | Stop build, Remove, Disconnect, Roll back |
| Icon | 40 square (44 phone), ghost look, `aria-label` + tooltip | theme, close, kebab, copy |
| **Action dock** [B] | three icon buttons joined in one pill group (32 high desktop, 44 phone), 1 px dividers, fixed order repo / VS Code / chat | project cards, project header, About card |
| Busy | spinner replaces the leading icon, width fixed, siblings in the group disabled (G-22) | everywhere |

**Simple inputs (identical in all four areas)** [A+B]: text box, text area (3 lines, grows), number box (no steppers,
wheel off), password box (eye toggle only while typing a new value), plain checkbox (20 px, radius 4), plain switch
(44x24, label right, "On"/"Off" exposed to screen readers), label, help line.
- Anatomy always: label above, control, help line (small, `--text-2`), validation line (G-23).
- Control: height 40, radius 6, `--input-bg`, 1 px `--input-border`; hover `--accent-2`; focus border `--accent` + ring;
  error border `--bad` + line with `warning-circle`; success line `--ok` with `check-circle` ("This name is free.");
  checking = small spinner at the right end + "Checking the name" (polite); read-only = `--surface-2`, no border, lock icon.
- "Optional" is never written except in key rows. Unsaved marker (G-21): `--attn` dot + "Unsaved changes" beside Save.

**Badges** [A+B]: pill, 24 high, 14 px icon + word (micro, `--text`), tone-soft fill, tone-edge border. Running badge
holds the spinner. Count badge: 18 px round, tabular digits. **Dot form** (icon in a 20 px circle with `aria-label`)
only in task dot strips.

**Status spine** [B]: 4 px left edge on project cards, builds-list rows, shelf rows, Needs-you cards, log rows (selected).
**Task bar** [B]: segmented 6 px bar, one segment per task, 3 px gaps: passed `--ok`, failed `--bad`, skipped `--info`
at 40%, pending `--surface-3`, running `--heat` sweeping, waiting `--hatch`. Used on project cards (bottom edge), builds
list, Overview current build, live build summary. `aria-label` "2 of 4 tasks done, 1 failed".

**Chips and tags** [A+B]: chip = pill, optional remove X (selected items, owner filter, "from: Full preset"). Tag =
radius 4 micro label: "private", "AI", "script", "gate", "Safety", "always on", "not yet supported", "Coming soon",
"Suggested". Needs-you flags (NY-04) are pills: `--bad` tone with `warning` icon, or `--info` tone with `info` icon.

**Area tag** [A+B]: outlined pill, icon + one word: `plus-circle Create`, `sliders-horizontal Setup`, `hammer Build`,
`gear Phoenix`. Sits at the right of every settings section title, wizard canvas title and settings dialog title.

**Info block** (G-24 mini block, G-14 inline error) [A]: radius 10, tone-soft fill, 1 px tone edge, 3 px solid tone bar
on the left, 20 px icon, text (small/p), optional action link. Tones: info, tip (accent, `lightbulb`), warning
(`--attn`, `warning`), error (`--bad`, `warning-octagon`), success (`--ok`, `check-circle`), locked (neutral, `lock`).

**Info drawer** (G-24) [A+B]: a ghost handle "What is this?" (or "What is a preset?") after a label; opens an info
block directly under it (200 ms height), Esc or the handle closes. Long help uses a **help sheet** (right side panel 360,
phone full screen) with the Agent drawer's chrome minus the composer. Never on the Projects page.

**Toasts** (1.3 of the inventory) [A, shifting rule B]: 360 wide, bottom-right on desktop (stacked up to 3, newest at the
bottom), full width at the top on phone; shift left of the Agent drawer when it is open. `--surface`, `shadow-3`, 3 px
tone bar left, 28 px tone icon, title (label), optional line (small), optional link, **X always** (44 px target phone),
2 px countdown bar on timed toasts (pauses on hover/focus). Success/info 5 s; warning/error stay until closed; loading
stays and turns into its result (never two toasts for one action). `aria-live` polite (success, info) / assertive
(warning, error). Built on shadcn Sonner.

**Dropdown items as mini cards** [A+B]: radius 10, height 56, padding 8; 36 px icon tile (`--surface-2`, 1 px `--line`),
title (label), one-line description (small, `--text-2`), right slot (tick, tag, dot). Hover/focus: icon tile turns
`--accent-soft` with `--accent` icon, border `--accent`, card shifts 2 px right (120 ms; reduced motion: no shift).
Selected: accent border + tick. Disabled: 45% + reason as the description. Panel: radius 14, `--surface`, `shadow-2`,
8 px padding, one column (two columns at 560 px+ when more than 6 items [B]), max height 420 with scroll; phone = bottom
sheet. Keyboard: arrows, Home/End, type-ahead, Enter picks, Esc closes and returns focus. Used by: SETUP swap menus,
Add project menu, card kebab. Filters never use mini cards.

**Dialogs** (G-15) [A+B]: centred 440 (wide 760 for D-08, D-11), `--surface`, radius 14, `shadow-3`, scrim 60%. Header:
tone icon tile + title (h3 size); body; footer right: Ghost "Cancel", then the confirm (Primary, or filled Danger).
Focus starts on Cancel for destructive dialogs, on the confirm otherwise; Esc cancels; focus returns to the trigger.
Phone: bottom sheet, buttons stacked full width, confirm on top; wide dialogs go full screen with a back arrow.

**Empty state** (G-12) [A+B]: 56 px duotone icon in a `--surface-2` circle, h3 title, one small line, one button that
fixes the emptiness. **Error state** (G-13): same with `warning-octagon` in `--bad`, the server's message (fallback
"Something went wrong."), button "Try again".

**Loaders** (G-11) [A]: skeletons shaped like the content (`--surface-2`, 1.4 s shimmer); **wire loader**: 2 px `--heat`
bar at the top of the well while a page or save is in flight; spinner = Phosphor `circle-notch` rotating 1 s (16/18/24);
region text such as "Loading keys..." stays as the accessible name.

**Step node** (step in progress; used in the live build, create/import/deploy/update progress, wizard plan) [A]:
24 px node. Pending = dashed hollow ring. Running = rotating `--heat` arc around a small core; row gets an
`--accent-soft` wash and a 2 px left accent bar. Passed = ring closes, check draws (200 ms). Failed = `--bad` ring with
`x`, one 120 ms shake. Waiting for you = `bell-ringing` on a hatched ring. Skipped = grey ring with a slash. Switched off =
hollow ring with a short bar. Held for update = `arrows-clockwise` on a grey ring. Reduced motion: static glyphs + word.

**Launch list** [A+B]: a vertical list of step nodes with a counter ("4 of 10", stat style) and a continuous 6 px bar
above. Used by create (NP-17), import (IM-04), deploy (OV-06), update waiting (UP-06), health run (GS-12).

**Tabs** (GitHub repo tabs) [A+B]: strip under the project title, full-width 1 px `--line` baseline; tab = 18 px icon +
label + optional count; inactive `--text-2`, hover `--text`, active `--text` 600 with a 2 px `--accent` underline that
slides (200 ms); 44 high. Build shows a blue pill with spinner and "2/4" while a build runs; Overview shows an amber
count dot when something needs Alex. Sticks under the header on scroll, with the project name at its left [B].
Phone: scrolls sideways (the only allowed sideways scroll), fade edges, active tab scrolled into view.

**Relative time / copy / long text** (G-17, G-18, G-19) [A+B]: `--text-2` with exact time in a tooltip and `title`;
Copy ghost button, icon to check and "Copied" for 1.5 s; one-line text cut at 90 characters with a tooltip.

**Live indicator** (G-20) [A]: `--accent-3` dot that pulses + "Live"; grey dot + "Updating every few seconds";
offline: sticky warning block at the top of the well "Can't reach Phoenix right now; showing the last update."

**Sticky save bar** (G-21) [A]: appears at the bottom of the well when the visible section is dirty: `--attn` dot
"Unsaved changes", Ghost "Discard", Primary "Save ...". Phone: full width, buttons full width.

**Agent drawer (reserve only)** [A+B]: 440 wide (wide 720, phone full screen), `--surface`, `shadow-3`, 2 px `--heat`
line on its left edge, header (flame, "Phoenix Agent", context chip "demo-site / Build", wide toggle, close). At 1360 px+
it pushes the well left; 768-1359 it overlays with a 50% scrim (page inert); phone full screen. All page layouts use
container queries on the well, so they reflow when it narrows. Nothing important sits under the right edge.

### 1.6 Icon map (Phosphor Duotone, bundled, `currentColor`) [A+B]

Sizes: 14 badges, 18 buttons and tabs, 24 tiles, 56 empty states. One concept, one icon.

| Concept | Icon | Concept | Icon |
| --- | --- | --- | --- |
| Phoenix brand, Phoenix Agent | `flame` | Settings (header cog, project tab) | `gear` |
| Projects | `squares-four` | Needs you, waiting | `bell-ringing` |
| Overview tab | `house-line` | Build tab, a build, Start build | `hammer` |
| Logs tab | `terminal-window` | Breadcrumb separator | `/` text |
| GitHub repo | `github-logo` | Open in VS Code | `code` |
| Open chat | `chat-circle-text` | Start chat | `play-circle` |
| Folder, path | `folder-simple` | Pick folder | `folder-open` |
| Add project | `plus` + `caret-down` | Create new | `plus-circle` |
| Import | `download-simple` | Search | `magnifying-glass` |
| Filter | `funnel` | Date | `calendar-blank` |
| Theme | `sun` / `moon` | Close, remove chip | `x` |
| Warning | `warning` | Error | `warning-octagon` |
| Info, help | `info` | Tip | `lightbulb` |
| Passed, connected | `check-circle` | Failed | `x-circle` |
| Running | `circle-notch` | Queued | `clock` |
| Paused (usage limit) | `pause-circle` | Stopped | `stop-circle` |
| Skipped | `skip-forward` | Pending, idle | `circle-dashed` |
| Held for update, refresh, check | `arrows-clockwise` | Update available | `arrow-circle-up` |
| Roll back | `arrow-counter-clockwise` | Merge | `git-merge` |
| Merge request link | `git-pull-request` | Code changes (log kind) | `git-diff` |
| Deploy, live site | `rocket-launch` | Preview | `eye` |
| Reveal / hide | `eye` / `eye-slash` | Locked, sealed | `lock` / `lock-key` |
| Project keys | `key` | Service, connect | `plugs-connected` |
| Disconnect | `plugs` | Template | `cube` |
| AI step, model | `sparkle` / `cpu` | Script step | `terminal` |
| Gate step | `hand-palm` | Safety tag | `shield-check` |
| Tools | `wrench` | Skills | `graduation-cap` |
| Advisor | `lightbulb-filament` | Telegram | `telegram-logo` |
| Health | `stethoscope` | Styles gallery | `palette` |
| Cost | `coins` | Duration | `timer` |
| Spec file | `file-text` | Plan | `list-checks` |
| Kebab | `dots-three` | Remove from Phoenix, delete key | `trash` |
| Copy | `copy` | External link | `arrow-up-right` |
| Back | `arrow-left` | Step log (kind) | `list-bullets` |
| Service logs (kind) | `hard-drives` | Questions (kind) | `hand-palm` |
| Profile: Web, Mobile, Desktop, Python, Research, Platform | `globe`, `device-mobile`, `desktop`, `file-py`, `book-open`, `stack` | Owner: client sites, own tools | `buildings`, `user` |

### 1.7 Status map [A+B]

| Status | Tone | Icon | Words | Spine |
| --- | --- | --- | --- | --- |
| Needs you (project) / Waiting for you (build, task, step) | attn | bell-ringing | "Needs you" / "Waiting for you" | hatched |
| Running | accent | circle-notch (spins) | "Running" / "Running task 2 of 4" | solid accent |
| Queued | info | clock | "Queued" | solid info |
| Paused (usage limit) | info | pause-circle | "Paused (usage limit)" | solid info |
| Passed / Done / Connected / OK | ok | check-circle | "Passed" (lists), "Done" (live header), "Connected" | solid ok |
| Failed | bad | x-circle | "Failed" / "1 of 3 tasks failed" | solid bad |
| Stopped | info | stop-circle | "Stopped" | solid info |
| Skipped / Pending / Idle | info, no fill | skip-forward / circle-dashed | "Skipped" / "Pending" / "Idle" | none |
| Held for an update (RV-08) | info | arrows-clockwise | "Paused for update" | solid info |
| Not connected | info | plugs | "Not connected" | none |

### 1.8 Wording [A+B; decisions from critic section 2]

Plain words, short sentences, say what happens next, sentence case, the button's verb repeated in its toast.
**Build** is the word for a run everywhere in the interface. Kept words: Projects, Needs you, Build, Preset,
Simple/Quick/Full/Custom, Acknowledged, Merge, Deploy, Project keys, Secret. "Coming soon" is the one phrase for a
designed but not yet built feature. [B]

| Today | New |
| --- | --- |
| "Skip task" | per kind: merge **"Don't merge"**, deploy **"Don't deploy"**, plan **"Skip planning"**, human task / escalation / service setup / step **"Skip this task"** |
| "Stop run", "Stop this run?" | **"Stop build"**, **"Stop this build?"** |
| global "Settings" page | **"Phoenix settings"** (header still shows the cog + "Settings"; tooltip "Phoenix settings") |
| Approve on a human task | **"Done"** [A] |
| profile names | Web app, Mobile app, Desktop app, Python script, Research, Platform |
| log kinds | AI conversation, Check results, Code changes, Step log, Questions, Commands, Service logs |
| run id `20261031-100000-pricing-page` | "Pricing page", "31 October"; id only in tooltip / small mono |
| `from: preset:full` | chip "from: Full preset" / "Phoenix default" / "Web profile" / "This project" / "This build" |
| CLAUDE.md choices | "Phoenix's instructions" / "The project's CLAUDE.md" / "Both" |
| MCP servers / Tools / Tools denied / Skills | "Extra connections (MCP servers)" / "Tools it may use" / "Tools it may not use" / "Skills it can use" |
| Max turns / Timeout (minutes) | "Turn limit" (help "How many back-and-forth turns the AI may take before it stops.") / "Time limit (minutes)" |
| step names (raw) | Pick up, Spec check, Planner, Branch, Service setup, Check writer, Red check, Builder, Diff rules, Secret scan, Acceptance, Verify, Reviewer, Commit, Full suite, Summary, Preview, Merge, Deploy, Notify |
| "Connecting service accounts comes in a later update." | until phase 4: info block "Service accounts are connected in Phoenix settings." |

Step one-liners (WZ-12, ST-13, D-08) [A+B]: Pick up "Takes the next build from the queue." · Spec check "Checks that the
spec can be built." · Planner "Turns a brief into a spec and asks you to approve it." · Branch "Starts a clean branch for
this build." · Service setup "Sets up the services this project uses." · Check writer "Writes the checks before any
code." · Red check "Confirms the new checks fail before the code exists." · Builder "Writes the code for one task." ·
Diff rules "Blocks changes to files the build must not touch." · Secret scan "Looks for keys left in the code." ·
Acceptance "Checks the task's done-when list." · Verify "Runs deeper checks on the finished task." · Reviewer "A fresh
reader checks the change and gives a verdict." · Commit "Saves the task's work." · Full suite "Runs every test in the
project." · Summary "Writes up what was built." · Preview "Puts a preview online before merging." · Merge "Merges the
finished work into main." · Deploy "Puts the merged work live." · Notify "Tells you when the build finishes or needs you."

---

## 2. Rich inputs: four dialects

### 2.1 The rule and the tells [A, tells from B]
Simple inputs are identical everywhere. Rich inputs change **container shape and behaviour**, never colours, fonts or
radii. Every option in every area keeps the same anatomy: icon, title, one-line description, state slot (tick, dot,
switch, tag). Alex can tell the area three ways at once:
1. **Shape** (below). 2. **Area tag** in the section title. 3. **Verb on the trigger** [B]: Create "Choose", Setup
"Change", Build none (controls are already open, you just set them), Phoenix "Connect" / "Edit".

| Area | Signature | Picture |
| --- | --- | --- |
| CREATE (New project, Import) | **Open tiles**: every option visible as a card you press; long lists in a chooser dialog | a shop shelf |
| SETUP (Settings tab, Project) | **Swap cards**: a card showing the current value + "Change", opening a dropdown of mini cards | a labelled drawer |
| BUILD (wizard, Settings tab, Build) | **Rows on a rail**: a vertical 2 px line with radio nodes (pick one) or switches (many) | a pipeline |
| PHOENIX (Phoenix settings) | **Ledger rows and sealed vaults**: dense rows with a status column, write-only key cards, select grids | an accounts book |

### 2.2 Input type x area (the table)

| Input type | CREATE | SETUP | BUILD | PHOENIX |
| --- | --- | --- | --- | --- |
| Single choice, 2-6 options | choice tiles (radio dot top-right) [A] | swap card + mini-card dropdown [B+A] | rail radio rows [A] | select in a ledger cell [A+B] |
| Single choice, long list (6+) | tile gallery with category chips (≤ 8) or chooser dialog (search) [A+B] | swap card + dropdown with search box [A] | rail list with search above, radio node per row [A] | ledger table with a radio column [A] |
| Multi-select | tiles with a check in the corner + "3 selected" [A] | swap card showing chips + "Change", checkbox mini cards, "Done" [B+A] | rail switch rows; long lists get search, group headings, "12 of 18 on", collapse to chips + "Edit" [A] | checklist ledger table [A] |
| Searchable picker (repo) | "Choose a repo" tile-button → chooser dialog → repo card with "Change" [A+B] | swap card (repo) → dropdown whose first row is the search box [B] | none (spec picker is the long list) | none |
| Folder / file picker | path box (mono, simple) + "Choose a folder" → chooser dialog in folder mode [A+B] | none today (would be: dropdown tree) | spec files = rail list, newest first [A] | none today (would be: Browse cell) |
| Key/value list | dashed draft rows ("not saved yet") [A] | saved table: Name, Value, Secret, Used for, actions [A] | none (Live port is a simple number) | sealed vault card per service: write-only [A+B] |
| Service picker | service tiles with connection dot [A] | swap card with chips + "Set up so far" list (ST-09) inside the card [B] | Service setup is one switch row: "Needs: Supabase, Resend" [A] | registry ledger rows with Connect / Disconnect [A+B] |
| Model picker | none | none | **model lane**: rail row with the model, numbered fallback rows under it, ↑↓ and X buttons, "+ Add a fallback" [A, no drag] | **model grid**: rows = AI steps, columns Model / Then / Then, each a select [B] |
| Step on/off list | none | none | the step rail (2.3 D) [A] | none |
| Filters (not an area) | owner chips with counts (Projects); select menus, kind toggle chips, date pill (Logs). Plain list rows, no mini cards, no area tag [B+A] | | | |

Locked options: CREATE tile dims with `lock` and the reason as its description; SETUP mini card disabled with the reason;
BUILD radio node shows `lock` and a locked info block under the group; PHOENIX cell shows `lock` and a note in the row.

### 2.3 Wireframes per dialect

Key: `( )` radio, `(o)` selected, `[ ]` checkbox, `[x]` ticked, `[=o]` switch on, `[o=]` off, `v` caret.

**A. CREATE: choice tiles** [A]
```
 +------------------+ +------------------+ +------------------+
 | [globe]       (o)| | [device]      ( )| | [desktop]     ( )|   tile 104 high; 3 across ≥ 720, 2 across ≥ 480,
 | Web app          | | Mobile app       | | Desktop app      |   1 column on phone. Selected: 2 px --accent border + glow
 | Sites and apps   | | Expo and native  | | Tauri            |   whole tile is the radio's label (one click target)
 +------------------+ +------------------+ +------------------+
 Multi-select tiles: [x] top-right instead of the dot; a counter line "2 selected · adds 3 key rows below".
 Follow-up field appears directly under the tile group with a 200 ms reveal and a thin connector line.
```

**B. CREATE: chooser dialog** (repo, folder, long template list) [A+B]
```
 +-- Choose a repo -------------------------------------------- [x] -+   640 wide; phone full screen
 | [mag] Search repos_______________________________________          |
 | rebirth-wd                                                          |   group headings by owner
 |   [gh] rebirth-wd/demo-site            private              [tick]  |
 |   [gh] rebirth-wd/old-site                                          |
 | alex-boop-chasey                                                    |
 |   [gh] alex-boop-chasey/tiny-tool                                   |
 | (empty) No repo found.                                              |
 +---------------------------------------------- [Cancel] [Use this repo]+
 After choosing, the form shows a repo card: [gh] rebirth-wd/demo-site  private   [Choose another]
 Folder mode: breadcrumb /srv/projects › …, folder rows with size, "already in Phoenix" rows disabled, [Use this folder].
```

**C. SETUP: swap card** [B trigger, A panel]
```
 Profile
 +---------------------------------------------------------------------+
 | [globe]  Web app            Sites and apps                 [Change]  |   swap card: --surface-2, radius 10,
 +---------------------------------------------------------------------+   the button opens the panel below it
   +--------------------------------+--------------------------------+
   | [globe] Web app             ✓  | [device] Mobile app            |   mini cards (1.5); two columns ≥ 560
   | [desktop] Desktop app          | [file-py] Python script        |   Picking one updates the card (draft);
   +--------------------------------+--------------------------------+   Save in the sticky bar commits it.
 Multi (Services):
 +---------------------------------------------------------------------+
 | (GitHub) (Supabase) (Resend)                               [Change]  |
 | Set up so far: Supabase · 31 October · by the "Pricing page" build ✓ |   ST-09 inside the card
 +---------------------------------------------------------------------+
   panel: [x] [supabase] Supabase  Postgres database, auth and storage   * Connected     (stays open; "Done" bottom-right)
```

**D. BUILD: rows on a rail** [A]
```
 When a task still fails                                           (label above, like every input)
  |
  o-- Continue                      Move on to tasks that don't depend on the failed one, and flag it.
  |
  @-- Pause for me                  Pause and show an escalation; press Acknowledged when fixed.   <- selected:
  |                                                                                               filled heat node,
  o-- Delegate to the project chat  The project's chat tries to fix it and only alerts you if it can't.   row --accent-soft
 Rail = 2 px --line; node 20 px; the whole row is the click target (44 px min). RadioGroup semantics; arrows move.

 Switch rows (multi, steps):
  |-- [sparkle] Check writer   AI                 Writes the checks before any code.          [=o]
  |-- [terminal] Red check     script  [Safety]   Confirms the new checks fail ...            [=o]
  |-- [terminal] Branch        script  always on                                              [lock =o]
 Model lane:
  Model        [cpu] claude-fable-5-1   v      Builder default            from: Phoenix default
   |-- 1  claude-opus-5-5     [↑][↓][x]       Tried in this order if the first one is unavailable.
   |-- + Add a fallback model
```

**E. PHOENIX: ledger rows, vaults, grid** [A+B]
```
 Registry row:
 | [supabase] Supabase   Postgres database, auth and storage | ✓ Connected | Key checked OK, 2 h ago | Used by demo-site, tiny-tool | [Disconnect] |
 Vault (Connect expands the row):
 +-- [lock-key] SUPABASE_ACCESS_TOKEN -------------------------------------+
 | [ ••••••••••••••••• ]   [ Save ]                                         |   write-only password box, cleared after Save
 | The value is never shown again.                                          |   result line: "Supabase: connected, key checked OK"
 +-------------------------------------------------------------------------+
 Model grid:
 | Step         | Model                  | Then                  | Then          |        |
 | Planner      | [claude-sonnet-5-5 v]  | [claude-opus-5-5 v]   | [None v]      | Reset  |
```

---

## 3. Navigation model and chrome

### 3.1 Structure [A]
`Projects` (home) → one project (tabs Overview, Build, Logs, Settings) → inside Build: list, one build, new build.
Global places: New project, Import, Phoenix settings, Styles, the Agent drawer. Three clicks at most from anywhere.
Location shown four ways: header nav underline, **breadcrumb** at the top of the well (`Projects / demo-site / Build /
Pricing page`), the h1, the tab underline. Phone: breadcrumb shrinks to one back link with today's words
("← Projects", "← All builds") (G-10). No left rail, no command palette, no phone bottom bar (critic 1.2).

### 3.2 Header (G-01..G-07), `--bg-page`, 56 px, sticky [A, bell split from B]
```
+------------------------------------------------------------------------------------------------------+
| [flame] PHOENIX  v9.1   Projects                [↑ Update v9.2] [bell 2] [flame •1] [sun] [gear Settings] |
+------------------------------------------------------------------------------------------------------+
  G-01      G-02  nav (active underline)          G-03           bell [new]  G-06     G-05   G-04 (rightmost)
```
- **G-01** wordmark (flame + "Phoenix", Big Shoulders), link to Projects. **G-02** version, mono small, tooltip
  "Installed release" (`9.0.0.dev0` today, `v9.1` in phase 4). Nav link "Projects" with the active underline.
- Right side, fixed order: **G-03** update pill (only when available; `arrow-circle-up` + "Update v9.2", accent
  outline; → phoenix9 Overview). **Needs-you bell** (`bell-ringing`, amber count badge, only when count > 0; opens a
  popover: one row per open question with project, title, flags, "Review" → that card; footer "See all projects";
  empty "Nothing needs you."). **G-06** Agent button (flame icon; tooltip "Phoenix Agent (Ctrl .)"; badge = unread
  replies only; flame breathes while working; Asleep = 50% flame, tooltip "The Phoenix Agent is asleep. Send a message to
  wake it."). **G-05** theme toggle (labels "Switch to light theme" / "Switch to dark theme"; remembered). **G-04**
  settings cog, rightmost, gear + "Settings" (word hidden below 900 px), tooltip "Phoenix settings".
- Shortcuts: Ctrl+. opens/closes the Agent, Esc closes, `/` focuses Projects search, `?` opens a shortcut help sheet.

**Phone (G-07, 360 px)**: 12 px gutters (336 usable). Two-line lockup (flame + "Phoenix" over `v9.1`, 72 px), spacer,
then 44 px icon buttons in the same order: `[↑]` (only when an update exists), `[bell 2]`, `[flame]`, `[sun]`, `[gear]`.
Worst case 72 + 5 x 44 + 4 x 4 gaps = 308 px. The "Projects" nav link is hidden (wordmark goes home).
```
+------------------------------------+
|[fl]Phoenix  [↑][bell2][fl][sun][gr]|
|    v9.1                            |
+------------------------------------+
```

### 3.3 Page frame inside the well [A]
```
+- well (--bg-dash) ------------------------------------------------------------------+
| (wire loader, 2 px, only while loading)                                              |
| Projects / demo-site / Build                    breadcrumb, small, --text-2         |
| H1 TITLE                                         [secondary]  [Primary action]       |  title row: same on every page
| one-line description                                                                 |
| (tabs, on project pages)                                                             |
| ------------------------------------------------------------------------------------ |
| content                                                                              |
+--------------------------------------------------------------------------------------+
```
Primary action top-right of the title row. Form pages also keep their commit button in a sticky place (receipt on
New project, save bar on Settings, dock on the wizard).

### 3.4 Deep links [A+B]
Addresses as G-09. Every section has an `h2` with an id; `?section=` scrolls it below the sticky parts and flashes a
1.5 s accent outline (the Agent's links land visibly). Settings tab: `?section=project|build`, extra anchors
`&anchor=keys|services|preset|steps|failures|merge|deploy`. Phoenix settings: `?section=health|services|updates|github|models|telegram`.
Telegram: `#/p/<name>/overview?q=<gate>` scrolls to the card, pulses it once and focuses its primary button.

---

## 4. Pages

Common states unless overridden [A+B]: **loading** = wire loader + skeletons in the content's shape; **whole-area error**
= G-13 with "Try again"; **offline** = sticky warning block at the top of the well, last data kept, live animations stop;
**live** = values change in place, tabular digits, no layout jumps; **phone** = one column, 44 px targets, no sideways
scroll except the tab strip.

### 4.1 Projects (`#/`): Switchboard [A + B details]

Desktop (`repeat(auto-fill, minmax(280px, 1fr))` by container query: 4 across at 1200, 3 with the Agent open):
```
 PROJECTS                                                                    [ + Add project  v ]   PJ-01, PJ-02/AP-01
 Every project on this server.
 [mag Search projects            /]  (All 4) (rebirth-wd 1) (alex-boop-chasey 2) (No repo 1)     3 of 4 projects
   PJ-03                               PJ-04 owner chips with counts [B]                            PJ-05
 +- Needs you · 2 -------------------------------------------------------------------------------+  PJ-22 shelf [A]
 |/ [bell] phoenix9    Merge API and dashboard?   (changes safety code)                  [Review] |  rows 44, hatched spine
 |/ [bell] demo-site   Task 2 needs you           (delegated to project chat)            [Review] |
 +-----------------------------------------------------------------------------------------------+
 +------------------------+ +------------------------+ +------------------------+ +------------------------+
 |/demo-site   [bell Needs you][⋯]| |▌tiny-tool [⟳ Running task 2 of 4][⋯]| |/phoenix9  [bell Needs you][⋯]| | notes-only   [Idle][⋯]|
 |/A small marketing site fo…| |▌A tiny command line tool…| |/Phoenix 9 itself: the pr…| | Reading notes and idea…|
 |/rebirth-wd  [gh|<>|chat•] | |▌alex-boop-chasey [gh|<>|chat•]| |/alex-boop-chasey [gh|<>|chat•]| | No repo  [gh̶|<>|▶ Start]|
 +------------------------+ |▓▓▓▓▓▓░░░░░░ task bar  | +------------------------+ +------------------------+
                            +------------------------+
```
**Card** (PJ-06..16), 92 px tall, radius 10, `--surface`, `shadow-1`, 4 px status spine, hover: `--line-strong` border +
2 px lift (reduced motion: border only):
- Row 1: **name** PJ-06 (mono 15/600, it is the link), **status badge** PJ-08 right (words from 1.7; "Running task 2 of
  4" shortens to "Running 2/4" under 300 px card width, full text in `aria-label`), **kebab** PJ-14 (`dots-three`, 32 px).
- Row 2: **description** PJ-07, one line, ellipsis, tooltip (G-19).
- Row 3: **owner** PJ-10 (small mono `rebirth-wd`, or "No repo") left; **action dock** right: repo PJ-11, VS Code
  PJ-12, chat PJ-13. **Chat dot** PJ-09: 6 px dot on the chat button's corner, green "Chat on" / grey "Chat off"
  (tooltip and `aria-label` "Open chat, chat on"). Project-level chat link: tooltip "Open chat (project)". No chat link:
  the button shows `play-circle` "Start chat" (busy spinner, then becomes Open chat) (phase 4.5). No repo: repo button
  disabled, owner slot reads "No repo" (that is the printed reason). Non-GitHub repo: repo button with `arrow-up-right`
  and the host in its tooltip.
- **Task bar** along the bottom edge when a build is running or waiting (carries "2 of 4" without height). [B]
- **Whole card** PJ-16: stretched-link pattern; the name link's `::after` covers the card; dock and kebab sit above it.
  Enter on the name opens; buttons are their own tab stops; dock buttons open new tabs.
- **Kebab** (PJ-14): mini-card menu with one item "Remove from Phoenix" (`trash`, danger text) → D-12. On `phoenix9`
  and `home` it is disabled with the description "Phoenix's own project can't be removed." (RM-02).
- PJ-15 path and size are not on the card (project header and About card instead).
- Sort: needs you, then running/queued/paused, then by name. A card that changes status moves (200 ms) but never while
  the pointer or focus is inside it. [A+B]

**Needs-you shelf** (PJ-22) [A]: shown only when at least one question is open; one row per question: hatched spine,
bell, project name (mono), question title (one line), flags as pills, "Review" (Secondary, small) → that project's
Overview `?q=<gate>`. No approving here. Collapses to "Needs you · 2" with "Show" when more than 5.

**Add project** (AP-01) Primary "Add project" + `caret-down`, top-right → menu AP-02 (4.2).
**Filters**: PJ-03 search (simple text box with `magnifying-glass` and a `/` hint; matches name or description; `?q=`;
Esc clears). PJ-04 owner chips with counts: All owners / `alex-boop-chasey` / `rebirth-wd` / No repo (`?owner=`), one
selected (ToggleGroup single). PJ-05 "3 of 4 projects", right-aligned.

Phone:
```
 PROJECTS
 [+ Add project v]                (full width primary)
 [mag Search projects           ]
 (All 4)(rebirth-wd 1)             owner chips wrap onto a second line (no sideways scroll)
 (alex-boop-chasey 2)(No repo 1)
 3 of 4 projects
 +- Needs you · 2 ---------------+
 |/ phoenix9  Merge API and da… >|  whole row is the Review link (44 px)
 |/ demo-site Task 2 needs you  >|
 +-------------------------------+
 +-------------------------------+
 |/ demo-site      [bell Needs you] [⋯]|
 |/ A small marketing site for a pre…  |
 |/ rebirth-wd                         |
 |/ [  gh  |  <>  |  chat•  ]          |  dock: three 44 px buttons, own row on phone
 +-------------------------------+
```
States: **PJ-17** 4 skeleton cards + skeleton shelf; **PJ-18** G-13; **PJ-19** empty: "No projects yet" / "Create your
first project to get started." / Primary "Add project" (opens AP-02); **PJ-20** "No projects match" / "Clear filters";
**PJ-21** live: refreshes on events and every 10 s; "Updating every few seconds" under the count only when live updates
fall back to polling.

### 4.2 Add project menu (AP-01, AP-02) [A+B]
Popover 360 wide under the button (phone: bottom sheet), two mini cards:
- `plus-circle` **Create new**: "Start a fresh project: empty, from a template, from a GitHub repo or from code on this
  server." → `#/new`.
- `download-simple` **Import**: "Bring back a project removed earlier, or a folder Phoenix doesn't list yet." → `#/import`.
States: closed, open (focus on the first card), keyboard focus per card, pressed; Esc/outside click closes and returns
focus. The empty state's button opens the same menu.

### 4.3 New project (`#/new`, CREATE): Order sheet [A + B details]

```
 Projects / New project
 NEW PROJECT                                   [plus-circle Create]          (NP-02, area tag; NP-01 = breadcrumb + phone back link)
 +- form (8 cols) -----------------------------------------+ +- receipt (4 cols, sticky) ------------------+
 | (x) error block NP-16 when the server refuses the form   | | What Phoenix will make                      |
 | 1  Name          [ bakery-site_______ ]                  | |  Folder    /srv/projects/bakery-site        |
 |                  ✓ This name is free.                    | |  Code      Astro + Tailwind template         |
 | 2  Description   [ text area, 3 lines ]                  | |  Kind      Web app                           |
 |    A few lines. They go into the project's CLAUDE.md.    | |  Repo      rebirth-wd/bakery-site (new)      |
 | 3  Where does the code come from?                        | |  Services  Supabase, Resend                  |
 |    [Empty] [Existing GitHub repo] [Template] [On this server]  (tiles)   |  Keys      3 rows (1 needs a value)     |
 |    └ follow-up: repo card / template gallery / folder    | |  Chat      set up and started                |
 | 4  What kind of project?   (6 profile tiles)             | | ------------------------------------------- |
 | 5  GitHub repo  [=o] Create a new GitHub repo            | | (!) Save the key rows before creating.      |
 |                 Owner: [rebirth-wd tile] [alex-boop-chasey tile]  |  -> link jumps to the keys          |
 | 6  Services     (9 service tiles, connection dots)       | | [        Create project        ]  NP-15    |
 | 7  Project keys (dashed draft rows)  [Save] [Add]        | +---------------------------------------------+
 +----------------------------------------------------------+
```
Numbers are right here: the form is a sequence. [A]
- **NP-03 Name** (simple text): 400 ms after typing stops, the check runs (spinner + "Checking the name"); lines:
  bad pattern "Use lowercase letters, digits and dashes, starting with a letter or digit (41 characters at most)." /
  taken "A project called 'demo-site' already exists." / free "This name is free." (G-23).
- **NP-04 Description** (simple text area) + help.
- **NP-05 Source** (choice tiles, 4): Empty `file` (default) / Existing GitHub repo `github-logo` / Template `cube` /
  Code already on this server `folder-open`. Follow-up appears directly under the tiles:
  - **NP-06** tile-button "Choose a repo" → chooser dialog (2.3 B) → repo card with "Choose another". Not connected:
    warning block "Connect GitHub in Phoenix settings to pick a repo." with the link.
  - **NP-07** template gallery: tiles (≤ 8, so no dialog): Astro + Tailwind (web), Next.js + Tailwind (web), Expo
    (React Native) (mobile), Tauri desktop app (desktop), Python CLI (python-script), Research notes (research), and a
    dashed tile "Another GitHub template…" that reveals **NP-08** simple text box "GitHub template" (placeholder
    `owner/name`). Choosing a template sets the Profile and prints "Profile set to Web app." under the gallery.
  - **NP-09** simple mono path box (placeholder `/srv/...`) + "Choose a folder" → chooser dialog in folder mode.
- **NP-10 Profile** (6 tiles with plain titles; default Web app).
- **NP-11** plain switch "Create a new GitHub repo" (on; only for Empty or Template) and **NP-12 Owner** as two tiles:
  `rebirth-wd` "Client sites" (`buildings`), `alex-boop-chasey` "Your own tools" (`user`); remembers the last choice.
  Not connected: switch disabled, warning block "Connect GitHub in Phoenix settings to create a repo."
- **NP-13 Services** (multi tiles, 3 across): GitHub, OpenRouter, Resend, Sentry, Supabase (+ Stripe, Clerk, Sanity, Mux
  in phase 4); each with a connection dot and word ("Connected" / "Not connected", with link "Connect in Phoenix
  settings"; still selectable). Counter "2 selected · adds 3 key rows below". Until phase 4: one info block "Service
  accounts are connected in Phoenix settings." and no dots.
- **NP-14 Project keys**: CREATE keys form (4.15), dashed rows; note under it while rows are unsaved: "Save the key rows
  before creating."
- **NP-15 Create project** (Primary) in the receipt; disabled until the name is free, the source is complete and no key
  row is unsaved. The receipt prints the **first unmet requirement as a link** that scrolls to and focuses the field
  ("Choose a repo to continue." / "Name is taken: pick another." / "Save the key rows before creating.") [B].
- **NP-16** request error: error block at the top of the form, e.g. "Another project is being created. Try again in a moment."

Phone: one column; receipt becomes a sticky bottom **dock**: one-sentence summary clamped to 2 lines ("A Web app called
bakery-site from Astro + Tailwind, new repo under rebirth-wd, 2 services, 3 keys.") with "More", the first-unmet line,
and a full-width "Create project". [A+B]
```
 NEW PROJECT
 1 Name [__________]
 …
 =============================
 A Web app called bakery-site… More
 (!) Save the key rows first.
 [      Create project      ]
```

**Create progress (NP-17..19)** [A+B]: the form folds into a one-line summary card and a **launch list** appears,
560 wide, centred, h2 "Making bakery-site", counter "4 of 10" + bar. Lines (only those that apply): Checking the form ·
Making the folder and notes · Getting the code · Writing CLAUDE.md · Writing phoenix.toml · Saving keys · Recording
project facts · Creating the GitHub repo · Switching the project chat on · Adding it to the project list. Before the
first line: "Starting..." with a spinner.
- **NP-18 success**: last node checks, the heat bar fills across the well once, toast "Project bakery-site created",
  final line "Chat is live" with Secondary "Open chat" (phase 4.5), then a **ready card**: "bakery-site is ready", the
  action dock, Primary "Open project". The Overview opens after 2 s unless the pointer or focus is on the ready card. [B]
- **NP-19 failure**: failed node; error block with the server message (fallback "Creating the project failed.") and
  "Nothing was left half-made."; Primary "Back to the form" restores the filled form.

### 4.4 Import a project (`#/import`, CREATE): Ghost shelf [B, order A]
```
 Projects / Import
 IMPORT A PROJECT                                   [plus-circle Create]          IM-01
 Bring back a removed project, or a folder Phoenix doesn't list yet.
 Removed earlier (1)
 +- - - - - - - - - - - - - - - - - - - - -+ +- - - - - - - - - - - - - - - - - - -+
 : old-site                       [Import] : : side-quest                   [Import] :   IM-02 ghost cards, 2 columns
 : /srv/projects/old-site                  : : /srv/projects/side-quest              :   dashed = not in Phoenix
 : rebirth-wd/old-site · removed 2 November: : no repo · not in Phoenix yet          :
 +- - - - - - - - - - - - - - - - - - - - -+ +- - - - - - - - - - - - - - - - - - -+
 Not in Phoenix yet (1)   (second group, same cards)
 +- Or pick a folder yourself ------------------------------------------------------------+   IM-03
 | [folder] [ /srv/projects/…                         ] [Choose a folder]   [ Import ]     |
 | (x) Folder not found.                                                                   |   IM-06 validation lines
 +----------------------------------------------------------------------------------------+
```
- Card: name (mono, label), path (small mono), repo or "no repo", origin "removed on 2026-11-02" / "not in Phoenix yet",
  Secondary "Import".
- **IM-04** pressing Import turns that card into a launch list ("Adding it back", "Adding standard workspace files if
  missing (nothing is overwritten)", "Setting up and starting its chat"); other Import buttons disable with "Another import
  is running."; success toast "old-site imported", then its Overview opens.
- **IM-05** empty: "Nothing to import" / "Every folder in /srv/projects is already in Phoenix." / Secondary "Back to projects";
  the path bar stays.
- **IM-06** errors as validation lines under the path box: "Folder not found." / "That folder is already in Phoenix." /
  "That folder isn't allowed. Projects live in /srv/projects." (server words when given).
- Phone: one column of cards; path bar stacks (box, then "Choose a folder" and "Import" full width).

### 4.5 Remove from Phoenix (RM-01..03) [A+B]
From the card kebab → **D-12** (4.20), focus on Cancel; the confirm button shows a spinner while removing. **RM-02**
disabled item with its reason for `phoenix9` and `home`. **RM-03** the card collapses (200 ms), toast "demo-site removed
from Phoenix" with the line "Bring it back any time with Import." and an "Import" link.

### 4.6 Project header and tabs (PH-01..09) [B identity, A meta line]
```
 Projects / demo-site
 rebirth-wd / DEMO-SITE   [bell Needs you]                     [gh | <> | chat•]   [ Start new build ]
 A small marketing site for a pretend bakery: home, menu, contact form.
 [folder] /srv/projects/demo-site [copy]   1.5 MB
 [house Overview (2)]  [hammer Build ⟳2/4]  [terminal Logs]  [gear Settings]
 ---------------------------------------------------------------------------------------------------
```
- **PH-01** h1: owner in `--text-2` as a link that sets the Projects owner filter, " / ", then the name (h1). No repo:
  "No repo / demo-site". **PH-02** one-line description with tooltip. **PH-03** the action dock; absent links are hidden
  here (not disabled), Start chat when no chat link. **PH-04** meta line: path (mono, Copy) and size ("1.5 MB", "…" while
  measured). **PH-05** status badge beside the name.
- **Primary top-right: "Start new build"** on every tab → `build?new=1`. When a build is queued, running or waiting the
  printed line under it reads "It will wait for the current build." (one build at a time).
- **PH-06** tabs as in 1.5: Overview with amber count when questions are open, Build with spinner pill "2/4". On scroll
  the tab strip sticks under the header with the project name at its left.
- **PH-07** skeleton header bar + real tabs; **PH-08** "No project called demo-site" + "Back to projects" (4.19);
  **PH-09** G-13 with "Try again".
Phone: line 1 name + badge; line 2 description (2 lines max); line 3 dock (three 44 px buttons) + compact Primary
"Start build"; path and size move to the About card; tabs scroll sideways.

### 4.7 Overview tab: Repo home [B]
```
 +-- main (flex, max 780) --------------------------------------+ +-- About (320, sticky) --------------+
 | NEEDS-YOU CARDS (OV-01), each full width, always first        | | About                     OV-02     |
 +---------------------------------------------------------------+ | A small marketing site for a pre…   |
 | Current build                         Open the Build tab  OV-03| | [gh] rebirth-wd/demo-site ↗         |
 | Pricing page            [bell Waiting for you]                 | | [chat] Open chat (project) ↗        |
 | ▓▓▓▓▒▒░░  Task 2 of 4 · $1.67 · 14 min                         | | [ <> Open in VS Code ]  Secondary   |
 | Now: Builder is working on task 2                              | | (!) No chat link yet. [Start chat]  | OV-07
 +---------------------------------------------------------------+ +-------------------------------------+
 | Deploy  (rocket)  This VPS (Docker)            [ Deploy now ] | OV-06
 | https://demo-site.example.test ↗                               |
 | Last deploy 2 hours ago · a1b2c3d · [✓ OK]                     |
 | History: 5 rows (deploy / preview with temporary address)      |
 +---------------------------------------------------------------+
 | Phoenix updates (phoenix9 only, OV-05) — component 4.17       |
 +---------------------------------------------------------------+
 | Recent changes                                          OV-04 |
 | ● 2026-11-01  dashboard  set the merge question to ask        |
 +---------------------------------------------------------------+
```
- **OV-01** Needs-you cards (4.8), full width, newest first.
- **OV-03 Current build** card: title (h3), status badge + words ("Running task 2 of 4" / "Waiting for you" / "Queued" /
  "Paused (usage limit)"), task bar, cost and duration (mono), a "Now:" line from the live step [B], link "Open the Build
  tab". None running: "No build running." + Secondary "Start new build".
- **OV-06 Deploy** card (phase 4; only when the deployer is not "none"): deployer title (h3), live address link, last
  deploy (relative time, `a1b2c3d` mono, result badge "OK" or "Rolled back: <reason>"), Secondary **Deploy now**
  (`rocket-launch`) → D-09 → compact launch list inside the card (button reads "Deploying…", disabled) → result block:
  success "Deployed a1b2c3d to https://demo-site.example.test with vps-docker" or error "Deploy failed, rolled back:
  <reason>". Unsupported deployer: info block "Vercel is not yet supported." and no button. History: last 5 rows
  (`rocket-launch` deploy / `eye` preview + temporary address).
- **OV-05** Updates panel (4.17), phoenix9 only.
- **OV-04 Recent changes**: thin vertical thread with dots; each line date (mono small), source tag ("dashboard"), text;
  10 newest. Empty: "No changes recorded yet."
- **OV-02 About** (sidebar, sticky): description or "No description."; Repo link or a dash; Chat link ("(project)" for
  the project-level link; Start chat button when none); Secondary "Open in VS Code". **OV-07** doctor warnings as warning
  blocks at the bottom of About, each with its fix ("No chat link yet." [Start chat] / "VS Code link missing." [Check again]).
- Live: cards update in place.
Phone order: Needs-you cards, Current build, About (3-line summary + "Show details", includes path and size), Deploy,
Updates, Recent changes. Agent drawer open (stage < 1000 px): About moves under the main column.

### 4.8 Needs-you card (NY-01..14), all variants [B shape, A wording, critic decisions]

The most important object in the app. Only component with a hatched spine and a bell tile. Built with container
queries so it works at 780 (Overview), 440 (Agent drawer) and 360 (Telegram link on a phone).
```
+-/------------------------------------------------------------------------------------------+
|/ [bell]  Merge API and dashboard?                                    Task 2 · Builder       |  NY-01 (h3), NY-03 right
|/  Every task passed; the merge question is set to ask.                                     |  NY-02
|/  (! changes safety code)  (! 2 tasks failed)  (i delegated to project chat)                |  NY-04 flags
|/  [i] Approving merges the work into main.                                                  |  NY-05 help (info block)
|/  ↗ Merge request   ↗ Summary   ↗ Preview                                                  |  NY-06 links, new tab
|/  [ Approve merge ] [ Send back with a note ] [ Don't merge ]                 [ Stop build ] |  NY-07; Stop ≥ 24 px apart
+--------------------------------------------------------------------------------------------+
  --attn-soft fill, 1 px --attn-edge border, 4 px hatched spine, radius 14
```
- Title: the data's "Needs you: " prefix is replaced by the bell tile (the word "Needs you" stays in the bell's
  `aria-label` and in the card's accessible name).
- **NY-07 buttons**, always this order: Primary (kind verb) · Secondary "Send back with a note" (where offered) ·
  Ghost skip (kind wording) · Danger-outline "Stop build" alone at the far right [B]. Under 560 px they wrap into two
  columns; under 400 px they stack full width in the same order with Stop build last after a 16 px gap.
- **NY-08** "Send back with a note" reveals (200 ms) a simple text area, label "Note for the builder", placeholder
  "What should change?", Primary "Send back" (disabled with the printed reason "Write what should change.") and Ghost
  "Cancel"; focus moves into the box.
- **NY-09** Stop → D-02. **NY-10** busy: spinner in the pressed button, all others disabled. **NY-11** answered: card
  turns `--ok` tone with "Answered: Approve merge" and a drawn check, removed after 2 s (the live region keeps the text).
  **NY-12** info line "Someone already answered this." then folds after 3 s. **NY-13** error block with the server
  message inside the card above the buttons; buttons re-enabled.
- **NY-14 compact variant** (under a failed step, in the build summary): one row, hatched spine, bell, title (one line),
  the kind's buttons at 32 px; "Show details" expands to the full card. [B]
- Arrival: one 2 s glow pulse, warning toast "Needs you" with the title and "Review", bell count ticks.

| Kind | Primary | Other buttons (in order) | Help line (NY-05) | Links (NY-06) |
| --- | --- | --- | --- | --- |
| merge | Approve merge | Send back with a note · Don't merge · Stop build | "Approving merges the work into main." | Merge request, Summary, Preview (phase 4) |
| plan | Approve plan | Send back with a note · Skip planning · Stop build | "The build starts when you approve." | Plan |
| human task | Done | Skip this task · Stop build | "Do it yourself, then press Done." | none |
| escalation | Acknowledged | Skip this task · Stop build | "Fix it (for example with the project's chat), then press Acknowledged; the task runs once more." | Attempt 3 logs |
| escalation, delegated | Acknowledged | Skip this task · Stop build | grey flag "delegated to project chat" + "The project's chat is working on it; it will answer this itself if it fixes it." | Attempt 3 logs |
| service setup (phase 4) | Done, keys pasted | Open project keys (Secondary → Settings `?section=project&anchor=keys`) · Skip this task · Stop build | "Paste the keys named below in this project's Settings, then press Done, keys pasted." Why lists missing key names grouped by service | none |
| deploy (phase 4) | Deploy now | Don't deploy · Stop build | "The live site is replaced by the merged code." | none |
| deploy failed (phase 4) | Acknowledged | Skip this task · Stop build | red flag "deploy rolled back"; why "deploy failed: <reason>; rolled back to a1b2c3d (healthy)" or "rollback could not restore the site" | none |
| step (future) | Approve | Send back with a note · Skip this task · Stop build | none | step-defined |

Phone (360, Telegram link):
```
+/---------------------------+
|/[bell] Merge API and dash… |
|/ Every task passed; the …  |
|/ (! changes safety code)   |
|/ ↗ Merge request ↗ Summary |
|/ [     Approve merge     ] |
|/ [ Send back with a note ] |
|/ [      Don't merge      ] |
|/                           |
|/ [      Stop build       ] |
+----------------------------+
```

### 4.9 Build tab: builds list (`?list=1`, BL-01..06): Ledger [A + B task bar]
```
 Builds                                                                 BL-01 (h2)   [ Start new build ] BL-02
 Today
 ▌ Add JSON output    Quick   ▓▓░░  [⟳ Running task 2 of 4]      8 min    $0.41     (hover: --surface-2)
 This week
 / Pricing page       Full    ▓▓▒░  [bell Waiting for you]       —        $1.67
 ▌ Blog section       Full    ▓▒░░  [x 1 of 3 tasks failed]      21 min   $2.04
 ▌ Contact form       Full    ▓▓▓▓  [✓ Passed]                   14 min   $1.23
 Earlier
 columns (visible header): Build · Preset · Tasks · Result · Duration · Cost ; date is the small line under the title
```
- **BL-04** rows 56 px, status spine, whole row is a link (stretched); Date = relative time under the title with exact
  time on hover; Spec title; Preset tag (Full / Quick / Simple / Custom); task bar; Result badge + words ("Passed", "1 of
  3 tasks failed", "Failed", "Stopped", "Running task 2 of 4", "Waiting for you", "Paused (usage limit)", "Queued");
  Duration ("14 min", "2 h 5 min", "45s", "—"); Cost ("$1.23", "—"). Group headings Today / This week / Earlier (h3).
- **BL-02** Start new build sits in the title row of the list as well as the project header (same action, the header one
  is the page Primary; the list one is Secondary).
- **BL-03** auto-open: a queued/running/waiting build opens directly; its breadcrumb shows "All builds".
- **BL-05** empty: `hammer`, "No builds yet", "A build runs a spec as a series of small steps.", Primary "Start new build".
- **BL-06** skeleton rows; G-13.
Phone: each build is a card: line 1 title + badge; line 2 task bar; line 3 date · duration · cost.

### 4.10 Build tab: one build, live (`?run=<id>`, RV-01..15): Pipeline [A + B dot strip]
```
 Projects / demo-site / Build / Pricing page                                          (RV-01 = breadcrumb; phone "← All builds")
 PRICING PAGE                                                                  [ Stop build ]  RV-02, RV-03
 (x) Could not stop the build: <message>                                         RV-05 (error block, when it fails)
 +-- rail (flex) ------------------------------------------------+ +-- summary (300, sticky) --------+
 | [clock] Queued: waiting for the runner to pick it up.   RV-06  | | [bell Waiting for you]          |  RV-04
 | [arrows] Paused while Phoenix updates itself; it carries on.  | | Task 2 of 3   ▓▓▒░            |
 |          RV-08                                                  | | Preset    Full                 |
 | NEEDS-YOU CARDS not tied to a step (merge, plan, deploy) RV-07 | | Started   5 minutes ago        |
 | [i] Planned steps; the runner fixes them when the build starts.| | Duration  14 min               |
 |     RV-09 (only before start; nodes dashed)                     | | Cost      $1.67                |
 | At the start                                          RV-10     | | ● Live                         |
 |  ✓── Pick up            Took 45s                    [✓ Passed]  | | See this build's logs ↗        |
 |  ✓── Spec check · ✓ Branch · – Planner (Switched off)          | +--------------------------------+
 | ┌ Task 1: Collect sources  ●●●●●●●●●  [✓ Passed]   (collapsed) ┐ RV-11 + B's dot strip
 | ┌ Task 2: Send the message ●●⟳○○○○○○  [⟳ Running] attempt 2 of 3┐
 |  ✓── Check writer       Took 2 min                  [✓ Passed]  |
 |  ✓── Red check          Took 20s                    [✓ Passed]  |
 |  ⟳── Builder            Started 5 minutes ago       [⟳ Running] |   RV-13 row
 |  ○── Diff rules · Secret scan · Acceptance · Verify · Reviewer · Commit (pending, quiet)
 | ┌ Task 3: …               –––––––––  [Skipped] depends on task 1, which failed ┐
 | At the end                                            RV-12     |
 |  ○── Full suite · Summary · Preview · Merge · Deploy · Notify   |
 | Result: 1 of 3 tasks failed   See this build's logs  [Back to builds]   RV-15 (when finished)
 +----------------------------------------------------------------+
```
- **RV-03** Stop build (danger outline, top-right; only while queued/running/waiting) → D-03.
- **RV-04** summary (sticky right ≥ 1100 px stage width): status badge + "Task 2 of 3", task bar, Preset, Started,
  Duration (ticks live), Cost, live indicator (G-20) "Live" / "Updating every few seconds"; offline block above the rail.
- **RV-11 task block**: a tile; header = "Task 2: Send the message", **dot strip** (one 12 px node per task step, same
  glyphs, `aria-hidden`; the rows below are the accessible version), task badge, "attempt 2 of 3". Passed tasks collapse
  to the header (click to open); running, waiting and failed tasks open. [A + B]
- **RV-13 step row**: node on the rail, title (label), one status text (small, `--text-2`; examples "Took 45s",
  "Started 5 minutes ago", "Waiting for you", "Switched off (off by default)", "Switched off (needs checks)", "The checks
  failed", "Skipped", "Depends on task 1, which failed", "No changes to merge", "The build failed", "Deploy is off for
  this project", "Nothing merged, nothing to deploy"), badge right. Switched-off rows at 70% opacity. Clicking a row
  opens Logs filtered to that step (`#/p/<name>/logs?run=&task=&step=`).
- **RV-14** compact Needs-you card directly under the failed step it belongs to.
- **RV-15** result block at the end of the rail: tone border (ok/bad/info), "Result: Passed" / "Result: 1 of 3 tasks
  failed" / "Result: Stopped" / "Result: Failed", link "See this build's logs", Secondary "Back to builds". While running
  only the logs link shows (in the summary).
- The view follows the running step (scrolls it into view) until Alex scrolls himself; then a "Jump to live step" chip appears. [B]
- States: loading skeleton rail; never loaded G-13 "Try again"; stale keeps the last view + offline block.
Phone: summary becomes a sticky bar under the title (badge, "Task 2 of 3", cost, Live dot, chevron to expand); Stop
build full width under the bar; rail full width; status text truncates with tooltip; badges stay visible.

### 4.11 Build wizard (`?new=1`, WZ-01..25, BUILD): Outline and canvas [B layout, A controls]
Project header and tabs stay visible (orientation); leaving with answers asks "Leave without starting the build?"
(Cancel / Leave). [new]
```
 Projects / demo-site / Build / New build
 +-- outline (240) ------------------+ +-- canvas (max 720) ---------------------------------------------+
 | ✓ 1 What to build                 | | Step 3 of 7                                         [hammer Build]|  WZ-01
 |     Use a spec: Pricing page      | | Steps                                       (h2 = slide title)   |
 | ✓ 2 Preset                        | | (slide content, BUILD dialect)                                   |
 |     Quick                         | |                                                                  |
 | ● 3 Steps            (you are here)| |                                                                  |
 |     17 steps, 4 off               | |                                                                  |
 |   4 Models and tools              | |                                                                  |
 |   5 Failures                      | |                                                                  |
 |   6 Finish                        | |                                                                  |
 |   7 Review and submit             | |                                                                  |
 +-----------------------------------+ +------------------------------------------------------------------+
 ===== dock (sticky bottom of the well) =========================================================
 [ Cancel ]                        (i) Choose a spec to build.  WZ-03        [ Back ]  [  Next  ]   WZ-02
```
- **WZ-01** "Step 3 of 7" + slide title; the outline is a `nav` with `aria-current="step"`, shows each visited slide's
  answer, a check for done, an `--attn` `warning` for a slide with a problem; visited slides and the next one are
  clickable, later ones locked. [B]
- **WZ-02** dock: Ghost "Cancel" (back to the list, nothing saved), Secondary "Back" (disabled on slide 1, printed "This
  is the first step."), Primary "Next" (disabled while the slide has a problem, and on slide 3 while "Working out the
  step list…"); slide 7 shows Primary **"Start build"** (spinner while starting) instead of Next.
- **WZ-03** problem line in the dock, `info` icon, `aria-live="polite"`, linked to Next by `aria-describedby`: "Choose a
  spec to build." / "Write a short brief for the Planner." / "Working out the step list…" (spinner) / "Tries must be a
  whole number from 1 to 10."
- **WZ-04** skeleton canvas; G-13.

Slides (all choices in the BUILD rail dialect):
- **1 What to build**: WZ-05 rail radio "Use a spec" / "Write a brief for the Planner". WZ-06 rail file list
  (placeholder line "Choose a spec"; rows: `file-text`, "Contact form", `specs/contact-form.md` mono, relative date;
  newest first; search above when > 6). Empty: info block "No specs yet. Put one in the project's notes/specs folder, or
  write a brief instead." WZ-07 simple text area (5 lines, placeholder "What should be built?") + help "The Planner
  turns your brief into a spec; you approve it before building."; choosing a brief prints "The Planner is switched on for you."
- **2 Preset**: WZ-08 rail radio rows Simple / Quick / Full / Custom, each with its full description ("Just build each
  task and check it. No planner, check writer, verify or reviewer." / "Simple, plus the project's tests run after each
  task." / "Everything on: plan, checks first, full verification and a review." / "Your own mix of steps."); info drawer
  "What is a preset?". WZ-09 chip "Preset: Custom, based on Quick". WZ-10 "These steps will run": the step rail read-only
  (ticks and dashes instead of switches).
- **3 Steps**: WZ-11 line "Preset: Quick (changing a step makes the preset Custom)"; for a brief, info block "The Planner
  stays on because you wrote a brief." WZ-12 step rail (below). WZ-13 above the rail: error block "These steps can't run
  together" + list; info block "Switched off by another step" + "Red check: needs checks".
- **4 Models and tools**: WZ-14 one tile per AI step that will run (Planner, Check writer, Builder, Reviewer): `sparkle`,
  title, "Model: claude-fable-5-1", "(edited)" tag when changed, button "Model and tools" opening the AI step editor
  (4.12) under the tile. Empty: "No AI steps are on."
- **5 Failures**: WZ-15 simple number "Tries per task" (1-10, default 3; help "How many times a task may be tried
  before it counts as failed."); WZ-16 rail radio Continue / Pause for me / Delegate to the project chat with descriptions.
- **6 Finish**: WZ-17 rail radio "Merge automatically" ("Merge when the checks pass.") / "Ask me first" ("Wait for you to
  approve each merge."); phoenix9: locked on Ask, locked block "Phoenix's own project always asks before merging."
  WZ-18 plain switch "Deploy", help states the project's mode ("Deploys when the merge happens." / "Asks you before
  deploying."); disabled with printed "Deployers come later." until a deployer exists. WZ-19 plain switch "Deploy a
  preview before merging" with tag "Coming soon", disabled. WZ-20 plain switch "Notifications" (on) "Send a message when
  the build finishes or needs you."
- **7 Review and submit**: WZ-21 definition list (What, Preset, Tries per task, When a task still fails, Merge, Deploy,
  Notifications) with "Edit" per row jumping to its slide. WZ-22 "The plan": numbered steps grouped At the start / For
  every task / At the end, switched-off steps struck through and labelled "off". WZ-23 plain checkbox "Remember these as
  this project's defaults" (ticked). WZ-24 error block "The build did not start" + message. **WZ-25** success: the live
  build view opens, toast "Build started".

**Step rail** (WZ-12, ST-13) [A]:
```
 At the start                                                                              (h3 on the rail)
 |-- [terminal] Pick up      script  always on    Takes the next build from the queue.         [lock =o]
 |-- [sparkle]  Planner      AI                   Turns a brief into a spec and asks you …     [o=]
 |-- [terminal] Branch       script  always on    Starts a clean branch for this build.        [lock =o]
 |-- [terminal] Service setup script              Sets up the services … Needs: Supabase, Resend [=o]
 For every task
 |-- [sparkle]  Check writer AI                   Writes the checks before any code.           [=o]
 |-- [terminal] Red check    script [Safety]      Confirms the new checks fail …               [o= disabled]
 |                           Can't run: needs checks                                       (printed reason, --attn)
 …  At the end  …
```
Row: rail node, kind icon, title (label), kind tag, Safety tag (`shield-check`), description (small), switch right.
Always-on: locked switch + "always on". Cannot run: disabled switch + printed reason. In Settings each AI row has a
"Model and tools" button opening its editor inline, with "(edited)" when changed.
Phone: outline collapses to a bar "Step 3 of 7: Steps" + 7-segment strip (tap → bottom sheet with the outline); canvas
full width; dock two rows: problem line, then Back and Next as halves; Cancel lives in the outline sheet.

### 4.12 AI step editor (AI-01..10, BUILD) [A layout, B tray]
A tray under an AI step tile (wizard slide 4, Settings Build steps). Header "Model and tools" + "(edited)" + close X.
Every field shows the value that applies now as a faint placeholder and a source chip ("from: Phoenix default" / "Web
profile" / "Full preset" / "This project" / "This build"); Ghost "Reset to default" per field once changed.
```
 +- Model and tools  (edited) ------------------------------------------------------------- [x] -+
 | Model          [cpu claude-fable-5-1 v]   Builder default            from: Phoenix default      |  AI-01 model lane
 |  |-- 1 claude-opus-5-5 [↑][↓][x]   + Add a fallback model                                      |  AI-02
 |      Tried in this order if the first one is unavailable.                                      |
 | Tools it may use       12 of 18 on  [search]  rail switches grouped Reading / Writing / Web      |  AI-03
 | Tools it may not use   1 of 18 on   rail switches                                               |  AI-04
 | Extra connections (MCP servers)   |-- context7  [=o]                                            |  AI-05
 | Skills it can use      |-- test-driven-development [=o]  |-- systematic-debugging [o=]          |  AI-06
 | Instructions           o Phoenix's instructions  @ The project's CLAUDE.md  o Both  (rail radio)|  AI-07
 | Turn limit [200]   Time limit (minutes) [60]   (simple numbers, side by side)                    |  AI-08, AI-09
 | Advisor (lightbulb-filament)                                                                    |  AI-10
 |  [o=] Use an advisor   Advisor model lane   When to ask: |-- Blocked [=o] |-- Before done [o=] |-- On demand [o=]
 |  Advisor instructions [text area]   (!) The advisor isn't available on this server. (doctor, phase 4)
 +-------------------------------------------------------------------------------------------------+
```
Long switch lists collapse to their "on" items as chips with "Change". Two columns on desktop, one on phone.

### 4.13 Logs tab (`#/p/<name>/logs`, LG-01..12): Console [A look + B toolbar]
Well switches to `--bg-console`; panes radius 6, 1 px lines, no floating tiles: the "technical room".
```
 LOGS                                                                       [arrows Refresh]  LG-01, LG-02
 [Run: All runs v] [Task: All tasks v] [Step: All steps v] [calendar Any date v] Clear filters   LG-03..05, 08, 07
 (sparkle AI conversation)(check Check results)(git-diff Code changes)(list Step log)(hand Questions)(terminal Commands)(drives Service logs)  LG-06
 +- list (360) ----------------------------------+ +- reader (flex, --bg-console) ------------------------+
 | ▌Builder session (task 2, attempt 3)          | | [AI conversation] Builder session (task 2, attempt 3)|
 |  AI conversation · Pricing page · Task 2 ·    | | Showing the last 2 MB                     [copy Copy] |
 |  attempt 3 · Builder        12 KB · 5 min ago | | ---------------------------------------------------- |
 |  Changes (task 2, attempt 1)                  | | mono 13/20, wraps, scrolled to the bottom, newest last|
 |  Code changes · …                             | | diff: file headers bold + divider, +++/--- bold,     |
 |  (1 new log)  chip at the top when live       | | @@ in --accent-text, + lines --ok with "+" gutter,   |
 |                                               | | - lines --bad with "-" gutter                         |
 +-----------------------------------------------+ +-----------------------------------------------------+
```
- **LG-03** Run select ("All runs", then "31 October · Pricing page · waiting"); **LG-04** Task ("All tasks", "Run
  level", "Task 1"…); **LG-05** Step ("All steps" + plain step names); **LG-06** kind toggle chips (multi) with icons and
  plain names; **LG-07** Ghost "Clear filters" only when a filter is set; **LG-08** date pill "Any date" with Today / Last
  7 days / Last 30 days / Pick dates (tag "Coming soon", disabled until built). Filters live in the address.
- **LG-09** list item: title, kind (icon + word), where line in plain words (build title · Task 2 · attempt 3 ·
  Builder; run id only in the tooltip), "12 KB · 5 minutes ago"; selected = `--surface-2` + accent spine. Empty: "No logs
  match these filters." + "Clear filters". New matching entries show a "1 new log" chip, never inserted under the pointer. [B]
- **LG-10** reader: nothing chosen = `terminal-window` + "Pick a log to read it."; header kind chip, title, "Showing the
  last 2 MB" when cut, Copy (G-18); body 60% of the screen height minimum, fills the rest of the well. **LG-11** diff as
  drawn (never colour alone). **LG-12** the phoenix9 updater log is a Service logs item "Updater log"; the Updates
  panel's "Last update log" opens Logs with it selected.
- Narrow stage (< 900 px, e.g. Agent open): list and reader stack; selecting opens the reader with "← Back to list".
Phone: "Filters (2)" button opens a bottom sheet with every filter; list of cards; reader full screen with "← Back to
list"; reader font 12, wraps. States: skeleton rows + tall skeleton reader; G-13 in the failed pane; Refresh busy.

### 4.14 Settings tab (`#/p/<name>/settings`, SETUP and BUILD): Settings index [A + B]
GitHub repository-settings pattern: a left index; **each group is its own view** (one area, one dialect on screen).
```
 [tabs …  Settings]
 +- index (220, sticky) -------+ +- content --------------------------------------------------------------+
 | Project      [sliders] ●    | | Project                                           [sliders-horizontal Setup] |
 |   Details                   | | Name         [ demo-site  lock ]                       ST-01              |
 |   Repo and kind             | | Description  [ text area ]  A few lines. They go into the project's CLAUDE.md. ST-02 |
 |   Services                  | | GitHub repo  [gh] rebirth-wd/demo-site  private              [Change] ST-03 |
 |   Project keys              | | Profile      [globe] Web app   Sites and apps                [Change] ST-04 |
 | Build        [hammer]       | | Services     (GitHub)(Supabase)(Resend)                     [Change] ST-05 |
 |   Preset                    | |              Set up so far: Supabase · 31 October · "Pricing page" ✓ ST-09 |
 |   Steps                     | | Project keys   (saved table, own Save/Add)                         ST-08 |
 |   Failures                  | |                                                                       |
 |   Merge and deploy          | |                                                                       |
 +-----------------------------+ +-----------------------------------------------------------------------+
 ===== save bar (only when this section is dirty) ===  ● Unsaved changes    [Discard]  [ Save project ]  ST-06
```
- Index: two groups with their area icons; the selected group is a view (`?section=project` default, `?section=build`);
  sub-items scroll to anchors and flash. An `--attn` dot on a group means it has unsaved changes; switching keeps drafts in
  memory; leaving the tab with unsaved changes asks "Leave without saving?" (Cancel / Leave).
- Rows: label above control (simple-input anatomy) inside each block; blocks are separated by hairlines, no floating tiles.

**Project section (SETUP)**: ST-01 read-only name; ST-02 description; ST-03 repo swap card → dropdown with search (rows
as mini cards, "private" tag); ST-04 profile swap card; ST-05 services swap card with chips and **ST-09** "Set up so far"
list inside it (empty "Nothing set up yet"); help until phase 4 "Service accounts are connected in Phoenix settings.";
ST-08 "Project keys" SETUP keys form (4.15) with help "Changes are picked up by the next build and the next chat
restart." and its own Save/Add (KF-03). **ST-06** save bar "Save project" (enabled only with changes) + "Unsaved
changes"; error block with the server message above the bar; toast "Project saved". **ST-07** D-04 when repo or profile
changed (title names what changed).

**Build section (BUILD)** (the second view):
```
 Build                                                                            [hammer Build]
 Preset        rail radio Simple / Quick / Full / Custom      [ Reset to preset ]        ST-10, ST-11
               Use Reset to preset to apply a preset's values.
 Steps         Show the effective step list ↗ (D-08)                                      ST-12
               step rail with "Model and tools" per AI row                                 ST-13
 Failures      Tries per task [3]      When a task still fails: rail radio                  ST-14, ST-15
 Merge         rail radio Merge automatically / Ask me first (lock note on phoenix9)        ST-16
 Deploy        Deploy with: rail list  none · This VPS (Docker) [Suggested for Web app] · GitHub release ·
                             Cloudflare Pages / Vercel / Expo EAS [not yet supported] (disabled, reason printed)  ST-17
               Deployer settings: Live port [3100]  (required for This VPS (Docker))         (reserved group)
               When to deploy: rail radio When a merge happens / When I press a button / Off (disabled while none)
               [o=] Deploy a preview (disabled while none, reason printed)
 (x) Nothing was saved: <one line per problem>                                              ST-18 (above the bar)
 ===== ● Unsaved changes   [Discard]  [ Save build settings ]                                ST-19
```
ST-11 Secondary "Reset to preset" → D-05 → toast "Build settings reset to Quick". Toast on save "Build settings saved".
Phone: index becomes a two-segment switch "Project | Build" under the tabs (sticky); sub-items become anchor chips;
rows stack; save bar full width at the bottom.
States: skeleton rows; "Loading keys…" (KF-06) with the wire loader; G-13; saving = busy Save, other controls disabled.

### 4.15 Keys form (KF-01..06): one component, two dialects [A + B]
**CREATE (New project)**: rows with a **dashed** outline (not saved yet): Name box (placeholder "NAME", mono), Value box
(placeholder "value"; hidden characters when Secret is ticked), Secret checkbox (ticked by default), trash. Service-added
rows arrive named with value placeholder "Needs a value" and the line "Needs a value" (KF-02). Buttons Secondary "Save"
and "Add" (KF-03: Add saves the rows, then shows one more empty row). Info block "Rows are kept here until you press
Create project." Saved rows turn solid with "Kept until you create".
**SETUP (Settings)**: a saved table in the section: [key] Name (read-only mono) | Value ("••••••" for secrets, or the
value) | Secret / Public tag (Secret checkbox locked with `lock` on saved secrets) | "Used for: Resend" chip (when a service
expects it) | actions: Reveal/Hide (`eye`/`eye-slash`, secrets only), Remove (`trash` → D-01). A new row appears at the top
with a dashed outline until saved. Buttons "Save" and "Add" under the table.
Both: **KF-04** row errors as red lines under the row: "Name can use letters, digits and underscores, and cannot start
with a digit." / "There are two keys named RESEND_API_KEY." / "The value cannot have line breaks." / "Enter a value."
**KF-05** form error block: server message / "Could not save the keys." / "Could not reveal the key." / "Could not
remove the key." **KF-06** "Loading keys…" (saved mode), toast "Keys saved". Examples: `RESEND_API_KEY` secret ••••••;
`PUBLIC_SITE_URL` = https://demo-site.example.test.
Phone: each row is a stacked mini tile: name, value, Secret, then 44 px icon buttons.

### 4.16 Phoenix settings (`#/settings`, PHOENIX): Control room [A + B details]
```
 PHOENIX SETTINGS                                                             [ stethoscope Run health check ]
 Settings for all of Phoenix.                                                               GS-01
 +- Health (GS-12) ---------------------------------------------------------------------------------+
 | [✓ All good] Services ✓  API ✓  Home folders ✓  Secrets ✓  Images ✓  Firewall ✓  Claude token ✓      |
 |              Advisor ✓  Disk space 42 GB ✓  Updater ✓  Project links ✓      (chips; click = detail)  |
 +-------------------------------------------------------------------------------------------------+
 +- Services (GS-05..09)  ● 4 of 9 connected  [gear Phoenix] ----+ +- Phoenix updates  ● v9.2 available -+
 | registry ledger rows (2.3 E)                                    | | (component 4.17)                     |
 | [gh] GitHub     ✓ Connected  OK 2 h ago  rebirth-wd, alex-…     | +-------------------------------------+
 | [supabase] Supabase ✓ Connected … Used by demo-site … [Disconnect]| +- Telegram  ● Not connected ---------+
 | [stripe] Stripe  No account connection needed                   | | (GS-11)                             |
 | [resend] Resend  ○ Not connected                     [Connect]  | +-------------------------------------+
 | Keys audit ↗ (GS-09)                                            | +- GitHub  ● Connected ---------------+
 +----------------------------------------------------------------+ | (GS-03, GS-04)                       |
 +- Default models (GS-10)  [gear Phoenix] ------------------------+ +-------------------------------------+
 | model grid (2.3 E)                         [Save default models]| +- Styles ----------------------------+
 +----------------------------------------------------------------+ | Open the style gallery ↗  (palette)  |
                                                                    +-------------------------------------+
```
Every board header: icon, title (h2), **status light + words** (the at-a-glance summary B wanted from its list),
`gear Phoenix` area tag, one headline action. [A + B]
- **GS-01** title "Phoenix settings", line "Settings for all of Phoenix." **GS-02** page error G-13.
- **Health** (GS-12): summary pill "All good" (ok) / "3 problems" (bad) / "1 warning" (attn, disk); chips per check
  (Services, API, Home folders, Secrets, Images, Firewall, Claude token, Advisor, Disk space — problem under 5 GB, warning
  under 15 GB —, Updater, and in phase 4.5 project chat and VS Code links); a chip opens an inline panel with detail + the
  one-line fix; problems sort first. "Run health check" (Primary) shows a launch list of checks in the board. Before the
  first run: "Run the check to see how Phoenix is doing."
- **GitHub** (GS-03, GS-04): "Connected" + accounts as chips (`rebirth-wd`, `alex-boop-chasey`), or "Not connected" +
  "Connecting GitHub from this page comes in a later update; for now ask the Phoenix chat to connect it." When the server
  offers it: vault "GitHub token" (password box, Save disabled while empty, cleared after saving); toasts "GitHub
  connected." / "Could not connect GitHub." (or the server's words). Phase 4: GitHub becomes the first Services row
  (`GH_TOKEN`) and this board shows that row expanded; never two forms for one key.
- **Services** (GS-05..09): today nine rows "Not connected" under info block "Connecting services comes in a later
  update."; phase 4: registry rows (icon, title + description, state badge Connected / Not connected / No account
  connection needed, last check line "Key checked OK" / "Saved, but Supabase refused it: HTTP 401" / "Not checked" with
  when, "Used by" chips, button). **GS-07** Connect expands the row into a vault with one password box per account key
  (labels fixed in mono: `GH_TOKEN`, `SUPABASE_ACCESS_TOKEN`, `RESEND_API_KEY`, `SENTRY_AUTH_TOKEN`, `OPENROUTER_API_KEY`),
  Save, cleared after sending, "The value is never shown again.", result line "Supabase: connected, key checked OK";
  toast "Supabase connected.". **GS-08** Disconnect (danger ghost) → D-10; toast "Supabase disconnected.". **GS-09**
  "Keys audit" → D-11.
- **Default models** (GS-10): today read-only lines ("Planner: claude-sonnet-5-5, then claude-opus-5-5"; help "Change
  these per project in a project's Settings tab."); spec: the model grid, editable, "Reset" per row, "Save default models"
  in the board header when dirty; toast "Default models saved".
- **Telegram** (GS-11): badge Connected / Not connected; reserved form (tag "Coming soon" until built): vault "Bot token",
  simple text "Chat ID", Secondary "Send a test message", result line; copy "Phoenix messages you here when a build
  finishes or needs you."
- **Phoenix updates**: 4.17. **Styles**: link tile to `#/styles`.
Phone: boards stack: Health, Phoenix updates (first when an update exists), Services, GitHub, Default models, Telegram,
Styles; a jump chip row at the top (`?section=`); ledger rows become tiles (title + badge, details, full-width button);
the model grid becomes one card per step with three stacked selects.

### 4.17 Updates panel (UP-01..11), two homes (phoenix9 Overview, Phoenix settings) [A + B]
```
 +-----------------+ +-----------------+ +--------------------+
 | Installed       | | Previous        | | Newest         (↑) |    stat numerals (Big Shoulders 28)
 | v9.1            | | v9.0            | | v9.2               |
 +-----------------+ +-----------------+ +--------------------+
 [ Install update v9.2 ]  [ Roll back to v9.0 ]     Check for updates · Last update log
 (i) Install waits: "Add JSON output" (tiny-tool) is on task 2 of 4.        <- printed reason (UP-03)
 (i) The dashboard is down for a few seconds while the update is swapped in.  UP-11
```
- **UP-01** before phase 4: "Installed: v9.0.0.dev0. Installing updates from the dashboard comes in a later update."
  **UP-02** the trio; "Phoenix 9 is not installed yet" when so.
- **UP-03** Primary "Install update v9.2" (`arrow-circle-up`); disabled reasons printed: "Install waits: <build>
  (<project>) is on task 2 of 4." / "You're on the newest version." / "An update is running." **UP-04** Secondary "Roll
  back to v9.0" (`arrow-counter-clockwise`); disabled reason "No earlier version is installed." **UP-05** D-07 / D-06.
- **UP-06** waiting: the buttons are replaced by a launch list that survives reloads: Installing… / Waiting for task 3 of
  "Add JSON output" to finish / Restarting… / then "Now v9.2" (success block + toast) or "Rolled back: <reason>". While
  the dashboard is away: banner "Phoenix is restarting; this page reconnects by itself." After the limit (3 min today,
  10 in phase 4): error block "Phoenix did not come back after 10 minutes. Check the Logs tab of phoenix9 for the update
  log." + link "Open the update log".
- **UP-07** results: installed "Updated to v9.2." · already installed "You already have v9.2." · tests failed "The update's
  tests failed. Nothing changed." · images failed "The update couldn't be prepared. Nothing changed." · harness busy "A
  build is in the middle of a task. The update waits for it." · rolled back "The update failed its health check and
  Phoenix went back to v9.1." · rolled back but unhealthy (error) "Phoenix went back to v9.1 but may be down. Check the
  update log." · rolled back by you "Phoenix went back to v9.0." · refused "Phoenix refused this update: <reason>." ·
  recovered "Phoenix recovered after an interrupted update."
- **UP-08** warning block "An update was interrupted." + Primary "Repair".
- **UP-09** "Last update log" expander: last 10 lines in mono + "Open in Logs" (LG-12). **UP-10** Ghost "Check for
  updates" (spinner while checking). **UP-11** note always shown.
- Header pill G-03 lands on phoenix9 Overview, which shows this panel.

### 4.18 Component gallery (`#/styles`): Specimen sheet [A + B]
Breadcrumb "Phoenix settings / Styles". Left topic tabs (phone: a select at the top): Tokens (colours both themes,
borders, radii, shadows, spacing), Type, Buttons, Simple inputs ("Identical in every area."), **Areas side by side**
(one single-choice and one multi-select rendered in the four dialects in four columns) [B], Badges and status, Info
blocks and drawers, Toasts, Tabs, Dialogs, Loaders and step nodes, Icons. Each specimen shows its states in a row
(default, hover, focus, disabled, error, busy) and its token names in mono. Theme switch pinned top-right. Static page.

### 4.19 Not found (NF-01, PH-08) [A+B]
Centred empty-state: `compass` icon (56), h2 "Page not found", "That address doesn't lead anywhere in Phoenix.", Primary
"Back to projects". PH-08: same with "No project called demo-site".

### 4.20 Dialogs (D-01..D-12), final copy [B copy, A layout]
| Id | Tone | Title | Body | Buttons |
| --- | --- | --- | --- | --- |
| D-01 | danger | Remove RESEND_API_KEY? | The saved value will be deleted. Builds and the chat stop using it from their next start. | Cancel / Remove key |
| D-02 | danger | Stop this build? | The build stops now. Work done so far stays on its branch. | Cancel / Stop build |
| D-03 | danger | Stop this build? | (same dialog as D-02, second entry point) | Cancel / Stop build |
| D-04 | caution | Change the repo? / Change the profile? / Change the repo and profile? | The next build uses the new one. | Cancel / Change it |
| D-05 | caution | Reset to the Quick preset? | Every step goes back to the Quick preset's on/off choices. Other step settings stay. Unsaved edits on this page are dropped. | Cancel / Reset to preset |
| D-06 | danger | Roll back to v9.0? | Phoenix goes back to the previous version. The dashboard is away for a few seconds. | Cancel / Roll back |
| D-07 | caution | Install update v9.2? | Phoenix restarts. The dashboard is away for a few seconds. | Cancel / Install update |
| D-08 | info, wide | What the next build will run | The steps that will run, and the settings that differ from the defaults. | Close (X and button) |
| D-09 | caution | Deploy demo-site now? | The live site is replaced by the latest merged code. If it fails its health check, the old version comes back. | Cancel / Deploy |
| D-10 | danger | Disconnect Supabase? | demo-site and tiny-tool use it. Their builds can't set Supabase up until you connect it again. | Cancel / Disconnect |
| D-11 | info, wide | Keys audit | read-only, below | Close |
| D-12 | danger | Remove demo-site from Phoenix? | Its folder, notes, code, repo and keys stay exactly where they are. Its chat stops and it disappears from the Claude app. You can bring it back with Import. | Cancel / Remove from Phoenix |
- **D-08** readable table, groups At the start / For every task / At the end; columns Step | State | Why; rows like
  "Pick up | On, always on | Takes the next build from the queue.", "Planner | Off | Off by default", "Red check | On |
  Safety step"; needs lines rewritten ("Needs a spec. Phoenix provides it." / "Needs a plan. With no plan it builds the
  spec as written."); rows that differ from defaults carry a "Changed" tag and an accent spine; tabs "Steps" / "Other
  settings"; footer "Copy as text".
- **D-11** tabs "Phoenix keys" (file, key names, used by, last changed, "Safe permissions" ✓ / "Too open: <what>" ✗) and
  "Project keys" (project, key, Secret/Public, Set/Empty, where used, last touched, expected by service); summary at the
  top "No problems found." or a problems list; a lock line "Values are never shown."
- Leave-confirms [new]: "Leave without starting the build?" (wizard) and "Leave without saving?" (Settings): Cancel / Leave.

---

## 5. Toasts (final copy; every toast has an X) [A+B]

| When | Kind | Title / line |
| --- | --- | --- |
| Create finished | success | "Project demo-site created" |
| Import finished | success | "old-site imported" |
| Remove finished | success | "demo-site removed from Phoenix" / "Bring it back any time with Import." + Import link |
| Keys saved | success | "Keys saved" |
| Save project | success | "Project saved" |
| Save build settings | success | "Build settings saved" |
| Reset to preset | success | "Build settings reset to Quick" |
| Save default models | success | "Default models saved" |
| Build started | success | "Build started" |
| GitHub token saved / refused | success / error | "GitHub connected." / "Could not connect GitHub." + server message |
| Service connected / disconnected | success | "Supabase connected." / "Supabase disconnected." |
| Update / roll back did not start | error (stays) | "The update did not start." / "The roll back did not start." + server message |
| Update running | loading → success/error | "Installing v9.2…" → "Now v9.2" / "Rolled back: <reason>" |
| Agent replied, drawer closed | info | "Phoenix Agent replied" + first line + "Open" (phase 6 reserve) |
| A question opens anywhere | warning (stays) | "Needs you" + question title + "Review" (phase 6 reserve) |
Form save failures are never toasts: they are error blocks next to the Save.

## 6. Cross-page states [A+B]

| State | Treatment |
| --- | --- |
| Loading | wire loader + skeletons; triggering button busy |
| Empty | icon, title, one line, the button that fixes it |
| Error (area) | G-13 + Try again; forms use error blocks |
| Running | spinner/arc, heat sweep, "Live" dot, solid accent spine |
| Needs you | hatched spine, bell, amber count on the header bell and Overview tab, warning toast |
| Disabled | 45%, reason printed and linked |
| Unsaved | dashed outline on drafts; amber dot "Unsaved changes" + save bar; leaving asks |
| Success | drawn check, ok block, toast |
| Offline | sticky warning block, last data kept, animations stop |
| Locked | `lock` + reason (phoenix9 merge, always-on steps, saved secrets) |
Keyboard: everything reachable with Tab; arrows inside menus, radio rails, tabs; visible focus; dialogs trap and
return focus; no drag anywhere in v1.

## 7. Distinct structures check (Alex's rule) [new]

| Page | Silhouette | Unique because |
| --- | --- | --- |
| Projects | shelf + uniform card grid | only grid of identical small cards |
| New project | numbered form + right receipt | only right-hand live summary |
| Import | dashed ghost cards | only dashed cards |
| Overview | main column + sticky About sidebar | only GitHub repo-home split |
| Builds list | grouped table with spines | only date-grouped table |
| One build | vertical rail + right summary | only node rail (with bands) |
| Wizard | left outline of answers + canvas + bottom dock | only stepped outline |
| Logs | toolbar + list + reader, darker well | only console surface, mono reader |
| Settings tab | left index + one section + save bar | only index-driven sub-views |
| Phoenix settings | health strip + mosaic of boards with lights | only board mosaic |
| Styles | topic tabs + specimen rows | only specimen sheet |
Settings tab (left index, content rows) and the wizard (left outline, canvas) both have a left column: they differ by
content (index of sections vs numbered answered steps), the bottom dock vs save bar, and the wizard's canvas card. Watch
this in the Playwright review; if Alex finds them alike, move the wizard outline into a top stepper with answers below
each dot (fallback).

---

## 8. Inventory checklist (every id placed)

Section numbers refer to this file.

- **Global chrome**: G-01, G-02, G-03, G-04, G-05, G-06, G-07 → 3.2. G-08 → 1.1 well rule, 3.3. G-09 → 3.1, 3.4. G-10 →
  3.1 (breadcrumb + phone back links). G-11 → 1.5 Loaders. G-12 → 1.5 Empty. G-13 → 1.5 Error. G-14 → 1.5 Info block
  (error tone). G-15 → 1.5 Dialogs, 4.20. G-16 → 1.5 Badges, 1.7. G-17, G-18, G-19 → 1.5 Relative time/copy. G-20 → 1.5
  Live indicator, 4.10. G-21 → 1.5 Sticky save bar, 4.14. G-22 → 1.5 Buttons (Busy). G-23 → 1.5 Simple inputs. G-24 → 1.5
  Info block, Info drawer. Toasts table (inventory 1.3) → 5. Agent reserve 2.20 → 1.5 Agent drawer, 3.2, 4.8 (card at 440).
- **Projects**: PJ-01, PJ-02, PJ-03, PJ-04, PJ-05, PJ-06, PJ-07, PJ-08, PJ-09, PJ-10, PJ-11, PJ-12, PJ-13, PJ-14,
  PJ-15 (moved to 4.6/4.7), PJ-16, PJ-17, PJ-18, PJ-19, PJ-20, PJ-21, PJ-22 → 4.1.
- **Add project**: AP-01, AP-02 → 4.1, 4.2.
- **New project**: NP-01, NP-02, NP-03, NP-04, NP-05, NP-06, NP-07, NP-08, NP-09, NP-10, NP-11, NP-12, NP-13, NP-14,
  NP-15, NP-16 → 4.3; NP-17, NP-18, NP-19 → 4.3 Create progress.
- **Import**: IM-01, IM-02, IM-03, IM-04, IM-05, IM-06 → 4.4.
- **Remove**: RM-01, RM-02, RM-03 → 4.5, 4.20 (D-12).
- **Project header**: PH-01, PH-02, PH-03, PH-04, PH-05, PH-06, PH-07, PH-08 (+4.19), PH-09 → 4.6.
- **Overview**: OV-01, OV-02, OV-03, OV-04, OV-05 (→ 4.17), OV-06, OV-07 → 4.7.
- **Needs-you card**: NY-01, NY-02, NY-03, NY-04, NY-05, NY-06, NY-07, NY-08, NY-09, NY-10, NY-11, NY-12, NY-13, NY-14
  → 4.8 (all nine kinds in its table).
- **Builds list**: BL-01, BL-02, BL-03, BL-04, BL-05, BL-06 → 4.9.
- **One build**: RV-01, RV-02, RV-03, RV-04, RV-05, RV-06, RV-07, RV-08, RV-09, RV-10, RV-11, RV-12, RV-13, RV-14, RV-15 → 4.10.
- **Wizard**: WZ-01, WZ-02, WZ-03, WZ-04 → 4.11 frame; WZ-05, WZ-06, WZ-07 slide 1; WZ-08, WZ-09, WZ-10 slide 2; WZ-11,
  WZ-12, WZ-13 slide 3 (+ step rail); WZ-14 slide 4; WZ-15, WZ-16 slide 5; WZ-17, WZ-18, WZ-19, WZ-20 slide 6; WZ-21, WZ-22,
  WZ-23, WZ-24, WZ-25 slide 7.
- **Logs**: LG-01, LG-02, LG-03, LG-04, LG-05, LG-06, LG-07, LG-08, LG-09, LG-10, LG-11, LG-12 → 4.13.
- **Settings tab**: ST-01, ST-02, ST-03, ST-04, ST-05, ST-06, ST-07, ST-08, ST-09 → 4.14 Project section; ST-10, ST-11,
  ST-12, ST-13, ST-14, ST-15, ST-16, ST-17 (incl. deployer settings), ST-18, ST-19 → 4.14 Build section.
- **Phoenix settings**: GS-01, GS-02, GS-03, GS-04, GS-05, GS-06, GS-07, GS-08, GS-09, GS-10, GS-11, GS-12 → 4.16.
- **Updates**: UP-01, UP-02, UP-03, UP-04, UP-05, UP-06, UP-07, UP-08, UP-09, UP-10, UP-11 → 4.17.
- **Dialogs**: D-01, D-02, D-03, D-04, D-05, D-06, D-07, D-08, D-09, D-10, D-11, D-12 → 4.20.
- **Keys form**: KF-01, KF-02, KF-03, KF-04, KF-05, KF-06 → 4.15 (+ 2.2 key/value row).
- **AI step editor**: AI-01, AI-02, AI-03, AI-04, AI-05, AI-06, AI-07, AI-08, AI-09, AI-10 → 4.12.
- **Not found**: NF-01 → 4.19. **Gallery** (2.19) → 4.18. **Agent reserve** (2.20) → 1.5, 3.2.
- **Rich inputs by area** (inventory part 3): every row (NP-05, NP-06, NP-07, NP-09, NP-10, NP-12, NP-13, NP-14, IM-02,
  IM-03; ST-03, ST-04, ST-05, ST-08; WZ-05, WZ-06, WZ-08/ST-10, WZ-12/ST-13, WZ-16/ST-15, WZ-17/ST-16, ST-17 x2, AI-01,
  AI-02, AI-03/04, AI-05, AI-06, AI-07, AI-10 x2; GS-07, GS-06, GS-10 x2) → 2.2 table, wireframes 2.3. Filters PJ-04,
  LG-03..06 → 2.2 last row.
- **Status values** (inventory part 4) → 1.7, plus Agent states (Idle, Working, Queued, Needs you, Asleep) → 3.2.
- **Wording and phone rules** (inventory part 5) → 1.8 and each page's phone notes; 360 px header → 3.2.

---

## 9. Open choices for Alex (with my recommendation)

1. **Projects page shape.** Grid of compact cards with a "Needs you" strip above it (recommended: it is the dense grid
   you asked for), or B's three columns "Needs you / Running / Idle".
2. **Watching one build.** A top-to-bottom list of steps like GitHub Actions, each task with a little row of dots
   (recommended), or B's grid of tasks across steps (prettier overview, harder on a phone, more to build).
3. **Project switcher down the left edge** (B's rail of project tiles, visible on every page). Recommended: no; the
   Projects page plus breadcrumbs keeps every page wider, and it is one more thing to build.
4. **Page titles in capitals** (the Ember look, recommended, page titles only) or normal sentence case everywhere.
5. **Light theme "needs you" colour.** Dark gold on a pale-yellow fill with diagonal stripes (recommended: your orange
   and the old gold are nearly the same shade, so stripes do the telling), or pick a different colour (for example
   purple) and drop the stripes.

---

## 10. Implementation notes (restyling the React + shadcn/ui app)

**Tokens.** One `tokens.css` with the section 1.1 tables as CSS variables under `:root` (dark default) and
`[data-theme="light"]`. Map shadcn's variables onto them: `--background` = `--bg-dash`, `--foreground` = `--text`,
`--card` = `--surface`, `--popover` = `--surface`, `--primary` = `--accent-fill`, `--primary-foreground` =
`--accent-ink`, `--secondary` = `--surface-2`, `--muted` = `--surface-2`, `--muted-foreground` = `--text-2`,
`--accent` (shadcn hover) = `--surface-2`, `--destructive` = `--bad-fill`, `--border` = `--line`, `--input` =
`--input-border`, `--ring` = `--focus`, `--radius` = 6px. Add Tailwind theme entries for `attn`, `ok`, `bad`, `info`,
their `-soft`/`-edge`, `heat`, `hatch`, `bg-page`, `bg-console`. Fonts via `@fontsource/big-shoulders-display`,
`@fontsource/figtree`, `@fontsource/ibm-plex-mono` (self-hosted). Icons via `@phosphor-icons/react` with
`weight="duotone"` (tree-shaken, bundled). Container queries: Tailwind's `@container` (built in from v4; plugin on v3).
Motion through `motion-safe:` / `motion-reduce:` variants.

**shadcn components to restyle (variants via cva)**
| shadcn | Change |
| --- | --- |
| Button | variants primary, secondary, ghost, danger (outline + `confirm` fill), icon; `busy` prop; 44 px on phone |
| Input, Textarea, Label, Checkbox, Switch | simple-input anatomy, `--input-bg`, `--input-border`, states; one `Field` wrapper (label, help, validation) |
| Badge | `StatusBadge` variants from 1.7, spinner slot, dot form |
| Tabs | GitHub underline style, icon + count slot, sticky, horizontal scroll on phone |
| Card | tone/spine variants (`spine="ok|bad|info|accent|attn-hatch"`) |
| Dialog, AlertDialog | tone icon header, destructive focus on Cancel, bottom sheet on phone (Drawer/vaul) |
| Sheet | help sheet, chooser on phone, Agent drawer shell (reserve) |
| Popover + Command | swap-card dropdown (mini cards), chooser dialog (CommandDialog), header bell inbox |
| DropdownMenu | Add project menu and kebab, items rendered as mini cards |
| RadioGroup | three skins: `tiles` (CREATE), `rail` (BUILD), plain (dialog use) |
| ToggleGroup | owner chips with counts, log kind chips |
| Select | Logs filters, model grid cells |
| Table | builds ledger, keys saved table, registry ledger, D-08, D-11 |
| Collapsible / Accordion | task blocks, AI step editor tray, info drawer, shelf collapse |
| Sonner | toasts (position, X, countdown bar, morphing loading toast) |
| Skeleton, Progress | skeletons; task bar built on Progress primitives |
| Tooltip | bonus tooltips only (reasons are printed) |
| Breadcrumb | well breadcrumb with phone back-link mode |
| Alert | InfoBlock (tones incl. locked) |
| ScrollArea | log reader, chooser lists |

**New components (all on shadcn primitives)**: `PageFrame`/`Well` (breadcrumb, title row, wire loader), `Header`
(with `NeedsYouBell`, `AgentButton` reserve), `ProjectCard` (stretched link), `ActionDock`, `NeedsYouShelf`,
`NeedsYouCard` (+ compact, kind table as config), `TaskBar`, `StepNode`, `LaunchList`, `StepRail` (radio and switch
rows, model lane), `ChoiceTiles` (single/multi), `SwapCard`, `ChooserDialog` (repo, folder, template), `KeysForm`
(`mode="draft"|"saved"`), `Vault`, `LedgerRow`, `ModelGrid`, `AreaTag`, `InfoDrawer`, `StickySaveBar`, `WizardOutline`
+ `WizardDock`, `LiveIndicator`, `RelativeTime`, `CopyButton`, `EmptyState`/`ErrorState`, `UpdatesPanel`, `HealthBoard`,
`StylesGallery` page. About 22 new, each small.

**Build order suggestion** (for the grunt step sheets): tokens + fonts + icons → simple inputs, Button, Badge, InfoBlock,
toasts, dialogs → PageFrame/Header → Projects → project header/tabs + Overview + NeedsYouCard → Build list + live build →
wizard + StepRail + AI editor → Settings tab + KeysForm + SwapCard → New project + Import + ChooserDialog → Logs →
Phoenix settings + Updates + Health → Styles gallery last (it renders everything else, so it doubles as the visual test
page for Playwright screenshots in both themes at 1280 and 360 px).

**Checks to automate**: axe on every route in both themes; a contrast unit test over the token table (the ratios in
1.1); Playwright screenshots of every page at 360 and 1280 px, with and without a 440 px right panel; keyboard-only
pass on the wizard, Needs-you card and keys form.
