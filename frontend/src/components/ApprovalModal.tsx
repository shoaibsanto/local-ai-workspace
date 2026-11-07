import { useState } from 'react'
import { AlertTriangle, Check, X } from 'lucide-react'
import { api, type ToolCall } from '../lib/api'
import { ModalShell } from './ModalShell'
import { Spinner } from './Spinner'

interface Props {
  conversationId: string
  toolCall: ToolCall
  serverName: string
  riskLevel: string
  onResolved: (approved: boolean) => void
}

const RISK_STYLES: Record<string, string> = {
  low: 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300',
  medium: 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300',
  high: 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300',
}

export function ApprovalModal({ conversationId, toolCall, serverName, riskLevel, onResolved }: Props) {
  const [submitting, setSubmitting] = useState<'approve' | 'reject' | null>(null)

  async function respond(approved: boolean) {
    setSubmitting(approved ? 'approve' : 'reject')
    try {
      await api.approveToolCall(conversationId, toolCall.id, approved)
    } catch (e) {
      console.error('Failed to submit tool approval', e)
    } finally {
      setSubmitting(null)
      onResolved(approved)
    }
  }

  const riskClass = RISK_STYLES[riskLevel.toLowerCase()] || RISK_STYLES.medium

  return (
    <ModalShell onClose={() => respond(false)} titleId="approval-modal-title" widthClassName="max-w-lg">
      <div className="flex items-center justify-between border-b border-neutral-200 px-5 py-3.5 dark:border-neutral-800">
        <h2 id="approval-modal-title" className="flex items-center gap-2 text-base font-semibold text-neutral-900 dark:text-neutral-100">
          <AlertTriangle size={18} className="text-amber-500" /> Tool Approval Required
        </h2>
      </div>

      <div className="flex-1 overflow-y-auto p-5 text-sm">
        <p className="mb-3 text-neutral-600 dark:text-neutral-300">
          <span className="font-medium text-neutral-900 dark:text-neutral-100">{serverName}</span> wants to run a tool on
          your behalf.
        </p>

        <div className="space-y-3 rounded-lg border border-neutral-200 p-3 dark:border-neutral-800">
          <div className="flex items-center justify-between">
            <div className="font-mono text-sm font-medium text-neutral-900 dark:text-neutral-100">{toolCall.name}</div>
            <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide ${riskClass}`}>
              {riskLevel} risk
            </span>
          </div>
          <div>
            <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-neutral-400">Arguments</div>
            <pre className="max-h-48 overflow-auto rounded-md bg-neutral-100 p-2 font-mono text-[12px] text-neutral-700 dark:bg-neutral-950 dark:text-neutral-300">
              {JSON.stringify(toolCall.arguments, null, 2)}
            </pre>
          </div>
        </div>
      </div>

      <div className="flex items-center justify-end gap-2 border-t border-neutral-200 px-5 py-3.5 dark:border-neutral-800">
        <button
          onClick={() => respond(false)}
          disabled={submitting !== null}
          className="flex h-10 min-w-[90px] items-center justify-center gap-1.5 rounded-lg border border-neutral-300 px-3 text-sm font-medium text-neutral-700 transition-colors duration-150 hover:bg-neutral-100 disabled:opacity-60 dark:border-neutral-700 dark:text-neutral-200 dark:hover:bg-neutral-800"
        >
          {submitting === 'reject' ? <Spinner size={14} /> : <X size={14} />} Reject
        </button>
        <button
          onClick={() => respond(true)}
          disabled={submitting !== null}
          className="flex h-10 min-w-[90px] items-center justify-center gap-1.5 rounded-lg bg-neutral-900 px-3 text-sm font-medium text-white transition-colors duration-150 hover:bg-neutral-700 disabled:opacity-60 dark:bg-white dark:text-neutral-900 dark:hover:bg-neutral-200"
        >
          {submitting === 'approve' ? <Spinner size={14} /> : <Check size={14} />} Approve
        </button>
      </div>
    </ModalShell>
  )
}
