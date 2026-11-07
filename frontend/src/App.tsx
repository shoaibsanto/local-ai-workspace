import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { Sidebar } from './components/Sidebar'
import { Composer } from './components/Composer'
import { MessageBubble } from './components/MessageBubble'
import { ErrorBoundary } from './components/ErrorBoundary'
import { Spinner } from './components/Spinner'
import { api, streamChat, type ChatEvent, type Message, type ProviderConfig, type ToolCall } from './lib/api'
import { useKeyboardShortcuts } from './hooks/useKeyboardShortcuts'
import { Sparkles, Menu } from 'lucide-react'

// Modals are only ever needed after a user action (never on initial paint), so
// they're split into separate chunks and loaded on demand via React.lazy.
const SettingsModal = lazy(() => import('./components/SettingsModal').then((m) => ({ default: m.SettingsModal })))
const McpModal = lazy(() => import('./components/McpModal').then((m) => ({ default: m.McpModal })))
const ApprovalModal = lazy(() => import('./components/ApprovalModal').then((m) => ({ default: m.ApprovalModal })))
const CommandPalette = lazy(() => import('./components/CommandPalette').then((m) => ({ default: m.CommandPalette })))
const ShortcutsHelp = lazy(() => import('./components/ShortcutsHelp').then((m) => ({ default: m.ShortcutsHelp })))

function ModalFallback() {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/20 dark:bg-black/50">
      <Spinner size={24} className="text-neutral-500 dark:text-neutral-300" />
    </div>
  )
}

const SUGGESTED_PROMPTS = [
  'Summarize the key ideas from a long article I paste in',
  'Help me debug a Python traceback',
  'Draft a polite email declining a meeting',
  'Explain this SQL query in plain English',
]

interface PendingApproval {
  conversationId: string
  toolCall: ToolCall
  serverName: string
  riskLevel: string
}

export default function App() {
  const [collapsed, setCollapsed] = useState(false)
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false)
  const [activeId, setActiveId] = useState<string | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [streamingText, setStreamingText] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [isSendingFirstMessage, setIsSendingFirstMessage] = useState(false)
  const [providers, setProviders] = useState<ProviderConfig[]>([])
  const [selectedProvider, setSelectedProvider] = useState<string | null>(null)
  const [selectedModel, setSelectedModel] = useState<string | null>(null)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [mcpOpen, setMcpOpen] = useState(false)
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [shortcutsOpen, setShortcutsOpen] = useState(false)
  const [pendingApproval, setPendingApproval] = useState<PendingApproval | null>(null)
  const [sidebarRefresh, setSidebarRefresh] = useState(0)
  const [toolCount, setToolCount] = useState(0)
  const [prefillText, setPrefillText] = useState<string | undefined>(undefined)
  const [liveAnnouncement, setLiveAnnouncement] = useState('')
  const abortRef = useRef<AbortController | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const resumeStreamRef = useRef<((approved: boolean) => void) | null>(null)

  useEffect(() => {
    api.listProviders().then((ps) => {
      setProviders(ps)
      const active = ps.find((p) => p.enabled)
      if (active) {
        setSelectedProvider(active.id)
        setSelectedModel(active.default_model || active.models[0] || null)
      }
    })
    api.listMcpTools().then((t) => setToolCount(t.length)).catch(() => {})
  }, [])

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages, streamingText])

  // Announce only at the message level (not per streaming delta) so screen
  // readers aren't overwhelmed by rapid token-by-token updates.
  useEffect(() => {
    const last = messages[messages.length - 1]
    if (last && last.role === 'assistant' && last.content) {
      setLiveAnnouncement(`Assistant replied: ${last.content.slice(0, 200)}`)
    } else if (last && last.role === 'user') {
      setLiveAnnouncement('Message sent')
    }
  }, [messages])

  async function loadConversation(id: string) {
    const { meta, messages } = await api.getConversation(id)
    setActiveId(id)
    setMessages(messages)
    if (meta.provider) setSelectedProvider(meta.provider)
    if (meta.model) setSelectedModel(meta.model)
    setMobileSidebarOpen(false)
  }

  async function handleNewChat() {
    setActiveId(null)
    setMessages([])
    setStreamingText('')
    setMobileSidebarOpen(false)
  }

  function closeTopModal() {
    if (shortcutsOpen) return setShortcutsOpen(false)
    if (paletteOpen) return setPaletteOpen(false)
    if (pendingApproval) return // force explicit approve/reject
    if (mcpOpen) return setMcpOpen(false)
    if (settingsOpen) return setSettingsOpen(false)
    if (mobileSidebarOpen) return setMobileSidebarOpen(false)
  }

  useKeyboardShortcuts({
    onOpenPalette: () => setPaletteOpen(true),
    onNewChat: handleNewChat,
    onEscape: closeTopModal,
    onShowHelp: () => setShortcutsOpen(true),
  })

  async function ensureConversation(): Promise<string> {
    if (activeId) return activeId
    const conv = await api.createConversation({
      provider: selectedProvider || undefined,
      model: selectedModel || undefined,
      title: 'New Conversation',
    })
    setActiveId(conv.id)
    setSidebarRefresh((r) => r + 1)
    return conv.id
  }

  async function handleSend(content: string) {
    if (!selectedProvider || !selectedModel) {
      alert('Select a model and provider first (Settings → add an API key).')
      return
    }
    setPrefillText(undefined)
    const isFirstMessage = messages.length === 0 && !activeId
    if (isFirstMessage) setIsSendingFirstMessage(true)

    let convId: string
    try {
      convId = await ensureConversation()
    } finally {
      setIsSendingFirstMessage(false)
    }

    if (messages.length === 0) {
      const title = content.length > 48 ? content.slice(0, 48) + '…' : content
      api.updateConversation(convId, { title, provider: selectedProvider, model: selectedModel })
      setSidebarRefresh((r) => r + 1)
    }

    setIsStreaming(true)
    setStreamingText('')
    const controller = new AbortController()
    abortRef.current = controller

    try {
      await consumeStream(streamChat(convId, content, controller.signal), convId)
    } catch (e) {
      if ((e as Error).name !== 'AbortError') {
        console.error(e)
      }
    } finally {
      setIsStreaming(false)
      setStreamingText('')
      setSidebarRefresh((r) => r + 1)
    }
  }

  async function consumeStream(gen: AsyncGenerator<ChatEvent>, convId: string) {
    for await (const event of gen) {
      if (event.type === 'user_message') {
        setMessages((m) => [...m, event.message])
      } else if (event.type === 'text_delta') {
        setStreamingText((t) => t + (event.text || ''))
      } else if (event.type === 'assistant_message') {
        setMessages((m) => [...m, event.message])
        setStreamingText('')
      } else if (event.type === 'tool_result') {
        setMessages((m) => [
          ...m,
          {
            id: `tool_${event.tool_result.tool_call_id}`,
            role: 'tool',
            content: '',
            tool_calls: [],
            tool_results: [event.tool_result],
            created_at: Date.now() / 1000,
          },
        ])
      } else if (event.type === 'approval_required') {
        // Pause processing further events until the user approves/rejects.
        // ApprovalModal itself POSTs the decision to the approval endpoint;
        // we just wait for it to resolve before resuming the SSE stream.
        await waitForApproval(convId, event.tool_call, event.server_name, event.risk_level)
      } else if (event.type === 'error') {
        // surfaced via assistant_message too in most flows; ignore standalone duplicate here
      }
    }
  }

  function waitForApproval(conversationId: string, toolCall: ToolCall, serverName: string, riskLevel: string): Promise<boolean> {
    return new Promise((resolve) => {
      setPendingApproval({ conversationId, toolCall, serverName, riskLevel })
      resumeStreamRef.current = (approved: boolean) => {
        setPendingApproval(null)
        resumeStreamRef.current = null
        resolve(approved)
      }
    })
  }

  function handleStop() {
    abortRef.current?.abort()
    setIsStreaming(false)
  }

  async function handleRegenerate() {
    if (!activeId) return
    const { resend_content } = await api.regenerate(activeId)
    setMessages((m) => m.slice(0, -1))
    handleSend(resend_content)
  }

  async function handleEdit(index: number, newContent: string) {
    if (!activeId) return
    await api.editResend(activeId, index, newContent)
    setMessages((m) => m.slice(0, index))
    handleSend(newContent)
  }

  return (
    <div className="flex h-screen flex-col bg-white transition-colors duration-200 dark:bg-neutral-950 md:flex-row">
      {/* Mobile top bar */}
      <div className="flex h-12 shrink-0 items-center gap-2 border-b border-neutral-200 bg-neutral-50 px-2 transition-colors duration-200 md:hidden dark:border-neutral-800 dark:bg-neutral-950">
        <button
          onClick={() => setMobileSidebarOpen(true)}
          aria-label="Open sidebar"
          className="flex h-10 w-10 items-center justify-center rounded-md transition-colors duration-150 hover:bg-neutral-200 dark:hover:bg-neutral-800"
        >
          <Menu size={20} />
        </button>
        <span className="text-sm font-semibold text-neutral-800 dark:text-neutral-100">Local AI Workspace</span>
      </div>

      <Sidebar
        collapsed={collapsed}
        onToggleCollapsed={() => setCollapsed((c) => !c)}
        activeId={activeId}
        onSelect={loadConversation}
        onNewChat={handleNewChat}
        onOpenSettings={() => setSettingsOpen(true)}
        onOpenMcp={() => setMcpOpen(true)}
        refreshKey={sidebarRefresh}
        mobileOpen={mobileSidebarOpen}
        onCloseMobile={() => setMobileSidebarOpen(false)}
      />

      <div className="flex min-h-0 flex-1 flex-col">
        <div
          ref={scrollRef}
          className="flex-1 overflow-y-auto"
          role="log"
          aria-live="polite"
          aria-relevant="additions"
        >
          <span className="sr-only" aria-live="polite">
            {liveAnnouncement}
          </span>
          {messages.length === 0 && !isStreaming ? (
            <div className="flex h-full flex-col items-center justify-center gap-4 px-4 text-neutral-400">
              <Sparkles size={32} />
              <div className="text-lg font-medium text-neutral-600 dark:text-neutral-300">How can I help you today?</div>
              <div className="flex max-w-xl flex-wrap justify-center gap-2">
                {SUGGESTED_PROMPTS.map((prompt) => (
                  <button
                    key={prompt}
                    onClick={() => setPrefillText(prompt)}
                    className="rounded-full border border-neutral-200 bg-white px-3.5 py-2 text-sm text-neutral-600 transition-colors duration-150 hover:bg-neutral-100 dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-300 dark:hover:bg-neutral-800"
                  >
                    {prompt}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            // Broader boundary around the whole message-rendering region: if
            // something outside an individual MessageBubble's own boundary
            // still throws, the sidebar/composer stay interactive and only
            // this region falls back.
            <ErrorBoundary
              label="MessageList"
              fallback={() => (
                <div className="mx-auto w-full max-w-3xl px-4 py-6 text-sm text-neutral-500 dark:text-neutral-400">
                  Couldn't render the conversation. Try starting a new chat.
                </div>
              )}
            >
              <div className="py-4">
                {messages.map((m, i) => (
                  <MessageBubble
                    key={m.id}
                    message={m}
                    onRegenerate={m.role === 'assistant' && i === messages.length - 1 ? handleRegenerate : undefined}
                    onEdit={m.role === 'user' ? (nc) => handleEdit(i, nc) : undefined}
                  />
                ))}
                {isStreaming && streamingText && (
                  <MessageBubble
                    message={{
                      id: 'streaming',
                      role: 'assistant',
                      content: streamingText,
                      tool_calls: [],
                      tool_results: [],
                      created_at: Date.now() / 1000,
                    }}
                    isStreaming
                  />
                )}
              </div>
            </ErrorBoundary>
          )}
        </div>

        <Composer
          providers={providers}
          selectedProvider={selectedProvider}
          selectedModel={selectedModel}
          onModelChange={(p, m) => {
            setSelectedProvider(p)
            setSelectedModel(m)
          }}
          onSend={handleSend}
          onStop={handleStop}
          isStreaming={isStreaming}
          toolCount={toolCount}
          isSendingFirstMessage={isSendingFirstMessage}
          prefill={prefillText}
        />
      </div>

      {settingsOpen && (
        <Suspense fallback={<ModalFallback />}>
          <SettingsModal
            onClose={() => {
              setSettingsOpen(false)
              api.listProviders().then(setProviders)
            }}
          />
        </Suspense>
      )}
      {mcpOpen && (
        <Suspense fallback={<ModalFallback />}>
          <McpModal
            onClose={() => {
              setMcpOpen(false)
              api.listMcpTools().then((t) => setToolCount(t.length)).catch(() => {})
            }}
          />
        </Suspense>
      )}
      {paletteOpen && (
        <Suspense fallback={<ModalFallback />}>
          <CommandPalette onClose={() => setPaletteOpen(false)} onSelect={loadConversation} />
        </Suspense>
      )}
      {shortcutsOpen && (
        <Suspense fallback={<ModalFallback />}>
          <ShortcutsHelp onClose={() => setShortcutsOpen(false)} />
        </Suspense>
      )}
      {pendingApproval && (
        <Suspense fallback={<ModalFallback />}>
          <ApprovalModal
            conversationId={pendingApproval.conversationId}
            toolCall={pendingApproval.toolCall}
            serverName={pendingApproval.serverName}
            riskLevel={pendingApproval.riskLevel}
            onResolved={(approved) => resumeStreamRef.current?.(approved)}
          />
        </Suspense>
      )}
    </div>
  )
}
