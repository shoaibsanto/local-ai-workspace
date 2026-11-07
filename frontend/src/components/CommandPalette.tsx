import { useEffect, useState } from 'react'
import { MessageSquare, Search } from 'lucide-react'
import { api, type ConversationMeta } from '../lib/api'
import { ModalShell } from './ModalShell'

interface Props {
  onClose: () => void
  onSelect: (id: string) => void
}

export function CommandPalette({ onClose, onSelect }: Props) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<ConversationMeta[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    const run = query ? api.searchConversations(query) : api.listConversations()
    run
      .then((data) => {
        if (!cancelled) setResults(data.sort((a, b) => b.updated_at - a.updated_at).slice(0, 20))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [query])

  return (
    <ModalShell onClose={onClose} titleId="command-palette-title" widthClassName="max-w-lg">
      <h2 id="command-palette-title" className="sr-only">
        Jump to conversation
      </h2>
      <div className="flex items-center gap-2 border-b border-neutral-200 px-4 py-3 dark:border-neutral-800">
        <Search size={16} className="text-neutral-400" />
        <input
          autoFocus
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Jump to a conversation…"
          aria-label="Search conversations"
          className="w-full bg-transparent text-sm outline-none placeholder:text-neutral-400 dark:text-neutral-100"
        />
      </div>
      <div className="max-h-96 overflow-y-auto p-2">
        {loading && <div className="px-3 py-4 text-sm text-neutral-400">Searching…</div>}
        {!loading && results.length === 0 && <div className="px-3 py-4 text-sm text-neutral-400">No conversations found.</div>}
        {!loading &&
          results.map((c) => (
            <button
              key={c.id}
              onClick={() => {
                onSelect(c.id)
                onClose()
              }}
              className="flex w-full items-center gap-2 rounded-lg px-3 py-2.5 text-left text-sm text-neutral-700 transition-colors duration-150 hover:bg-neutral-100 dark:text-neutral-200 dark:hover:bg-neutral-800"
            >
              <MessageSquare size={14} className="shrink-0 text-neutral-400" />
              <span className="flex-1 truncate">{c.title}</span>
            </button>
          ))}
      </div>
    </ModalShell>
  )
}
