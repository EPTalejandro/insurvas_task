import type { ReactNode } from 'react'

export function Loading({ what = 'Loading' }: { what?: string }) {
  return (
    <div className="state" role="status" aria-busy="true">
      <p>{what}…</p>
      <div className="skeleton" aria-hidden="true">
        <span />
        <span />
        <span />
      </div>
    </div>
  )
}

export function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="state state-error" role="alert">
      <p>
        <strong>This section did not load.</strong> {message}
      </p>
      <p>If it keeps failing, check that the backend is running on port 8000.</p>
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
