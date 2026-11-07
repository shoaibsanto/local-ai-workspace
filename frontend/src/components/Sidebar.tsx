import { useEffect, useState } from 'react'
import {
  PanelLeftClose,
  PanelLeft,
  Plus,
  Search,
  Settings,
  Plug,
  MessageSquare,
  Pin,
  Trash2,
  FolderKanban,
  Sun,
  Moon,
  X,
} from 'lucide-react'
import { api, type ConversationMeta } from '../lib/api'
import { cn } from '../lib/utils'
import { useTheme } from '../lib/theme'

interface Props {
  collapsed: boolean
  onToggleCollapsed: () => void
  activeId: string | null
  onSelect: (id: string) => void
  onNewChat: () => void
  onOpenSettings: () => void
  onOpenMcp: () => void
  refreshKey: number
  mobileOpen?: boolean
  onCloseMobile?: () => void
}

export function Sidebar({
  collapsed,
  onToggleCollapsed,
  activeId,
  onSelect,
  onNewChat,
  onOpenSettings,
  onOpenMcp,
  refreshKey,
  mobileOpen = false,
  onCloseMobile,
}: Props) {
  const [conversations, setConversations] = useState<ConversationMeta[]>([])
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(true)
  const { theme, toggleTheme } = useTheme()

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
      <div className="hidden h-full w-14 flex-col items-center gap-2 border-r border-neutral-200 bg-neutral-50 py-3 transition-colors duration-200 md:flex dark:border-neutral-800 dark:bg-neutral-950">
        <button
          onClick={onToggleCollapsed}
          aria-label="Expand sidebar"
          title="Expand sidebar"
          className="flex h-10 w-10 items-center justify-center rounded-md transition-colors duration-150 hover:bg-neutral-200 dark:hover:bg-neutral-800"
        >
          <PanelLeft size={18} />
        </button>
        <button
          onClick={onNewChat}
          aria-label="New chat"
          title="New chat"
          className="flex h-10 w-10 items-center justify-center rounded-md transition-colors duration-150 hover:bg-neutral-200 dark:hover:bg-neutral-800"
        >
          <Plus size={18} />
        </button>
        <div className="flex-1" />
        <button
          onClick={toggleTheme}
          aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
          title="Toggle theme"
          className="flex h-10 w-10 items-center justify-center rounded-md transition-colors duration-150 hover:bg-neutral-200 dark:hover:bg-neutral-800"
        >
          {theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
        </button>
        <button
          onClick={onOpenMcp}
          aria-label="MCP connections"
          title="MCP Connections"
          className="flex h-10 w-10 items-center justify-center rounded-md transition-colors duration-150 hover:bg-neutral-200 dark:hover:bg-neutral-800"
        >
          <Plug size={18} />
        </button>
        <button
          onClick={onOpenSettings}
          aria-label="Settings"
          title="Settings"
          className="flex h-10 w-10 items-center justify-center rounded-md transition-colors duration-150 hover:bg-neutral-200 dark:hover:bg-neutral-800"
        >
          <Settings size={18} />
        </button>
      </div>
    )
  }

  const pinned = conversations.filter((c) => c.pinned)
  const rest = conversations.filter((c) => !c.pinned)

  const sidebarBody = (
    <div className="flex h-full w-72 flex-col border-r border-neutral-200 bg-neutral-50 transition-colors duration-200 dark:border-neutral-800 dark:bg-neutral-950">
      <div className="flex items-center justify-between px-3 pt-3">
        <span className="text-sm font-semibold tracking-tight text-neutral-800 dark:text-neutral-100">Local AI Workspace</span>
        <div className="flex items-center gap-1">
          <button
            onClick={onCloseMobile}
            aria-label="Close sidebar"
            className="flex h-10 w-10 items-center justify-center rounded-md transition-colors duration-150 hover:bg-neutral-200 md:hidden dark:hover:bg-neutral-800"
          >
            <X size={16} />
          </button>
          <button
            onClick={onToggleCollapsed}
            aria-label="Collapse sidebar"
            title="Collapse sidebar"
            className="hidden h-10 w-10 items-center justify-center rounded-md transition-colors duration-150 hover:bg-neutral-200 md:flex dark:hover:bg-neutral-800"
          >
            <PanelLeftClose size={16} />
          </button>
        </div>
      </div>

      <div className="px-3 pt-3">
        <button
          onClick={onNewChat}
          className="flex h-10 w-full items-center gap-2 rounded-lg border border-neutral-300 bg-white px-3 text-sm font-medium text-neutral-800 shadow-sm transition-colors duration-150 hover:bg-neutral-100 dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-100 dark:hover:bg-neutral-800"
        >
          <Plus size={16} /> New Chat
        </button>
      </div>

      <div className="px-3 pt-3">
        <div className="flex items-center gap-2 rounded-lg border border-neutral-200 bg-white px-2.5 py-1.5 transition-colors duration-150 dark:border-neutral-700 dark:bg-neutral-900">
          <Search size={14} className="text-neutral-400" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search conversations"
            aria-label="Search conversations"
            className="w-full bg-transparent text-sm outline-none placeholder:text-neutral-400 dark:text-neutral-100"
          />
        </div>
      </div>

      <div className="mt-2 flex-1 overflow-y-auto px-2 pb-2">
        {loading && conversations.length === 0 && (
          <div className="mt-2 space-y-1.5 px-2">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="h-9 animate-skeleton rounded-lg bg-neutral-200 dark:bg-neutral-800" />
            ))}
          </div>
        )}
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

      <div className="border-t border-neutral-200 p-2 dark:border-neutral-800">
        <button
          onClick={onOpenMcp}
          className="flex h-10 w-full items-center gap-2 rounded-lg px-3 text-sm text-neutral-700 transition-colors duration-150 hover:bg-neutral-200 dark:text-neutral-300 dark:hover:bg-neutral-800"
        >
          <Plug size={16} /> MCP Connections
        </button>
        <button
          onClick={onOpenSettings}
          className="flex h-10 w-full items-center gap-2 rounded-lg px-3 text-sm text-neutral-700 transition-colors duration-150 hover:bg-neutral-200 dark:text-neutral-300 dark:hover:bg-neutral-800"
        >
          <Settings size={16} /> Settings
        </button>
        <button
          disabled
          className="flex h-10 w-full items-center gap-2 rounded-lg px-3 text-sm text-neutral-400 dark:text-neutral-600"
          title="Projects: coming soon"
        >
          <FolderKanban size={16} /> Projects
        </button>
        <button
          onClick={toggleTheme}
          aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
          className="flex h-10 w-full items-center gap-2 rounded-lg px-3 text-sm text-neutral-700 transition-colors duration-150 hover:bg-neutral-200 dark:text-neutral-300 dark:hover:bg-neutral-800"
        >
          {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
          {theme === 'dark' ? 'Light mode' : 'Dark mode'}
        </button>
      </div>
    </div>
  )

  return (
    <>
      {/* Desktop sidebar */}
      <div className="hidden md:flex md:h-full">{sidebarBody}</div>

      {/* Mobile off-canvas drawer */}
      {mobileOpen && (
        <div className="fixed inset-0 z-40 md:hidden">
          <div
            className="absolute inset-0 bg-black/40 animate-overlay-in"
            onClick={onCloseMobile}
            aria-hidden="true"
          />
          <div className="absolute inset-y-0 left-0 animate-drawer-in">{sidebarBody}</div>
        </div>
      )}
    </>
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
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter') onSelect(c.id)
      }}
      className={cn(
        'group mt-0.5 flex cursor-pointer items-center gap-2 rounded-lg px-2 py-2 text-sm transition-colors duration-150',
        active
          ? 'bg-neutral-200 text-neutral-900 dark:bg-neutral-800 dark:text-neutral-100'
          : 'text-neutral-700 hover:bg-neutral-200/60 dark:text-neutral-300 dark:hover:bg-neutral-800/60'
      )}
    >
      <MessageSquare size={14} className="shrink-0 text-neutral-400" />
      <span className="flex-1 truncate">{c.title}</span>
      <button
        onClick={(e) => onPin(e, c)}
        aria-label={c.pinned ? 'Unpin conversation' : 'Pin conversation'}
        className="hidden h-7 w-7 shrink-0 items-center justify-center rounded transition-colors duration-150 hover:bg-neutral-300 group-hover:flex dark:hover:bg-neutral-700"
      >
        <Pin size={13} className={c.pinned ? 'fill-neutral-600 text-neutral-600 dark:fill-neutral-300 dark:text-neutral-300' : 'text-neutral-400'} />
      </button>
      <button
        onClick={(e) => onDelete(e, c.id)}
        aria-label="Delete conversation"
        className="hidden h-7 w-7 shrink-0 items-center justify-center rounded transition-colors duration-150 hover:bg-neutral-300 group-hover:flex dark:hover:bg-neutral-700"
      >
        <Trash2 size={13} className="text-neutral-400" />
      </button>
    </div>
  )
}
