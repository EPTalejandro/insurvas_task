import { metaUrl } from './api.ts'
import { Competitors } from './components/Competitors.tsx'
import { Header } from './components/Header.tsx'
import { Insights } from './components/Insights.tsx'
import { Sources } from './components/Sources.tsx'
import { ErrorBox, Loading } from './components/StateViews.tsx'
import { TopContent } from './components/TopContent.tsx'
import { AppContext } from './context.ts'
import { useFetch } from './hooks.ts'
import type { Meta } from './types.ts'
import { useUrlState } from './url.ts'

export default function App() {
  const { state, update, href } = useUrlState()
  const { data: meta, error, reload } = useFetch<Meta>(metaUrl)

  // Nothing can be shown before we know the windows, platforms and labels.
  if (error) {
    return (
      <main className="page">
        <h1>Competitor Content Intelligence</h1>
        <ErrorBox message={`The API is not answering (${error}). Is the backend running?`} onRetry={reload} />
      </main>
    )
  }
  if (!meta) {
    return (
      <main className="page">
        <Loading what="Loading" />
      </main>
    )
  }

  return (
    <AppContext.Provider value={{ meta, state, update, href }}>
      <main className="page">
        <Header />
        {state.tab === 'content' && <TopContent />}
        {state.tab === 'competitors' && <Competitors />}
        {state.tab === 'insights' && <Insights />}
        {state.tab === 'sources' && <Sources />}
      </main>
    </AppContext.Provider>
  )
}
