# Local AI Workspace

A local-first, Claude-inspired AI chat workspace. Runs entirely on your own
machine — no cloud backend, no mandatory account, no external database.
Bring your own LLM provider (OpenRouter, Anthropic, a self-hosted
OpenAI-compatible endpoint, Ollama, etc.) and your own MCP servers.

## Status

Early MVP. Core chat loop, filesystem persistence, OpenAI-compatible +
Anthropic providers, and native MCP (stdio + OAuth-capable remote servers)
are implemented and working. UI is a minimal Claude-inspired React app.

## Why local-first

- Your conversations live in plain JSON/JSONL files on your disk, under your
  OS's standard app-data directory. Nothing is uploaded anywhere by this app.
- No database server, no Docker Compose, no signup page.
- You supply your own API keys for whichever LLM provider you want; this
  project doesn't proxy, meter, or see your traffic.

## Install

```bash
pip install -e .
local-ai serve
```

This starts a server on `http://127.0.0.1:8420` (local-only by default) and
opens it in your browser.

## Configuration

On first run, three default provider entries are created (OpenRouter,
Anthropic, local Ollama) but disabled until you add an API key through the
Settings panel. API keys and MCP OAuth tokens are encrypted at rest with a
machine-local key (`cryptography`'s Fernet) — see
`src/local_ai_workspace/storage/secrets.py` for exactly what that does and
does not protect against.

Data directory:

```bash
local-ai data-dir
```

## MCP servers

Add stdio-based MCP servers (most local tool servers) or remote
SSE/streamable-HTTP servers. For servers requiring OAuth, the app drives the
standard OAuth 2.1 + PKCE flow via a one-shot local callback server and
opens your browser — the same pattern as `gh auth login` or `gcloud auth
login`. Tokens are stored encrypted, never sent anywhere but the MCP server
itself.

## Development

Backend:

```bash
source .venv/bin/activate
uv pip install -e ".[dev]"
uvicorn local_ai_workspace.api.app:create_app --factory --reload
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

## License

MIT
