export interface ToolCall {
  id: string
  name: string
  arguments: Record<string, unknown>
}

export interface ToolResult {
  tool_call_id: string
  name: string
  content: string
  is_error: boolean
}

export interface Message {
  id: string
  role: 'user' | 'assistant' | 'system' | 'tool'
  content: string
  tool_calls: ToolCall[]
  tool_results: ToolResult[]
  created_at: number
  model?: string | null
  provider?: string | null
  error?: string | null
}

export interface ConversationMeta {
  id: string
  title: string
  project_id: string | null
  model: string | null
  provider: string | null
  created_at: number
  updated_at: number
  pinned: boolean
  message_count: number
}

export interface ProviderConfig {
  id: string
  name: string
  base_url: string
  api_key_ref: string | null
  default_model: string | null
  models: string[]
  kind: 'openai_compatible' | 'anthropic'
  enabled: boolean
}

export interface MCPServerConfig {
  id: string
  name: string
  transport: 'stdio' | 'sse' | 'streamable_http'
  command: string | null
  args: string[]
  env: Record<string, string>
  url: string | null
  requires_oauth: boolean
  enabled: boolean
  status: 'disconnected' | 'connecting' | 'connected' | 'error' | 'needs_auth'
  last_error: string | null
  tool_count: number
}

export type ChatEvent =
  | { type: 'user_message'; message: Message }
  | { type: 'assistant_message'; message: Message }
  | { type: 'text_delta'; text: string }
  | { type: 'tool_call_requested'; tool_call: ToolCall }
  | { type: 'tool_executing'; tool_call: ToolCall }
  | { type: 'tool_result'; tool_result: ToolResult }
  | { type: 'approval_required'; tool_call: ToolCall; server_name: string; risk_level: string }
  | { type: 'error'; error: string }
  | { type: 'turn_complete' }

const BASE = ''

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
  })
  if (!resp.ok) {
    const text = await resp.text()
    throw new Error(`${resp.status}: ${text}`)
  }
  return resp.json()
}

export const api = {
  listConversations: (projectId?: string) =>
    json<ConversationMeta[]>(`/api/conversations${projectId ? `?project_id=${projectId}` : ''}`),
  createConversation: (body: { title?: string; project_id?: string; model?: string; provider?: string }) =>
    json<ConversationMeta>('/api/conversations', { method: 'POST', body: JSON.stringify(body) }),
  getConversation: (id: string) =>
    json<{ meta: ConversationMeta; messages: Message[] }>(`/api/conversations/${id}`),
  updateConversation: (id: string, body: Partial<Pick<ConversationMeta, 'title' | 'pinned' | 'model' | 'provider'>>) =>
    json<ConversationMeta>(`/api/conversations/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  deleteConversation: (id: string) =>
    json<{ ok: boolean }>(`/api/conversations/${id}`, { method: 'DELETE' }),
  searchConversations: (q: string) =>
    json<ConversationMeta[]>(`/api/conversations/search?q=${encodeURIComponent(q)}`),
  regenerate: (id: string) =>
    json<{ ok: boolean; resend_content: string }>(`/api/conversations/${id}/regenerate`, { method: 'POST' }),
  editResend: (id: string, message_index: number, new_content: string) =>
    json<{ ok: boolean }>(`/api/conversations/${id}/edit_resend`, {
      method: 'POST',
      body: JSON.stringify({ message_index, new_content }),
    }),

  listProviders: () => json<ProviderConfig[]>('/api/providers'),
  createProvider: (body: Partial<ProviderConfig>) =>
    json<ProviderConfig>('/api/providers', { method: 'POST', body: JSON.stringify(body) }),
  setProviderKey: (id: string, api_key: string) =>
    json<ProviderConfig>(`/api/providers/${id}/api_key`, { method: 'PUT', body: JSON.stringify({ api_key }) }),
  deleteProvider: (id: string) => json<{ ok: boolean }>(`/api/providers/${id}`, { method: 'DELETE' }),

  listMcpServers: () => json<MCPServerConfig[]>('/api/mcp/servers'),
  createMcpServer: (body: Partial<MCPServerConfig>) =>
    json<MCPServerConfig>('/api/mcp/servers', { method: 'POST', body: JSON.stringify(body) }),
  connectMcpServer: (id: string) =>
    json<MCPServerConfig>(`/api/mcp/servers/${id}/connect`, { method: 'POST' }),
  disconnectMcpServer: (id: string) =>
    json<MCPServerConfig>(`/api/mcp/servers/${id}/disconnect`, { method: 'POST' }),
  deleteMcpServer: (id: string) => json<{ ok: boolean }>(`/api/mcp/servers/${id}`, { method: 'DELETE' }),
  listMcpTools: () => json<unknown[]>('/api/mcp/tools'),
  // NOTE: backend endpoint for reauthorize may not exist yet (built by a concurrent workstream).
  reauthorizeMcpServer: (id: string) =>
    json<MCPServerConfig>(`/api/mcp/servers/${id}/reauthorize`, { method: 'POST' }),

  // NOTE: backend endpoint for tool-call approval may not exist yet (built by a concurrent workstream).
  approveToolCall: (conversationId: string, toolCallId: string, approved: boolean) =>
    json<{ ok: boolean }>(`/api/conversations/${conversationId}/tool_calls/${toolCallId}/approve`, {
      method: 'POST',
      body: JSON.stringify({ approved }),
    }),
}

export async function* streamChat(conversationId: string, content: string, signal?: AbortSignal): AsyncGenerator<ChatEvent> {
  const resp = await fetch(`${BASE}/api/conversations/${conversationId}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content }),
    signal,
  })
  if (!resp.ok || !resp.body) {
    const text = resp.body ? await resp.text() : 'No response body'
    throw new Error(`Chat request failed: ${resp.status} ${text}`)
  }
  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const parts = buffer.split('\n\n')
    buffer = parts.pop() ?? ''
    for (const part of parts) {
      const line = part.trim()
      if (!line.startsWith('data:')) continue
      const data = line.slice(5).trim()
      if (data === '[DONE]') return
      try {
        yield JSON.parse(data) as ChatEvent
      } catch {
        // ignore malformed SSE fragment
      }
    }
  }
}
