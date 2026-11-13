import { useClock } from '../state/clock'
import { useViewer } from '../state/viewer'
import { useCaseLink } from '../state/caseLink'
import { useLoad } from '../state/useLoad'
import { Link } from 'react-router-dom'
import LoadFailed from './LoadFailed'

type Item = {
  case_id: number
  ref_id: string
  kind: string
  approval_deadline?: string | null
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
const REPLY_COLUMN = '회신 대기' // 서버 todo 칸 이름: 회신 입력 화면으로 가는 링크를 붙인다
const ALARM = '마감 알림' // 서버 알림 종류 이름: 도장색 글씨로 보인다

function second(column: string, it: Item): { meta: string; text: string; seal: boolean } {
  const parts: string[] = []
  if (column === '작업') {
    if (it.due) parts.push(`기한 ${it.due}`)
    if (it.detail) parts.push(it.detail)
    return { meta: parts.join(' · '), text: '', seal: false }
  }
  if (column === '승인 대기') {
    if (it.approval_deadline) parts.push(`마지막 승인일 ${it.approval_deadline}`)
    parts.push(`${it.stage ?? '1차'} 승인`)
    const up = it.상신?.[0]
    if (up) parts.push(`${up.from}에서 올림: ${up.reason}`)
    return { meta: parts.join(' · '), text: '', seal: false }
  }
  if (it.approval_deadline && column === '기한 임박') parts.push(`마지막 승인일 ${it.approval_deadline}`)
  if (it.stage) parts.push(it.stage)
  return { meta: parts.join(' · '), text: it.text ?? it.reason ?? '', seal: column === '알림' && it.kind === ALARM }
}

export default function TodoList() {
  const { person, failed: viewerFailed, retry: retryViewer } = useViewer()
  const { version } = useClock()
  const go = useCaseLink()
  const { data, error, retry } = useLoad<Todo>(person ? `/api/todo/${encodeURIComponent(person.name)}` : null, [person?.name, version])

  let body
  if (!person && viewerFailed) {
    body = <LoadFailed retry={retryViewer} message="보는 사람을 불러오지 못했어요" buttonName="보는 사람 다시 시도" />
  } else if (error) {
    body = <LoadFailed retry={retry} />
  } else if (!data) {
    body = <p className="muted">불러오는 중</p>
  } else {
    const filled = COLUMNS.filter((c) => Array.isArray(data[c]) && (data[c] as Item[]).length > 0)
    body =
      filled.length === 0 ? (
        <p className="muted">지금 할 일이 없어요</p>
      ) : (
        filled.map((c) => (
          <div key={c} className="col">
            <h3>{c}</h3>
            <ul>
              {(data[c] as Item[]).map((it, i) => {
                const s = second(c, it)
                return (
                  <li key={i}>
                    <button type="button" onClick={() => go(it.case_id)}>
                      <span className="head">
                        <span className="name">{it.title || it.ref_id}</span>
                        {it.title && it.title !== it.ref_id && <span className="ref">{it.ref_id}</span>}
                      </span>
                      {(s.meta || s.text) && (
                        <span className="sub">
                          {s.meta && <span>{s.meta}</span>}
                          {s.text && <span data-seal={s.seal}>{s.text}</span>}
                        </span>
                      )}
                    </button>
                  </li>
                )
              })}
            </ul>
            {c === REPLY_COLUMN && (
              <Link className="to-replies" to={'/replies' + (person ? `?as=${encodeURIComponent(person.name)}` : '')}>
                회신 입력으로 가기
              </Link>
            )}
          </div>
        ))
      )
  }

  return (
    <section className="todo" aria-label="할 일">
      <h2>할 일</h2>
      {body}
    </section>
  )
}
