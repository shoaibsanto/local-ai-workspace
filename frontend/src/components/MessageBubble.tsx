import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneDark, oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism'
import { Copy, Check, RefreshCw, Pencil, Wrench, AlertCircle } from 'lucide-react'
import type { Message } from '../lib/api'
import { cn } from '../lib/utils'
import { useTheme } from '../lib/theme'

interface Props {
  message: Message
  isStreaming?: boolean
  onRegenerate?: () => void
  onEdit?: (newContent: string) => void
}

export function MessageBubble({ message, isStreaming, onRegenerate, onEdit }: Props) {
  const [copied, setCopied] = useState(false)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(message.content)
  const isUser = message.role === 'user'

  async function copyAll() {
    await navigator.clipboard.writeText(message.content)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  if (message.role === 'tool') {
    return (
      <div className="mx-auto w-full max-w-3xl px-3 sm:px-4">
        {message.tool_results.map((tr) => (
          <div
            key={tr.tool_call_id}
            className="mb-2 rounded-lg border border-neutral-200 bg-neutral-50 p-2 text-xs text-neutral-600 dark:border-neutral-800 dark:bg-neutral-900 dark:text-neutral-300"
          >
            <div className="mb-1 flex items-center gap-1.5 font-medium text-neutral-500 dark:text-neutral-400">
              <Wrench size={12} /> {tr.name} result
            </div>
            <pre className="whitespace-pre-wrap break-words font-mono text-[11px] text-neutral-700 dark:text-neutral-300">
              {tr.content.slice(0, 2000)}
            </pre>
          </div>
        ))}
      </div>
    )
  }

  return (
    <div className={cn('mx-auto w-full max-w-3xl px-3 py-3 sm:px-4', isUser && 'flex justify-end')}>
      <div className={cn('group relative', isUser ? 'max-w-[85%] sm:max-w-[80%]' : 'w-full')}>
        {message.tool_calls.length > 0 && (
          <div className="mb-2 space-y-1">
            {message.tool_calls.map((tc) => (
              <div
                key={tc.id}
                className="flex items-center gap-1.5 rounded-md bg-amber-50 px-2 py-1 text-xs text-amber-700 dark:bg-amber-900/30 dark:text-amber-300"
              >
                <Wrench size={12} /> Calling tool: <span className="font-mono">{tc.name}</span>
              </div>
            ))}
          </div>
        )}

        {editing ? (
          <div className="rounded-2xl border border-neutral-300 bg-white p-3 dark:border-neutral-700 dark:bg-neutral-900">
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              className="w-full resize-none bg-transparent text-sm text-neutral-900 outline-none dark:text-neutral-100"
              rows={3}
              autoFocus
              aria-label="Edit message"
            />
            <div className="mt-2 flex justify-end gap-2">
              <button
                onClick={() => setEditing(false)}
                className="flex h-9 items-center rounded-md px-3 text-xs text-neutral-500 transition-colors duration-150 hover:bg-neutral-100 dark:text-neutral-400 dark:hover:bg-neutral-800"
              >
                Cancel
              </button>
              <button
                onClick={() => {
                  setEditing(false)
                  onEdit?.(draft)
                }}
                className="flex h-9 items-center rounded-md bg-neutral-900 px-3 text-xs text-white transition-colors duration-150 hover:bg-neutral-700 dark:bg-white dark:text-neutral-900 dark:hover:bg-neutral-200"
              >
                Save & Resend
              </button>
            </div>
          </div>
        ) : (
          <div
            className={cn(
              'prose-chat text-[15px] leading-relaxed',
              isUser
                ? 'rounded-2xl bg-neutral-900 px-4 py-2.5 text-white dark:bg-neutral-100 dark:text-neutral-900'
                : 'text-neutral-900 dark:text-neutral-100'
            )}
          >
            {message.error ? (
              <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-300">
                <AlertCircle size={16} className="mt-0.5 shrink-0" />
                <span>{message.error}</span>
              </div>
            ) : isUser ? (
              <span className="whitespace-pre-wrap">{message.content}</span>
            ) : (
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  code({ className, children, ...props }) {
                    const match = /language-(\w+)/.exec(className || '')
                    const isInline = !match
                    if (isInline) {
                      return (
                        <code
                          className="rounded bg-neutral-100 px-1.5 py-0.5 font-mono text-[0.85em] text-neutral-800 dark:bg-neutral-800 dark:text-neutral-200"
                          {...props}
                        >
                          {children}
                        </code>
                      )
                    }
                    const code = String(children).replace(/\n$/, '')
                    return <CodeBlock code={code} language={match![1]} />
                  },
                }}
              >
                {message.content || (isStreaming ? '...' : '')}
              </ReactMarkdown>
            )}
          </div>
        )}

        {!editing && !isStreaming && message.content && (
          <div
            className={cn(
              'mt-1.5 flex items-center gap-1 opacity-0 transition-opacity duration-150 group-hover:opacity-100 group-focus-within:opacity-100',
              isUser && 'justify-end'
            )}
          >
            <button
              onClick={copyAll}
              aria-label="Copy message"
              title="Copy"
              className="flex h-9 w-9 items-center justify-center rounded text-neutral-400 transition-colors duration-150 hover:bg-neutral-100 hover:text-neutral-700 dark:hover:bg-neutral-800 dark:hover:text-neutral-200"
            >
              {copied ? <Check size={14} /> : <Copy size={14} />}
            </button>
            {isUser && onEdit && (
              <button
                onClick={() => setEditing(true)}
                aria-label="Edit and resend message"
                title="Edit & resend"
                className="flex h-9 w-9 items-center justify-center rounded text-neutral-400 transition-colors duration-150 hover:bg-neutral-100 hover:text-neutral-700 dark:hover:bg-neutral-800 dark:hover:text-neutral-200"
              >
                <Pencil size={14} />
              </button>
            )}
            {!isUser && onRegenerate && (
              <button
                onClick={onRegenerate}
                aria-label="Regenerate response"
                title="Regenerate"
                className="flex h-9 w-9 items-center justify-center rounded text-neutral-400 transition-colors duration-150 hover:bg-neutral-100 hover:text-neutral-700 dark:hover:bg-neutral-800 dark:hover:text-neutral-200"
              >
                <RefreshCw size={14} />
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

function CodeBlock({ code, language }: { code: string; language: string }) {
  const [copied, setCopied] = useState(false)
  const { theme } = useTheme()
  return (
    <div className="my-2 overflow-hidden rounded-lg border border-neutral-800 dark:border-neutral-700">
      <div className="flex items-center justify-between bg-neutral-800 px-3 py-1.5 text-xs text-neutral-300 dark:bg-neutral-950">
        <span className="font-mono">{language}</span>
        <button
          onClick={async () => {
            await navigator.clipboard.writeText(code)
            setCopied(true)
            setTimeout(() => setCopied(false), 1500)
          }}
          aria-label="Copy code"
          className="flex h-8 items-center gap-1 rounded px-1.5 transition-colors duration-150 hover:text-white"
        >
          {copied ? <Check size={12} /> : <Copy size={12} />}
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      <SyntaxHighlighter
        language={language}
        style={theme === 'dark' ? oneDark : oneLight}
        customStyle={{ margin: 0, fontSize: '0.85em', background: theme === 'dark' ? '#0a0a0a' : '#fafafa' }}
      >
        {code}
      </SyntaxHighlighter>
    </div>
  )
}
