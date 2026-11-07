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

Production-hardening release. First stable (non-pre-1.0) release, genuinely
`pip install`-able outside the dev environment. Backend: 87/87 tests
passing, `ruff check`/`ruff format --check` clean, `mypy` clean (32 source
files, 0 issues). CI green on GitHub Actions for both Python 3.11/3.12 and
the frontend build.

### Added
- CI/CD pipeline (`.github/workflows/ci.yml`): GitHub Actions matrix across
  Python 3.11/3.12 running pytest, ruff lint, ruff format check, and mypy;
  a separate Node 20 job running `tsc --noEmit` and `npm run build`.
- Static analysis: ruff linting + formatting and mypy type checking wired
  into `pyproject.toml`, documented strictness tradeoffs (e.g. why FastAPI
  route handlers are exempt from `disallow_untyped_defs`, why the MCP SDK
  is treated as untyped).
- `local-ai doctor` CLI diagnostics: checks Python version, data directory
  writability, bundled frontend presence, port availability, and secrets
  master key loadability, with PASS/WARN/FAIL output and a non-zero exit
  on any FAIL.
- `local-ai --version`, reading the installed version from package
  metadata via `importlib.metadata.version("local-ai-workspace")` so there
  is a single source of truth (the `[project].version` field in
  `pyproject.toml`) instead of a duplicated `__version__` string.
- Global exception handling (`api/app.py`): any unhandled exception returns
  a generic `{"error": "internal_error", "request_id": ...}` 500 instead of
  leaking a stack trace or file path; the full traceback is still logged
  server-side (through the redaction-aware logger) keyed by request id.
  Deliberate `HTTPException`s (404s, validation errors) keep their normal
  status/detail but also carry the request id.
- Request-id correlation: every request gets a UUID, returned as an
  `X-Request-Id` response header and attached to every log record emitted
  while handling it (`core/logging_setup.py`'s `RequestIdFilter`), via a
  `contextvars.ContextVar` so deeply-nested storage/provider/MCP code can
  log with request context without threading a parameter everywhere.
- Request size limits: request bodies over 10MB (configurable via
  `MAX_REQUEST_BODY_BYTES`) are rejected with a clean 413, checked via
  `Content-Length` up front and a streaming byte-count backstop for
  chunked bodies with no declared length.
- Chat rate limiting (`core/rate_limit.py`): an in-memory sliding-window
  limiter applied specifically to `POST .../chat` and `.../resume` (not
  every endpoint), scoped per-conversation, configurable via
  `settings.chat_rate_limit_per_minute` (default 20/min), returning 429
  with a clear message when exceeded.
- Startup validation (`core/startup_checks.py`): before `local-ai serve`
  accepts traffic, it verifies the data directory is writable, the
  secrets master key is loadable, and the configured port is free,
  failing fast with an actionable error instead of starting broken.
- Concurrency-safe storage: per-resource locks (keyed by conversation id
  or settings file path) held for the whole read-modify-write sequence in
  `storage/json_store.py` / `storage/conversation_store.py` /
  `storage/settings_store.py`, verified by a test firing 50 concurrent
  `add_message` calls at the same conversation with zero lost messages.
- Dependency pin ranges tightened from unbounded `>=X` to `>=X,<NEXT_MAJOR`
  across `pyproject.toml`, documented inline per package.
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
- Frontend code-splitting: `React.lazy` + `Suspense` for all modal
  components and the syntax-highlighter-heavy `CodeBlock`, shrinking the
  main entry chunk from ~1.1MB to 445KB (gzip: 367KB -> 136KB), with the
  syntax highlighter isolated into its own lazily-loaded chunk.
- React error boundaries: an app-level `ErrorBoundary` (Reload button,
  dev-only stack trace) and a narrower one around message rendering so a
  single malformed AI response can't blank-screen the whole app.
- Frontend: dark/light theme with OS-preference default, responsive
  mobile layout (off-canvas sidebar drawer), keyboard shortcuts (command
  palette, new chat, shortcuts help), loading/empty states, accessible
  modals with focus trapping and `aria-live` streaming announcements, a
  tool-approval modal, and MCP OAuth status/reauthorize UI.
- Playwright smoke test (`frontend/e2e/smoke.spec.ts`) asserting the built
  app loads, the composer is visible, and a lazy-loaded modal open/close
  (shortcuts help) completes with zero console errors.

### Fixed
- `StreamEvent.usage` was typed as `dict[str, int]`, which crashed the SSE
  response mid-stream (after text had already been sent to the client, but
  before the assistant message was persisted) whenever a provider returned
  nested usage detail objects (observed with OpenRouter's
  `prompt_tokens_details` / `completion_tokens_details` / `cost_details`).
  Widened to `dict[str, Any]`. Found via a real wheel-installed end-to-end
  LLM smoke test, not a unit test.
- `.gitignore`'s bare `lib/` rule was unintentionally also matching
  `frontend/src/lib/`, so `api.ts`, `theme.ts`, and `utils.ts` were never
  committed to git -- they only existed in local working trees. Scoped the
  rule to `/lib/` (repo root only) and committed the previously-untracked
  files.
- CI's `uv` setup had `enable-cache: true` with no `uv.lock` committed
  (this project intentionally uses plain `>=X,<Y` ranges, not a locked
  resolution), which made the cache step fail outright. Removed the cache
  flag.

### Changed
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
- The wheel installs cleanly (non-editable, plain `pip install`) into a
  brand-new virtualenv with no other local-ai-workspace install present;
  `local-ai --version` reports `local-ai-workspace 1.0.0`; `local-ai
  doctor` reports all-PASS.
- The wheel-installed `local-ai serve --no-browser` binds, serves the real
  bundled frontend `index.html` at `/`, reports `{"status":"ok"}` at
  `/api/health`, and lists the three seeded default providers at
  `/api/providers`.
- One real end-to-end LLM round trip through the wheel-installed server:
  set an OpenRouter API key via `/api/providers/{id}/api_key`, created a
  conversation against a free-tier OpenRouter model
  (`nvidia/nemotron-3.5-lightning:free`), sent a prompt asking for an exact
  phrase, and confirmed the SSE stream delivered and persisted the exact
  text `PRODUCTION RELEASE TEST OK` to the conversation's message history
  on disk.
- Live security behaviors on a running wheel-installed server: SSRF guard
  blocks a real outbound request to a cloud-metadata-style address;
  Origin/CSRF middleware blocks a cross-origin POST while allowing a
  local-origin one; `POST /api/admin/wipe` refuses without `confirm: true`;
  every response carries a unique `X-Request-Id` header; a forced
  unhandled exception returns `{"error": "internal_error", "request_id":
  ...}` with no stack trace or file path in the response body.
- Graceful shutdown: sending `SIGTERM` to a running `local-ai serve`
  process produces a clean `Application shutdown complete` / `Finished
  server process` log sequence with no `asyncio` "Task was destroyed but
  it is pending" warnings.
- CI green on GitHub Actions for this exact `main` HEAD: Backend (py3.11),
  Backend (py3.12), and Frontend (node 20) jobs all passing.

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
