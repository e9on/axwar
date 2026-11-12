import { useCallback, useEffect, useState } from 'react'
import { api } from '../api'

type Loaded<T> = { data: T | null; error: string | null; loading: boolean; retry: () => void }

/** path를 읽는다. path나 deps(기준일 version 등)가 바뀌면 다시 읽는다. path가 null이면 기다린다. */
export function useLoad<T>(path: string | null, deps: unknown[]): Loaded<T> {
  const [state, setState] = useState<{ data: T | null; error: string | null; loading: boolean }>({ data: null, error: null, loading: true })
  const [tries, setTries] = useState(0)

  useEffect(() => {
    if (path === null) return
    let alive = true
    setState((s) => ({ ...s, error: null, loading: true }))
    api.get<T>(path).then(
      (data) => alive && setState({ data, error: null, loading: false }),
      (e: Error) => alive && setState({ data: null, error: e.message, loading: false }),
    )
    return () => {
      alive = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, tries, ...deps])

  const retry = useCallback(() => setTries((n) => n + 1), [])
  return { ...state, retry }
}
