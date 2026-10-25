import { useState } from 'react'
import { competitorsUrl } from '../api.ts'
import { useApp } from '../context.ts'
import { humanize, percent } from '../format.ts'
import { useFetch } from '../hooks.ts'
import type { CompetitorsPage } from '../types.ts'
import { AppLink } from './AppLink.tsx'
import { LocationBadge, ScoreBadge } from './Badges.tsx'
import { CompetitorDetailView } from './CompetitorDetailView.tsx'
import { Empty, ErrorBox, Loading } from './StateViews.tsx'

function Leaderboard() {
  const { meta, state } = useApp()
  const [includeLow, setIncludeLow] = useState(false)
  const { data, error, loading, reload } = useFetch<CompetitorsPage>(
    competitorsUrl(state.window, includeLow),
  )
  const minPosts = meta.thresholds.min_posts_by_window[String(state.window)]
  const platformName = (id: string) => meta.platforms.find((p) => p.id === id)?.label ?? id

  return (
    <section aria-busy={loading}>
      <p className="summary">
        Competitors ranked by the median score of their posts, lowered when only a few posts are
        good. A competitor needs at least {minPosts} posts in {state.window} days to be ranked.
      </p>
      <label className="inline-check">
        <input
          type="checkbox"
          checked={includeLow}
          onChange={(event) => setIncludeLow(event.target.checked)}
        />
        Show competitors with too few posts
        {data && !includeLow && data.hidden_low_sample > 0 && ` (${data.hidden_low_sample} hidden)`}
      </label>

      {error && <ErrorBox message={error} onRetry={reload} />}
      {!error && !data && <Loading what="Loading competitors" />}
      {data && data.items.length === 0 && (
        <Empty>
          <p>No competitor has enough ranked posts in the last {state.window} days.</p>
          <p>Try a longer window{data.hidden_low_sample > 0 && ' or show competitors with few posts'}.</p>
        </Empty>
      )}

      {data && data.items.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Rank</th>
                <th>Competitor</th>
                <th>Score</th>
                <th>Posts</th>
                <th title="Share of their posts with a score of 50 or more">Consistency</th>
                <th>Top topic</th>
                <th>Top hook</th>
                <th>Best post</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((c) => (
                <tr key={c.id}>
                  <td className="rank">{c.rank ?? '—'}</td>
                  <td>
                    <AppLink patch={{ competitor: c.id }}>
                      <strong>{c.name}</strong>
                    </AppLink>
                    <small>
                      {humanize(c.kind)} on {c.accounts.map((a) => platformName(a.platform)).join(', ')}
                    </small>
                    <div className="flags">
                      {c.accounts.map((a) => (
                        <LocationBadge key={`${a.platform}-${a.handle}`} location={a.location} />
                      ))}
                    </div>
                  </td>
                  <td>{c.score === null ? '—' : <ScoreBadge score={c.score} />}</td>
                  <td>
                    {c.posts_count}
                    {c.low_sample && <small title="Too few posts to trust the score"> (few)</small>}
                  </td>
                  <td>{percent(c.consistency)}</td>
                  <td>{humanize(c.top_topic)}</td>
                  <td>{humanize(c.top_hook)}</td>
                  <td>
                    {c.best_post ? (
                      <a href={c.best_post.url} target="_blank" rel="noopener noreferrer">
                        {c.best_post.title ?? 'Open post'}
                      </a>
                    ) : (
                      '—'
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

export function Competitors() {
  const { state } = useApp()
  return state.competitor === null ? <Leaderboard /> : <CompetitorDetailView id={state.competitor} />
}
