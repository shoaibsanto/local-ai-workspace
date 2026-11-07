import { useEffect, useRef, useState } from 'react'
import { Sidebar } from './components/Sidebar'
import { Composer } from './components/Composer'
import { MessageBubble } from './components/MessageBubble'
import { SettingsModal } from './components/SettingsModal'
import { McpModal } from './components/McpModal'
import { api, streamChat, type Message, type ProviderConfig } from './lib/api'
import { Sparkles } from 'lucide-react'

export default function App() {
  const [collapsed, setCollapsed] = useState(false)
  const [activeId, setActiveId] = useState<string | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [streamingText, setStreamingText] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [providers, setProviders] = useState<ProviderConfig[]>([])
  const [selectedProvider, setSelectedProvider] = useState<string | null>(null)
  const [selectedModel, setSelectedModel] = useState<string | null>(null)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [mcpOpen, setMcpOpen] = useState(false)
  const [sidebarRefresh, setSidebarRefresh] = useState(0)
  const [toolCount, setToolCount] = useState(0)
  const abortRef = useRef<AbortController | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)

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

  async function loadConversation(id: string) {
    const { meta, messages } = await api.getConversation(id)
    setActiveId(id)
    setMessages(messages)
    if (meta.provider) setSelectedProvider(meta.provider)
    if (meta.model) setSelectedModel(meta.model)
  }

  async function handleNewChat() {
    setActiveId(null)
    setMessages([])
    setStreamingText('')
  }

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
    const convId = await ensureConversation()
    if (messages.length === 0) {
      // Auto-title from first message
      const title = content.length > 48 ? content.slice(0, 48) + '…' : content
      api.updateConversation(convId, { title, provider: selectedProvider, model: selectedModel })
      setSidebarRefresh((r) => r + 1)
    }

    setIsStreaming(true)
    setStreamingText('')
    const controller = new AbortController()
    abortRef.current = controller

    let currentAssistant: Message | null = null

    try {
      for await (const event of streamChat(convId, content, controller.signal)) {
        if (event.type === 'user_message') {
          setMessages((m) => [...m, event.message])
        } else if (event.type === 'text_delta') {
          setStreamingText((t) => t + (event.text || ''))
        } else if (event.type === 'assistant_message') {
          currentAssistant = event.message
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
        } else if (event.type === 'error' && !currentAssistant) {
          // surfaced via assistant_message too; ignore standalone duplicate
        }
      }
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
    <div className="flex h-screen bg-white">
      <Sidebar
        collapsed={collapsed}
        onToggleCollapsed={() => setCollapsed((c) => !c)}
        activeId={activeId}
        onSelect={loadConversation}
        onNewChat={handleNewChat}
        onOpenSettings={() => setSettingsOpen(true)}
        onOpenMcp={() => setMcpOpen(true)}
        refreshKey={sidebarRefresh}
      />

      <div className="flex flex-1 flex-col">
        <div ref={scrollRef} className="flex-1 overflow-y-auto">
          {messages.length === 0 && !isStreaming ? (
            <div className="flex h-full flex-col items-center justify-center gap-3 text-neutral-400">
              <Sparkles size={32} />
              <div className="text-lg font-medium text-neutral-600">How can I help you today?</div>
            </div>
          ) : (
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
        />
      </div>

      {settingsOpen && <SettingsModal onClose={() => { setSettingsOpen(false); api.listProviders().then(setProviders) }} />}
      {mcpOpen && <McpModal onClose={() => { setMcpOpen(false); api.listMcpTools().then((t) => setToolCount(t.length)).catch(() => {}) }} />}
    </div>
  )
}
