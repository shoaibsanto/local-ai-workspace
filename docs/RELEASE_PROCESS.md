# Release Process

This documents the steps used to cut a `local-ai-workspace` release
(e.g. the 1.0.0 release). Follow it in order for future 1.x releases.

## 0. Prerequisites

- Clean working tree, on `main`, up to date with `origin/main`.
- `uv` installed and `.venv` present with the dev deps:
  `uv pip install -e ".[dev]"`.
- Node/npm available for the frontend build.
- `gh` CLI authenticated if you'll be pushing a tag / creating a GitHub
  release.

## 1. Build the frontend

```bash
cd frontend
npm ci
npm run build
```

This produces `frontend/dist/`. `npm ci` (not `npm install`) is used so the
build uses exactly what's pinned in `package-lock.json`.

## 2. Copy the built frontend into the package

```bash
cd ..   # repo root
rm -rf src/local_ai_workspace/static
cp -r frontend/dist src/local_ai_workspace/static
```

`src/local_ai_workspace/static/` is gitignored — it is a build artifact,
regenerated for every release, not committed. `pyproject.toml` bundles it
into the wheel via:

```toml
[tool.hatch.build.targets.wheel]
packages = ["src/local_ai_workspace"]
artifacts = ["src/local_ai_workspace/static/**"]
```

## 3. Bump the version

Edit `[project].version` in `pyproject.toml` (the single source of truth —
the CLI's `local-ai --version` reads this value at runtime via
`importlib.metadata.version("local-ai-workspace")`, so there is nothing
else to keep in sync). Bump the `Development Status ::` classifier too if
appropriate (e.g. `3 - Alpha` -> `5 - Production/Stable` for a 1.0 release).

Update `CHANGELOG.md` with a new `## [X.Y.Z] - <date>` section.

## 4. Build the wheel and sdist

```bash
source .venv/bin/activate
rm -rf dist
uv build --sdist
uv build --wheel
```

**Important:** build the sdist and the wheel as two separate steps (or run
plain `uv build` and verify after — see pitfall below). Prefer
`uv build --wheel`, which builds the wheel directly from the working
tree, picking up the freshly-copied `static/` directory.

### Pitfall: `uv build` (no flags) can ship an empty wheel

Plain `uv build` first builds the sdist, then builds the wheel *from that
sdist* rather than from the working tree. Since `static/` (and `dist/`) are
gitignored, hatchling's sdist step can omit `static/` from the sdist
tarball, and the wheel built from that sdist then silently ships without
the frontend. Always verify the wheel's contents (step 5) before trusting
a build, and prefer `uv build --wheel` run directly against the source
tree if you hit this.

## 5. Verify the wheel actually contains the frontend

```bash
ls dist/
python -m zipfile -l dist/local_ai_workspace-X.Y.Z-py3-none-any.whl | grep static
```

You must see `local_ai_workspace/static/index.html`,
`local_ai_workspace/static/assets/*.js`, and `*.css` in the listing. If you
don't, go back to step 1-2 and step 4's pitfall note.

## 6. Smoke-test in a completely fresh virtualenv

Never trust an editable (`-e .`) install for this — it hides missing
package-data/static-asset bugs. Use a venv outside the repo, with no other
local-ai-workspace install present:

```bash
python3 -m venv /tmp/lai-release-smoketest-venv
source /tmp/lai-release-smoketest-venv/bin/activate
pip install /path/to/repo/dist/local_ai_workspace-X.Y.Z-py3-none-any.whl

which local-ai
local-ai --version   # must print the new version

mkdir -p /tmp/lai-release-smoketest-data
export LOCAL_AI_WORKSPACE_HOME=/tmp/lai-release-smoketest-data
local-ai serve --no-browser --port 8491 &

curl -sf http://127.0.0.1:8491/api/health        # {"status":"ok"}
curl -s  http://127.0.0.1:8491/                   # real index.html, not 404
curl -s  http://127.0.0.1:8491/api/providers       # 3 seeded default providers
```

Optionally, prove one real LLM round trip end to end (set a provider API
key via `PUT /api/providers/{id}/api_key`, create a conversation, POST to
`/api/conversations/{id}/chat`, confirm the expected text streams back and
is persisted via `GET /api/conversations/{id}`). This is the single best
way to catch packaging regressions that unit tests miss — it exercises the
exact artifact a user would install.

Kill the server and delete both the venv and data dir afterward so no test
artifacts are left on the machine:

```bash
kill %1
rm -rf /tmp/lai-release-smoketest-venv /tmp/lai-release-smoketest-data
```

## 7. Commit, tag, push

Only after the smoke test passes:

```bash
git add pyproject.toml CHANGELOG.md docs/RELEASE_PROCESS.md
git commit -m "Release vX.Y.Z"
git tag vX.Y.Z
git push origin main --tags
```

`dist/` is gitignored and is never committed — it's a local/CI build
artifact. If publishing to PyPI, upload from the verified `dist/` produced
in step 4 (`twine upload dist/*` or equivalent), not a re-build, so what
you tested is exactly what you ship.

## 8. (Optional) GitHub release

```bash
gh release create vX.Y.Z dist/local_ai_workspace-X.Y.Z-py3-none-any.whl dist/local_ai_workspace-X.Y.Z.tar.gz \
  --title "vX.Y.Z" --notes-file <(sed -n '/## \[X.Y.Z\]/,/## \[/p' CHANGELOG.md)
```
