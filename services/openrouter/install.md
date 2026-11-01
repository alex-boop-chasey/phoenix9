# Adding OpenRouter to a project

Packages: none required. OpenRouter speaks the OpenAI-style API, so use the project's HTTP client, or
the `openai` package (pnpm for web / node, requirements file for python) with the base address
`https://openrouter.ai/api/v1`.

Config: read `OPENROUTER_API_KEY` (secret) from the environment, server-side only. List the name in
`.env.example` with an empty value.
