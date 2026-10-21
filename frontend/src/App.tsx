import { useEffect, useState } from 'react'
import { getHealth } from './api'

export default function App() {
  const [apiStatus, setApiStatus] = useState('checking…')

  useEffect(() => {
    getHealth()
      .then((health) => setApiStatus(health.status))
      .catch((error: Error) => setApiStatus(`unreachable (${error.message})`))
  }, [])

  return (
    <main className="container">
      <h1>Competitor Content Intelligence</h1>
      <p>Public content from life insurance agents, labeled and ranked.</p>
      <p>
        API: <strong>{apiStatus}</strong>
      </p>
    </main>
  )
}
