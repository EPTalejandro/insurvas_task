import { insightsUrl } from '../api.ts'
import { useApp } from '../context.ts'
import { compactNumber, humanize } from '../format.ts'
import { useFetch } from '../hooks.ts'
import type { Insights as InsightsData } from '../types.ts'
import { GROUPS, type GroupBy, type UrlState } from '../url.ts'
import { AppLink } from './AppLink.tsx'
import { Empty, ErrorBox, Loading } from './StateViews.tsx'

/** Clicking a bar shows the posts behind it. */
function filterPatch(groupBy: GroupBy, value: string): Partial<UrlState> {
  if (groupBy === 'topic') return { tab: 'content', topic: value }
  if (groupBy === 'hook_type') return { tab: 'content', hook_type: value }
  return { tab: 'content', format: value }
}

export function Insights() {
  const { state } = useApp()
  const { data, error, loading, reload } = useFetch<InsightsData>(
    insightsUrl(state.window, state.group_by, state.platform),
  )

  return (
    <section aria-busy={loading}>
      <p className="summary">
        Average score of the ranked posts of the last {state.window} days, grouped by what the post
        does. Groups with fewer than {data?.min_group_size ?? 5} posts are left out.
      </p>

      <div role="group" aria-label="Group by">
        {GROUPS.map((group) => (
          <AppLink
            key={group.id}
            role="button"
            className={group.id === state.group_by ? undefined : 'secondary outline'}
            patch={{ group_by: group.id }}
            current={group.id === state.group_by}
          >
            {group.label}
          </AppLink>
        ))}
      </div>

      {error && <ErrorBox message={error} onRetry={reload} />}
      {!error && !data && <Loading what="Loading insights" />}

      {data && data.groups.length === 0 && (
        <Empty>
          <p>Not enough posts to compare yet: every group has fewer than {data.min_group_size} posts.</p>
          <p>Try a longer window or all platforms.</p>
        </Empty>
      )}

      {data && data.groups.length > 0 && (
        <>
          <ul className="bars">
            {data.groups.map((group) => (
              <li key={group.value}>
                <AppLink
                  className="bar-row"
                  patch={filterPatch(state.group_by, group.value)}
                  title={`${group.label}. Click to see these posts.`}
                >
                  <span className="bar-label">{humanize(group.value)}</span>
                  <span className="bar-track">
                    <span className="bar-fill" style={{ width: `${Math.min(100, group.avg_score)}%` }} />
                  </span>
                  <span className="bar-value">{Math.round(group.avg_score)}</span>
                  <span className="bar-meta">
                    {group.count} posts · {compactNumber(Math.round(group.avg_engagement))} avg engagements
                  </span>
                </AppLink>
              </li>
            ))}
          </ul>
          {data.hidden_groups > 0 && (
            <p className="summary">
              {data.hidden_groups} {data.hidden_groups === 1 ? 'group' : 'groups'} ({data.hidden_posts}{' '}
              posts) hidden: fewer than {data.min_group_size} posts each.
            </p>
          )}
        </>
      )}
    </section>
  )
}
