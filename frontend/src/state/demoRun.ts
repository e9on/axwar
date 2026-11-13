import { createContext, createElement, useContext, useState, type ReactNode } from 'react'
import type { AdvanceReply, StepOutcome } from '../adminTypes'

/** 시연 조작판이 이번 접속에서 받은 단계별 결과. 진행 위치는 서버가 기억하고(GET /api/demo/state),
 *  여기에는 다른 화면에 갔다 와도 남도록 결과 글만 앞단 층에 둔다. 새로고침하면 결과 글은 비고 위치는 서버 값이다. */
export type DemoRun = { scenario: string | null; outcomes: Record<number, StepOutcome>; advanced?: AdvanceReply | null }

type Value = { run: DemoRun; setRun: (next: DemoRun | ((prev: DemoRun) => DemoRun)) => void }

const EMPTY: DemoRun = { scenario: null, outcomes: {} }
const Context = createContext<Value | null>(null)

export function DemoRunProvider({ children }: { children: ReactNode }) {
  const [run, setRun] = useState<DemoRun>(EMPTY)
  return createElement(Context.Provider, { value: { run, setRun } }, children)
}

export function useDemoRun(): Value {
  const value = useContext(Context)
  if (!value) throw new Error('DemoRunProvider 안에서 써야 해요')
  return value
}
