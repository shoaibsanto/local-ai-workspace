# Architecture

## Overview

```
┌─────────────────────────────────────────────────────────┐
│  Browser (React + Vite, served by the Python backend)   │
│  Sidebar / Chat / Composer / Settings / MCP modals       │
└───────────────────────┬───────────────────────────────────┘
                         │ REST + SSE over localhost
┌───────────────────────▼───────────────────────────────────┐
│  FastAPI app (src/local_ai_workspace/api/app.py)          │
│  - conversations, providers, mcp CRUD                     │
│  - /chat SSE streaming endpoint                            │
├─────────────────────────────────────────────────────────┤
│  ChatOrchestrator (core/chat.py)                           │
│  - context compaction                                       │
│  - agent loop: model -> tool_calls -> MCP exec -> model    │
├───────────────┬───────────────────────┬───────────────────┤
│ Provider client│   MCPManager          │  Storage layer     │
│ (providers/)   │   (mcp/manager.py)    │  (storage/)        │
│ - OpenAI-compat│   - stdio/SSE/HTTP    │  - JSON/JSONL files │
│ - Anthropic    │   - OAuth flow        │  - Fernet secrets   │
└───────────────┴───────────────────────┴───────────────────┘
```

## Why these choices

**Filesystem persistence, not a database.** Conversations are
`conversations/<id>/{meta.json, messages.jsonl}`. JSONL is append-only, so a
crash mid-write loses at most the last line, never the whole file. No schema
migrations, no connection pool, no lock contention — a chat app for one user
doesn't need them. `platformdirs` picks the correct OS-specific data
directory automatically.

**Secrets encrypted with a machine-local Fernet key.** `storage/secrets.py`
generates a random key on first run, stored with 0600 permissions, and
encrypts a JSON blob of secrets at `secrets.enc`. This protects against
casual disk inspection and accidental git-commits of config files; it does
**not** protect against an attacker with root/your-user access to the
machine while it's running (no OS keychain integration yet — see Roadmap).

**One provider abstraction, two implementations today.**
`providers/client.py` defines `StreamEvent` as the universal wire format the
orchestrator speaks. `OpenAICompatibleClient` covers the overwhelming
majority of real "custom endpoint" providers (OpenRouter, Ollama, LM Studio,
vLLM, Together, Groq, etc. all speak this protocol). `AnthropicClient`
exists because Anthropic's Messages API has a genuinely different wire
shape. Adding a third provider kind means writing one new class satisfying
the same `stream()` interface — the orchestrator never changes.

**Native MCP OAuth via the official SDK, not a custom reimplementation.**
`mcp.client.auth.OAuthClientProvider` already implements OAuth 2.1 + PKCE +
dynamic client registration correctly. We only provide the two things it
needs from a desktop app: a `redirect_handler` (open the system browser) and
a `TokenStorage` (encrypt-on-disk instead of the SDK's in-memory default).
See `mcp/oauth_flow.py` (loopback callback server) and
`mcp/oauth_storage.py` (encrypted token storage adapter).

**Context compaction is a token-budget heuristic, not a summarizer.**
`core/chat._compact_messages` estimates tokens at 4 chars/token and drops
the oldest non-system messages when a conversation would exceed budget,
always preserving the system prompt and the live exchange. This is
deliberately dumb: an LLM-based summarizer that silently drops or distorts
facts is worse than an honest truncation notice. If/when this needs to be
smarter (e.g. per-provider tokenizers, semantic compaction), it's a single
function to replace.

## Request lifecycle for a chat turn

1. Frontend calls `POST /api/conversations/{id}/chat` with the new message.
2. `ChatOrchestrator.run_turn` persists the user message immediately (so a
   crash mid-generation never loses what the user typed).
3. History is loaded, converted to wire format, compacted if needed.
4. MCP tools from all connected servers are gathered as OpenAI function
   schemas and passed to the provider client.
5. The provider streams text deltas and/or tool call requests over SSE to
   the frontend in near-real-time.
6. If the model requested tool calls, `MCPManager.call_tool` executes them
   against the right connected server and the results are fed back to the
   model — looping (max 8 iterations) until the model stops requesting
   tools.
7. Every assistant/tool message is persisted as it completes.

## Roadmap / known limitations

- No OS keychain integration (Keychain/Credential Manager/libsecret) for
  secrets — currently a single Fernet key file. Worth adding via `keyring`
  for defense-in-depth.
- Context compaction uses a character heuristic, not real tokenizers.
- No conversation export/import yet (trivial given the JSONL format).
- Projects/workspaces API exists but has minimal UI.
- Frontend has one JS chunk (~1MB) — fine for a local app, but could be
  code-split if it matters.
