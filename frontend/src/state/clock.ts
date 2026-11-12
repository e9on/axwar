import { createContext, createElement, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { api } from '../api'

type ClockReply = { date: string; mode: string }

type ClockValue = {
  date: string | null
  mode: string | null
  /** 기준일이 바뀔 때마다 1씩 커지는 숫자. 다른 화면은 이 값이 바뀌면 다시 읽는다. */
  version: number
  advance: (to: string) => Promise<void>
}

const ClockContext = createContext<ClockValue | null>(null)

export function ClockProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<{ date: string | null; mode: string | null }>({ date: null, mode: null })
  const [version, setVersion] = useState(0)

  useEffect(() => {
    let alive = true
    api.get<ClockReply>('/api/clock').then(
      (reply) => {
        if (alive) setState({ date: reply.date, mode: reply.mode })
      },
      () => undefined,
    )
    return () => {
      alive = false
    }
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

  return createElement(ClockContext.Provider, { value: { ...state, version, advance } }, children)
}

export function useClock(): ClockValue {
  const value = useContext(ClockContext)
  if (!value) throw new Error('ClockProvider 안에서 써야 해요')
  return value
}
