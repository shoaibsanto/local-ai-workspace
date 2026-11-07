import { useEffect, useState } from 'react'
import { X, Key, Check, Trash2, Plus } from 'lucide-react'
import { api, type ProviderConfig } from '../lib/api'

interface Props {
  onClose: () => void
}

export function SettingsModal({ onClose }: Props) {
  const [providers, setProviders] = useState<ProviderConfig[]>([])
  const [keyDrafts, setKeyDrafts] = useState<Record<string, string>>({})
  const [saved, setSaved] = useState<Record<string, boolean>>({})
  const [adding, setAdding] = useState(false)
  const [newProvider, setNewProvider] = useState({ name: '', base_url: '', default_model: '', models: '', kind: 'openai_compatible' as const })

  useEffect(() => {
    load()
  }, [])

  async function load() {
    setProviders(await api.listProviders())
  }

  async function saveKey(id: string) {
    const key = keyDrafts[id]
    if (!key) return
    await api.setProviderKey(id, key)
    setSaved((s) => ({ ...s, [id]: true }))
    setTimeout(() => setSaved((s) => ({ ...s, [id]: false })), 1500)
    load()
  }

  async function removeProvider(id: string) {
    if (!confirm('Remove this provider and its stored API key?')) return
    await api.deleteProvider(id)
    load()
  }

  async function createProvider() {
    await api.createProvider({
      name: newProvider.name,
      base_url: newProvider.base_url,
      default_model: newProvider.default_model || undefined,
      models: newProvider.models.split(',').map((m) => m.trim()).filter(Boolean),
      kind: newProvider.kind,
      enabled: false,
    })
    setAdding(false)
    setNewProvider({ name: '', base_url: '', default_model: '', models: '', kind: 'openai_compatible' })
    load()
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30">
      <div className="flex max-h-[85vh] w-full max-w-2xl flex-col rounded-xl bg-white shadow-xl">
        <div className="flex items-center justify-between border-b border-neutral-200 px-5 py-3.5">
          <h2 className="text-base font-semibold">Model Providers</h2>
          <button onClick={onClose} className="rounded-md p-1.5 hover:bg-neutral-100">
            <X size={18} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-5">
          <p className="mb-4 text-sm text-neutral-500">
            Add your own API key for any provider. Keys are encrypted at rest on your machine and sent only to that
            provider's API — never to any central server.
          </p>

          <div className="space-y-3">
            {providers.map((p) => (
              <div key={p.id} className="rounded-lg border border-neutral-200 p-3">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="flex items-center gap-2 text-sm font-medium">
                      {p.name}
                      {p.enabled && (
                        <span className="rounded-full bg-green-100 px-2 py-0.5 text-[11px] font-medium text-green-700">Active</span>
                      )}
                    </div>
                    <div className="text-xs text-neutral-400">{p.base_url}</div>
                  </div>
                  <button onClick={() => removeProvider(p.id)} className="rounded-md p-1.5 text-neutral-400 hover:bg-neutral-100">
                    <Trash2 size={14} />
                  </button>
                </div>
                <div className="mt-2 flex items-center gap-2">
                  <div className="flex flex-1 items-center gap-2 rounded-lg border border-neutral-200 px-2.5 py-1.5">
                    <Key size={14} className="text-neutral-400" />
                    <input
                      type="password"
                      placeholder={p.api_key_ref ? 'Key configured — enter to replace' : 'Enter API key'}
                      value={keyDrafts[p.id] || ''}
                      onChange={(e) => setKeyDrafts((d) => ({ ...d, [p.id]: e.target.value }))}
                      className="w-full bg-transparent text-sm outline-none"
                    />
                  </div>
                  <button
                    onClick={() => saveKey(p.id)}
                    className="flex items-center gap-1 rounded-lg bg-neutral-900 px-3 py-1.5 text-sm text-white hover:bg-neutral-700"
                  >
                    {saved[p.id] ? <Check size={14} /> : 'Save'}
                  </button>
                </div>
                {p.models.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1">
                    {p.models.map((m) => (
                      <span key={m} className="rounded-full bg-neutral-100 px-2 py-0.5 text-[11px] text-neutral-600">
                        {m}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>

          {adding ? (
            <div className="mt-4 space-y-2 rounded-lg border border-neutral-200 p-3">
              <input
                placeholder="Provider name"
                value={newProvider.name}
                onChange={(e) => setNewProvider((v) => ({ ...v, name: e.target.value }))}
                className="w-full rounded-md border border-neutral-200 px-2.5 py-1.5 text-sm outline-none"
              />
              <input
                placeholder="Base URL (e.g. https://api.example.com/v1)"
                value={newProvider.base_url}
                onChange={(e) => setNewProvider((v) => ({ ...v, base_url: e.target.value }))}
                className="w-full rounded-md border border-neutral-200 px-2.5 py-1.5 text-sm outline-none"
              />
              <input
                placeholder="Models (comma-separated)"
                value={newProvider.models}
                onChange={(e) => setNewProvider((v) => ({ ...v, models: e.target.value }))}
                className="w-full rounded-md border border-neutral-200 px-2.5 py-1.5 text-sm outline-none"
              />
              <select
                value={newProvider.kind}
                onChange={(e) => setNewProvider((v) => ({ ...v, kind: e.target.value as 'openai_compatible' }))}
                className="w-full rounded-md border border-neutral-200 px-2.5 py-1.5 text-sm outline-none"
              >
                <option value="openai_compatible">OpenAI-compatible</option>
                <option value="anthropic">Anthropic</option>
              </select>
              <div className="flex justify-end gap-2 pt-1">
                <button onClick={() => setAdding(false)} className="rounded-md px-3 py-1.5 text-sm text-neutral-500 hover:bg-neutral-100">
                  Cancel
                </button>
                <button onClick={createProvider} className="rounded-md bg-neutral-900 px-3 py-1.5 text-sm text-white hover:bg-neutral-700">
                  Add Provider
                </button>
              </div>
            </div>
          ) : (
            <button
              onClick={() => setAdding(true)}
              className="mt-4 flex w-full items-center justify-center gap-1.5 rounded-lg border border-dashed border-neutral-300 py-2.5 text-sm text-neutral-500 hover:bg-neutral-50"
            >
              <Plus size={14} /> Add custom provider
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
