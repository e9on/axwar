import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useClock } from '../state/clock'
import { useStartScene } from '../state/demoScene'
import { useViewer } from '../state/viewer'
import { useLoad } from '../state/useLoad'
import { DEMO_MODE } from '../decisions'
import { sceneSummary } from '../copy'
import type { DemoState, Scenario } from '../adminTypes'
import FormDialog from '../components/FormDialog'
import LoadFailed from '../components/LoadFailed'
import './Admin.css'

function DemoPanel() {
  const { person } = useViewer()
  const navigate = useNavigate()
  const start = useStartScene()
  const scenes = useLoad<Scenario[]>('/api/demo/scenarios', [])
  const position = useLoad<DemoState>('/api/demo/state', [])
  const [asking, setAsking] = useState<Scenario | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const guard = useRef(false)

  // 진행 위치는 서버가 기억한다(새로고침해도 그대로)
  const where = position.data
  const active = scenes.data?.find((s) => s.name === where?.scenario) ?? null

  async function begin(scene: Scenario) {
    if (guard.current) return
    guard.current = true
    setBusy(true)
    setError(null)
    try {
      await start(scene.name, scene.script ?? [])
    } catch (e) {
      setError((e as Error).message)
    } finally {
      guard.current = false
      setBusy(false)
    }
  }

  const toMain = () => navigate('/' + (person ? `?as=${encodeURIComponent(person.name)}` : ''))

  return (
    <main className="admin">
      <h1>시연 조작판</h1>
      <p className="lead">장면을 고르고 시작하면 메인 화면으로 가요. 날짜는 메인에서 하루씩 넘기고, 결정할 때 멈춰요.</p>

      {active && (
        <section aria-label="진행">
          <h2>지금 진행 중인 장면: {active.title}</h2>
          <p className="muted">메인에서 진행하세요.</p>
          <details className="scene-more">
            <summary>자세히</summary>
            <p className="scene-desc">{active.description}</p>
          </details>
          <div className="bar-tools">
            <button type="button" className="btn pri" onClick={toMain}>
              메인으로
            </button>
            <button type="button" className="btn deny" disabled={busy} onClick={() => setAsking(active)}>
              처음부터
            </button>
          </div>
        </section>
      )}
      {error && !asking && (
        <p className="err" role="alert">
          {error}
        </p>
      )}

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
                  <span className="go-start">시작</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      {asking && (
        <FormDialog
          title="장면 불러오기"
          confirmLabel="초기화하고 시작"
          tone="deny"
          busy={busy}
          error={error}
          onConfirm={() => begin(asking)}
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
