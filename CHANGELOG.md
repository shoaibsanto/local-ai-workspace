# Changelog

All notable changes to this project are documented here.
This project does not yet follow strict SemVer release cadence; it is
pre-1.0 and under active development.

## [Unreleased]

### Added
- Gemini provider adapter (`providers/gemini.py`) with streaming, message
  format conversion, and model listing.
- Provider capability detection (`providers/capabilities.py`) and a
  test-connection endpoint for diagnosing provider setup issues.
- MCP OAuth hardening: `streamable_http`-first auto-connect with SSE
  fallback, automatic OAuth discovery via the MCP auth spec's protected
  resource / authorization server metadata, token expiry + refresh
  lifecycle, reauthorize/revoke endpoints, per-tool enable/disable, and
  strict per-server token isolation.
- Tool approval policy engine (`core/approval.py`): configurable
  auto-approve-readonly / always-ask / auto-approve-all modes with
  per-tool overrides, heuristic risk classification, a pausable/resumable
  agent loop driven by `approval_required` SSE events persisted to disk,
  and an untrusted-content marker wrapped around tool results fed back to
  the model.
- Context compaction (`core/compaction.py`): structured, incrementally
  updated conversation summaries (`summary.md` + `context.json`) layered
  on top of the existing cheap truncation safety net, with a timeout and
  defensive fallback on parse failure. Original `messages.jsonl` is never
  modified.
- Storage hardening: configurable data directory, backup/restore
  (zip-slip-safe), conversation export/import, corrupted-JSONL tolerance,
  OS keyring integration for the secrets master key, log redaction, and a
  rotating application log file.
- Security hardening: SSRF guard for outbound provider/MCP URLs (DNS
  resolution + private/link-local/cloud-metadata IP blocking, with an
  explicit `allow_local` opt-out for local model endpoints), Origin/CSRF
  middleware restricting non-GET requests to localhost/127.0.0.1 origins,
  and a confirm-gated admin "wipe all data" endpoint/CLI command.
- Frontend: dark/light theme with OS-preference default, responsive
  mobile layout (off-canvas sidebar drawer), keyboard shortcuts (command
  palette, new chat, shortcuts help), loading/empty states, accessible
  modals with focus trapping and `aria-live` streaming announcements, a
  tool-approval modal, and MCP OAuth status/reauthorize UI.

## [1.0.0] - 2026-11-07

Production-hardening release. First stable (non-pre-1.0) release, intended
to be genuinely `pip install`-able outside the dev environment. Consolidates
work from several concurrent hardening passes landed around the same time;
exact item attribution may need a follow-up edit once all changes are
reconciled.

### Added
- CI/CD pipeline (lint/type-check/test on PRs; see `tool.ruff` / `tool.mypy`
  config in `pyproject.toml`).
- Static analysis: ruff linting + formatting and mypy type checking wired
  into `pyproject.toml` with project-appropriate strictness.
- `local-ai doctor`-style diagnostics tooling in the CLI for verifying a
  local install/environment.
- `local-ai --version`, reading the installed version from package
  metadata via `importlib.metadata.version("local-ai-workspace")` so there
  is a single source of truth (the `[project].version` field in
  `pyproject.toml`) instead of a duplicated `__version__` string.
- Global error handling / request-id wiring in the API layer for clearer
  production diagnostics.
- Graceful shutdown handling for the `local-ai serve` process.
- Concurrency-safe storage access for the JSON/JSONL filesystem backend.
- Basic rate limiting on API endpoints.
- Frontend code-splitting and React error boundaries to avoid a single
  blank-screen failure mode.

### Fixed
- `StreamEvent.usage` was typed as `dict[str, int]`, which crashed the SSE
  response mid-stream (after text had already been sent to the client, but
  before the assistant message was persisted) whenever a provider returned
  nested usage detail objects (observed with OpenRouter's
  `prompt_tokens_details` / `completion_tokens_details` / `cost_details`).
  Widened to `dict[str, Any]`. Found via a real wheel-installed end-to-end
  LLM smoke test, not a unit test — see Verified section.

### Changed
- Dependency pin ranges tightened in `pyproject.toml` for reproducible
  installs.
- `pyproject.toml` version bumped `0.1.0` -> `1.0.0`; classifier updated to
  `Development Status :: 5 - Production/Stable`.

### Verified
- Fresh `npm ci && npm run build` of `frontend/`, copied into
  `src/local_ai_workspace/static/`.
- `uv build` (sdist via `uv build --sdist`, wheel via `uv build --wheel`
  directly from the source tree — building the wheel from the sdist alone
  undercounts files because `static/` is gitignored and therefore absent
  from the sdist) produces `dist/local_ai_workspace-1.0.0-py3-none-any.whl`
  and `.tar.gz`, with `local_ai_workspace/static/**` confirmed present in
  the wheel's file listing.
- The wheel installs cleanly (non-editable) into a brand-new virtualenv
  with no other local-ai-workspace install present; `local-ai --version`
  reports `local-ai-workspace 1.0.0`.
- The wheel-installed `local-ai serve --no-browser` binds, serves the real
  bundled frontend `index.html` at `/`, reports `{"status":"ok"}` at
  `/api/health`, and lists the three seeded default providers at
  `/api/providers`.
- One real end-to-end LLM round trip through the wheel-installed server:
  set an OpenRouter API key via `/api/providers/{id}/api_key`, created a
  conversation against a free-tier OpenRouter model
  (`nvidia/nemotron-3.5-lightning:free`), sent a prompt asking for an exact
  phrase, and confirmed the SSE stream delivered and persisted the exact
  text `PRODUCTION WHEEL TEST OK` to the conversation's message history.

## [0.1.0] - Initial MVP

- FastAPI backend with filesystem-only persistence (JSON + JSONL), no
  database.
- OpenAI-compatible and Anthropic provider clients with SSE streaming.
- MCP client integration (stdio / SSE / streamable HTTP transports) with
  OAuth scaffolding.
- React + TypeScript + Vite + Tailwind v4 Claude-inspired chat UI:
  sidebar, conversation list, markdown rendering with syntax highlighting,
  provider and MCP settings modals.
- CLI (`local-ai serve`, `local-ai data-dir`) and Python packaging via
  `pyproject.toml` / hatchling, with the built frontend bundled into the
  installed package.
- 7 passing smoke tests; live end-to-end verification against an
  OpenRouter free-tier model.
