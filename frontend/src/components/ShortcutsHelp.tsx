import { ModalShell } from './ModalShell'

interface Props {
  onClose: () => void
}

const SHORTCUTS: { keys: string; label: string }[] = [
  { keys: 'Ctrl/⌘ K', label: 'Open the conversation search palette' },
  { keys: 'Ctrl/⌘ N', label: 'Start a new chat' },
  { keys: 'Esc', label: 'Close the current modal' },
  { keys: 'Ctrl/⌘ /', label: 'Show this shortcuts overlay' },
]

export function ShortcutsHelp({ onClose }: Props) {
  return (
    <ModalShell onClose={onClose} titleId="shortcuts-help-title" widthClassName="max-w-sm">
      <div className="flex items-center justify-between border-b border-neutral-200 px-5 py-3.5 dark:border-neutral-800">
        <h2 id="shortcuts-help-title" className="text-base font-semibold text-neutral-900 dark:text-neutral-100">
          Keyboard Shortcuts
        </h2>
      </div>
      <div className="p-5">
        <ul className="space-y-2.5">
          {SHORTCUTS.map((s) => (
            <li key={s.keys} className="flex items-center justify-between text-sm">
              <span className="text-neutral-600 dark:text-neutral-300">{s.label}</span>
              <kbd className="rounded-md border border-neutral-300 bg-neutral-100 px-2 py-1 font-mono text-xs text-neutral-700 dark:border-neutral-700 dark:bg-neutral-800 dark:text-neutral-200">
                {s.keys}
              </kbd>
            </li>
          ))}
        </ul>
      </div>
    </ModalShell>
  )
}
