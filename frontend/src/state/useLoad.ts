import { useCallback, useEffect, useState } from 'react'
import { api } from '../api'

type Loaded<T> = { data: T | null; error: string | null; loading: boolean; retry: () => void }
type State<T> = { data: T | null; error: string | null; loading: boolean; path: string | null }

/** path를 읽는다. path나 deps(기준일 version 등)가 바뀌면 다시 읽는다. path가 null이면 기다린다.
 *  deps만 바뀌면 다시 읽는 동안 이전 데이터를 그대로 두고(화면이 깜빡이지 않게), path가 바뀌면 비운다. */
export function useLoad<T>(path: string | null, deps: unknown[]): Loaded<T> {
  const [state, setState] = useState<State<T>>({ data: null, error: null, loading: true, path })
  const [tries, setTries] = useState(0)

  useEffect(() => {
    if (path === null) return
    let alive = true
    setState((s) => ({ data: s.path === path ? s.data : null, error: null, loading: true, path }))
    api.get<T>(path).then(
      (data) => alive && setState({ data, error: null, loading: false, path }),
      (e: Error) => alive && setState({ data: null, error: e.message, loading: false, path }),
    )
    return () => {
      alive = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, tries, ...deps])

  const retry = useCallback(() => setTries((n) => n + 1), [])
  return { data: state.data, error: state.error, loading: state.loading, retry }
}
