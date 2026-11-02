# Adding GitHub to a project

GitHub needs no package in the project's code. Releases and tags are made by Phoenix itself through
the key proxy, so the project needs no token.

- Do not add a GitHub token, `GH_TOKEN` or `GITHUB_TOKEN` to the code, config or workflows.
- Do not edit `.github/workflows`; that folder is protected.
- If the code needs to know its repository, read it from `.phoenix/project.json` (`repo`).
