import { keywordsUrl, runsUrl } from '../api.ts'
import { useApp } from '../context.ts'
import { LOCATION_LABELS, humanize, relativeTime } from '../format.ts'
import { useFetch } from '../hooks.ts'
import type { Keyword, Run } from '../types.ts'
import { StatusBadge } from './Badges.tsx'
import { ErrorBox, Loading } from './StateViews.tsx'

const LOCATION_HELP: Record<string, string> = {
  us: 'The channel says its country is the US.',
  likely_us: 'No country, but a US phone number, an NPN or "licensed in …" appears in the bio, posts or caption.',
  probable_us: 'An English caption with US cues: a state, a US product (IUL, Medicare), a $ amount or a US time zone. Hashtag posts only.',
  unverified: 'Not enough evidence either way. Competitors stay listed with this badge; hashtag posts are not ranked.',
  non_us: 'Another country, a non-US currency, or not in English. Left out.',
}

function RunsTable() {
  const { data, error, loading, reload } = useFetch<Run[]>(runsUrl)
  return (
    <section aria-busy={loading}>
      <h3>Recent runs</h3>
      {error && <ErrorBox message={error} onRetry={reload} />}
      {!error && !data && <Loading what="Loading runs" />}
      {data && data.length === 0 && <p>Nothing has run yet. Use the command line: refresh --discover.</p>}
      {data && data.length > 0 && (
        <div className="table-wrap">
          <table className="striped">
            <thead>
              <tr>
                <th>Step</th>
                <th>Platform</th>
                <th>Status</th>
                <th>OK / failed</th>
                <th>Quota</th>
                <th>When</th>
                <th>Message</th>
              </tr>
            </thead>
            <tbody>
              {data.map((run) => (
                <tr key={run.id}>
                  <td>{humanize(run.kind)}</td>
                  <td>{run.platform ? humanize(run.platform) : 'All'}</td>
                  <td>
                    <StatusBadge status={run.status} />
                  </td>
                  <td>
                    {run.items_ok} / {run.items_failed}
                  </td>
                  <td>{run.quota_used || '—'}</td>
                  <td>{relativeTime(run.finished_at ?? run.started_at)}</td>
                  <td className="message" title={run.message ?? undefined}>
                    {run.message ?? '—'}
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

function KeywordsTable() {
  const { data, error, loading, reload } = useFetch<Keyword[]>(keywordsUrl)
  return (
    <section aria-busy={loading}>
      <h3>Search terms</h3>
      {error && <ErrorBox message={error} onRetry={reload} />}
      {!error && !data && <Loading what="Loading keywords" />}
      {data && (
        <div className="table-wrap">
          <table className="striped">
            <thead>
              <tr>
                <th>Term</th>
                <th>Used for</th>
                <th>Active</th>
              </tr>
            </thead>
            <tbody>
              {data.map((keyword) => (
                <tr key={keyword.id}>
                  <td>{keyword.platform === 'instagram' ? `#${keyword.term}` : keyword.term}</td>
                  <td>
                    {keyword.platform === 'instagram'
                      ? 'Instagram hashtag'
                      : keyword.platform
                        ? humanize(keyword.platform)
                        : 'YouTube discovery'}
                  </td>
                  <td>{keyword.active ? 'Yes' : 'No'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

export function Sources() {
  const { meta } = useApp()
  return (
    <>
      <h3>Platforms</h3>
      <div className="grid-2">
        {meta.platforms.map((platform) => (
          <article key={platform.id}>
            <h4>{platform.label}</h4>
            <p>
              {platform.enabled ? 'Keys set: collecting.' : 'No keys in .env: not collecting.'}
              <br />
              {platform.posts} posts stored.
            </p>
          </article>
        ))}
      </div>

      <h3>How we know it is US-based</h3>
      <p className="summary">
        Hover a badge to see its evidence. Hashtag posts have no known author, so only their caption is judged.
      </p>
      <ul className="plain-list">
        {Object.entries(LOCATION_LABELS).map(([status, info]) => (
          <li key={status}>
            <span className={`badge tone-${info.tone}`}>{info.text}</span> {LOCATION_HELP[status]}
          </li>
        ))}
      </ul>

      <KeywordsTable />
      <RunsTable />
    </>
  )
}
