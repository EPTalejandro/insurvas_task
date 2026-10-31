// Fetch helpers and the URL of every API call. Paths are relative, so the Vite proxy handles
// them in development.
import type { GroupBy } from './url.ts'

/**
 * The API explains bad requests in `detail`: a sentence (for example the allowed windows), or
 * FastAPI's list of field errors, whose first message is enough here.
 */
async function errorMessage(response: Response): Promise<string> {
  let message = `${response.status} ${response.statusText}`
  try {
    const body = (await response.json()) as { detail?: unknown }
    if (typeof body.detail === 'string') message = body.detail
    else if (Array.isArray(body.detail) && typeof body.detail[0]?.msg === 'string') message = body.detail[0].msg
  } catch {
    // The body was not JSON: keep the status text.
  }
  return message
}

export async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path)
  if (!response.ok) throw new Error(await errorMessage(response))
  return response.json() as Promise<T>
}

/** A change (only keywords can be changed). Returns the answer, or null for 204 No Content. */
export async function sendJson<T>(method: 'POST' | 'PATCH' | 'DELETE', path: string, body?: unknown): Promise<T | null> {
  const response = await fetch(path, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!response.ok) throw new Error(await errorMessage(response))
  return response.status === 204 ? null : (response.json() as Promise<T>)
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
export const hashtagBudgetUrl = '/api/hashtag-budget'

export function keywordUrl(id: number): string {
  return `${keywordsUrl}/${id}`
}

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
