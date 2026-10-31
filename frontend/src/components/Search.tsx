import { useState } from 'react'
import { hashtagBudgetUrl, jobUrl, jobsUrl, keywordsUrl, sendJson } from '../api.ts'
import { dateTime, localInputValue, relativeTime, statusTone, untilTime } from '../format.ts'
import { useFetch, useInterval } from '../hooks.ts'
import type { HashtagBudget, Job, JobStep, Keyword } from '../types.ts'
import { StatusBadge } from './Badges.tsx'
import { ErrorBox, Loading } from './StateViews.tsx'

// The steps a search can have, in the order they run (the API keeps this order too).
const STEP_OPTIONS: { id: string; label: string; hint: string }[] = [
  { id: 'discover', label: 'Discover YouTube channels', hint: 'Finds new competitors. Uses about 3,000 of the 10,000 daily quota units.' },
  { id: 'youtube', label: 'Collect YouTube videos', hint: "The active competitors' recent videos." },
  { id: 'instagram_accounts', label: 'Collect Instagram accounts', hint: 'Links competitors to their accounts, then reads their posts.' },
  { id: 'hashtags', label: 'Collect Instagram hashtags', hint: 'Top posts of the hashtags picked below.' },
  { id: 'label', label: 'Label posts', hint: 'Topic, hook and call to action of new or changed posts.' },
  { id: 'rank', label: 'Rank posts and competitors', hint: 'New scores for 7, 30 and 90 days.' },
]
const FAST_POLL_MS = 1500 // while a search runs
const SLOW_POLL_MS = 30000 // otherwise, so a scheduled search is seen starting

/** Started, or due and about to be picked up by the scheduler. */
function isActive(job: Job, now: number): boolean {
  return job.status === 'running' || (job.status === 'scheduled' && new Date(job.run_at).getTime() <= now)
}

function toggled(list: string[], value: string, on: boolean): string[] {
  return on ? [...list, value] : list.filter((item) => item !== value)
}

function stepLabels(job: Job): string {
  return job.steps.map((step) => step.label).join(', ')
}

/** Which terms (or hashtags) this search uses: a wrapping row of checkboxes. */
function TermPicker(props: {
  title: string
  terms: string[]
  picked: string[]
  onChange: (picked: string[]) => void
  show: (term: string) => string
}) {
  return (
    <fieldset className="term-picker">
      <legend>{props.title}</legend>
      {props.terms.length === 0 ? (
        <p className="summary">None yet. Add them in the Sources tab.</p>
      ) : (
        props.terms.map((term) => (
          <label key={term}>
            <input
              type="checkbox"
              checked={props.picked.includes(term)}
              onChange={(event) => props.onChange(toggled(props.picked, term, event.target.checked))}
            />
            {props.show(term)}
          </label>
        ))
      )}
    </fieldset>
  )
}

function NewSearch({ keywords, budget, onCreated }: { keywords: Keyword[]; budget: HashtagBudget | null; onCreated: () => void }) {
  const youtubeTerms = keywords.filter((k) => k.platform !== 'instagram')
  const hashtagTerms = keywords.filter((k) => k.platform === 'instagram')
  // Discovery is off by default: it spends most of the day's YouTube quota.
  const [steps, setSteps] = useState(STEP_OPTIONS.filter((s) => s.id !== 'discover').map((s) => s.id))
  // Active terms are the default pick, like the command line uses them.
  const [pickedTerms, setPickedTerms] = useState(youtubeTerms.filter((k) => k.active).map((k) => k.term))
  const [pickedTags, setPickedTags] = useState(hashtagTerms.filter((k) => k.active).map((k) => k.term))
  const [when, setWhen] = useState('')
  const [earliest] = useState(() => localInputValue(new Date())) // the API checks it again
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Hashtags that would take a new weekly slot: the warning never blocks the search.
  const holding = new Set((budget?.slots ?? []).map((slot) => slot.tag))
  const newTags = steps.includes('hashtags') ? pickedTags.filter((tag) => !holding.has(tag.toLowerCase())) : []
  const overBudget = budget !== null && newTags.length > budget.free

  async function submit(runAt: string | null) {
    setBusy(true)
    setError(null)
    try {
      await sendJson('POST', jobsUrl, {
        steps: STEP_OPTIONS.map((s) => s.id).filter((id) => steps.includes(id)),
        // The input is local time; the API wants an exact moment, so it goes as UTC.
        run_at: runAt === null ? null : new Date(runAt).toISOString(),
        youtube_terms: pickedTerms,
        hashtags: pickedTags,
      })
      setWhen('')
      onCreated()
    } catch (failure) {
      setError((failure as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section>
      <h3>New search</h3>
      <fieldset className="step-picks">
        <legend className="visually-hidden">Steps, in the order they run</legend>
        <ol className="plain-list">
          {STEP_OPTIONS.map((option, index) => (
            <li key={option.id} className={steps.includes(option.id) ? undefined : 'off'}>
              <label>
                <span className="step-no" aria-hidden="true">
                  {index + 1}
                </span>
                <input
                  type="checkbox"
                  checked={steps.includes(option.id)}
                  onChange={(event) => setSteps(toggled(steps, option.id, event.target.checked))}
                />
                <span>
                  <strong>{option.label}</strong>
                  <small>{option.hint}</small>
                </span>
              </label>
            </li>
          ))}
        </ol>
      </fieldset>

      {(steps.includes('discover') || steps.includes('hashtags')) && (
        <div className="panels">
          {steps.includes('discover') && (
            <TermPicker
              title="YouTube search terms"
              terms={youtubeTerms.map((k) => k.term)}
              picked={pickedTerms}
              onChange={setPickedTerms}
              show={(term) => term}
            />
          )}
          {steps.includes('hashtags') && (
            <TermPicker
              title="Instagram hashtags"
              terms={hashtagTerms.map((k) => k.term)}
              picked={pickedTags}
              onChange={setPickedTags}
              show={(term) => `#${term}`}
            />
          )}
        </div>
      )}
      {overBudget && budget && (
        <p className="term-error" role="status">
          {newTags.length} of the picked hashtags need a new weekly slot and only {budget.free} of {budget.limit} are
          free, so the extra ones will fail.
        </p>
      )}

      <div className="search-actions">
        <button className="quiet solid" type="button" disabled={busy || steps.length === 0} onClick={() => void submit(null)}>
          Run now
        </button>
        <span className="search-or">or start at</span>
        <input
          type="datetime-local"
          aria-label="Start time"
          value={when}
          min={earliest}
          onChange={(event) => setWhen(event.target.value)}
        />
        <button className="quiet" type="button" disabled={busy || steps.length === 0 || !when} onClick={() => void submit(when)}>
          Schedule
        </button>
      </div>
      {error && (
        <p className="term-error" role="alert">
          {error}
        </p>
      )}
    </section>
  )
}

/** One step as a bar, like an Insights row: name, track, and the percent done as a numeral. */
function StepBar({ step }: { step: JobStep }) {
  const counting = step.status === 'running' && step.total === null
  let percent: number | null = null
  if (step.total) percent = Math.round((100 * (step.done ?? 0)) / step.total)
  else if (step.total === 0 && ['ok', 'partial'].includes(step.status)) percent = 100

  const meta: string[] = []
  if (step.total) meta.push(`${step.done ?? 0} of ${step.total}`)
  if (step.total === 0 && step.status !== 'running') meta.push('nothing to do')
  if (step.detail && step.status === 'running') meta.push(step.detail)
  if (counting) meta.push('counting')

  return (
    <li className={`step-bar step-${step.status}`}>
      <span className="bar-label">{step.label}</span>
      <span className="bar-track">
        <span className={counting ? 'bar-fill counting' : 'bar-fill'} style={{ width: `${percent ?? 0}%` }} />
      </span>
      <span className="bar-value">{percent === null ? '—' : percent}</span>
      <span className="bar-meta">
        <StatusBadge status={step.status} />
        {meta.length > 0 && <span>{meta.join(', ')}</span>}
        {step.message && <span className="step-message">{step.message}</span>}
      </span>
    </li>
  )
}

function RunningSearch({ job }: { job: Job }) {
  const terms = [...job.youtube_terms, ...job.hashtags.map((tag) => `#${tag}`)]
  return (
    <div className="running-search">
      <p className="meta-line">
        <StatusBadge status={job.status} />
        <span>{job.status === 'running' ? `Started ${relativeTime(job.started_at)}` : 'Starting'}</span>
        {terms.length > 0 && <span>Terms: {terms.join(', ')}</span>}
      </p>
      <ul className="bars">
        {job.steps.map((step) => (
          <StepBar key={step.step} step={step} />
        ))}
      </ul>
    </div>
  )
}

function ScheduledTable({ jobs, onCancel }: { jobs: Job[]; onCancel: (job: Job) => void }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Starts</th>
            <th>Steps</th>
            <th>Terms</th>
            <th>
              <span className="visually-hidden">Cancel</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {jobs.map((job) => (
            <tr key={job.id}>
              <td>
                <strong>{dateTime(job.run_at)}</strong>
                <small>{untilTime(job.run_at)}</small>
              </td>
              <td>{stepLabels(job)}</td>
              <td>{[...job.youtube_terms, ...job.hashtags.map((tag) => `#${tag}`)].join(', ') || '—'}</td>
              <td>
                <button className="link-button term-delete" onClick={() => onCancel(job)}>
                  Cancel
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** Finished searches. A step's dot shows how it went; its tooltip has the details. */
function HistoryTable({ jobs }: { jobs: Job[] }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Finished</th>
            <th>Result</th>
            <th>Steps</th>
          </tr>
        </thead>
        <tbody>
          {jobs.map((job) => (
            <tr key={job.id}>
              <td>
                <strong>{relativeTime(job.finished_at ?? job.started_at ?? job.run_at)}</strong>
                <small>{dateTime(job.finished_at ?? job.run_at)}</small>
              </td>
              <td>
                <StatusBadge status={job.status} />
                <small>{job.message}</small>
              </td>
              <td>
                <span className="flags">
                  {job.steps.map((step) => (
                    <span
                      key={step.step}
                      className={`flag tone-${statusTone(step.status)}`}
                      title={`${step.status}: ${step.message ?? 'no details'}`}
                    >
                      {step.label}
                    </span>
                  ))}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function Search() {
  const jobs = useFetch<Job[]>(`${jobsUrl}?limit=30`)
  const keywords = useFetch<Keyword[]>(keywordsUrl)
  const budget = useFetch<HashtagBudget>(hashtagBudgetUrl)
  const [cancelError, setCancelError] = useState<string | null>(null)
  // The clock moves with each poll, so a due search moves from Scheduled to Running.
  const [now, setNow] = useState(() => Date.now())
  const refresh = () => {
    setNow(Date.now())
    jobs.reload()
  }

  const all = jobs.data ?? []
  const active = all.filter((job) => isActive(job, now)).reverse() // oldest first: the order they run
  const scheduled = all.filter((job) => job.status === 'scheduled' && !isActive(job, now)).reverse()
  const history = all.filter((job) => !['scheduled', 'running'].includes(job.status))
  // Poll fast only while something runs. The budget changes when a hashtag search ends.
  useInterval(() => {
    refresh()
    if (active.length > 0) budget.reload()
  }, active.length > 0 ? FAST_POLL_MS : SLOW_POLL_MS)

  async function cancel(job: Job) {
    if (!window.confirm(`Cancel the search planned for ${dateTime(job.run_at)}?`)) return
    setCancelError(null)
    try {
      await sendJson('DELETE', jobUrl(job.id))
    } catch (failure) {
      setCancelError((failure as Error).message)
    }
    refresh()
  }

  return (
    <>
      <p className="summary">
        Collect new posts now or at a set time. Pick the steps and the terms; the steps run in order, and each one shows
        its progress here. Scheduled searches run while the app server is on, and one that was missed starts when it
        comes back.
      </p>

      {jobs.error && <ErrorBox message={jobs.error} onRetry={jobs.reload} />}
      {active.length > 0 && (
        <section aria-live="polite">
          <h3>Running</h3>
          {active.map((job) => (
            <RunningSearch key={job.id} job={job} />
          ))}
        </section>
      )}

      {keywords.error && <ErrorBox message={keywords.error} onRetry={keywords.reload} />}
      {!keywords.error && !keywords.data && <Loading what="Loading search terms" />}
      {keywords.data && <NewSearch keywords={keywords.data} budget={budget.data} onCreated={refresh} />}

      {!jobs.error && !jobs.data && <Loading what="Loading searches" />}
      {jobs.data && (
        <>
          <h3>Scheduled</h3>
          {cancelError && (
            <p className="term-error" role="alert">
              {cancelError}
            </p>
          )}
          {scheduled.length === 0 ? (
            <p className="summary">Nothing is scheduled. Pick a start time above to plan a search.</p>
          ) : (
            <ScheduledTable jobs={scheduled} onCancel={(job) => void cancel(job)} />
          )}

          <details className="dropdown-section">
            <summary>Past searches ({history.length})</summary>
            {history.length === 0 ? (
              <p className="summary">No search has finished yet.</p>
            ) : (
              <HistoryTable jobs={history} />
            )}
          </details>
        </>
      )}
    </>
  )
}
