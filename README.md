# Local AI Workspace

A local-first, Claude-inspired AI chat workspace. Runs entirely on your own
machine — no cloud backend, no mandatory account, no external database, no
telemetry. Bring your own LLM provider (OpenRouter, Anthropic, Gemini, a
self-hosted OpenAI-compatible endpoint, Ollama, etc.) and your own MCP
servers, with native MCP OAuth support.

## What it does

- A browser-based chat UI on `localhost`, styled after Claude Desktop/Web,
  running against a local Python backend — nothing leaves your machine except
  the exact requests you make to a provider or MCP server you configured.
- Multiple custom LLM providers with custom base URLs, API keys, headers,
  timeouts, and capability flags (streaming, tool calling, vision, structured
  output) — OpenAI-compatible, Anthropic, and Gemini out of the box.
- Native MCP (Model Context Protocol) integration: connect by URL only,
  automatic transport detection (`streamable_http` preferred, `sse`
  fallback), automatic OAuth discovery and authorization (OAuth 2.1 + PKCE),
  per-tool enable/disable, and a configurable tool-approval policy so
  consequential actions (delete, send, publish, purchase, etc.) require your
  explicit sign-off before they run.
- Filesystem-only persistence: conversations, providers, MCP configs, and
  secrets all live as JSON/JSONL files under your OS's standard app-data
  directory. No SQLite, no Postgres, no ORM.
- Intelligent context compaction: once a conversation approaches a model's
  context window, the app maintains an incrementally updated structured
  summary (facts, decisions, pending tasks) layered on top of a cheap
  truncation safety net — your original message history is never deleted.
- Conversation export/import and full data backup/restore, all local.

## Architecture

```
┌─────────────────────────────┐
│   Browser (React + Vite)    │  served by the backend after `npm run build`
└──────────────┬──────────────┘
               │ REST + SSE, same-origin only (127.0.0.1)
┌──────────────▼──────────────┐
│   FastAPI backend (uvicorn)  │
│  ┌────────────────────────┐ │
│  │ core/chat.py            │ │  agent loop: provider stream + MCP tools
│  │ core/approval.py        │ │  tool-approval policy engine
│  │ core/compaction.py      │ │  context summarization
│  │ core/ssrf_guard.py      │ │  outbound URL validation
│  ├────────────────────────┤ │
│  │ providers/*.py          │ │  OpenAI-compatible / Anthropic / Gemini
│  │ mcp/manager.py          │ │  MCP sessions, OAuth, tool discovery
│  ├────────────────────────┤ │
│  │ storage/*.py             │ │  JSON/JSONL files, Fernet-encrypted secrets
│  └────────────────────────┘ │
└──────────────┬──────────────┘
               │ filesystem only
┌──────────────▼──────────────┐
│  ~/.local/share/local-ai-    │  (platformdirs; override via
│  workspace/ (or similar)     │   LOCAL_AI_WORKSPACE_HOME or `local-ai config`)
│   conversations/ providers   │
│   mcp_servers/ secrets/      │
│   backups/ logs/             │
└───────────────────────────────┘
```

See `docs/ARCHITECTURE.md` for more detail.

## Screenshots

_(placeholder — add screenshots of the chat UI, settings modal, and MCP
connection flow here once captured)_

## Installation

```bash
git clone https://github.com/shoaibsanto/local-ai-workspace.git
cd local-ai-workspace
uv venv .venv
source .venv/bin/activate
uv pip install -e ".[dev]"
```

The frontend ships pre-built inside the package for a normal install; if
you're building from source you need Node once to produce it (see
*Development setup* below) — end users installing a published release do
**not** need Node or npm.

## Running the application

```bash
local-ai serve
```

This starts the server on `http://127.0.0.1:8420` by default (configurable
with `--port`), opens your default browser, and serves the app from there.
Use `--no-browser` to skip auto-opening a tab (useful on a headless/remote
box where you forward the port yourself).

```bash
local-ai data-dir          # print the active data directory
local-ai config get/set    # view or override the data root persistently
```

## Configuring your first AI model

1. Open Settings (left sidebar, gear icon).
2. Three disabled default providers are pre-seeded: OpenRouter, Anthropic,
   and a local Ollama entry. Pick one, paste in your API key (or point the
   base URL at a local server), and enable it.
3. Click **Test Connection** to confirm it works before chatting.

## Adding custom API endpoints

Any OpenAI-compatible endpoint (vLLM, LM Studio, Ollama, a custom proxy) can
be added as a new provider: set its base URL, model ID(s), and an API key if
required. If the endpoint is on your local machine (e.g.
`http://localhost:11434/v1`), mark it `allow_local` so the SSRF guard doesn't
reject it — see *Security and privacy* below for why that guard exists.

## Connecting MCP servers

1. Open the MCP panel and click **Add MCP Server**.
2. Enter just a name and the server's URL, then **Connect**.
3. The app auto-detects the transport (`streamable_http` first, `sse`
   fallback) and checks whether the server requires OAuth by looking for its
   Protected Resource Metadata / Authorization Server Metadata per the MCP
   auth spec.
4. If OAuth is required, your browser opens to the server's login page.
   After you approve access, the app captures the redirect on a local
   loopback listener, exchanges the code, and stores the token encrypted.
5. Discovered tools appear in the panel — enable/disable individual tools as
   needed.

### OAuth authorization

- Implements Authorization Code + PKCE (S256), state validation, exact
  redirect URI matching, and automatic token refresh with expiry tracking.
- **Reauthorize** clears the stored token and re-runs the flow.
- **Revoke credentials** deletes the stored token without removing the
  server configuration.
- Tokens are strictly isolated per server — a token for server A is never
  readable or usable when talking to server B (see `tests/test_mcp_oauth.py`).

## Managing tool permissions

By default, read-only-looking tools (list/search/read/get) are
auto-approved and anything that looks consequential (delete/send/
publish/purchase/write/modify/execute/drop, heuristically detected) pauses
the conversation and asks you to approve or reject it before it runs — shown
with the server name, tool name, description, and arguments. You can change
the default mode (`auto_approve_readonly` / `always_ask` / `auto_approve_all`)
or override individual tools in Settings. This is a heuristic safeguard, not
a guarantee — review what a new MCP server's tools actually do.

## Local data storage

Everything lives under one data directory (platformdirs default, or your own
via `LOCAL_AI_WORKSPACE_HOME` / `local-ai config set`):

```
config/            settings.json, providers.json, mcp_servers.json
conversations/<id>/  meta.json, messages.jsonl, summary.md, context.json
credentials/        encrypted secrets (API keys, OAuth tokens)
backups/            timestamped full-data-dir zip backups
logs/               application.log (secrets redacted)
```

Nothing here is synced anywhere by default. Conversations persist across
restarts; corrupted individual files are skipped with a warning rather than
crashing the app.

## Context compaction

When a conversation's estimated token usage crosses ~75% of the active
model's context window, the app asks the model to produce or update a
structured summary (user instructions, decisions, pending tasks, tool
results of note) and uses that plus the most recent messages for the next
turn — your full original `messages.jsonl` is never deleted or rewritten.
You can trigger compaction manually, view the current summary, or confirm
the full original history is still intact, all from the conversation menu.

## Export and backup

- **Export a conversation** to a single JSON file and **import** it back in
  (always as a new conversation, never overwriting an existing one).
- **Backup** zips your entire data directory to `backups/` with a timestamp;
  **restore** extracts it back (with zip-slip protection).
- **Wipe all data** is available but requires an explicit confirmation flag
  — it will never run accidentally.

```bash
local-ai backup
local-ai restore <path-to-backup.zip>
local-ai export <conversation-id> <output.json>
local-ai wipe --confirm
```

## Security and privacy

- Binds to `127.0.0.1` only; never exposed to your network by default.
- No telemetry, no analytics, no mandatory account.
- API keys and OAuth tokens encrypted at rest (Fernet), with the master key
  stored in your OS keychain when available, falling back to a
  file-permission-protected local key otherwise.
- SSRF guard on every outbound provider/MCP request: resolves DNS and blocks
  private/link-local/cloud-metadata IPs unless you explicitly flag an
  endpoint as local.
- Origin-checking middleware blocks cross-origin requests to the local API
  (mitigates DNS rebinding / malicious-website attacks against localhost
  services).
- Logs are redacted for anything that looks like a secret before being
  written to disk.

See `SECURITY.md` for the full threat model and known limitations.

## Troubleshooting

- **Port already in use**: pass `--port` to `local-ai serve` to pick a
  different one.
- **Provider test fails with a network error**: check the base URL and that
  it's reachable from this machine; if it's a local model server, make sure
  `allow_local` is set on that provider.
- **MCP server stuck on "needs_auth"**: click **Authorize** again — it
  reopens the browser flow. If it keeps failing, use **Revoke credentials**
  then **Connect** to start clean.
- **Corrupted conversation file**: the app skips malformed lines/files with
  a warning in `logs/application.log` rather than crashing; check that log
  for details.

## Development setup

```bash
cd local-ai-workspace
uv venv .venv && source .venv/bin/activate
uv pip install -e ".[dev]"

cd frontend
npm install
npm run build
cd ..
rm -rf src/local_ai_workspace/static
cp -r frontend/dist src/local_ai_workspace/static
```

Run tests:

```bash
python -m pytest tests/ -v
```

Run the frontend in dev mode (hot reload, proxies `/api` to the backend):

```bash
# terminal 1
LOCAL_AI_WORKSPACE_HOME=/tmp/lai-dev local-ai serve --no-browser --port 8421
# terminal 2
cd frontend && npm run dev
```

## Contribution guidelines

See `CONTRIBUTING.md`.

## License

MIT — see `LICENSE`.
