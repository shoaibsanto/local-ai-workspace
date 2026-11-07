import type { ReactNode } from 'react'
import { useFocusTrap } from '../hooks/useFocusTrap'

interface Props {
  onClose: () => void
  titleId: string
  children: ReactNode
  widthClassName?: string
}

/**
 * Shared modal chrome: overlay + focus trap + dialog semantics + fade/scale transition.
 * Escape-to-close is handled globally by useKeyboardShortcuts in App.tsx.
 */
export function ModalShell({ onClose, titleId, children, widthClassName = 'max-w-2xl' }: Props) {
  const containerRef = useFocusTrap(true)

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4 animate-overlay-in dark:bg-black/60"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div
        ref={containerRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className={`flex max-h-[85vh] w-full ${widthClassName} flex-col rounded-xl bg-white shadow-xl animate-modal-in outline-none dark:bg-neutral-900 dark:border dark:border-neutral-800`}
      >
        {children}
      </div>
    </div>
  )
}
