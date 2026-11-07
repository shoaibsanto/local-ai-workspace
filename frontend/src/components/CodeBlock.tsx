import { useState } from 'react'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneDark, oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism'
import { Copy, Check } from 'lucide-react'
import { useTheme } from '../lib/theme'

/**
 * Split into its own module so it (and the heavy react-syntax-highlighter
 * Prism bundle + language grammars + themes it pulls in) can be loaded via
 * React.lazy from MessageBubble.tsx instead of shipping in the main entry
 * chunk — most messages never render a fenced code block on initial paint.
 */
export default function CodeBlock({ code, language }: { code: string; language: string }) {
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
