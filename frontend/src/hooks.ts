import { useEffect, useState } from 'react'
import { getJson } from './api.ts'

interface Result<T> {
  url: string | null
  data: T | null
  error: string | null
}

/**
 * Load JSON from an API url. A new url starts a new request; an answer to an old url is
 * ignored. While loading, the previous data stays available, so the screen does not flash.
 */
export function useFetch<T>(url: string): {
  data: T | null
  error: string | null
  loading: boolean
  reload: () => void
} {
  const [result, setResult] = useState<Result<T>>({ url: null, data: null, error: null })
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let cancelled = false
    getJson<T>(url)
      .then((data) => {
        if (!cancelled) setResult({ url, data, error: null })
      })
      .catch((error: Error) => {
        if (!cancelled) setResult({ url, data: null, error: error.message })
      })
    return () => {
      cancelled = true
    }
  }, [url, attempt])

  return {
    data: result.data,
    error: result.url === url ? result.error : null,
    loading: result.url !== url,
    reload: () => {
      setResult((previous) => ({ ...previous, url: null }))
      setAttempt((n) => n + 1)
    },
  }
}
