import { useState } from 'react'
import { postSeenUrl, postsUrl, sendJson } from '../api.ts'
import { useApp } from '../context.ts'
import { humanize, relativeTime } from '../format.ts'
import { useFetch } from '../hooks.ts'
import type { Option, Post, PostsPage } from '../types.ts'
import type { View } from '../url.ts'
import { AppLink } from './AppLink.tsx'
import { Empty, ErrorBox, Loading } from './StateViews.tsx'
import { PostCard, type SeenControl } from './PostCard.tsx'

const PAGE_SIZE = 20
const VIEWS: { id: View; label: string }[] = [
  { id: 'new', label: 'New' },
  { id: 'seen', label: 'Seen' },
]

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

/** The page of posts. Not remounted on a filter change, so the old list stays up while the new one loads. */
export function TopContent() {
  const { meta, state, update } = useApp()
  // The page belongs to the filters it was chosen for: new filters start again at page 1.
  const filters = [state.window, state.platform, state.topic, state.hook_type, state.format, state.competitor, state.view].join('|')
  const [page, setPage] = useState({ filters, offset: 0 })
  const offset = page.filters === filters ? page.offset : 0
  const inSeen = state.view === 'seen'
  const { data, error, loading, reload } = useFetch<PostsPage>(
    postsUrl({ ...state, seen: inSeen, offset, limit: PAGE_SIZE }),
  )
  // Seen changes made here, by post id: when it was marked, or null once unmarked. The cards stay
  // where they are (dimmed) until the list reloads, so the list does not jump while you read.
  const [changed, setChanged] = useState<Map<number, string | null>>(() => new Map())

  function setSeen(post: Post, seen: boolean) {
    setChanged((previous) => new Map(previous).set(post.id, seen ? new Date().toISOString() : null))
    sendJson(seen ? 'PUT' : 'DELETE', postSeenUrl(post.id)).catch(() => {
      // The server did not save it: show the card as it really is again.
      setChanged((previous) => {
        const next = new Map(previous)
        next.delete(post.id)
        return next
      })
    })
  }

  function seenControl(post: Post): SeenControl {
    const at = changed.has(post.id) ? (changed.get(post.id) ?? null) : post.seen_at
    const onOpen = () => {
      if (!at) setSeen(post, true)
    }
    if (at && !inSeen) return { onOpen, note: 'Seen', action: 'Undo', onAction: () => setSeen(post, false), dimmed: true }
    if (at) return { onOpen, note: `Seen ${relativeTime(at)}`, action: 'Mark as unseen', onAction: () => setSeen(post, false), dimmed: false }
    if (inSeen) return { onOpen, note: 'Back in New', action: 'Undo', onAction: () => setSeen(post, true), dimmed: true }
    return { onOpen, note: null, action: '', onAction: () => {}, dimmed: false }
  }

  const hasFilters = Boolean(state.topic || state.hook_type || state.format || state.competitor)
  const competitorName = data?.items[0]?.creator.name ?? `#${state.competitor}`
  const longerWindow = meta.windows.find((days) => days > state.window)
  const goToPage = (next: number) => {
    setPage({ filters, offset: next })
    window.scrollTo({ top: 0 })
  }

  return (
    <section aria-busy={loading}>
      <div className="options view-switch" role="toolbar" aria-label="Posts to show">
        {VIEWS.map((view) => (
          <AppLink key={view.id} patch={{ view: view.id }} current={view.id === state.view}>
            {view.label}
          </AppLink>
        ))}
      </div>

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
          {inSeen ? (
            <p>No seen posts match these filters in the last {state.window} days. Opening a post's link marks it as seen.</p>
          ) : (
            <p>No new posts match these filters in the last {state.window} days. Posts you have opened are under Seen.</p>
          )}
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
            {data.total} {inSeen ? '' : 'ranked '}
            {data.total === 1 ? 'post' : 'posts'} {inSeen ? 'you have opened' : 'you have not opened yet'}, best first.
            {data.too_new > 0 &&
              ` ${data.too_new} more ${data.too_new === 1 ? 'is' : 'are'} too new to rank yet (under ${meta.thresholds.min_post_age_hours} hours).`}
          </p>
          <div className="post-list">
            {data.items.map((post, index) => (
              <PostCard key={post.id} post={post} lead={offset === 0 && index === 0} seen={seenControl(post)} />
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
