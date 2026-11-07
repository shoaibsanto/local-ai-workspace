import { useEffect, useState } from 'react'
import { X, Key, Check, Trash2, Plus, Inbox } from 'lucide-react'
import { api, type ProviderConfig } from '../lib/api'
import { ModalShell } from './ModalShell'
import { Spinner } from './Spinner'

interface Props {
  onClose: () => void
}

export function SettingsModal({ onClose }: Props) {
  const [providers, setProviders] = useState<ProviderConfig[]>([])
  const [loading, setLoading] = useState(true)
  const [keyDrafts, setKeyDrafts] = useState<Record<string, string>>({})
  const [saved, setSaved] = useState<Record<string, boolean>>({})
  const [adding, setAdding] = useState(false)
  const [newProvider, setNewProvider] = useState({ name: '', base_url: '', default_model: '', models: '', kind: 'openai_compatible' as const })

  useEffect(() => {
    load()
  }, [])

  async function load() {
    setLoading(true)
    try {
      setProviders(await api.listProviders())
    } finally {
      setLoading(false)
    }
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
    <ModalShell onClose={onClose} titleId="settings-modal-title">
      <div className="flex items-center justify-between border-b border-neutral-200 px-5 py-3.5 dark:border-neutral-800">
        <h2 id="settings-modal-title" className="text-base font-semibold text-neutral-900 dark:text-neutral-100">
          Model Providers
        </h2>
        <button
          onClick={onClose}
          aria-label="Close settings"
          className="flex h-10 w-10 items-center justify-center rounded-md transition-colors duration-150 hover:bg-neutral-100 dark:hover:bg-neutral-800"
        >
          <X size={18} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-5">
        <p className="mb-4 text-sm text-neutral-500 dark:text-neutral-400">
          Add your own API key for any provider. Keys are encrypted at rest on your machine and sent only to that
          provider's API — never to any central server.
        </p>

        {loading ? (
          <div className="flex items-center justify-center gap-2 py-10 text-sm text-neutral-400">
            <Spinner size={18} /> Loading providers…
          </div>
        ) : (
          <>
            {providers.length === 0 && (
              <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-neutral-300 py-8 text-center dark:border-neutral-700">
                <Inbox size={24} className="text-neutral-300 dark:text-neutral-600" />
                <div className="text-sm font-medium text-neutral-600 dark:text-neutral-300">No providers configured</div>
                <div className="max-w-xs text-xs text-neutral-400">
                  Add a provider below to start chatting with a model.
                </div>
              </div>
            )}
            <div className="space-y-3">
              {providers.map((p) => (
                <div key={p.id} className="rounded-lg border border-neutral-200 p-3 transition-colors duration-150 dark:border-neutral-800">
                  <div className="flex items-center justify-between">
                    <div>
                      <div className="flex items-center gap-2 text-sm font-medium text-neutral-900 dark:text-neutral-100">
                        {p.name}
                        {p.enabled && (
                          <span className="rounded-full bg-green-100 px-2 py-0.5 text-[11px] font-medium text-green-700 dark:bg-green-900/40 dark:text-green-300">
                            Active
                          </span>
                        )}
                      </div>
                      <div className="text-xs text-neutral-400">{p.base_url}</div>
                    </div>
                    <button
                      onClick={() => removeProvider(p.id)}
                      aria-label={`Remove provider ${p.name}`}
                      className="flex h-10 w-10 items-center justify-center rounded-md text-neutral-400 transition-colors duration-150 hover:bg-neutral-100 dark:hover:bg-neutral-800"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                  <div className="mt-2 flex items-center gap-2">
                    <label htmlFor={`api-key-${p.id}`} className="sr-only">
                      API key for {p.name}
                    </label>
                    <div className="flex flex-1 items-center gap-2 rounded-lg border border-neutral-200 px-2.5 py-1.5 dark:border-neutral-700">
                      <Key size={14} className="text-neutral-400" />
                      <input
                        id={`api-key-${p.id}`}
                        type="password"
                        placeholder={p.api_key_ref ? 'Key configured — enter to replace' : 'Enter API key'}
                        value={keyDrafts[p.id] || ''}
                        onChange={(e) => setKeyDrafts((d) => ({ ...d, [p.id]: e.target.value }))}
                        className="w-full bg-transparent text-sm text-neutral-900 outline-none dark:text-neutral-100"
                      />
                    </div>
                    <button
                      onClick={() => saveKey(p.id)}
                      className="flex h-10 items-center gap-1 rounded-lg bg-neutral-900 px-3 text-sm text-white transition-colors duration-150 hover:bg-neutral-700 dark:bg-white dark:text-neutral-900 dark:hover:bg-neutral-200"
                    >
                      {saved[p.id] ? <Check size={14} /> : 'Save'}
                    </button>
                  </div>
                  {p.models.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1">
                      {p.models.map((m) => (
                        <span
                          key={m}
                          className="rounded-full bg-neutral-100 px-2 py-0.5 text-[11px] text-neutral-600 dark:bg-neutral-800 dark:text-neutral-300"
                        >
                          {m}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </>
        )}

        {adding ? (
          <div className="mt-4 space-y-2 rounded-lg border border-neutral-200 p-3 dark:border-neutral-800">
            <label htmlFor="new-provider-name" className="sr-only">
              Provider name
            </label>
            <input
              id="new-provider-name"
              placeholder="Provider name"
              value={newProvider.name}
              onChange={(e) => setNewProvider((v) => ({ ...v, name: e.target.value }))}
              className="w-full rounded-md border border-neutral-200 px-2.5 py-2 text-sm text-neutral-900 outline-none dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-100"
            />
            <label htmlFor="new-provider-url" className="sr-only">
              Base URL
            </label>
            <input
              id="new-provider-url"
              placeholder="Base URL (e.g. https://api.example.com/v1)"
              value={newProvider.base_url}
              onChange={(e) => setNewProvider((v) => ({ ...v, base_url: e.target.value }))}
              className="w-full rounded-md border border-neutral-200 px-2.5 py-2 text-sm text-neutral-900 outline-none dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-100"
            />
            <label htmlFor="new-provider-models" className="sr-only">
              Models
            </label>
            <input
              id="new-provider-models"
              placeholder="Models (comma-separated)"
              value={newProvider.models}
              onChange={(e) => setNewProvider((v) => ({ ...v, models: e.target.value }))}
              className="w-full rounded-md border border-neutral-200 px-2.5 py-2 text-sm text-neutral-900 outline-none dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-100"
            />
            <label htmlFor="new-provider-kind" className="sr-only">
              Provider kind
            </label>
            <select
              id="new-provider-kind"
              value={newProvider.kind}
              onChange={(e) => setNewProvider((v) => ({ ...v, kind: e.target.value as 'openai_compatible' }))}
              className="w-full rounded-md border border-neutral-200 px-2.5 py-2 text-sm text-neutral-900 outline-none dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-100"
            >
              <option value="openai_compatible">OpenAI-compatible</option>
              <option value="anthropic">Anthropic</option>
            </select>
            <div className="flex justify-end gap-2 pt-1">
              <button
                onClick={() => setAdding(false)}
                className="flex h-10 items-center rounded-md px-3 text-sm text-neutral-500 transition-colors duration-150 hover:bg-neutral-100 dark:text-neutral-400 dark:hover:bg-neutral-800"
              >
                Cancel
              </button>
              <button
                onClick={createProvider}
                className="flex h-10 items-center rounded-md bg-neutral-900 px-3 text-sm text-white transition-colors duration-150 hover:bg-neutral-700 dark:bg-white dark:text-neutral-900 dark:hover:bg-neutral-200"
              >
                Add Provider
              </button>
            </div>
          </div>
        ) : (
          <button
            onClick={() => setAdding(true)}
            className="mt-4 flex h-11 w-full items-center justify-center gap-1.5 rounded-lg border border-dashed border-neutral-300 text-sm text-neutral-500 transition-colors duration-150 hover:bg-neutral-50 dark:border-neutral-700 dark:text-neutral-400 dark:hover:bg-neutral-900"
          >
            <Plus size={14} /> Add custom provider
          </button>
        )}
      </div>
    </ModalShell>
  )
}
