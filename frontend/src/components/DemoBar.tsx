import { useState } from 'react'
import { koDate, koDateWeekday } from '../date'
import { actionLine, josa } from '../format'
import { ga, plainLine } from '../copy'
import { useStartScene } from '../state/demoScene'
import type { useDemoScene } from '../state/demoScene'
import FormDialog from './FormDialog'
import './DemoBar.css'

type Scene = ReturnType<typeof useDemoScene>

const DECISION_WORD: Record<string, string> = { 분할승인: '분할 승인' }
const ACT_DECIDE = '결정'

/** 결정권자가 해야 할 일의 이름: 결정이면 승인·거절 같은 결정 이름, 아니면 단계 이름(발송·공지…) */
function needWord(w: NonNullable<Scene['waiting']>): string {
  const decision = (w.step as { decision?: unknown } | undefined)?.decision
  if (w.action === ACT_DECIDE && typeof decision === 'string') return DECISION_WORD[decision] ?? decision
  return w.action
}

export default function DemoBar({ demo }: { demo: Scene }) {
  const { scene, date, person, waiting, nextDate, ended, running, busy, notice, error, result, decided } = demo
  const start = useStartScene()
  const [asking, setAsking] = useState(false)
  const [failed, setFailed] = useState<string | null>(null)
  const [resetting, setResetting] = useState(false)
  const [risky, setRisky] = useState<null | (() => void)>(null)
  if (!scene) return null

  const need = waiting?.ready
  const who = waiting?.actor ?? null
  // 오늘이 결재의 마지막 승인일인데 아직 결정하지 않았으면, 날짜를 넘기기 전에 묻는다(넘기면 내일 기본 거부)
  const lastDay = !!need && !!waiting?.due && !!date && date >= waiting.due
  const guard = (go: () => void) => () => (lastDay && !running ? setRisky(() => go) : go())
  const lines = notice ? [...notice.applied, ...notice.actions.map((a) => actionLine({ ...a, text: plainLine(a.text, 80) }))] : []

  let message: string
  if (ended) message = '장면이 끝났어요'
  else if (need && waiting) message = `${who ?? '시연자'}의 ${ga(needWord(waiting))} 필요해요 — 아래 할 일을 눌러 ${waiting.action === ACT_DECIDE ? '결정' : '처리'}하세요`
  else if (decided) message = '결정했어요. ▶ 진행을 눌러 이어 가세요'
  else if (running) message = '진행 중이에요'
  else message = '▶ 진행을 눌러 시작하세요'

  async function restart() {
    setResetting(true)
    setFailed(null)
    try {
      await start(scene!.scenario!)
      setAsking(false)
    } catch (e) {
      setFailed((e as Error).message)
    } finally {
      setResetting(false)
    }
  }

  return (
    <section className="demo-bar" aria-label="시연 진행" data-state={ended ? 'end' : need ? 'wait' : running ? 'run' : 'idle'}>
      <div className="db-date">
        <b>{date ? koDateWeekday(date) : '불러오는 중'}</b>
        <span>{scene.title}</span>
      </div>
      <div className="db-tools">
        <button type="button" className="btn pri" onClick={guard(demo.toggle)} disabled={ended || (!running && busy)}>
          {running ? '❚❚ 멈춤' : '▶ 진행'}
        </button>
        <button type="button" className="btn" onClick={guard(demo.nextDay)} disabled={busy || running || ended}>
          다음 날
        </button>
        <button type="button" className="btn" onClick={guard(demo.toNextEvent)} disabled={busy || running || !nextDate} title="조용한 날을 건너뛰고 다음 일이 있는 날로 가요">
          다음 일까지
        </button>
        {ended && (
          <button type="button" className="btn deny" onClick={() => setAsking(true)}>
            처음부터
          </button>
        )}
      </div>
      <p className="db-msg" role="status" data-need={!!need}>
        <b>{message}</b>
        {ended && result && <span className="db-result"> {plainLine(result, 120)}</span>}
        {!ended && !need && waiting?.due && (
          <span className="db-result"> · {who ?? '시연자'} {needWord(waiting)} 마감 {koDate(waiting.due)} · 할 일에서 먼저 할 수 있어요</span>
        )}
        {need && who && who !== person?.name && (
          <button type="button" className="btn small" onClick={() => demo.switchTo(who)}>
            {josa(who, '로')} 바꾸기
          </button>
        )}
      </p>
      {error && (
        <p className="db-error" role="alert">
          {error}
        </p>
      )}
      {lines.length > 0 && (
        <ul className="db-notice" role="status" aria-label="이번에 일어난 일">
          {lines.map((l, i) => (
            <li key={i}>{l}</li>
          ))}
        </ul>
      )}
      {risky && waiting && (
        <FormDialog
          title="오늘이 마지막 승인일이에요"
          confirmLabel="그래도 진행"
          tone="deny"
          onConfirm={() => { const go = risky; setRisky(null); go() }}
          onCancel={() => setRisky(null)}
        >
          <p>
            {who ?? '시연자'}의 {ga(needWord(waiting))} 아직 남았어요. 날짜를 넘기면 내일 기본 거부되고 건은 확정 보류(철회)로 끝나요.
          </p>
        </FormDialog>
      )}
      {asking && (
        <FormDialog title="장면 불러오기" confirmLabel="초기화하고 시작" tone="deny" busy={resetting} error={failed} onConfirm={restart} onCancel={() => setAsking(false)}>
          <p>
            <b>{scene.title}</b>{josa(scene.title ?? '', '을').slice((scene.title ?? '').length)} 처음부터 시작하면 시연 데이터가 지워져요.
          </p>
        </FormDialog>
      )}
    </section>
  )
}
