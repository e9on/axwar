import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import { useClock } from '../state/clock'
import { useDemoRun } from '../state/demoRun'
import { useViewer } from '../state/viewer'
import { useLoad } from '../state/useLoad'
import { DEMO_MODE } from '../decisions'
import { addDays, koDate } from '../date'
import { ga, plainLine, sceneSummary, shortTitle, stepSentence } from '../copy'
import { actionLine, josa } from '../format'
import type { CaseListRow } from '../caseTypes'
import type { AdvanceReply, DemoState, Scenario, StepOutcome } from '../adminTypes'
import FormDialog from '../components/FormDialog'
import LoadFailed from '../components/LoadFailed'
import './Admin.css'

/** 단계 하나의 결과를 몇 줄 글로. 서버 응답에 있는 항목만 쓴다 */
function outcomeLines(o: StepOutcome): string[] {
  const lines: string[] = []
  if (o.ignored) lines.push(`저장하지 않았어요: ${plainLine(o.reason ?? '', 80) || '이미 처리된 요청'}`)
  if (o.status) lines.push(`건 상태: ${o.status}${o.changed === false ? ' (그대로)' : ''}`)
  if (o.judgment?.stance) lines.push(`AI 해석: ${o.judgment.stance}`)
  for (const a of o.actions ?? []) lines.push(actionLine({ ...a, text: plainLine(a.text, 80) }))
  if (lines.length === 0) lines.push('바뀐 것이 없어요')
  return lines
}

function DemoPanel() {
  const { date, refresh, advance } = useClock()
  const { setPerson } = useViewer()
  const navigate = useNavigate()
  const { run, setRun } = useDemoRun()
  const caseRows = useLoad<CaseListRow[]>('/api/cases', [])
  const [target, setTarget] = useState('')
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
  const dates = Array.from(new Set([...script.map((s) => s.date).filter((d): d is string => !!d), ...(date ? [date] : [])])).sort()
  const kindsOn = (d: string) => Array.from(new Set(script.filter((s) => s.date === d).map((s) => s.action))).join('·')
  const nextDate = where?.next_date ?? null
  const waiting = where?.waiting ?? null
  const notice = run.scenario === where?.scenario ? (run.advanced ?? null) : null

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
  const sync = () => Promise.all([position.retry(), caseRows.retry(), refresh()])

  const reset = (scene: Scenario) =>
    guarded(
      async () => {
        await api.post('/api/demo/reset', { scenario: scene.name })
        setRun({ scenario: scene.name, outcomes: {}, advanced: null })
        setAsking(null)
        await sync()
      },
      () => undefined,
    )

  /** 날짜로 진행: 그 날까지 도착할 회신·리뷰·반품·판매를 서버가 넣고, 결정은 시연자가 누른다 */
  const advanceTo = (to: string) =>
    guarded(async () => {
      if (!active) {
        await advance(to)
        return
      }
      try {
        const reply = await api.post<AdvanceReply>('/api/demo/advance', { date: to })
        setRun((r) => ({ scenario: active.name, outcomes: r.scenario === active.name ? r.outcomes : {}, advanced: reply }))
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
          advanced: r.scenario === active.name ? r.advanced : null,
        }))
      } finally {
        await sync()
      }
    })

  const byRef = new Map((caseRows.data ?? []).map((c) => [c.ref_id, c]))
  const nameOf = (ref: string | undefined) => (ref ? shortTitle(byRef.get(ref)?.title, ref) : '')
  const guideCase = waiting?.ready && waiting.target ? byRef.get(waiting.target) : undefined
  const fullName = guideCase?.title || guideCase?.ref_id || ''
  const goAs = () => {
    if (!waiting?.actor || !guideCase) return
    setPerson(waiting.actor)
    navigate(`/cases/${guideCase.id}?as=${encodeURIComponent(waiting.actor)}`)
  }

  return (
    <main className="admin">
      <h1>시연 조작판</h1>
      <p className="lead">장면을 고르고 날짜를 넘기며 진행하세요. 회신은 날짜가 되면 저절로 오고, 결정만 직접 눌러요.</p>

      <section className="date-line" aria-label="기준일">
        <span>
          기준일 <b>{date ? koDate(date) : '불러오는 중'}</b>
        </span>
        <button type="button" className="btn small" disabled={!date || busy} onClick={() => date && advanceTo(addDays(date, 1))} title="기준일을 하루 뒤로 옮겨요">
          다음 날로
        </button>
        <input type="date" lang="ko" aria-label="이동할 날짜" value={target} onChange={(e) => setTarget(e.target.value)} />
        <button type="button" className="btn small" disabled={!target} onClick={() => advanceTo(target)}>
          날짜로 이동
        </button>
      </section>

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
                  <span className="sub">{s.summary?.trim() || sceneSummary(s.name, s.description)}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      {active && (
        <section aria-label="진행">
          <h2>{active.title}</h2>
          <details className="scene-more">
            <summary>자세히</summary>
            <p className="scene-desc">{active.description}</p>
          </details>
          <div className="bar-tools">
            <button type="button" className="btn pri" disabled={busy || !nextDate} onClick={() => nextDate && advanceTo(nextDate)}>
              {nextDate ? `다음 날짜로 (${koDate(nextDate)})` : '다음 날짜로'}
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
            <ol className="date-strip" aria-label="날짜 띠">
              {dates.map((d) => {
                const isToday = !!date && d === date
                const past = !!date && d < date
                const kinds = kindsOn(d)
                return (
                  <li key={d} data-today={isToday} data-past={past}>
                    {isToday ? (
                      <span className="dot-now">
                        <b>오늘 {koDate(d)}</b>
                        {kinds && <span className="ev">{kinds}</span>}
                      </span>
                    ) : (
                      <button type="button" className="dot-btn" disabled={busy || past} aria-label={`${koDate(d)}로 넘기기${kinds ? ` (${kinds})` : ''}`} onClick={() => advanceTo(d)}>
                        <span>{koDate(d)}</span>
                        {kinds && <span className="ev">{kinds}</span>}
                      </button>
                    )}
                  </li>
                )
              })}
            </ol>
          )}

          {notice && (notice.applied.length > 0 || notice.actions.length > 0 || notice.skipped.length > 0) && (
            <div className="advance-notice" role="status" aria-label="이번에 일어난 일">
              <ul>
                {notice.applied.map((line, i) => (
                  <li key={`a${i}`}>{line}</li>
                ))}
                {notice.actions.map((a, i) => (
                  <li key={`c${i}`}>{actionLine({ ...a, text: plainLine(a.text, 80) })}</li>
                ))}
                {notice.skipped.map((line, i) => (
                  <li key={`s${i}`} className="muted">
                    {line}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {waiting && waiting.ready && (
            <p className="guide">
              <span>
                <b>
                  이제 {ga(waiting.actor ?? '시연자')} {waiting.action === '결정' ? '결정할' : '할'} 차례예요.
                </b>{' '}
                {waiting.text}
                {guideCase && <> ({fullName})</>}
              </span>
              {waiting.actor && guideCase && (
                <button type="button" className="btn small" onClick={goAs}>
                  {josa(waiting.actor, '로')} 바꿔 건 열기
                </button>
              )}
            </p>
          )}
          {waiting && !waiting.ready && (
            <p className="muted">
              회신이 도착하면 {waiting.text}
              {nextDate ? ` 먼저 다음 날짜(${koDate(nextDate)})로 넘기세요.` : ''}
            </p>
          )}
          {!waiting && !finished && !nextDate && <p className="muted">더 넘길 날짜가 없어요.</p>}

          <details className="scene-more auto-run">
            <summary>대본 끝까지 자동 진행</summary>
            <p className="muted">시험용이에요. 결정까지 자동으로 진행해서 대본 끝으로 가요.</p>
            <button type="button" className="btn small" disabled={busy || finished} onClick={playAll}>
              끝까지 진행
            </button>
          </details>

          <ul className="ledger steps" aria-label="대본 단계">
            {script.map((s, i) => {
              const out = outcomes[i]
              const next = i === done && !finished
              const target = nameOf(s.plan ?? s.contract)
              return (
                <li key={i} data-next={next} data-done={i < done}>
                  <span className="no">{i < done ? '✓' : i + 1}</span>
                  <div>
                    <span className="k">{stepSentence(s)}</span>
                    {next && <span className="next">다음</span>}
                    {target && <div className="sub">{target}</div>}
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
