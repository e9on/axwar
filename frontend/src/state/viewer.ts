import { createContext, createElement, useContext, useEffect, useState, type ReactNode } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api'

export type Person = { name: string; role: string }

type ViewerValue = { person: Person | null; setPerson: (name: string) => void; people: Person[] }

const ViewerContext = createContext<ViewerValue | null>(null)

/** 지금 보는 사람. URL 쿼리 ?as= 와 같이 움직인다. 없거나 모르는 이름이면 목록 첫 사람. */
export function ViewerProvider({ children }: { children: ReactNode }) {
  const [people, setPeople] = useState<Person[]>([])
  const [params, setParams] = useSearchParams()

  useEffect(() => {
    let alive = true
    api.get<Person[]>('/api/people').then(
      (list) => {
        if (alive) setPeople(list)
      },
      () => undefined, // 알림 줄이 이미 보여 줌
    )
    return () => {
      alive = false
    }
  }, [])

  const asked = params.get('as')
  const person = people.find((p) => p.name === asked) ?? people[0] ?? null

  const setPerson = (name: string) => {
    const next = new URLSearchParams(params)
    next.set('as', name)
    setParams(next)
  }

  return createElement(ViewerContext.Provider, { value: { person, setPerson, people } }, children)
}

export function useViewer(): ViewerValue {
  const value = useContext(ViewerContext)
  if (!value) throw new Error('ViewerProvider 안에서 써야 해요')
  return value
}
