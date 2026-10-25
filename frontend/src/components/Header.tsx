import { useApp } from '../context.ts'
import { compactNumber, relativeTime } from '../format.ts'
import { TABS } from '../url.ts'
import { AppLink } from './AppLink.tsx'

export function Header() {
  const { meta, state, update } = useApp()
  // Competitors and Sources are not split by platform.
  const platformMatters = state.tab === 'content' || state.tab === 'insights'

  return (
    <header className="masthead">
      <div className="masthead-top">
        <h1 className="wordmark">Competitor Content Intelligence</h1>
        <p className="status">
          {meta.counts.competitors} competitors, {compactNumber(meta.counts.posts)} posts, updated{' '}
          {relativeTime(meta.last_updated)}
        </p>
      </div>

      <div className="masthead-bar">
        <nav className="tabs" aria-label="Sections">
          {TABS.map((tab) => (
            <AppLink key={tab.id} patch={{ tab: tab.id }} current={tab.id === state.tab}>
              {tab.label}
            </AppLink>
          ))}
        </nav>

        <div className="controls">
          <div className="options" role="toolbar" aria-label="Time window">
            {meta.windows.map((days) => (
              <button
                key={days}
                aria-pressed={days === state.window}
                onClick={() => update({ window: days })}
              >
                {days} days
              </button>
            ))}
          </div>
          <select
            aria-label="Platform"
            value={state.platform}
            disabled={!platformMatters}
            title={platformMatters ? undefined : 'This tab shows all platforms'}
            onChange={(event) => update({ platform: event.target.value })}
          >
            <option value="">All platforms</option>
            {meta.platforms
              .filter((platform) => platform.posts > 0)
              .map((platform) => (
                <option key={platform.id} value={platform.id}>
                  {platform.label}
                </option>
              ))}
          </select>
        </div>
      </div>
    </header>
  )
}
