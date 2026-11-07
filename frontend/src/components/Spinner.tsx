import { cn } from '../lib/utils'

interface Props {
  size?: number
  className?: string
  label?: string
}

export function Spinner({ size = 16, className, label = 'Loading' }: Props) {
  return (
    <span
      role="status"
      aria-label={label}
      className={cn('inline-block animate-spin rounded-full border-2 border-current border-t-transparent', className)}
      style={{ width: size, height: size }}
    />
  )
}
