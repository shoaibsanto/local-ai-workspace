import { useEffect, useState } from 'react'
import { X, Plus, Plug, PlugZap, AlertTriangle, Trash2, RefreshCw } from 'lucide-react'
import { api, type MCPServerConfig } from '../lib/api'

interface Props {
  onClose: () => void
}

export function McpModal({ onClose }: Props) {
  const [servers, setServers] = useState<MCPServerConfig[]>([])
  const [adding, setAdding] = useState(false)
  const [transport, setTransport] = useState<'stdio' | 'sse' | 'streamable_http'>('stdio')
  const [form, setForm] = useState({ name: '', command: '', args: '', url: '', requires_oauth: false })

  useEffect(() => {
    load()
  }, [])

  async function load() {
    setServers(await api.listMcpServers())
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

  async function remove(id: string) {
    if (!confirm('Remove this MCP server?')) return
    await api.deleteMcpServer(id)
    load()
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30">
      <div className="flex max-h-[85vh] w-full max-w-2xl flex-col rounded-xl bg-white shadow-xl">
        <div className="flex items-center justify-between border-b border-neutral-200 px-5 py-3.5">
          <h2 className="text-base font-semibold">MCP Connections</h2>
          <button onClick={onClose} className="rounded-md p-1.5 hover:bg-neutral-100">
            <X size={18} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-5">
          <p className="mb-4 text-sm text-neutral-500">
            Connect local (stdio) or remote (SSE / streamable HTTP) MCP servers. Remote servers requiring OAuth will
            open your browser to authorize — tokens are stored encrypted on this machine.
          </p>

          <div className="space-y-2">
            {servers.map((s) => (
              <div key={s.id} className="flex items-center justify-between rounded-lg border border-neutral-200 p-3">
                <div className="flex items-center gap-3">
                  {s.status === 'connected' ? (
                    <PlugZap size={16} className="text-green-600" />
                  ) : s.status === 'needs_auth' || s.status === 'error' ? (
                    <AlertTriangle size={16} className="text-amber-500" />
                  ) : (
                    <Plug size={16} className="text-neutral-300" />
                  )}
                  <div>
                    <div className="text-sm font-medium">{s.name}</div>
                    <div className="text-xs text-neutral-400">
                      {s.transport} {s.status === 'connected' && `· ${s.tool_count} tools`}
                      {s.last_error && <span className="text-red-500"> · {s.last_error.slice(0, 60)}</span>}
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => toggleConnect(s)}
                    className="flex items-center gap-1 rounded-md px-2.5 py-1.5 text-xs font-medium hover:bg-neutral-100"
                  >
                    <RefreshCw size={12} />
                    {s.status === 'connected' ? 'Disconnect' : 'Connect'}
                  </button>
                  <button onClick={() => remove(s.id)} className="rounded-md p-1.5 text-neutral-400 hover:bg-neutral-100">
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
            ))}
            {servers.length === 0 && <div className="py-6 text-center text-sm text-neutral-400">No MCP servers configured.</div>}
          </div>

          {adding ? (
            <div className="mt-4 space-y-2 rounded-lg border border-neutral-200 p-3">
              <input
                placeholder="Server name"
                value={form.name}
                onChange={(e) => setForm((v) => ({ ...v, name: e.target.value }))}
                className="w-full rounded-md border border-neutral-200 px-2.5 py-1.5 text-sm outline-none"
              />
              <select
                value={transport}
                onChange={(e) => setTransport(e.target.value as typeof transport)}
                className="w-full rounded-md border border-neutral-200 px-2.5 py-1.5 text-sm outline-none"
              >
                <option value="stdio">stdio (local command)</option>
                <option value="sse">SSE (remote)</option>
                <option value="streamable_http">Streamable HTTP (remote)</option>
              </select>
              {transport === 'stdio' ? (
                <>
                  <input
                    placeholder="Command (e.g. npx)"
                    value={form.command}
                    onChange={(e) => setForm((v) => ({ ...v, command: e.target.value }))}
                    className="w-full rounded-md border border-neutral-200 px-2.5 py-1.5 text-sm outline-none"
                  />
                  <input
                    placeholder="Args (space-separated, e.g. -y @modelcontextprotocol/server-filesystem /path)"
                    value={form.args}
                    onChange={(e) => setForm((v) => ({ ...v, args: e.target.value }))}
                    className="w-full rounded-md border border-neutral-200 px-2.5 py-1.5 text-sm outline-none"
                  />
                </>
              ) : (
                <>
                  <input
                    placeholder="Server URL"
                    value={form.url}
                    onChange={(e) => setForm((v) => ({ ...v, url: e.target.value }))}
                    className="w-full rounded-md border border-neutral-200 px-2.5 py-1.5 text-sm outline-none"
                  />
                  <label className="flex items-center gap-2 text-sm text-neutral-600">
                    <input
                      type="checkbox"
                      checked={form.requires_oauth}
                      onChange={(e) => setForm((v) => ({ ...v, requires_oauth: e.target.checked }))}
                    />
                    Requires OAuth authorization
                  </label>
                </>
              )}
              <div className="flex justify-end gap-2 pt-1">
                <button onClick={() => setAdding(false)} className="rounded-md px-3 py-1.5 text-sm text-neutral-500 hover:bg-neutral-100">
                  Cancel
                </button>
                <button onClick={addServer} className="rounded-md bg-neutral-900 px-3 py-1.5 text-sm text-white hover:bg-neutral-700">
                  Add & Connect
                </button>
              </div>
            </div>
          ) : (
            <button
              onClick={() => setAdding(true)}
              className="mt-4 flex w-full items-center justify-center gap-1.5 rounded-lg border border-dashed border-neutral-300 py-2.5 text-sm text-neutral-500 hover:bg-neutral-50"
            >
              <Plus size={14} /> Add MCP server
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
