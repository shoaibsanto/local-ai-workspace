import { useEffect, useRef, useState } from 'react'
import { ArrowUp, Square, ChevronDown, Wrench } from 'lucide-react'
import type { ProviderConfig } from '../lib/api'
import { cn } from '../lib/utils'
import { Spinner } from './Spinner'

interface Props {
  providers: ProviderConfig[]
  selectedProvider: string | null
  selectedModel: string | null
  onModelChange: (providerId: string, model: string) => void
  onSend: (content: string) => void
  onStop: () => void
  isStreaming: boolean
  toolCount: number
  isSendingFirstMessage?: boolean
  prefill?: string
}

export function Composer({
  providers,
  selectedProvider,
  selectedModel,
  onModelChange,
  onSend,
  onStop,
  isStreaming,
  toolCount,
  isSendingFirstMessage = false,
  prefill,
}: Props) {
  const [text, setText] = useState('')
  const [pickerOpen, setPickerOpen] = useState(false)
  const taRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    const ta = taRef.current
    if (!ta) return
    ta.style.height = 'auto'
    ta.style.height = Math.min(ta.scrollHeight, 240) + 'px'
  }, [text])

  useEffect(() => {
    if (prefill !== undefined) {
      setText(prefill)
      taRef.current?.focus()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefill])

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  function submit() {
    const trimmed = text.trim()
    if (!trimmed || isStreaming) return
    onSend(trimmed)
    setText('')
  }

  const activeProvider = providers.find((p) => p.id === selectedProvider)
  const enabledProviders = providers.filter((p) => p.enabled)
  const busy = isStreaming || isSendingFirstMessage

  return (
    <div className="mx-auto w-full max-w-3xl px-3 pb-3 sm:px-4 sm:pb-4">
      <div className="rounded-2xl border border-neutral-300 bg-white shadow-sm transition-colors duration-200 dark:border-neutral-700 dark:bg-neutral-900">
        <textarea
          ref={taRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Message Local AI Workspace..."
          aria-label="Message input"
          rows={1}
          className="max-h-60 w-full resize-none bg-transparent px-4 pt-3 text-[15px] text-neutral-900 outline-none placeholder:text-neutral-400 dark:text-neutral-100 dark:placeholder:text-neutral-500"
        />
        <div className="flex items-center justify-between px-3 pb-2.5 pt-1">
          <div className="relative">
            <button
              onClick={() => setPickerOpen((v) => !v)}
              aria-haspopup="listbox"
              aria-expanded={pickerOpen}
              className="flex h-10 items-center gap-1.5 rounded-lg px-2 text-sm text-neutral-600 transition-colors duration-150 hover:bg-neutral-100 dark:text-neutral-300 dark:hover:bg-neutral-800"
            >
              <span className="font-medium text-neutral-800 dark:text-neutral-100">{selectedModel || 'Select model'}</span>
              <span className="hidden text-neutral-400 sm:inline">· {activeProvider?.name || 'No provider'}</span>
              <ChevronDown size={14} />
            </button>
            {pickerOpen && (
              <div className="absolute bottom-full left-0 mb-1 w-72 rounded-lg border border-neutral-200 bg-white py-1 shadow-lg transition-colors duration-200 dark:border-neutral-700 dark:bg-neutral-900">
                {enabledProviders.length === 0 && (
                  <div className="px-3 py-2 text-sm text-neutral-400">No providers configured. Open Settings.</div>
                )}
                {enabledProviders.map((p) => (
                  <div key={p.id}>
                    <div className="px-3 pt-2 text-[11px] font-semibold uppercase text-neutral-400">{p.name}</div>
                    {p.models.map((m) => (
                      <button
                        key={m}
                        onClick={() => {
                          onModelChange(p.id, m)
                          setPickerOpen(false)
                        }}
                        className={cn(
                          'flex w-full items-center px-3 py-2 text-left text-sm transition-colors duration-150 hover:bg-neutral-100 dark:text-neutral-200 dark:hover:bg-neutral-800',
                          p.id === selectedProvider && m === selectedModel && 'bg-neutral-100 font-medium dark:bg-neutral-800'
                        )}
                      >
                        {m}
                      </button>
                    ))}
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="flex items-center gap-2">
            {toolCount > 0 && (
              <div
                className="flex items-center gap-1 rounded-full bg-neutral-100 px-2 py-1 text-xs text-neutral-600 dark:bg-neutral-800 dark:text-neutral-300"
                title={`${toolCount} MCP tools available`}
              >
                <Wrench size={12} /> {toolCount}
              </div>
            )}
            {isStreaming ? (
              <button
                onClick={onStop}
                aria-label="Stop generating"
                className="flex h-10 w-10 items-center justify-center rounded-full bg-neutral-900 text-white transition-colors duration-150 hover:bg-neutral-700 dark:bg-white dark:text-neutral-900 dark:hover:bg-neutral-200"
              >
                <Square size={14} fill="currentColor" />
              </button>
            ) : (
              <button
                onClick={submit}
                disabled={!text.trim() || busy}
                aria-label="Send message"
                className="flex h-10 w-10 items-center justify-center rounded-full bg-neutral-900 text-white transition-colors duration-150 hover:bg-neutral-700 disabled:bg-neutral-200 disabled:text-neutral-400 dark:bg-white dark:text-neutral-900 dark:hover:bg-neutral-200 dark:disabled:bg-neutral-800 dark:disabled:text-neutral-600"
              >
                {isSendingFirstMessage ? <Spinner size={16} /> : <ArrowUp size={16} />}
              </button>
            )}
          </div>
        </div>
      </div>
      <div className="mt-1.5 text-center text-[11px] text-neutral-400">
        Runs locally. Your conversations never leave this machine except to the model provider you configured.
      </div>
    </div>
  )
}
