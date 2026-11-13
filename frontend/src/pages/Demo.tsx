import { useRef, useState } from 'react'
import { api } from '../api'
import { useClock } from '../state/clock'
import { useDemoRun } from '../state/demoRun'
import { useLoad } from '../state/useLoad'
import { DEMO_MODE } from '../decisions'
import { koDate } from '../date'
import { actionLine } from '../format'
import type { DemoState, Scenario, ScenarioStep, StepOutcome } from '../adminTypes'
import FormDialog from '../components/FormDialog'
import LoadFailed from '../components/LoadFailed'
import './Admin.css'

/** 단계 하나의 결과를 몇 줄 글로. 서버 응답에 있는 항목만 쓴다 */
function outcomeLines(o: StepOutcome): string[] {
  const lines: string[] = []
  if (o.ignored) lines.push(`저장하지 않았어요: ${o.reason ?? '이미 처리된 요청'}`)
  if (o.status) lines.push(`건 상태: ${o.status}${o.changed === false ? ' (그대로)' : ''}`)
  if (o.judgment?.stance) lines.push(`AI 해석: ${o.judgment.stance}`)
  for (const a of o.actions ?? []) lines.push(actionLine(a))
  if (lines.length === 0) lines.push('바뀐 것이 없어요')
  return lines
}

function who(step: ScenarioStep): string {
  return step.actor ?? step.dept ?? '—'
}

function target(step: ScenarioStep): string {
  return step.plan ?? step.contract ?? ''
}

function DemoPanel() {
  const { date, refresh, advance } = useClock()
  const { run, setRun } = useDemoRun()
  const scenes = useLoad<Scenario[]>('/api/demo/scenarios', [])
  const position = useLoad<DemoState>('/api/demo/state', [])
  const [asking, setAsking] = useState<Scenario | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const guard = useRef(false)

  // 진행 위치는 서버가 기억한다(새로고침해도 그대로). 이 접속에서 받은 결과 글은 같은 장면일 때만 붙인다.
  const where = position.data
  const active = scenes.data?.find((s) => s.name === where?.scenario) ?? null
  const script = active?.script ?? []
  const done = where?.done ?? 0
  const finished = !!active && !!where?.finished
  const outcomes = run.scenario === where?.scenario ? run.outcomes : {}
  const dates = Array.from(new Set(script.map((s) => s.date).filter((d): d is string => !!d))).sort()

  async function guarded(job: () => Promise<void>, onError?: (message: string) => void) {
    if (guard.current) return
    guard.current = true
    setBusy(true)
    setError(null)
    try {
      await job()
    } catch (e) {
      const message = (e as Error).message
      setError(message)
      onError?.(message)
    } finally {
      guard.current = false
      setBusy(false)
    }
  }

  /** 서버의 진행 위치와 기준일을 다시 읽는다(중간에 멈춰도 지금까지의 위치로 맞춘다) */
  const sync = () => Promise.all([position.retry(), refresh()])

  const reset = (scene: Scenario) =>
    guarded(
      async () => {
        await api.post('/api/demo/reset', { scenario: scene.name })
        setRun({ scenario: scene.name, outcomes: {} })
        setAsking(null)
        await sync()
      },
      () => undefined,
    )

  const playOne = () =>
    guarded(async () => {
      if (!active || finished) return
      try {
        const out = await api.post<StepOutcome>('/api/demo/play', { step: script[done] })
        setRun((r) => ({ scenario: active.name, outcomes: { ...(r.scenario === active.name ? r.outcomes : {}), [done]: out } }))
      } finally {
        await sync()
      }
    })

  // 끝까지: 서버에 지금 위치(from_step)를 알려 남은 단계만 돌린다
  const playAll = () =>
    guarded(async () => {
      if (!active || finished) return
      try {
        const outs = await api.post<StepOutcome[]>('/api/demo/run', { scenario: active.name, from_step: done })
        setRun((r) => ({
          scenario: active.name,
          outcomes: { ...(r.scenario === active.name ? r.outcomes : {}), ...Object.fromEntries(outs.map((o, i) => [done + i, o])) },
        }))
      } finally {
        await sync()
      }
    })

  return (
    <main className="admin">
      <h1>시연 조작판</h1>
      <p className="lead">장면을 고르면 시연 데이터를 지우고 처음부터 시작해요. 한 단계씩 또는 끝까지 진행하면 메인과 건 상세가 새 기준일로 다시 읽혀요.</p>

      <section aria-label="장면 목록">
        <h2>장면</h2>
        {scenes.error ? (
          <LoadFailed retry={scenes.retry} message={`장면을 불러오지 못했어요. ${scenes.error}`} />
        ) : !scenes.data ? (
          <p role="status" className="muted">
            불러오는 중…
          </p>
        ) : scenes.data.length === 0 ? (
          <p className="muted">시연 장면이 없어요</p>
        ) : (
          <ul className="scenes">
            {scenes.data.map((s) => (
              <li key={s.name}>
                <button type="button" className="scene" aria-pressed={s.name === where?.scenario} disabled={busy} onClick={() => setAsking(s)}>
                  <span className="k">{s.title}</span>
                  <span className="sub" title={s.description}>{s.description}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      {active && (
        <section aria-label="진행">
          <h2>{active.title}</h2>
          <p className="scene-desc">{active.description}</p>
          <div className="bar-tools">
            <button type="button" className="btn pri" disabled={busy || finished} onClick={playOne}>
              한 단계 진행
            </button>
            <button type="button" className="btn" disabled={busy || finished} onClick={playAll}>
              끝까지
            </button>
            <button type="button" className="btn deny" disabled={busy} onClick={() => setAsking(active)}>
              처음부터
            </button>
            <span className="muted" role="status">
              {busy ? '진행 중…' : `${done} / ${script.length}단계 진행`}
            </span>
          </div>
          {error && (
            <p className="err" role="alert">
              {error}
            </p>
          )}

          {dates.length > 0 && (
            <div className="bar-tools">
              <span className="muted">기준일 바로 이동</span>
              <span className="dates">
                {dates.map((d) => (
                  <button
                    key={d}
                    type="button"
                    className="btn small"
                    disabled={busy || (!!date && d < date)}
                    aria-label={`기준일을 ${d}로 이동`}
                    onClick={() => advance(d)}
                  >
                    {koDate(d)}
                  </button>
                ))}
              </span>
            </div>
          )}

          <ul className="ledger steps" aria-label="대본 단계">
            {script.map((s, i) => {
              const out = outcomes[i]
              const next = i === done
              return (
                <li key={i} data-next={next}>
                  <span className="no">{i + 1}</span>
                  <div>
                    <span className="k">{s.action}</span>
                    {i < done && <span className="state">진행함</span>}
                    {next && !finished && <span className="next">다음</span>}
                    <div className="sub">
                      {[s.date ? s.date : '날짜 그대로', who(s), target(s)].filter(Boolean).join(' · ')}
                    </div>
                    {out && (
                      <ul className="result">
                        {outcomeLines(out).map((line, j) => (
                          <li key={j}>{line}</li>
                        ))}
                      </ul>
                    )}
                  </div>
                </li>
              )
            })}
          </ul>
        </section>
      )}

      {asking && (
        <FormDialog
          title="장면 불러오기"
          confirmLabel="초기화하고 시작"
          tone="deny"
          busy={busy}
          error={error}
          onConfirm={() => reset(asking)}
          onCancel={() => {
            setAsking(null)
            setError(null)
          }}
        >
          <p>
            <b>{asking.title}</b>을(를) 시작하면 시연 데이터가 지워져요. 지금까지 진행한 것은 사라지고 장면 처음으로 돌아가요.
          </p>
        </FormDialog>
      )}
    </main>
  )
}

export default function Demo() {
  const { mode } = useClock()
  if (mode === null) {
    return (
      <main className="admin">
        <h1>시연 조작판</h1>
        <p role="status" className="muted">
          불러오는 중…
        </p>
      </main>
    )
  }
  if (mode !== DEMO_MODE) {
    return (
      <main className="admin">
        <h1>시연 조작판</h1>
        <p className="note">시연 조작판은 시연 모드에서만 쓸 수 있어요. 지금은 {mode} 모드예요.</p>
      </main>
    )
  }
  return <DemoPanel />
}
