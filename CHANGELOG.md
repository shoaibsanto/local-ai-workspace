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
