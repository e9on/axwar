import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../api'

type Loaded<T> = { data: T | null; error: string | null; /** 실패한 응답의 HTTP 상태(연결 실패는 0) */ status: number | null; loading: boolean; /** 다시 읽는다. 돌려주는 약속은 그 읽기가 끝나면(성공이든 실패든) 풀린다 */ retry: () => Promise<void> }
type State<T> = { data: T | null; error: string | null; status: number | null; loading: boolean; path: string | null }

/** path를 읽는다. path나 deps(기준일 version 등)가 바뀌면 다시 읽는다. path가 null이면 기다린다.
 *  deps만 바뀌면 다시 읽는 동안 이전 데이터를 그대로 두고(화면이 깜빡이지 않게), path가 바뀌면 비운다. */
export function useLoad<T>(path: string | null, deps: unknown[]): Loaded<T> {
  const [state, setState] = useState<State<T>>({ data: null, error: null, status: null, loading: true, path })
  const [tries, setTries] = useState(0)
  const waiters = useRef<(() => void)[]>([])
  const settle = () => {
    waiters.current.splice(0).forEach((done) => done())
  }

  useEffect(() => {
    if (path === null) {
      settle()
      return
    }
    let alive = true
    setState((s) => ({ data: s.path === path ? s.data : null, error: null, status: null, loading: true, path }))
    api.get<T>(path).then(
      (data) => {
        if (!alive) return
        setState({ data, error: null, status: null, loading: false, path })
        settle()
      },
      (e: Error) => {
        if (!alive) return
        setState({ data: null, error: e.message, status: e instanceof ApiError ? e.status : null, loading: false, path })
        settle()
      },
    )
    return () => {
      alive = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, tries, ...deps])

  const retry = useCallback(
    () =>
      new Promise<void>((done) => {
        waiters.current.push(done)
        setTries((n) => n + 1)
      }),
    [],
  )
  return { data: state.data, error: state.error, status: state.status, loading: state.loading, retry }
}
