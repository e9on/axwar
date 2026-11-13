import { createContext, createElement, useContext, useState, type ReactNode } from 'react'
import type { StepOutcome } from '../adminTypes'

/** 시연 조작판이 어디까지 진행했는지. 다른 화면에 갔다 와도 남도록 앱 바깥 층에 둔다(서버 상태는 서버에 있다). */
export type DemoRun = { scenario: string | null; done: number; outcomes: StepOutcome[] }

type Value = { run: DemoRun; setRun: (next: DemoRun | ((prev: DemoRun) => DemoRun)) => void }

const EMPTY: DemoRun = { scenario: null, done: 0, outcomes: [] }
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
