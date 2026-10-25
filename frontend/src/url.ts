// The URL is the app's state: reload or share it and you get the same view. No router needed.
import { useCallback, useMemo, useSyncExternalStore } from 'react'

export type Tab = 'content' | 'competitors' | 'insights' | 'sources'
export type GroupBy = 'hook_type' | 'topic' | 'format'

export const TABS: { id: Tab; label: string }[] = [
  { id: 'content', label: 'Top content' },
  { id: 'competitors', label: 'Competitors' },
  { id: 'insights', label: 'Insights' },
  { id: 'sources', label: 'Sources' },
]
export const GROUPS: { id: GroupBy; label: string }[] = [
  { id: 'hook_type', label: 'Hook' },
  { id: 'topic', label: 'Topic' },
  { id: 'format', label: 'Format' },
]
export const DEFAULT_WINDOW = 7

export interface UrlState {
  tab: Tab
  window: number
  platform: string
  topic: string
  hook_type: string
  format: string
  competitor: number | null
  group_by: GroupBy
}

export function parseSearch(search: string): UrlState {
  const params = new URLSearchParams(search)
  const window = Number(params.get('window'))
  const competitor = Number(params.get('competitor'))
  return {
    tab: TABS.find((t) => t.id === params.get('tab'))?.id ?? 'content',
    window: Number.isInteger(window) && window > 0 ? window : DEFAULT_WINDOW,
    platform: params.get('platform') ?? '',
    topic: params.get('topic') ?? '',
    hook_type: params.get('hook_type') ?? '',
    format: params.get('format') ?? '',
    competitor: Number.isInteger(competitor) && competitor > 0 ? competitor : null,
    group_by: GROUPS.find((g) => g.id === params.get('group_by'))?.id ?? 'hook_type',
  }
}

/** Only values that differ from the defaults go in the URL, so it stays short. */
export function toSearch(state: UrlState): string {
  const params = new URLSearchParams()
  if (state.tab !== 'content') params.set('tab', state.tab)
  if (state.window !== DEFAULT_WINDOW) params.set('window', String(state.window))
  if (state.platform) params.set('platform', state.platform)
  if (state.topic) params.set('topic', state.topic)
  if (state.hook_type) params.set('hook_type', state.hook_type)
  if (state.format) params.set('format', state.format)
  if (state.competitor !== null) params.set('competitor', String(state.competitor))
  if (state.group_by !== 'hook_type') params.set('group_by', state.group_by)
  const text = params.toString()
  return text ? `?${text}` : window.location.pathname
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener('popstate', onChange) // back and forward buttons
  window.addEventListener('urlchange', onChange) // our own changes
  return () => {
    window.removeEventListener('popstate', onChange)
    window.removeEventListener('urlchange', onChange)
  }
}

export function useUrlState(): {
  state: UrlState
  update: (patch: Partial<UrlState>) => void
  href: (patch: Partial<UrlState>) => string
} {
  const search = useSyncExternalStore(subscribe, () => window.location.search)
  const state = useMemo(() => parseSearch(search), [search])

  const update = useCallback((patch: Partial<UrlState>) => {
    const next = { ...parseSearch(window.location.search), ...patch }
    window.history.pushState(null, '', toSearch(next))
    window.dispatchEvent(new Event('urlchange'))
  }, [])

  // A real link for every state change, so "open in new tab" and copy link work.
  const href = useCallback((patch: Partial<UrlState>) => toSearch({ ...state, ...patch }), [state])

  return { state, update, href }
}
