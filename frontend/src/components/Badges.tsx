import { useApp } from '../context.ts'
import { LOCATION_LABELS, humanize, scoreLevel } from '../format.ts'
import type { Location } from '../types.ts'

/** The 0-100 score as a numeral. Marked yellow from the "strong" threshold, blue from "good". */
export function ScoreBadge({ score }: { score: number }) {
  const { meta } = useApp()
  const level = scoreLevel(score, meta.thresholds.strong_score, meta.thresholds.good_score)
  return (
    <span className={`score score-${level}`} title={`Score ${score.toFixed(1)} of 100`} aria-label={`Score ${Math.round(score)}`}>
      {Math.round(score)}
    </span>
  )
}

/** Is it US-based? The tooltip shows the evidence behind the answer. */
export function LocationBadge({ location }: { location: Location }) {
  const info = LOCATION_LABELS[location.status] ?? { text: humanize(location.status), tone: 'unknown' }
  return (
    <span className={`flag tone-${info.tone}`} title={location.evidence ?? 'No evidence recorded'}>
      {info.text}
    </span>
  )
}

export function StatusBadge({ status }: { status: string }) {
  const tone = status === 'ok' ? 'yes' : status === 'partial' ? 'maybe' : status === 'error' ? 'no' : 'unknown'
  return <span className={`flag tone-${tone}`}>{status}</span>
}
