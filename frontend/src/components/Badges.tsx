import type { CSSProperties } from 'react'
import { useApp } from '../context.ts'
import { LOCATION_LABELS, humanize, scoreLevel } from '../format.ts'
import type { Location } from '../types.ts'

/** The 0-100 score as a large numeral with a bar under it. The top tier is red, the good tier navy. */
export function ScoreBadge({ score }: { score: number }) {
  const { meta } = useApp()
  const level = scoreLevel(score, meta.thresholds.strong_score, meta.thresholds.good_score)
  return (
    <span
      className={`score score-${level}`}
      style={{ '--pct': Math.min(1, Math.max(0, score / 100)) } as CSSProperties}
      title={`Score ${score.toFixed(1)} of 100`}
      aria-label={`Score ${Math.round(score)}`}
    >
      <span className="score-num">{Math.round(score)}</span>
      <span className="score-bar" />
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
