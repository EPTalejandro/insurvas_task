// Fetch helpers and the URL of every API call. Paths are relative, so the Vite proxy handles
// them in development.
import type { GroupBy } from './url.ts'

export async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path)
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`
    try {
      // The API explains bad requests in `detail` (for example the allowed windows).
      const body = (await response.json()) as { detail?: unknown }
      if (typeof body.detail === 'string') message = body.detail
    } catch {
      // The body was not JSON: keep the status text.
    }
    throw new Error(message)
  }
  return response.json() as Promise<T>
}

type Param = string | number | boolean | null | undefined

/** "?a=1&b=2", leaving out empty values. */
function query(params: Record<string, Param>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') search.set(key, String(value))
  }
  const text = search.toString()
  return text ? `?${text}` : ''
}

export interface PostsQuery {
  window: number
  platform: string
  topic: string
  hook_type: string
  format: string
  competitor: number | null
  limit: number
  offset: number
}

export const metaUrl = '/api/meta'
export const runsUrl = '/api/runs?limit=12'
export const keywordsUrl = '/api/keywords'

export function postsUrl(q: PostsQuery): string {
  return `/api/posts${query({
    window: q.window,
    platform: q.platform,
    topic: q.topic,
    hook_type: q.hook_type,
    format: q.format,
    competitor_id: q.competitor,
    limit: q.limit,
    offset: q.offset,
  })}`
}

export function competitorsUrl(window: number, includeLowSample: boolean): string {
  return `/api/competitors${query({ window, include_low_sample: includeLowSample })}`
}

export function competitorUrl(id: number, window: number): string {
  return `/api/competitors/${id}${query({ window })}`
}

export function insightsUrl(window: number, groupBy: GroupBy, platform: string): string {
  return `/api/insights${query({ window, group_by: groupBy, platform })}`
}
