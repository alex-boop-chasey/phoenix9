# Dashboard pages

Open a page for Alex with `go_to` (the page name and its options). `routes` lists every page you can open.

## Projects (page: projects)

The home page: every project as a row with its status, owner and what needs Alex.
Options: q (search words), status, owner, sort, attention.

## New project (page: new)

The new-project wizard: name, owner, template and first spec. You can also create a project yourself with
`project-create` after asking Alex the choices.

## One project (page: p/name/overview)

One project: its state, its open questions (Needs you) and recent builds.
Options: gate (opens one question).

## Builds (page: p/name/build)

One project's builds: start a build, follow a run's steps and tasks. The wizard option opens a slide of the
build wizard (1 to 7).
Options: run, wizard.

## Logs (page: p/name/logs)

One project's logs and run documents; run, step, task, kind and log pick what to show.
Options: run, step, task, kind, log.

## Project settings (page: p/name/settings)

One project's settings, in two sections: project and build. The key option jumps to one setting. The Delete
button for the project lives here; deleting is Alex's alone.
Options: section, key.

## Phoenix settings (page: settings)

Phoenix's own settings, in sections: services, models, updates, addresses.
Options: section.

## Document viewer (page: doc)

Shows one notes or research document. The path option is its id, like notes:project/specs/file.md. You can read
the same documents yourself with `docs-show`.
Options: path.

In each page name above, "name" stands for the project's name, for example p/demo-site/build.
