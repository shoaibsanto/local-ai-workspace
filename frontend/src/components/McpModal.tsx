import { useEffect, useState } from 'react'
import { X, Plus, Plug, PlugZap, AlertTriangle, Trash2, RefreshCw, ShieldCheck, Inbox } from 'lucide-react'
import { api, type MCPServerConfig } from '../lib/api'
import { ModalShell } from './ModalShell'
import { Spinner } from './Spinner'

interface Props {
  onClose: () => void
}

export function McpModal({ onClose }: Props) {
  const [servers, setServers] = useState<MCPServerConfig[]>([])
  const [loading, setLoading] = useState(true)
  const [adding, setAdding] = useState(false)
  const [transport, setTransport] = useState<'stdio' | 'sse' | 'streamable_http'>('stdio')
  const [form, setForm] = useState({ name: '', command: '', args: '', url: '', requires_oauth: false })
  const [authorizing, setAuthorizing] = useState<string | null>(null)
  const [toast, setToast] = useState<string | null>(null)

  useEffect(() => {
    load()
  }, [])

  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => setToast(null), 5000)
    return () => clearTimeout(t)
  }, [toast])

  async function load() {
    setLoading(true)
    try {
      setServers(await api.listMcpServers())
    } finally {
      setLoading(false)
    }
  }

  async function addServer() {
    await api.createMcpServer({
      name: form.name,
      transport,
      command: transport === 'stdio' ? form.command : undefined,
      args: transport === 'stdio' ? form.args.split(' ').filter(Boolean) : [],
      url: transport !== 'stdio' ? form.url : undefined,
      requires_oauth: form.requires_oauth,
      enabled: true,
    })
    setAdding(false)
    setForm({ name: '', command: '', args: '', url: '', requires_oauth: false })
    load()
  }

  async function toggleConnect(s: MCPServerConfig) {
    if (s.status === 'connected') {
      await api.disconnectMcpServer(s.id)
    } else {
      await api.connectMcpServer(s.id)
    }
    load()
  }

  async function authorize(s: MCPServerConfig) {
    setAuthorizing(s.id)
    try {
      await api.reauthorizeMcpServer(s.id)
      setToast(`Check your browser to finish authorizing "${s.name}".`)
    } catch (e) {
      setToast(`Could not start authorization for "${s.name}". ${(e as Error).message}`)
    } finally {
      setAuthorizing(null)
      load()
    }
  }

  async function remove(id: string) {
    if (!confirm('Remove this MCP server?')) return
    await api.deleteMcpServer(id)
    load()
  }

  return (
    <ModalShell onClose={onClose} titleId="mcp-modal-title">
      <div className="flex items-center justify-between border-b border-neutral-200 px-5 py-3.5 dark:border-neutral-800">
        <h2 id="mcp-modal-title" className="text-base font-semibold text-neutral-900 dark:text-neutral-100">
          MCP Connections
        </h2>
        <button
          onClick={onClose}
          aria-label="Close MCP connections"
          className="flex h-10 w-10 items-center justify-center rounded-md transition-colors duration-150 hover:bg-neutral-100 dark:hover:bg-neutral-800"
        >
          <X size={18} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-5">
        <p className="mb-4 text-sm text-neutral-500 dark:text-neutral-400">
          Connect local (stdio) or remote (SSE / streamable HTTP) MCP servers. Remote servers requiring OAuth will
          open your browser to authorize — tokens are stored encrypted on this machine.
        </p>

        {toast && (
          <div
            role="status"
            className="mb-4 flex items-center gap-2 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-700 dark:border-blue-900/50 dark:bg-blue-950/40 dark:text-blue-300"
          >
            <ShieldCheck size={16} className="shrink-0" /> {toast}
          </div>
        )}

        {loading ? (
          <div className="flex items-center justify-center gap-2 py-10 text-sm text-neutral-400">
            <Spinner size={18} /> Loading MCP servers…
          </div>
        ) : (
          <div className="space-y-2">
            {servers.map((s) => (
              <div
                key={s.id}
                className="flex flex-col gap-2 rounded-lg border border-neutral-200 p-3 transition-colors duration-150 sm:flex-row sm:items-center sm:justify-between dark:border-neutral-800"
              >
                <div className="flex items-center gap-3">
                  {s.status === 'connected' ? (
                    <PlugZap size={16} className="text-green-600 dark:text-green-400" />
                  ) : s.status === 'needs_auth' || s.status === 'error' ? (
                    <AlertTriangle size={16} className="text-amber-500" />
                  ) : (
                    <Plug size={16} className="text-neutral-300 dark:text-neutral-600" />
                  )}
                  <div>
                    <div className="text-sm font-medium text-neutral-900 dark:text-neutral-100">{s.name}</div>
                    <div className="text-xs text-neutral-400">
                      {s.transport} {s.status === 'connected' && `· ${s.tool_count} tools`}
                      {s.status === 'needs_auth' && <span className="text-amber-500"> · Needs authorization</span>}
                      {s.last_error && <span className="text-red-500 dark:text-red-400"> · {s.last_error.slice(0, 60)}</span>}
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-1">
                  {s.status === 'needs_auth' && (
                    <button
                      onClick={() => authorize(s)}
                      disabled={authorizing === s.id}
                      className="flex h-9 items-center gap-1 rounded-md bg-amber-500 px-2.5 text-xs font-medium text-white transition-colors duration-150 hover:bg-amber-600 disabled:opacity-60"
                    >
                      {authorizing === s.id ? <Spinner size={12} /> : <ShieldCheck size={12} />}
                      Authorize
                    </button>
                  )}
                  <button
                    onClick={() => toggleConnect(s)}
                    className="flex h-9 items-center gap-1 rounded-md px-2.5 text-xs font-medium transition-colors duration-150 hover:bg-neutral-100 dark:text-neutral-200 dark:hover:bg-neutral-800"
                  >
                    <RefreshCw size={12} />
                    {s.status === 'connected' ? 'Disconnect' : 'Connect'}
                  </button>
                  <button
                    onClick={() => remove(s.id)}
                    aria-label={`Remove server ${s.name}`}
                    className="flex h-9 w-9 items-center justify-center rounded-md text-neutral-400 transition-colors duration-150 hover:bg-neutral-100 dark:hover:bg-neutral-800"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
            ))}
            {servers.length === 0 && (
              <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-neutral-300 py-8 text-center dark:border-neutral-700">
                <Inbox size={24} className="text-neutral-300 dark:text-neutral-600" />
                <div className="text-sm font-medium text-neutral-600 dark:text-neutral-300">No MCP servers configured yet</div>
                <div className="max-w-xs text-xs text-neutral-400">
                  Connect a local or remote MCP server to give the assistant tools it can call during chat.
                </div>
                <button
                  onClick={() => setAdding(true)}
                  className="mt-2 flex h-10 items-center gap-1.5 rounded-lg bg-neutral-900 px-4 text-sm font-medium text-white transition-colors duration-150 hover:bg-neutral-700 dark:bg-white dark:text-neutral-900 dark:hover:bg-neutral-200"
                >
                  <Plus size={14} /> Add MCP server
                </button>
              </div>
            )}
          </div>
        )}

        {adding ? (
          <div className="mt-4 space-y-2 rounded-lg border border-neutral-200 p-3 dark:border-neutral-800">
            <label htmlFor="mcp-server-name" className="sr-only">
              Server name
            </label>
            <input
              id="mcp-server-name"
              placeholder="Server name"
              value={form.name}
              onChange={(e) => setForm((v) => ({ ...v, name: e.target.value }))}
              className="w-full rounded-md border border-neutral-200 px-2.5 py-2 text-sm text-neutral-900 outline-none dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-100"
            />
            <label htmlFor="mcp-transport" className="sr-only">
              Transport
            </label>
            <select
              id="mcp-transport"
              value={transport}
              onChange={(e) => setTransport(e.target.value as typeof transport)}
              className="w-full rounded-md border border-neutral-200 px-2.5 py-2 text-sm text-neutral-900 outline-none dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-100"
            >
              <option value="stdio">stdio (local command)</option>
              <option value="sse">SSE (remote)</option>
              <option value="streamable_http">Streamable HTTP (remote)</option>
            </select>
            {transport === 'stdio' ? (
              <>
                <label htmlFor="mcp-command" className="sr-only">
                  Command
                </label>
                <input
                  id="mcp-command"
                  placeholder="Command (e.g. npx)"
                  value={form.command}
                  onChange={(e) => setForm((v) => ({ ...v, command: e.target.value }))}
                  className="w-full rounded-md border border-neutral-200 px-2.5 py-2 text-sm text-neutral-900 outline-none dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-100"
                />
                <label htmlFor="mcp-args" className="sr-only">
                  Arguments
                </label>
                <input
                  id="mcp-args"
                  placeholder="Args (space-separated, e.g. -y @modelcontextprotocol/server-filesystem /path)"
                  value={form.args}
                  onChange={(e) => setForm((v) => ({ ...v, args: e.target.value }))}
                  className="w-full rounded-md border border-neutral-200 px-2.5 py-2 text-sm text-neutral-900 outline-none dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-100"
                />
              </>
            ) : (
              <>
                <label htmlFor="mcp-url" className="sr-only">
                  Server URL
                </label>
                <input
                  id="mcp-url"
                  placeholder="Server URL"
                  value={form.url}
                  onChange={(e) => setForm((v) => ({ ...v, url: e.target.value }))}
                  className="w-full rounded-md border border-neutral-200 px-2.5 py-2 text-sm text-neutral-900 outline-none dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-100"
                />
                <label className="flex items-center gap-2 text-sm text-neutral-600 dark:text-neutral-300">
                  <input
                    type="checkbox"
                    checked={form.requires_oauth}
                    onChange={(e) => setForm((v) => ({ ...v, requires_oauth: e.target.checked }))}
                    className="h-4 w-4"
                  />
                  Requires OAuth authorization
                </label>
              </>
            )}
            <div className="flex justify-end gap-2 pt-1">
              <button
                onClick={() => setAdding(false)}
                className="flex h-10 items-center rounded-md px-3 text-sm text-neutral-500 transition-colors duration-150 hover:bg-neutral-100 dark:text-neutral-400 dark:hover:bg-neutral-800"
              >
                Cancel
              </button>
              <button
                onClick={addServer}
                className="flex h-10 items-center rounded-md bg-neutral-900 px-3 text-sm text-white transition-colors duration-150 hover:bg-neutral-700 dark:bg-white dark:text-neutral-900 dark:hover:bg-neutral-200"
              >
                Add & Connect
              </button>
            </div>
          </div>
        ) : (
          servers.length > 0 && (
            <button
              onClick={() => setAdding(true)}
              className="mt-4 flex h-11 w-full items-center justify-center gap-1.5 rounded-lg border border-dashed border-neutral-300 text-sm text-neutral-500 transition-colors duration-150 hover:bg-neutral-50 dark:border-neutral-700 dark:text-neutral-400 dark:hover:bg-neutral-900"
            >
              <Plus size={14} /> Add MCP server
            </button>
          )
        )}
      </div>
    </ModalShell>
  )
}
