// Small pure helpers for showing numbers, dates and labels.

/** 41234 -> "41.2k". Unknown numbers show a dash, never 0. */
export function compactNumber(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  if (value < 1000) return String(value)
  const units: [number, string][] = [
    [1e3, 'k'],
    [1e6, 'M'],
    [1e9, 'B'],
  ]
  let index = 0
  while (index + 1 < units.length && value >= units[index + 1][0]) index += 1
  const [size, suffix] = units[index]
  const rounded = Math.round((value / size) * 10) / 10
  // 999,999 rounds to "1000k": show it as 1M instead.
  if (rounded >= 1000 && index + 1 < units.length) return `1${units[index + 1][1]}`
  return `${rounded}${suffix}`
}

/** "3h ago", "2d ago". `now` is a parameter so the function stays easy to check. */
export function relativeTime(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return '—'
  const seconds = Math.floor((now - new Date(iso).getTime()) / 1000)
  if (seconds < 60) return 'just now'
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days}d ago`
  return new Date(iso).toLocaleDateString()
}

/** "in 6d", "in 5h": how long until a future moment. `now` is a parameter, like relativeTime. */
export function untilTime(iso: string, now: number = Date.now()): string {
  const minutes = Math.max(1, Math.ceil((new Date(iso).getTime() - now) / 60000))
  if (minutes < 60) return `in ${minutes}m`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `in ${hours}h`
  return `in ${Math.floor(hours / 24)}d`
}

/** "Nov 6" */
export function shortDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

const ACRONYMS: Record<string, string> = { iul: 'IUL', cta: 'CTA' }

/** "final_expense" -> "Final expense", "iul" -> "IUL" */
export function humanize(id: string | null | undefined): string {
  if (!id) return '—'
  const text = id
    .split('_')
    .map((word) => ACRONYMS[word] ?? word)
    .join(' ')
  return text.charAt(0).toUpperCase() + text.slice(1)
}

/** The API joins parts of a reason with " · "; the page shows them as plain sentences. */
export function plainReason(reason: string): string {
  return reason.split(' · ').join(', ')
}

export function percent(value: number | null | undefined): string {
  return value === null || value === undefined ? '—' : `${Math.round(value * 100)}%`
}

export type ScoreLevel = 'strong' | 'good' | 'normal'

export function scoreLevel(score: number, strong: number, good: number): ScoreLevel {
  if (score >= strong) return 'strong'
  if (score >= good) return 'good'
  return 'normal'
}

// How each location status is shown. The evidence goes in a tooltip.
export const LOCATION_LABELS: Record<string, { text: string; tone: 'yes' | 'maybe' | 'no' | 'unknown' }> = {
  us: { text: 'US', tone: 'yes' },
  likely_us: { text: 'Likely US', tone: 'yes' },
  probable_us: { text: 'Probable US', tone: 'maybe' },
  unverified: { text: 'Unverified', tone: 'unknown' },
  non_us: { text: 'Non-US', tone: 'no' },
}
