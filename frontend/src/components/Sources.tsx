import { useState, type FormEvent, type ReactNode } from 'react'
import { hashtagBudgetUrl, keywordUrl, keywordsUrl, runsUrl, sendJson } from '../api.ts'
import { useApp } from '../context.ts'
import { humanize, relativeTime, shortDate, untilTime } from '../format.ts'
import { useFetch } from '../hooks.ts'
import type { HashtagBudget, Keyword, Run } from '../types.ts'
import { StatusBadge } from './Badges.tsx'
import { ErrorBox, Loading } from './StateViews.tsx'

function RunsTable() {
  const { data, error, loading, reload } = useFetch<Run[]>(runsUrl)
  return (
    <div aria-busy={loading}>
      {error && <ErrorBox message={error} onRetry={reload} />}
      {!error && !data && <Loading what="Loading runs" />}
      {data && data.length === 0 && <p>Nothing has run yet. Use the command line: refresh --discover.</p>}
      {data && data.length > 0 && (
        <div className="table-wrap">
          <table>
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
    </div>
  )
}

/** Closed by default; the runs are only fetched once it is opened. */
function RunsDropdown() {
  const [open, setOpen] = useState(false)
  return (
    <details className="dropdown-section" onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary>Recent runs</summary>
      {open && <RunsTable />}
    </details>
  )
}

/**
 * One list of terms: add, turn on or off, delete. YouTube search terms and Instagram hashtags use
 * the same panel, so both have the same controls.
 */
function TermPanel(props: {
  title: string
  platform: string | null
  placeholder: string
  terms: Keyword[]
  onChange: () => void
  show: (term: string) => string
  note?: (term: string) => string | null
  children?: ReactNode
}) {
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Every change goes through here: one at a time, errors shown under the form.
  async function change(action: () => Promise<unknown>): Promise<boolean> {
    setBusy(true)
    setError(null)
    try {
      await action()
      props.onChange()
      return true
    } catch (failure) {
      setError((failure as Error).message)
      return false
    } finally {
      setBusy(false)
    }
  }

  async function add(event: FormEvent) {
    event.preventDefault()
    const added = await change(() => sendJson('POST', keywordsUrl, { term: draft, platform: props.platform }))
    if (added) setDraft('')
  }

  function remove(keyword: Keyword) {
    if (window.confirm(`Delete ${props.show(keyword.term)}?`)) {
      void change(() => sendJson('DELETE', keywordUrl(keyword.id)))
    }
  }

  return (
    <section className="term-panel">
      <h4>{props.title}</h4>
      {props.children}
      <form className="term-add" onSubmit={add}>
        <input
          aria-label={`New ${props.title.toLowerCase()}`}
          placeholder={props.placeholder}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
        />
        <button className="quiet" type="submit" disabled={busy || !draft.trim()}>
          Add
        </button>
      </form>
      {error && (
        <p className="term-error" role="alert">
          {error}
        </p>
      )}
      {props.terms.length === 0 ? (
        <p className="summary">None yet.</p>
      ) : (
        <ul className="plain-list term-list">
          {props.terms.map((keyword) => {
            const note = props.note?.(keyword.term)
            return (
              <li key={keyword.id} className={keyword.active ? undefined : 'inactive'}>
                <label>
                  <input
                    type="checkbox"
                    role="switch"
                    checked={keyword.active}
                    disabled={busy}
                    onChange={(event) => {
                      const active = event.target.checked
                      void change(() => sendJson('PATCH', keywordUrl(keyword.id), { active }))
                    }}
                  />
                  {props.show(keyword.term)}
                </label>
                {note && <small>{note}</small>}
                <button className="link-button term-delete" disabled={busy} onClick={() => remove(keyword)}>
                  Delete
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}

function HashtagBudgetLine({ budget, error }: { budget: HashtagBudget | null; error: string | null }) {
  if (error) return <p className="summary">The hashtag budget did not load ({error}).</p>
  if (!budget) return null
  return (
    <>
      <p className="summary">
        {budget.used} of {budget.limit} hashtags used in the last 7 days, {budget.free} free
        {budget.next_free_at && `, next slot frees ${untilTime(budget.next_free_at)}`}. Searching a
        hashtag again inside the week keeps the same slot.
      </p>
      {budget.free === 0 && budget.next_free_at && (
        <p className="term-error" role="status">
          No free hashtag slots: a new hashtag will fail until {shortDate(budget.next_free_at)}.
        </p>
      )}
    </>
  )
}

function SearchTerms() {
  const keywords = useFetch<Keyword[]>(keywordsUrl)
  const budget = useFetch<HashtagBudget>(hashtagBudgetUrl)
  const reloadAll = () => {
    keywords.reload()
    budget.reload()
  }
  const slotEnd = new Map((budget.data?.slots ?? []).map((slot) => [slot.tag, slot.frees_at]))
  const terms = keywords.data ?? []

  return (
    <section aria-busy={keywords.loading}>
      <h3>Search terms</h3>
      <p className="summary">
        Changes are used on the next pipeline run: <code>make refresh DISCOVER=1</code> for YouTube search terms,{' '}
        <code>make refresh</code> for hashtags.
      </p>
      {keywords.error && <ErrorBox message={keywords.error} onRetry={reloadAll} />}
      {!keywords.error && !keywords.data && <Loading what="Loading search terms" />}
      {keywords.data && (
        <div className="panels">
          <TermPanel
            title="YouTube search terms"
            platform={null}
            placeholder="life insurance agent"
            terms={terms.filter((keyword) => keyword.platform !== 'instagram')}
            onChange={reloadAll}
            show={(term) => term}
          />
          <TermPanel
            title="Instagram hashtags"
            platform="instagram"
            placeholder="#lifeinsurance"
            terms={terms.filter((keyword) => keyword.platform === 'instagram')}
            onChange={reloadAll}
            show={(term) => `#${term}`}
            note={(term) => {
              const frees = slotEnd.get(term.toLowerCase())
              return frees ? `slot until ${shortDate(frees)}` : null
            }}
          >
            <HashtagBudgetLine budget={budget.data} error={budget.error} />
          </TermPanel>
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
      <div className="facts">
        {meta.platforms.map((platform) => (
          <div key={platform.id}>
            <h4>{platform.label}</h4>
            <p>
              {platform.enabled ? 'Keys set, collecting.' : 'No keys in .env, not collecting.'}{' '}
              {platform.posts} posts stored.
            </p>
          </div>
        ))}
      </div>

      <h3>Posts left out as flexes</h3>
      <p className="summary">
        {meta.counts.flex_posts} {meta.counts.flex_posts === 1 ? 'post was' : 'posts were'} left out
        as flexes: they show off results (income, sales records, awards) without a lesson for the
        viewer. They are still stored, just never ranked.
      </p>

      <SearchTerms />
      <RunsDropdown />
    </>
  )
}
