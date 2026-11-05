# Alex's decisions on the round-2 open choices (2026-11-01)

These override specs/round2/merged-plan.md wherever they differ.

## 1. Projects page
- Projects are HORIZONTAL RECTANGLES (full-width rows), minimal information only:
  title; status; the project's path underneath the title; the GitHub repo (link); and three buttons in
  each card: **Remove**, **Chat**, **VS Code**. Clicking elsewhere on the card opens the project page.
- No fixed categories/columns. Instead, a strong FILTER and SORT bar: e.g. "Needs my attention"
  (approval waiting / escalations) flips the list so matching projects come first ABOVE A DIVIDER LINE
  and everything else sits below the line. Other filters/sorts likely: running, failed, idle, owner,
  recently active, name, size.
- Search and filters must be drivable by the Phoenix Agent (phase 6): e.g. "show me all the projects
  that need my attention" → matching projects shown in the chat as clickable mini cards. So filters
  must be a shared query (API/ops function + URL state), not page-only logic.

## 2. A running build
- Stacked BLOCKS, one on top of the other (like the original Phoenix harness): each block shows the
  step/task title, the task name, the model running it, and ONE indicator:
  passed = green, failed = red, pending = grey, running = spinning blue progress wheel.

## 3. Project switcher
- YES: a project switcher down the left edge on DESKTOP only. On phone it becomes something else
  (e.g. a project picker opened from the header). (Critic recommended no; Alex chose yes.)

## 4. Page titles
- ALL CAPS page titles: try it; easy to change later.

## 5. "Needs you" colour
- Solid ORANGE, "Achtung" style, in BOTH themes; orange is reserved for Needs-you only.
- DECIDED (Alex, option A): the light theme's buttons, links and highlights become ELECTRIC BLUE,
  matching the dark theme, so orange means only "Needs you" everywhere. Light theme backgrounds,
  text and other colours stay as they are. Check contrast of blue on the warm light backgrounds
  (WCAG AA for text and buttons) when tokens are set.

## Search/filter first, agent operates it (Alex, 2026-11-01)
- Phase 5 builds the Projects search bar + filters as ONE shared query: an ops function + API endpoint +
  `phoenix project list --filter ...` CLI, with the filter state in the page URL (linkable). Tested with
  ordinary tests, no AI involved.
- Phase 6: the Phoenix Agent only OPERATES those filters (one "set filters" capability); it never
  computes results itself. Replies show the matching projects as mini cards in the chat plus a button
  that applies the same filter on the Projects page, so chat and page always show the same list.

## Approvals inside the running build (Alex, 2026-11-01)
- Already built (phase 2/3): in "ask" mode the Merge step opens a GitHub merge request and the step's
  block shows a Needs-you card (Approve / Send back with a note / Don't merge); Approve merges it on
  GitHub via the server's gh login (steps/merge/run.py on_approved) and updates code/; Send back posts
  the note as a PR comment. Plan approval, human tasks, escalations and deploy confirmations appear
  the same way in their step blocks.
- NEW for phase 5: when a merge step is waiting, its block expands into an in-panel REVIEW: title,
  Phoenix's plain-English summary, tasks passed/failed, full-suite result, "changes safety code" flag,
  changed files list with an expandable diff (from the run's own diff/patches and `gh pr view/diff`),
  then Approve & merge / Send back / Don't merge right under it. Alex can read and approve without
  leaving the build; the merge still happens on GitHub.
