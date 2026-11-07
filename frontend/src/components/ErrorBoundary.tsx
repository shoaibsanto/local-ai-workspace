import { Component, type ErrorInfo, type ReactNode } from 'react'

interface Props {
  children: ReactNode
  /** Optional custom fallback renderer; receives the caught error. */
  fallback?: (error: Error, reset: () => void) => ReactNode
  /** Label used in the default full-page fallback's console log, e.g. "App" or "MessageBubble". */
  label?: string
}

interface State {
  error: Error | null
}

/**
 * Generic class-based error boundary. React only supports error boundaries as
 * classes (no hook equivalent yet), so this stays a class component.
 *
 * Two instances are used in this app:
 *  - A top-level boundary (wraps <App /> in main.tsx) showing a full "Something
 *    went wrong" screen with a Reload button, so a crash never produces a blank
 *    white page.
 *  - A narrow per-message boundary (wraps MessageBubble's rendered output) so a
 *    single malformed AI response's markdown/syntax-highlighting error can't take
 *    down the sidebar, composer, or other messages.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Always log to the console so the failure is visible in dev tools / CI
    // console-capture, regardless of environment.
    console.error(`[ErrorBoundary${this.props.label ? `:${this.props.label}` : ''}]`, error, info.componentStack)
  }

  reset = () => {
    this.setState({ error: null })
  }

  render() {
    const { error } = this.state
    if (!error) return this.props.children

    if (this.props.fallback) {
      return this.props.fallback(error, this.reset)
    }

    return (
      <div className="flex h-screen w-full flex-col items-center justify-center gap-4 bg-white px-6 text-center dark:bg-neutral-950">
        <div className="text-lg font-semibold text-neutral-800 dark:text-neutral-100">Something went wrong</div>
        <p className="max-w-md text-sm text-neutral-500 dark:text-neutral-400">
          The app hit an unexpected error and couldn't continue rendering. Reloading usually fixes it.
        </p>
        <button
          onClick={() => window.location.reload()}
          className="rounded-md bg-neutral-900 px-4 py-2 text-sm font-medium text-white transition-colors duration-150 hover:bg-neutral-700 dark:bg-white dark:text-neutral-900 dark:hover:bg-neutral-200"
        >
          Reload
        </button>
        {import.meta.env.DEV && (
          <pre className="mt-4 max-h-64 max-w-xl overflow-auto rounded-lg border border-red-200 bg-red-50 p-3 text-left text-xs text-red-700 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-300">
            {error.message}
            {error.stack ? `\n\n${error.stack}` : ''}
          </pre>
        )}
      </div>
    )
  }
}
