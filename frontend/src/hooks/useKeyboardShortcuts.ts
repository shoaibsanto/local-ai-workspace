import { useEffect } from 'react'

interface ShortcutHandlers {
  onOpenPalette: () => void
  onNewChat: () => void
  onEscape: () => void
  onShowHelp: () => void
}

/**
 * Single global keyboard-shortcut listener, wired once in App.tsx.
 *  - Cmd/Ctrl+K: open command/search palette
 *  - Cmd/Ctrl+N: new chat
 *  - Escape: close any open modal
 *  - Cmd/Ctrl+/: shortcuts help overlay
 */
export function useKeyboardShortcuts({ onOpenPalette, onNewChat, onEscape, onShowHelp }: ShortcutHandlers) {
  useEffect(() => {
    function handler(e: KeyboardEvent) {
      const mod = e.metaKey || e.ctrlKey
      if (mod && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        onOpenPalette()
        return
      }
      if (mod && e.key.toLowerCase() === 'n') {
        e.preventDefault()
        onNewChat()
        return
      }
      if (mod && (e.key === '/' || e.key === '?')) {
        e.preventDefault()
        onShowHelp()
        return
      }
      if (e.key === 'Escape') {
        onEscape()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onOpenPalette, onNewChat, onEscape, onShowHelp])
}
