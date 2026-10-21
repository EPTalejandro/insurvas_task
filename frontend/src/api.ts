// Thin wrappers around fetch. Paths are relative so the Vite proxy handles them in dev.
export async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path)
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`)
  return response.json() as Promise<T>
}

export type Health = { status: string }

export const getHealth = () => getJson<Health>('/api/health')
