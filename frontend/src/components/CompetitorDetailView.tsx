import { competitorUrl } from '../api.ts'
import { useApp } from '../context.ts'
import { compactNumber, humanize, percent } from '../format.ts'
import { useFetch } from '../hooks.ts'
import type { CompetitorDetail } from '../types.ts'
import { AppLink } from './AppLink.tsx'
import { LocationBadge, ScoreBadge } from './Badges.tsx'
import { PostCard } from './PostCard.tsx'
import { ErrorBox, Loading } from './StateViews.tsx'

export function CompetitorDetailView({ id }: { id: number }) {
  const { meta, state } = useApp()
  const { data, error, loading, reload } = useFetch<CompetitorDetail>(competitorUrl(id, state.window))
  const platformName = (platform: string) => meta.platforms.find((p) => p.id === platform)?.label ?? platform

  return (
    <section aria-busy={loading}>
      <AppLink className="back" patch={{ competitor: null }}>
        All competitors
      </AppLink>

      {error && <ErrorBox message={error} onRetry={reload} />}
      {!error && !data && <Loading what="Loading competitor" />}

      {data && (
        <>
          <header className="detail-head">
            <h2>{data.competitor.name}</h2>
            <p className="meta-line">
              <span>{humanize(data.competitor.kind)}</span>
              {data.competitor.rank !== null && (
                <span>
                  Rank {data.competitor.rank} in {state.window} days
                </span>
              )}
              {data.competitor.status !== 'active' && <span>{humanize(data.competitor.status)}</span>}
              {data.competitor.website && (
                <a href={data.competitor.website} target="_blank" rel="noopener noreferrer">
                  {data.competitor.website}
                </a>
              )}
            </p>
          </header>

          <div className="panels">
            <section>
              <h3>Accounts</h3>
              <ul className="plain-list">
                {data.competitor.accounts.map((account) => (
                  <li key={`${account.platform}-${account.handle}`}>
                    <strong>{platformName(account.platform)}</strong>{' '}
                    {account.url ? (
                      <a href={account.url} target="_blank" rel="noopener noreferrer">
                        {account.handle}
                      </a>
                    ) : (
                      account.handle
                    )}{' '}
                    <span className="meta-line">
                      <span>{compactNumber(account.followers)} followers</span>
                      <LocationBadge location={account.location} />
                    </span>
                    {account.location.evidence && <small className="evidence">{account.location.evidence}</small>}
                  </li>
                ))}
              </ul>
            </section>

            <section>
              <h3>Score by window</h3>
              {data.scores_by_window.length === 0 ? (
                <p>Not ranked yet: no posts have enough engagement.</p>
              ) : (
                <table>
                  <thead>
                    <tr>
                      <th>Window</th>
                      <th>Score</th>
                      <th>Posts</th>
                      <th>Consistency</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.scores_by_window.map((row) => (
                      <tr key={row.window} className={row.window === state.window ? 'current-row' : undefined}>
                        <td>{row.window} days</td>
                        <td>
                          <ScoreBadge score={row.score} />
                        </td>
                        <td>
                          {row.posts_count}
                          {row.low_sample && <small> (few)</small>}
                        </td>
                        <td>{percent(row.consistency)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </section>
          </div>

          <h3>Top posts, last {state.window} days</h3>
          {data.top_posts.length === 0 ? (
            <p>No ranked posts in this window.</p>
          ) : (
            <>
              <div className="post-list">
                {data.top_posts.map((post) => (
                  <PostCard key={post.id} post={post} />
                ))}
              </div>
              <p className="pager">
                <AppLink patch={{ tab: 'content', competitor: id }}>See all their ranked posts</AppLink>
              </p>
            </>
          )}
        </>
      )}
    </section>
  )
}
