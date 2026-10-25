import type { ReactNode } from 'react'
import { useApp } from '../context.ts'
import type { UrlState } from '../url.ts'

interface Props {
  patch: Partial<UrlState>
  className?: string
  title?: string
  role?: string
  current?: boolean
  children: ReactNode
}

/** A link that changes the URL state without reloading. Still a real link: it can be copied. */
export function AppLink({ patch, className, title, role, current, children }: Props) {
  const { href, update } = useApp()
  return (
    <a
      href={href(patch)}
      className={className}
      title={title}
      role={role}
      aria-current={current ? 'page' : undefined}
      onClick={(event) => {
        // Let the browser handle "open in a new tab" clicks.
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return
        event.preventDefault()
        update(patch)
      }}
    >
      {children}
    </a>
  )
}
