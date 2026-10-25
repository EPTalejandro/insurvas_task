import { createContext, useContext } from 'react'
import type { Meta } from './types.ts'
import type { UrlState } from './url.ts'

export interface AppContextValue {
  meta: Meta
  state: UrlState
  update: (patch: Partial<UrlState>) => void
  href: (patch: Partial<UrlState>) => string
}

export const AppContext = createContext<AppContextValue | null>(null)

/** The loaded meta data plus the URL state, available to every component. */
export function useApp(): AppContextValue {
  const value = useContext(AppContext)
  if (!value) throw new Error('useApp must be used inside the app')
  return value
}
