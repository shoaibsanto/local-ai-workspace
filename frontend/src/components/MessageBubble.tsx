import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism'
import { Copy, Check, RefreshCw, Pencil, Wrench, AlertCircle } from 'lucide-react'
import type { Message } from '../lib/api'
import { cn } from '../lib/utils'

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
      <div className="mx-auto w-full max-w-3xl px-4">
        {message.tool_results.map((tr) => (
          <div key={tr.tool_call_id} className="mb-2 rounded-lg border border-neutral-200 bg-neutral-50 p-2 text-xs text-neutral-600">
            <div className="mb-1 flex items-center gap-1.5 font-medium text-neutral-500">
              <Wrench size={12} /> {tr.name} result
            </div>
            <pre className="whitespace-pre-wrap break-words font-mono text-[11px] text-neutral-700">{tr.content.slice(0, 2000)}</pre>
          </div>
        ))}
      </div>
    )
  }

  return (
    <div className={cn('mx-auto w-full max-w-3xl px-4 py-3', isUser && 'flex justify-end')}>
      <div className={cn('group relative', isUser ? 'max-w-[80%]' : 'w-full')}>
        {message.tool_calls.length > 0 && (
          <div className="mb-2 space-y-1">
            {message.tool_calls.map((tc) => (
              <div key={tc.id} className="flex items-center gap-1.5 rounded-md bg-amber-50 px-2 py-1 text-xs text-amber-700">
                <Wrench size={12} /> Calling tool: <span className="font-mono">{tc.name}</span>
              </div>
            ))}
          </div>
        )}

        {editing ? (
          <div className="rounded-2xl border border-neutral-300 bg-white p-3">
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              className="w-full resize-none bg-transparent text-sm outline-none"
              rows={3}
              autoFocus
            />
            <div className="mt-2 flex justify-end gap-2">
              <button onClick={() => setEditing(false)} className="rounded-md px-3 py-1 text-xs text-neutral-500 hover:bg-neutral-100">
                Cancel
              </button>
              <button
                onClick={() => {
                  setEditing(false)
                  onEdit?.(draft)
                }}
                className="rounded-md bg-neutral-900 px-3 py-1 text-xs text-white hover:bg-neutral-700"
              >
                Save & Resend
              </button>
            </div>
          </div>
        ) : (
          <div
            className={cn(
              'prose-chat text-[15px] leading-relaxed',
              isUser ? 'rounded-2xl bg-neutral-900 px-4 py-2.5 text-white' : 'text-neutral-900'
            )}
          >
            {message.error ? (
              <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
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
                        <code className="rounded bg-neutral-100 px-1.5 py-0.5 font-mono text-[0.85em]" {...props}>
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
              'mt-1.5 flex items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100',
              isUser && 'justify-end'
            )}
          >
            <button onClick={copyAll} className="rounded p-1 text-neutral-400 hover:bg-neutral-100 hover:text-neutral-700" title="Copy">
              {copied ? <Check size={14} /> : <Copy size={14} />}
            </button>
            {isUser && onEdit && (
              <button
                onClick={() => setEditing(true)}
                className="rounded p-1 text-neutral-400 hover:bg-neutral-100 hover:text-neutral-700"
                title="Edit & resend"
              >
                <Pencil size={14} />
              </button>
            )}
            {!isUser && onRegenerate && (
              <button
                onClick={onRegenerate}
                className="rounded p-1 text-neutral-400 hover:bg-neutral-100 hover:text-neutral-700"
                title="Regenerate"
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
  return (
    <div className="my-2 overflow-hidden rounded-lg border border-neutral-800">
      <div className="flex items-center justify-between bg-neutral-800 px-3 py-1.5 text-xs text-neutral-300">
        <span className="font-mono">{language}</span>
        <button
          onClick={async () => {
            await navigator.clipboard.writeText(code)
            setCopied(true)
            setTimeout(() => setCopied(false), 1500)
          }}
          className="flex items-center gap-1 hover:text-white"
        >
          {copied ? <Check size={12} /> : <Copy size={12} />}
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      <SyntaxHighlighter language={language} style={oneDark} customStyle={{ margin: 0, fontSize: '0.85em' }}>
        {code}
      </SyntaxHighlighter>
    </div>
  )
}
