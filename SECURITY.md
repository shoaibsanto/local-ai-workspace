# Security Policy

local-ai-workspace is a local-first desktop application. Its threat model and
mitigations are summarized below.

## Design posture

- The backend binds to `127.0.0.1` only, by default, and is never intended to
  be exposed on a public network interface.
- There is no mandatory remote account, no telemetry, and no analytics.
  Conversation data never leaves your machine except to the AI provider you
  explicitly configure (and only when you send a message).
- API keys and OAuth tokens are encrypted at rest (Fernet / AES-128-CBC +
  HMAC) using a master key that is stored in your OS keychain when available
  (macOS Keychain, Windows Credential Manager, Linux Secret Service via
  `keyring`), falling back to a file with `0600` permissions outside the
  config tree if no OS keyring is available.
- Outbound requests to provider base URLs and MCP server URLs are checked by
  an SSRF guard (`core/ssrf_guard.py`) that resolves DNS and rejects private,
  link-local, and cloud-metadata IP ranges unless you explicitly mark an
  endpoint `allow_local` (for things like a local Ollama server).
- Cross-origin requests to the local API are rejected by an Origin-check
  middleware unless the Origin is `http(s)://127.0.0.1:*` or
  `http(s)://localhost:*` — this mitigates DNS-rebinding and malicious-website
  attacks against the local API.
- MCP tool output is treated as untrusted content: tool results are wrapped
  with an explicit boundary marker before being fed back to the model, as a
  mitigation (not a guarantee) against prompt injection via tool output.
- Consequential tool calls (delete/send/publish/purchase/etc., heuristically
  classified) require explicit user approval by default before execution.

## Known limitations

- The tool-risk classifier (`classify_tool_risk`) is a heuristic based on
  tool name/description keywords. It can misclassify a tool. Treat the
  default policy as a convenience, not a guarantee — review tool
  permissions for any MCP server you connect, especially ones you don't
  fully trust.
- The SSRF guard checks the resolved IP at connection time; it does not
  defend against a server that passes the initial check and later redirects
  or rebinds mid-connection for long-lived streaming responses.
- Full file-system access for "projects" is intentionally never automatic:
  the app only reads files and directories you explicitly select.

## Reporting a vulnerability

This is an individual open-source project. Please open a GitHub issue at
https://github.com/shoaibsanto/local-ai-workspace/issues marked
`security`, or contact the maintainer directly via the email in the commit
history, before public disclosure if the issue is serious (e.g. a remote
code execution path, a credential-exfiltration bug, or an SSRF bypass).
