import { fromTo } from '../copy'
import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { useClock } from '../state/clock'
import { useViewer } from '../state/viewer'
import { useLoad } from '../state/useLoad'
import { koDate } from '../date'
import { num, pct } from '../format'
import { R_DONE, R_HUMAN, R_WAIT } from '../decisions'
import type { ReplyCase, ReplyResult, RequestRow } from '../replyTypes'
import type { ReplyJudgment } from '../caseTypes'
import Badge from '../components/Badge'
import LoadFailed from '../components/LoadFailed'
import './Replies.css'

const GROUPS: { status: string; title: string }[] = [
  { status: R_WAIT, title: '대기' },
  { status: R_HUMAN, title: '사람 확인' },
  { status: R_DONE, title: '완료' },
]

/** 목록 한 줄: 건 번호·목적, 요청 문장, 상태 */
function Row({ r, selected, onPick }: { r: RequestRow; selected: boolean; onPick: () => void }) {
  return (
    <li>
      <button type="button" className="rrow" aria-pressed={selected} onClick={onPick}>
        <span className="rname">
          {r.ref_id} · {r.purpose}
        </span>
        <span className="rsub">{r.text}</span>
      </button>
    </li>
  )
}

function judgmentLine(j: ReplyJudgment): string {
  const parts = [j.stance ?? '해석 없음']
  if (j.qty_limit !== null && j.qty_limit !== undefined) parts.push(`수량 제한 ${num(j.qty_limit)}개`)
  if (j.next_date) parts.push(`다음 날짜 ${koDate(j.next_date)}`)
  if (j.confidence !== null && j.confidence !== undefined) parts.push(`확신도 ${pct(j.confidence)}`)
  parts.push(j.model)
  parts.push(j.needs_human ? (j.human_confirmed ? `사람이 확인함${j.confirmed_by ? ` (${j.confirmed_by})` : ''}` : '사람 확인 필요') : '사람 확인 불필요')
  return parts.join(' · ')
}

type Snapshot = { status: string; phase1Date: string | null; taskIds: number[] }
type Saved = { requestId: number; reply: ReplyResult; before: Snapshot }

/** 저장 결과: AI 해석과 그에 따라 바뀐 상태 */
function SavedResult({ saved, now }: { saved: Saved; now: ReplyCase | null }) {
  const r = saved.reply
  const j = r.judgment
  const newTasks = (now?.tasks ?? []).filter((t) => !saved.before.taskIds.includes(t.id))
  const nowDate = now?.facts.phase1_date ?? null
  const dateChanged = now && nowDate && saved.before.phase1Date && nowDate !== saved.before.phase1Date
  const yes = (b: boolean) => (b ? '예' : '아니오')
  return (
    <section className="saved" aria-label="저장 결과">
      <h3>저장 결과</h3>
      {r.ignored ? (
        <p>저장하지 않았어요: {r.reason ?? '이미 처리된 요청'}</p>
      ) : (
        <>
          <h4>
            <Badge kind="AI" /> AI 해석
          </h4>
          {j ? (
            <dl className="kv">
              <dt>입장</dt>
              <dd>{j.stance ?? '없음'}</dd>
              <dt>수량 제한</dt>
              <dd>{j.qty_limit !== null && j.qty_limit !== undefined ? `${num(j.qty_limit)}개` : '없음'}</dd>
              <dt>다음 날짜</dt>
              <dd>{j.next_date ? koDate(j.next_date) : '없음'}</dd>
              <dt>사람 확인 필요</dt>
              <dd>{yes(j.needs_human)}</dd>
              <dt>확신도</dt>
              <dd>{j.confidence !== null && j.confidence !== undefined ? pct(j.confidence) : '없음'}</dd>
              <dt>모델</dt>
              <dd>{j.model}</dd>
            </dl>
          ) : (
            <p className="muted">해석 기록이 없어요</p>
          )}
          <h4>바뀐 상태</h4>
          <ul className="changed">
            <li>
              건 상태: {saved.before.status === r.status ? `${r.status} (그대로)` : fromTo(String(saved.before.status), r.status)}
            </li>
            {r.needs_human && <li>이 회신은 사람 확인으로 넘어갔어요. 담당자 확인이 필요해요.</li>}
            {newTasks.map((t) => (
              <li key={t.id}>
                새 작업: {t.title} ({t.dept}, 기한 {koDate(t.due)})
              </li>
            ))}
            {dateChanged && (
              <li>
                집행일: {fromTo(koDate(saved.before.phase1Date as string), koDate(nowDate as string))}
              </li>
            )}
          </ul>
        </>
      )}
    </section>
  )
}

function Detail({ row, who, onSaved }: { row: RequestRow; who: string; onSaved: () => Promise<void> }) {
  const { version } = useClock()
  const { person } = useViewer()
  const load = useLoad<ReplyCase>(`/api/cases/${row.case_id}`, [version])
  const [text, setText] = useState('')
  const [attach, setAttach] = useState('0')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState<Saved | null>(null)
  const guard = useRef(false)

  const d = load.data
  const req = d?.requests.find((x) => x.id === row.id)
  const human = (req?.status ?? row.status) === R_HUMAN
  const done = (req?.status ?? row.status) === R_DONE
  const attachments = Math.max(0, Math.floor(Number(attach) || 0))
  const caseLink = `/cases/${row.case_id}` + (person ? `?as=${encodeURIComponent(person.name)}` : '')

  async function save() {
    if (guard.current || !d || !text.trim()) return
    guard.current = true
    setSending(true)
    setError(null)
    const before: Snapshot = { status: d.case.status, phase1Date: d.facts.phase1_date ?? null, taskIds: d.tasks.map((t) => t.id) }
    try {
      const reply = await api.post<ReplyResult>(`/api/requests/${row.id}/${human ? 'resolve' : 'reply'}`, { actor: who, text: text.trim(), attachments })
      setSaved({ requestId: row.id, reply, before })
      setText('')
      setAttach('0')
      await Promise.all([load.retry(), onSaved()])
    } catch (e) {
      setError((e as Error).message)
    } finally {
      guard.current = false
      setSending(false)
    }
  }

  if (!d) {
    return load.error ? (
      <LoadFailed retry={load.retry} message={`건을 불러오지 못했어요. ${load.error}`} />
    ) : (
      <p role="status" className="muted">
        불러오는 중…
      </p>
    )
  }

  return (
    <article className="doc rdoc">
      <div className="rhead">
        <div>
          <span className="no">
            {row.ref_id} · {row.purpose}
          </span>
          <h2>{d.case.title || row.ref_id}</h2>
          <div className="facts">
            <span>
              요청 부서 <b>{row.dept}</b>
            </span>
            <span>
              건 상태 <b>{d.case.status}</b>
            </span>
            {d.deadline && (
              <span>
                확정 기한 <b>{koDate(d.deadline)}</b>
              </span>
            )}
            {d.approval_deadline && (
              <span>
                마지막 승인일 <b>{koDate(d.approval_deadline)}</b>
              </span>
            )}
            <span>
              요청 상태 <b>{req?.status ?? row.status}</b>
            </span>
          </div>
        </div>
        <Link className="back" to={caseLink}>
          건 상세 보기
        </Link>
      </div>

      <p className="ask">{row.text}</p>
      {row.attach_required && <p className="muted">이 요청은 첨부가 필수예요.</p>}

      <h3>{human ? '원래 회신과 AI 해석' : '지금까지의 회신'}</h3>
      {(req?.replies ?? []).length === 0 ? (
        <p className="muted">아직 회신이 없어요</p>
      ) : (
        <ul className="past">
          {req?.replies.map((p) => (
            <li key={p.id}>
              <p>
                <Badge kind="회신" />
                {p.text}
                {p.attachments > 0 && <span className="muted"> · 첨부 {p.attachments}건</span>}
              </p>
              {p.judgment ? (
                <p className="interp">
                  <Badge kind="AI" />
                  {judgmentLine(p.judgment)}
                </p>
              ) : (
                <p className="interp muted">해석 기록 없음</p>
              )}
            </li>
          ))}
        </ul>
      )}

      {done ? (
        <p className="muted">이미 처리된 요청이에요. 더 회신할 수 없어요.</p>
      ) : (
        <form
          className="rform"
          onSubmit={(e) => {
            e.preventDefault()
            void save()
          }}
        >
          <h3>{human ? '사람 확인' : '회신 입력'}</h3>
          {human && <p className="muted">AI가 사람 확인이 필요하다고 본 회신이에요. 확인한 내용을 적어 저장하면 다시 해석해 반영해요. 권한은 서버가 판단해요.</p>}
          <label>
            {human ? '확인 내용' : '회신 내용'}
            <textarea rows={3} value={text} onChange={(e) => setText(e.target.value)} />
          </label>
          <label className="num">
            첨부 개수
            <input type="number" min={0} value={attach} onChange={(e) => setAttach(e.target.value)} />
          </label>
          {row.attach_required && attachments === 0 && (
            <p role="status" className="warn">
              첨부가 필요한 요청이에요. 첨부 개수가 0이면 서버가 사람 확인으로 넘겨요.
            </p>
          )}
          {error && (
            <p role="alert" className="err">
              {error}
            </p>
          )}
          <button type="submit" className="btn pri" disabled={sending || !text.trim()}>
            {sending ? '저장하는 중…' : human ? '확인 저장' : '회신 저장'}
          </button>
        </form>
      )}

      {saved && saved.requestId === row.id && <SavedResult saved={saved} now={d} />}
    </article>
  )
}

export default function Replies() {
  const { person, failed: viewerFailed, retry: retryViewer } = useViewer()
  const { version } = useClock()
  const [pick, setPick] = useState<{ who: string; row: RequestRow } | null>(null)

  const mine = useLoad<RequestRow[]>(person ? `/api/requests?dept=${encodeURIComponent(person.role)}` : null, [person?.name, version])
  const checks = useLoad<RequestRow[]>(person ? '/api/human-checks' : null, [person?.name, version])
  const reloadLists = async () => {
    await Promise.all([mine.retry(), checks.retry()])
  }

  const selected = pick && person && pick.who === person.name ? pick.row : null
  const choose = (row: RequestRow) => person && setPick({ who: person.name, row })

  let left
  if (!person && viewerFailed) {
    left = <LoadFailed retry={retryViewer} message="보는 사람을 불러오지 못했어요" buttonName="보는 사람 다시 시도" />
  } else if (mine.error) {
    left = <LoadFailed retry={mine.retry} message={`요청 목록을 불러오지 못했어요. ${mine.error}`} />
  } else if (!mine.data) {
    left = (
      <p role="status" className="muted">
        불러오는 중…
      </p>
    )
  } else if (mine.data.length === 0) {
    left = <p className="muted">우리 부서에 온 요청이 없어요</p>
  } else {
    left = (
      <>
        {GROUPS.map((g) => {
          const rows = (mine.data ?? []).filter((r) => r.status === g.status)
          return rows.length === 0 ? null : (
            <div key={g.status} className="rgroup">
              <h3>
                {g.title} ({rows.length})
              </h3>
              <ul className="rows">
                {rows.map((r) => (
                  <Row key={r.id} r={r} selected={selected?.id === r.id} onPick={() => choose(r)} />
                ))}
              </ul>
            </div>
          )
        })}
      </>
    )
  }

  const mineIds = new Set((mine.data ?? []).map((r) => r.id))
  const others = (checks.data ?? []).filter((r) => !mineIds.has(r.id))

  return (
    <main className="page replies">
      <h1>회신 입력</h1>
      <p className="muted">내 부서 요청을 골라 회신을 입력하세요.</p>
      <div className="rgrid">
        <div className="rlist">
          <section aria-label="내 부서 요청">
            <h2>내 부서 요청{person ? ` · ${person.role}` : ''}</h2>
            {left}
          </section>
          <section aria-label="사람 확인이 필요한 회신">
            <h2>사람 확인이 필요한 회신</h2>
            {checks.error ? (
              <LoadFailed retry={checks.retry} message={`사람 확인 목록을 불러오지 못했어요. ${checks.error}`} buttonName="사람 확인 다시 시도" />
            ) : !checks.data ? (
              <p className="muted">불러오는 중…</p>
            ) : others.length === 0 ? (
              <p className="muted">다른 부서에서 사람 확인을 기다리는 회신은 없어요</p>
            ) : (
              <ul className="rows">
                {others.map((r) => (
                  <Row key={r.id} r={r} selected={selected?.id === r.id} onPick={() => choose(r)} />
                ))}
              </ul>
            )}
          </section>
        </div>
        <div className="rdetail">
          {selected && person ? (
            <Detail key={selected.id} row={selected} who={person.name} onSaved={reloadLists} />
          ) : (
            <p className="muted">왼쪽에서 요청을 고르면 회신을 입력할 수 있어요.</p>
          )}
        </div>
      </div>
    </main>
  )
}
