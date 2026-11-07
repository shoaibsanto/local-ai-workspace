# Contributing

Thanks for considering a contribution to local-ai-workspace.

## Development setup

```bash
git clone https://github.com/shoaibsanto/local-ai-workspace.git
cd local-ai-workspace
uv venv .venv
source .venv/bin/activate
uv pip install -e ".[dev]"

cd frontend
npm install
npm run build
cd ..
rm -rf src/local_ai_workspace/static
cp -r frontend/dist src/local_ai_workspace/static
```

Run the dev servers separately while iterating on the UI:

```bash
# terminal 1 — backend
source .venv/bin/activate
LOCAL_AI_WORKSPACE_HOME=/tmp/lai-dev local-ai serve --no-browser --port 8421

# terminal 2 — frontend (proxies /api to :8421, see vite.config.ts)
cd frontend && npm run dev
```

## Before opening a PR

Run the full check suite and make sure everything is green — don't open a PR
with known-failing checks:

```bash
source .venv/bin/activate
python -m pytest tests/ -v

cd frontend
npx tsc --noEmit -p tsconfig.app.json
npm run build
```

## Code style

- Backend: typed Python, Pydantic models for all persisted/wire shapes, async
  where the rest of the codebase is async. Prefer small, focused modules
  (see `core/`, `storage/`, `providers/`, `mcp/`) over one large file.
- Frontend: TypeScript strict mode, functional components, Tailwind v4
  utility classes (no CSS-in-JS). Keep accessibility (aria labels, focus
  traps, keyboard nav) in mind for anything interactive — see
  `frontend/ACCESSIBILITY_NOTES.md` for the baseline this project targets.
- Document non-obvious design decisions with a short comment or module
  docstring explaining the "why", not just the "what" — this keeps the
  codebase legible for future contributors (and future you).

## Filing issues

Please include: your OS, Python version, Node version (if frontend-related),
the exact command you ran, and the full error output. For security issues,
see `SECURITY.md` instead of a public issue.

## License

By contributing, you agree your contributions are licensed under the
project's MIT license (see `LICENSE`).
