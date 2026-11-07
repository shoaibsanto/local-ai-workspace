import { useEffect, useState } from 'react'
import { PanelLeftClose, PanelLeft, Plus, Search, Settings, Plug, MessageSquare, Pin, Trash2, FolderKanban } from 'lucide-react'
import { api, type ConversationMeta } from '../lib/api'
import { cn } from '../lib/utils'

interface Props {
  collapsed: boolean
  onToggleCollapsed: () => void
  activeId: string | null
  onSelect: (id: string) => void
  onNewChat: () => void
  onOpenSettings: () => void
  onOpenMcp: () => void
  refreshKey: number
}

export function Sidebar({ collapsed, onToggleCollapsed, activeId, onSelect, onNewChat, onOpenSettings, onOpenMcp, refreshKey }: Props) {
  const [conversations, setConversations] = useState<ConversationMeta[]>([])
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    load()
  }, [refreshKey])

  async function load() {
    setLoading(true)
    try {
      const data = query ? await api.searchConversations(query) : await api.listConversations()
      setConversations(data.sort((a, b) => b.updated_at - a.updated_at))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    const t = setTimeout(load, 250)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query])

  async function handleDelete(e: React.MouseEvent, id: string) {
    e.stopPropagation()
    if (!confirm('Delete this conversation?')) return
    await api.deleteConversation(id)
    load()
  }

  async function handlePin(e: React.MouseEvent, c: ConversationMeta) {
    e.stopPropagation()
    await api.updateConversation(c.id, { pinned: !c.pinned })
    load()
  }

  if (collapsed) {
    return (
      <div className="flex h-full w-14 flex-col items-center gap-2 border-r border-neutral-200 bg-neutral-50 py-3">
        <button onClick={onToggleCollapsed} className="rounded-md p-2 hover:bg-neutral-200" title="Expand sidebar">
          <PanelLeft size={18} />
        </button>
        <button onClick={onNewChat} className="rounded-md p-2 hover:bg-neutral-200" title="New chat">
          <Plus size={18} />
        </button>
        <div className="flex-1" />
        <button onClick={onOpenMcp} className="rounded-md p-2 hover:bg-neutral-200" title="MCP Connections">
          <Plug size={18} />
        </button>
        <button onClick={onOpenSettings} className="rounded-md p-2 hover:bg-neutral-200" title="Settings">
          <Settings size={18} />
        </button>
      </div>
    )
  }

  const pinned = conversations.filter((c) => c.pinned)
  const rest = conversations.filter((c) => !c.pinned)

  return (
    <div className="flex h-full w-72 flex-col border-r border-neutral-200 bg-neutral-50">
      <div className="flex items-center justify-between px-3 pt-3">
        <span className="text-sm font-semibold tracking-tight text-neutral-800">Local AI Workspace</span>
        <button onClick={onToggleCollapsed} className="rounded-md p-1.5 hover:bg-neutral-200" title="Collapse sidebar">
          <PanelLeftClose size={16} />
        </button>
      </div>

      <div className="px-3 pt-3">
        <button
          onClick={onNewChat}
          className="flex w-full items-center gap-2 rounded-lg border border-neutral-300 bg-white px-3 py-2 text-sm font-medium text-neutral-800 shadow-sm hover:bg-neutral-100"
        >
          <Plus size={16} /> New Chat
        </button>
      </div>

      <div className="px-3 pt-3">
        <div className="flex items-center gap-2 rounded-lg border border-neutral-200 bg-white px-2.5 py-1.5">
          <Search size={14} className="text-neutral-400" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search conversations"
            className="w-full bg-transparent text-sm outline-none placeholder:text-neutral-400"
          />
        </div>
      </div>

      <div className="mt-2 flex-1 overflow-y-auto px-2 pb-2">
        {pinned.length > 0 && (
          <div className="mt-2">
            <div className="px-2 text-[11px] font-semibold uppercase tracking-wide text-neutral-400">Pinned</div>
            {pinned.map((c) => (
              <ConvoRow key={c.id} c={c} active={c.id === activeId} onSelect={onSelect} onDelete={handleDelete} onPin={handlePin} />
            ))}
          </div>
        )}
        <div className="mt-2">
          <div className="px-2 text-[11px] font-semibold uppercase tracking-wide text-neutral-400">Recent</div>
          {rest.map((c) => (
            <ConvoRow key={c.id} c={c} active={c.id === activeId} onSelect={onSelect} onDelete={handleDelete} onPin={handlePin} />
          ))}
          {!loading && rest.length === 0 && pinned.length === 0 && (
            <div className="px-2 py-4 text-sm text-neutral-400">No conversations yet.</div>
          )}
        </div>
      </div>

      <div className="border-t border-neutral-200 p-2">
        <button
          onClick={onOpenMcp}
          className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm text-neutral-700 hover:bg-neutral-200"
        >
          <Plug size={16} /> MCP Connections
        </button>
        <button
          onClick={onOpenSettings}
          className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm text-neutral-700 hover:bg-neutral-200"
        >
          <Settings size={16} /> Settings
        </button>
        <button
          disabled
          className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm text-neutral-400"
          title="Projects: coming soon"
        >
          <FolderKanban size={16} /> Projects
        </button>
      </div>
    </div>
  )
}

function ConvoRow({
  c,
  active,
  onSelect,
  onDelete,
  onPin,
}: {
  c: ConversationMeta
  active: boolean
  onSelect: (id: string) => void
  onDelete: (e: React.MouseEvent, id: string) => void
  onPin: (e: React.MouseEvent, c: ConversationMeta) => void
}) {
  return (
    <div
      onClick={() => onSelect(c.id)}
      className={cn(
        'group mt-0.5 flex cursor-pointer items-center gap-2 rounded-lg px-2 py-2 text-sm',
        active ? 'bg-neutral-200 text-neutral-900' : 'text-neutral-700 hover:bg-neutral-200/60'
      )}
    >
      <MessageSquare size={14} className="shrink-0 text-neutral-400" />
      <span className="flex-1 truncate">{c.title}</span>
      <button onClick={(e) => onPin(e, c)} className="hidden shrink-0 rounded p-1 hover:bg-neutral-300 group-hover:block">
        <Pin size={13} className={c.pinned ? 'fill-neutral-600 text-neutral-600' : 'text-neutral-400'} />
      </button>
      <button onClick={(e) => onDelete(e, c.id)} className="hidden shrink-0 rounded p-1 hover:bg-neutral-300 group-hover:block">
        <Trash2 size={13} className="text-neutral-400" />
      </button>
    </div>
  )
}
