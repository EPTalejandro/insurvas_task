import type { ReactNode } from 'react'

export function Loading({ what = 'Loading' }: { what?: string }) {
  return (
    <p className="state" aria-busy="true">
      {what}…
    </p>
  )
}

export function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="state state-error" role="alert">
      <p>
        <strong>Something went wrong.</strong> {message}
      </p>
      {onRetry && (
        <button className="quiet" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  )
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="state state-empty">{children}</div>
}
