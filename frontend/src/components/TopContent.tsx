import { useState } from 'react'
import { postsUrl } from '../api.ts'
import { useApp } from '../context.ts'
import { humanize } from '../format.ts'
import { useFetch } from '../hooks.ts'
import type { Option, PostsPage } from '../types.ts'
import { Empty, ErrorBox, Loading } from './StateViews.tsx'
import { PostCard } from './PostCard.tsx'

const PAGE_SIZE = 20

function FilterSelect(props: {
  label: string
  all: string
  value: string
  options: Option[]
  onChange: (value: string) => void
}) {
  return (
    <select
      aria-label={props.label}
      value={props.value}
      onChange={(event) => props.onChange(event.target.value)}
    >
      <option value="">{props.all}</option>
      {props.options.map((option) => (
        <option key={option.id} value={option.id} title={option.label}>
          {humanize(option.id)}
        </option>
      ))}
    </select>
  )
}

/** The page of posts. It is remounted when a filter changes, so paging starts again at 1. */
function PostList() {
  const { meta, state, update } = useApp()
  const [offset, setOffset] = useState(0)
  const { data, error, loading, reload } = useFetch<PostsPage>(
    postsUrl({ ...state, offset, limit: PAGE_SIZE }),
  )

  const hasFilters = Boolean(state.topic || state.hook_type || state.format || state.competitor)
  const competitorName = data?.items[0]?.creator.name ?? `#${state.competitor}`
  const longerWindow = meta.windows.find((days) => days > state.window)
  const goToPage = (next: number) => {
    setOffset(next)
    window.scrollTo({ top: 0 })
  }

  return (
    <section aria-busy={loading}>
      <div className="filters">
        <FilterSelect
          label="Topic"
          all="All topics"
          value={state.topic}
          options={meta.taxonomy.topics}
          onChange={(topic) => update({ topic })}
        />
        <FilterSelect
          label="Hook"
          all="All hooks"
          value={state.hook_type}
          options={meta.taxonomy.hooks}
          onChange={(hook_type) => update({ hook_type })}
        />
        <FilterSelect
          label="Format"
          all="All formats"
          value={state.format}
          options={meta.taxonomy.formats}
          onChange={(format) => update({ format })}
        />
        {state.competitor !== null && <span className="tag tag-static">Competitor: {competitorName}</span>}
        {(state.competitor !== null || hasFilters) && (
          <button
            className="quiet"
            onClick={() => update({ topic: '', hook_type: '', format: '', competitor: null })}
          >
            Clear filters
          </button>
        )}
      </div>

      {error && <ErrorBox message={error} onRetry={reload} />}
      {!error && !data && <Loading what="Loading posts" />}

      {data && data.items.length === 0 && (
        <Empty>
          <p>No ranked posts match these filters in the last {state.window} days.</p>
          {data.too_new > 0 && <p>{data.too_new} newer posts are too new to rank yet.</p>}
          <div className="state-actions">
            {(hasFilters || state.platform) && (
              <button
                className="link-button"
                onClick={() => update({ topic: '', hook_type: '', format: '', competitor: null, platform: '' })}
              >
                Clear the filters
              </button>
            )}
            {longerWindow && (
              <button className="link-button" onClick={() => update({ window: longerWindow })}>
                Show the last {longerWindow} days
              </button>
            )}
          </div>
        </Empty>
      )}

      {data && data.items.length > 0 && (
        <>
          <p className="summary">
            {data.total} ranked posts, best first.
            {data.too_new > 0 &&
              ` ${data.too_new} more ${data.too_new === 1 ? 'is' : 'are'} too new to rank yet (under ${meta.thresholds.min_post_age_hours} hours).`}
          </p>
          <div className="post-list">
            {data.items.map((post, index) => (
              <PostCard key={post.id} post={post} lead={offset === 0 && index === 0} />
            ))}
          </div>
          <nav className="pager" aria-label="Pages">
            <button
              className="quiet"
              disabled={offset === 0}
              onClick={() => goToPage(Math.max(0, offset - PAGE_SIZE))}
            >
              Previous
            </button>
            <span>
              {offset + 1}–{Math.min(offset + PAGE_SIZE, data.total)} of {data.total}
            </span>
            <button
              className="quiet"
              disabled={offset + PAGE_SIZE >= data.total}
              onClick={() => goToPage(offset + PAGE_SIZE)}
            >
              Next
            </button>
          </nav>
        </>
      )}
    </section>
  )
}

export function TopContent() {
  const { state } = useApp()
  const key = [state.window, state.platform, state.topic, state.hook_type, state.format, state.competitor].join('|')
  return <PostList key={key} />
}
