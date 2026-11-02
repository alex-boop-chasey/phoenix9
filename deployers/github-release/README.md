# github-release

Publishes a numbered release (`v1`, `v2`, ...) on GitHub for the project's current commit, with built files attached.
Meant for Python scripts (profile `python-script`) and desktop apps.

## What a deploy does
1. Looks at the repo's existing tags with your prefix and picks the next number. If this commit already has a
   release tag, it stops: "this commit is already released as vN".
2. Builds the files. **The build runs sealed in a throw-away container** (the same kind Verify uses: firewalled,
   no project keys, no GitHub access), never on the server itself, because it is your project's code. Files it
   leaves in `/out` are the release files. For `python-script` the default is `python3 -m pip wheel --no-deps -w /out .`.
   For `desktop` you must set `build_command`. Other profiles build nothing unless you set it (`"none"` = no files).
3. Creates the tag, the release (text from the changelog lines since the last release, or from commit
   subjects with `notes_from = "commits"`) and uploads each file.
4. Phoenix then checks the release exists and has exactly the uploaded files. If not, the new release and tag are
   deleted; the previous release stays the latest.

If any step after the tag fails, the half-made release and tag are removed straight away.

## GitHub access
Connect GitHub once in Global settings. Phoenix talks to GitHub only through the **key proxy**, which holds the token
and allows a fixed list of calls (listed in `services/github/service.toml`). This deployer never sees the token.

## Settings (`[deploy.settings]` in phoenix.toml)
- `repo`: `owner/name`; empty = the project's own repo.
- `tag_prefix`: default `v`.
- `build_command`: empty = profile default; `"none"` = no files.
- `artefacts`: globs inside `/out`; empty = everything. Symlinks are skipped, 2 GB maximum in all.
- `notes_from`: `changelog` or `commits`.
