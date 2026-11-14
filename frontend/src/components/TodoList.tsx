import { useClock } from '../state/clock'
import { useViewer } from '../state/viewer'
import { useCaseLink } from '../state/caseLink'
import { useLoad } from '../state/useLoad'
import { useNavigate } from 'react-router-dom'
import { koDate } from '../date'
import { DEMO_MODE } from '../decisions'
import { TODO_VERB, plainLine } from '../copy'
import LoadFailed from './LoadFailed'

type Item = {
  case_id: number
  ref_id: string
  kind: string
  approval_deadline?: string | null
  deadline?: string | null
  stage?: string
  text?: string
  title?: string
  detail?: string
  due?: string
  reason?: string
  상신?: { from: string; actor: string; opinion: string; reason: string }[]
}
type Todo = Record<string, unknown>

/** 칸 순서(서버 todo의 칸 이름). */
const COLUMNS = ['승인 대기', '알림', '기한 임박', '권한 이동', '회신 대기', '작업']
const REPLY_COLUMN = '회신 대기' // 서버 todo 칸 이름: 줄 버튼이 회신 화면으로 간다
const HUMAN_TASK = '회신 사람 확인' // 서버 작업 이름: 처리 칸이 회신 화면에 있어 그리로 간다
const WORK_COLUMN = '작업' // 서버가 title을 작업 이름으로 덮어 보낸다
const ALARM = '마감 알림' // 서버 알림 종류 이름: 도장색 글씨로 보인다

/** 줄 아래 한 줄(말줄임)과 펼쳤을 때 전체 */
function more(column: string, it: Item): { full: string; seal: boolean } {
  if (column === WORK_COLUMN) return { full: it.detail ?? '', seal: false }
  if (column === '승인 대기') {
    const up = it.상신?.[0]
    return { full: up ? `${up.from}에서 올림: ${up.reason}` : '', seal: false }
  }
  return { full: it.text ?? it.reason ?? '', seal: column === '알림' && it.kind === ALARM }
}

function until(column: string, it: Item): string | null {
  const day = column === WORK_COLUMN ? (it.due ?? null) : (it.approval_deadline ?? it.deadline ?? it.due ?? null)
  return day ? `${koDate(day)}까지` : null
}

/** highlightRef: 시연이 결정을 기다리는 건의 이름표(있으면 그 건의 줄을 강조). inScene: 시연 장면이 진행 중이면 비었을 때 장면 고르기 안내를 뺀다 */
export default function TodoList({ highlightRef = null, inScene = false }: { highlightRef?: string | null; inScene?: boolean }) {
  const { person, failed: viewerFailed, retry: retryViewer } = useViewer()
  const { version, mode } = useClock()
  const go = useCaseLink()
  const navigate = useNavigate()
  const asQuery = person ? `?as=${encodeURIComponent(person.name)}` : ''
  const { data, error, retry } = useLoad<Todo>(person ? `/api/todo/${encodeURIComponent(person.name)}` : null, [person?.name, version])

  const rows = data ? COLUMNS.flatMap((c) => (Array.isArray(data[c]) ? (data[c] as Item[]) : []).map((it) => ({ column: c, it }))) : []
  // 시연이 기다리는 건이 여러 칸(승인 대기·기한 임박·알림)에 있어도 강조는 맨 앞 줄 하나만
  const waitingRow = highlightRef ? rows.findIndex((r) => r.it.ref_id === highlightRef) : -1

  let body
  if (!person && viewerFailed) {
    body = <LoadFailed retry={retryViewer} message="보는 사람을 불러오지 못했어요" buttonName="보는 사람 다시 시도" />
  } else if (error) {
    body = <LoadFailed retry={retry} />
  } else if (!data) {
    body = <p className="muted">불러오는 중</p>
  } else if (rows.length === 0) {
    body = (
      <div className="empty">
        <p>지금 할 일이 없어요</p>
        {mode === DEMO_MODE && !inScene && (
          <button type="button" className="go" onClick={() => navigate('/demo' + asQuery)}>
            시연 조작판에서 장면을 고르세요
          </button>
        )}
      </div>
    )
  } else {
    body = (
      <ul className="rows" aria-label="할 일 목록">
        {rows.map(({ column, it }, i) => {
          const name = it.title || it.ref_id
          const m = more(column, it)
          const line = plainLine(m.full)
          const day = until(column, it)
          return (
            <li key={i} data-column={column} data-waiting={i === waitingRow}>
              <span className="verb">{TODO_VERB[column] ?? column}</span>
              <span className="who">
                <span className="name">{name}</span>
                {it.title && it.title !== it.ref_id && <span className="ref">{it.ref_id}</span>}
              </span>
              <span className="when">{day}</span>
              {column === REPLY_COLUMN || it.title === HUMAN_TASK ? (
                <button type="button" className="go" aria-label={`${name} ${it.ref_id} 회신하기`} onClick={() => navigate('/replies' + asQuery)}>
                  회신하기
                </button>
              ) : (
                <button type="button" className="go" aria-label={`${name} ${it.ref_id} 열기`} onClick={() => go(it.case_id)}>
                  열기
                </button>
              )}
              {m.full && (
                <details className="more" data-seal={m.seal}>
                  <summary>{line || '자세히'}</summary>
                  <p>{m.full}</p>
                </details>
              )}
            </li>
          )
        })}
      </ul>
    )
  }

  return (
    <section className="todo" aria-label="할 일">
      <h2>{data && rows.length > 0 ? `할 일 ${rows.length}건` : '할 일'}</h2>
      {body}
    </section>
  )
}
