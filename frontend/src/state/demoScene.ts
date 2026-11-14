import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import { addDays } from '../date'
import { DEMO_MODE } from '../decisions'
import { useClock } from './clock'
import { useDemoRun } from './demoRun'
import { useViewer } from './viewer'
import type { AdvanceReply, DemoState } from '../adminTypes'

/** ▶ 진행이 하루를 넘기는 간격(밀리초). 시험은 환경값 VITE_DEMO_TICK_MS 로 짧게 바꾼다 */
const DEFAULT_TICK_MS = 1000
/** 알림 줄이 떠 있는 시간(밀리초) */
const NOTICE_MS = 2500

function tickMs(): number {
  const given = Number((import.meta.env as Record<string, string | undefined>).VITE_DEMO_TICK_MS)
  return Number.isFinite(given) && given > 0 ? given : DEFAULT_TICK_MS
}

/** 메인의 시연 막대가 쓰는 상태와 동작. 시연 모드에서 진행 중인 장면이 있을 때만 scene이 채워진다 */
export function useDemoScene() {
  const { date, mode, version, refresh } = useClock()
  const { person, setPerson } = useViewer()
  const { run, setRun } = useDemoRun()
  const [state, setState] = useState<DemoState | null>(null)
  const [running, setRunning] = useState(false)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<AdvanceReply | null>(null)
  const [last, setLast] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const guard = useRef(false)
  const demo = mode === DEMO_MODE

  // 진행 위치는 서버가 기억한다. 조용히 읽는다(시연이 아닌 화면의 알림 줄을 건드리지 않게)
  useEffect(() => {
    if (!demo) {
      setState(null)
      return
    }
    let alive = true
    fetch('/api/demo/state')
      .then((r) => (r.ok ? r.json() : null))
      .then((d: DemoState | null) => alive && setState(d && d.scenario ? d : null))
      .catch(() => undefined)
    return () => {
      alive = false
    }
  }, [demo, version])

  useEffect(() => {
    if (!notice) return
    const t = setTimeout(() => setNotice(null), NOTICE_MS)
    return () => clearTimeout(t)
  }, [notice])

  const go = useCallback(
    async (to: string) => {
      if (guard.current) return
      guard.current = true
      setBusy(true)
      setError(null)
      try {
        const reply = await api.post<AdvanceReply>('/api/demo/advance', { date: to })
        const { applied = [], skipped, actions = [], ...pos } = reply
        void skipped
        const waiting = pos.waiting ?? null
        const next = pos.next_date ?? null
        setState((s) => (s ? { ...s, ...pos, waiting, next_date: next } : s))
        const lines = [...applied, ...actions.map((a) => a.text)]
        if (lines.length > 0) {
          setNotice(reply)
          setLast(lines[lines.length - 1])
        }
        await refresh()
        if (waiting?.ready) {
          setRunning(false)
          setRun((r) => ({ ...r, paused: 'decide' }))
          if (waiting.actor) setPerson(waiting.actor)
        } else if (!waiting && !next) {
          setRunning(false)
        }
      } catch (e) {
        setRunning(false)
        setError((e as Error).message)
      } finally {
        guard.current = false
        setBusy(false)
      }
    },
    [refresh, setPerson, setRun],
  )

  // 진행 중이면 한 번에 하루씩, 정해진 간격으로
  const goRef = useRef(go)
  goRef.current = go
  useEffect(() => {
    if (!running || busy || !date) return
    const t = setTimeout(() => void goRef.current(addDays(date, 1)), tickMs())
    return () => clearTimeout(t)
  }, [running, busy, date])

  const waiting = state?.waiting ?? null
  const nextDate = state?.next_date ?? null
  const ended = !!state && !waiting && !nextDate

  return {
    scene: state,
    date,
    person,
    waiting,
    nextDate,
    ended,
    running,
    busy,
    notice,
    error,
    /** 끝났을 때 보이는 결과 한 줄: 서버가 준 장면 건들의 지금 상태, 없으면 이번 접속에서 본 마지막 일이나 마지막 도착 사건 */
    result: state?.outcome?.length ? `결과: ${state.outcome.join(', ')}` : (last ?? state?.arrived?.[(state.arrived?.length ?? 0) - 1] ?? null),
    /** 결정을 기다리느라 멈췄다가 돌아왔는지 */
    decided: run.paused === 'decide' && !(waiting?.ready),
    highlightRef: waiting?.ready ? (waiting.target ?? null) : null,
    toggle: () => {
      if (running) {
        setRunning(false)
        return
      }
      if (!date || ended) return
      setRun((r) => ({ ...r, paused: null }))
      setRunning(true)
      void go(addDays(date, 1))
    },
    nextDay: () => {
      if (!date) return
      setRun((r) => ({ ...r, paused: null }))
      void go(addDays(date, 1))
    },
    toNextEvent: () => {
      if (!nextDate) return
      setRun((r) => ({ ...r, paused: null }))
      void go(nextDate)
    },
    switchTo: (name: string) => setPerson(name),
  }
}

/** 장면을 처음부터 시작한다: 초기화하고, 첫 결정권자로 바꿔 메인으로 간다 */
export function useStartScene() {
  const { refresh } = useClock()
  const { setRun } = useDemoRun()
  const { person } = useViewer()
  const navigate = useNavigate()
  return async (name: string, script: { action: string; actor?: string | null }[] = []) => {
    await api.post('/api/demo/reset', { scenario: name })
    setRun({ scenario: name, outcomes: {}, advanced: null, paused: null })
    const st = await api.get<DemoState>('/api/demo/state')
    const who = st.waiting?.actor ?? script.find((s) => s.action === '결정' && s.actor)?.actor ?? script.find((s) => s.actor)?.actor ?? person?.name ?? null
    await refresh()
    navigate(who ? `/?as=${encodeURIComponent(who)}` : '/')
  }
}
