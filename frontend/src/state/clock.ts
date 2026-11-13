import { createContext, createElement, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { api } from '../api'

type ClockReply = { date: string; mode: string }

type ClockValue = {
  date: string | null
  mode: string | null
  /** 기준일이 바뀔 때마다 1씩 커지는 숫자. 다른 화면은 이 값이 바뀌면 다시 읽는다. */
  version: number
  /** 기준일을 읽지 못했는지, 다시 읽기 */
  failed: boolean
  retry: () => void
  advance: (to: string) => Promise<void>
  /** 서버의 기준일·모드를 다시 읽고 version을 올려 다른 화면이 다시 읽게 한다(시연 진행·모드 전환 뒤). */
  refresh: () => Promise<void>
}

const ClockContext = createContext<ClockValue | null>(null)

export function ClockProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<{ date: string | null; mode: string | null }>({ date: null, mode: null })
  const [version, setVersion] = useState(0)
  const [failed, setFailed] = useState(false)
  const [tries, setTries] = useState(0)

  useEffect(() => {
    let alive = true
    api.get<ClockReply>('/api/clock').then(
      (reply) => {
        if (alive) {
          setState({ date: reply.date, mode: reply.mode })
          setFailed(false)
        }
      },
      () => alive && setFailed(true), // 알림 줄도 보여 줌
    )
    return () => {
      alive = false
    }
  }, [tries])

  const retry = useCallback(() => {
    setFailed(false)
    setTries((n) => n + 1)
  }, [])

  const advance = useCallback(async (to: string) => {
    try {
      const reply = await api.post<ClockReply>('/api/clock', { date: to })
      setState({ date: reply.date, mode: reply.mode })
      setVersion((v) => v + 1)
    } catch {
      // 알림 줄이 이미 보여 줌
    }
  }, [])

  const refresh = useCallback(async () => {
    try {
      const reply = await api.get<ClockReply>('/api/clock')
      setState({ date: reply.date, mode: reply.mode })
      setFailed(false)
      setVersion((v) => v + 1)
    } catch {
      setFailed(true) // 알림 줄이 이미 보여 줌
    }
  }, [])

  return createElement(ClockContext.Provider, { value: { ...state, version, failed, retry, advance, refresh } }, children)
}

export function useClock(): ClockValue {
  const value = useContext(ClockContext)
  if (!value) throw new Error('ClockProvider 안에서 써야 해요')
  return value
}
