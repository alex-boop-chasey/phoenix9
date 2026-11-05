# Dashboard design (phase 5)

The approved look is `mockup.html`: open it in a browser (it is self-contained; data in it is demo data).
It wins over everything else here. Then `alex-decisions.md`, then `merged-plan.md` (the long design plan),
then `phase-4-5-project-list.md` (Remove / Import / reliable Chat and VS Code links).

## Alex's changes made after merged-plan.md (2026-11-02; these override it)
1. "Needs you" is plain solid orange everywhere. No orange-and-black hazard stripes anywhere
   (project row edge, Needs-you card edge, Merge step, task bar segment).
2. Phoenix updates appear ONLY in Phoenix settings (Updates tab), never on a project's Overview.
3. A project's About card shows what was chosen at setup (kind/profile, started from, repo owner,
   build preset, merging rule, created date, services as chips) plus size and chat on/off.
   No VS Code / Repo / Chat links in it (those are in the project header).
4. Radio choices (wizard, project Settings) are separate options with a faint outline each and NO
   connecting line. The connecting rail stays only where things really are a sequence (the step list,
   "These steps will run").
5. Wizard step 2's "These steps will run" summary is computed from the chosen preset and the step
   switches on step 3 (they share one state). Changing a switch makes the preset Custom. Choosing
   "Write a brief for the Planner" forces Planner on.
6. Wizard step 4 lists every AI step that is switched on; each has a working "Model and tools" button
   that opens its model, fallback models, tools and limits.
7. Phoenix settings has tabs like a project: Services, Models, Updates (Health strip above the tabs,
   Style reference link in the title row). Every service row has Configure (a dialog with that
   service's keys and settings; saved secrets show "Saved, ends in …abcd" with Replace, never the value)
   plus Connect or Disconnect. GitHub and Telegram are rows in Services, not separate cards.
8. Recent changes on Overview: plain bullet points, no connecting line.

## Mapping the mockup's demo addresses to the real app
Mockup `#projects` = `/`, `#new` = `/new`, `#import` = `/import`, `#overview|build|logs|proj-settings`
= `/p/<name>/<tab>`, `#wizard` = the Build tab's new-build view, `#global` = `/settings` (tab in `?tab=`),
`#styles` = `/styles`. The "Mockup only, show this build" switch is demo-only: do not build it.
