import { useState } from 'react'
import Badge from './Badge'
import type { AiText, ApproverChange, CaseDetailData, CaseEvent, CaseRequest, Escalation, Judgment } from '../caseTypes'
import { koDate } from '../date'

/** 결재선이 바뀐 이력: 상신은 "A → B, 상신(의견): 이유", 그 밖의 권한 이동은 "A → B: 이유" */
export function ChangeLines({ escalations, changes }: { escalations: Escalation[]; changes: ApproverChange[] }) {
  const other = changes.filter((c) => !c.reason.startsWith('상신'))
  if (escalations.length === 0 && other.length === 0) return null
  return (
    <ul className="changes" aria-label="결재선 변경 이력">
      {escalations.map((e, i) => (
        <li key={`e${i}`}>
          {e.stage === '2차' && '2차 '}
          {e.from} → {e.to}, 상신({e.opinion}): {e.reason} <span className="muted">· {e.actor}, {koDate(e.at)}</span>
        </li>
      ))}
      {other.map((c, i) => (
        <li key={`c${i}`}>
          {c.before.join('·')} → {c.after.join('·')}: {c.reason} <span className="muted">· {koDate(c.at.slice(0, 10))}</span>
        </li>
      ))}
    </ul>
  )
}

function interpretation(j: Judgment): string {
  const r = j.result
  const parts = [r.stance ?? '해석 없음']
  if (r.qty_limit !== null && r.qty_limit !== undefined) parts.push(`수량 한도 ${r.qty_limit.toLocaleString('ko-KR')}개`)
  if (r.next_date) parts.push(`다음 날짜 ${koDate(r.next_date)}`)
  return parts.join(' · ')
}

/** 부서 요청과 회신. 회신마다 AI 해석 결과와 사람 확인 여부를 붙인다. */
export function Requests({ requests, judgments }: { requests: CaseRequest[]; judgments: Judgment[] }) {
  if (requests.length === 0) return <p className="muted">부서에 보낸 요청이 없어요</p>
  return (
    <ul className="reqs">
      {requests.map((r) => (
        <li key={r.id}>
          <p>
            <b>{r.dept}</b> <span className="muted">· {r.purpose} · {r.status}</span>
          </p>
          <p className="req-text">{r.text}</p>
          {r.replies.length === 0 && <p className="muted">아직 회신이 없어요</p>}
          {r.replies.map((p) => {
            const j = judgments.find((x) => x.kind === '회신해석' && x.input_summary === `${r.dept} 회신: ${p.text}`)
            const human = j ? (j.needs_human ? (r.status === '처리됨' ? '사람이 확인함' : '사람 확인 필요') : '사람 확인 불필요') : null
            return (
              <div className="reply" key={p.id}>
                <p>
                  <Badge kind="회신" />
                  {p.text}
                  {p.attachments > 0 && <span className="muted"> · 첨부 {p.attachments}건</span>}
                </p>
                {j && (
                  <p className="interp">
                    <Badge kind="AI" />
                    해석: {interpretation(j)} <span className="muted">· {j.model} · {human}</span>
                  </p>
                )}
              </div>
            )
          })}
        </li>
      ))}
    </ul>
  )
}

type AiProps = { title: string; text: AiText | null; canMake: boolean; making?: boolean; onMake?: () => void; emptyHint: string }

/** AI가 쓴 글(브리핑·반대 근거). AI 배지, 모델과 날짜, 낡았으면 다시 만들어야 한다는 문장. */
export function AiBlock({ title, text, canMake, making, onMake, emptyHint }: AiProps) {
  return (
    <section className="ai">
      <h3>{title}</h3>
      {text ? (
        <div className="brief">
          <p>
            <Badge kind="AI" />
            {text.ok ? text.text : 'AI가 글을 만들지 못했어요'}
          </p>
          <p className="conf">
            {text.model} · {koDate(text.sim_date)}
          </p>
          {text.stale && <p className="stale">사실이 바뀌어 다시 만들어야 함</p>}
        </div>
      ) : (
        <p className="muted">{emptyHint}</p>
      )}
      {onMake && canMake && (!text || text.stale || !text.ok) && (
        <button type="button" className="btn-sm" disabled={making} onClick={onMake}>
          {making ? '만드는 중…' : text ? 'AI 브리핑 다시 만들기' : 'AI 브리핑 만들기'}
        </button>
      )}
    </section>
  )
}

const HEAD = 3

function eventText(e: CaseEvent): string {
  const d = e.detail
  const pick = ['note', 'text', 'reason', 'comment'].map((k) => d[k]).find((v) => typeof v === 'string' && v)
  if (typeof pick === 'string') return pick
  if (typeof d.from === 'string' && typeof d.to === 'string') return `${d.from} → ${d.to}`
  return ''
}

/** 처리 기록: 접힌 상태에서는 가장 최근 몇 건, 펼치면 전체(시간순). */
export function History({ events }: { events: CaseEvent[] }) {
  const [open, setOpen] = useState(false)
  if (events.length === 0) return <p className="muted">처리 기록이 없어요</p>
  const shown = open ? events : events.slice(-HEAD)
  return (
    <div className="history">
      <ol>
        {shown.map((e) => (
          <li key={e.id}>
            <span className="muted">{koDate(e.sim_date)}</span> <b>{e.kind}</b> <span className="muted">{e.actor}</span> {eventText(e)}
          </li>
        ))}
      </ol>
      {events.length > HEAD && (
        <button type="button" className="btn-sm" aria-expanded={open} onClick={() => setOpen(!open)}>
          {open ? '접기' : `전체 ${events.length}건 펼치기`}
        </button>
      )}
    </div>
  )
}

export function Tasks({ detail }: { detail: CaseDetailData }) {
  const open = detail.tasks.filter((t) => t.status === '대기')
  if (open.length === 0) return null
  return (
    <>
      <h3>남은 작업</h3>
      <ul className="tasks">
        {open.map((t) => (
          <li key={t.id}>
            <b>{t.dept}</b> {t.title} <span className="muted">· 기한 {koDate(t.due)}</span>
          </li>
        ))}
      </ul>
    </>
  )
}
