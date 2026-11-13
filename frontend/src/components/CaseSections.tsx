import { useState } from 'react'
import Badge from './Badge'
import Fold from './Fold'
import { signalValue } from './EvidenceList'
import { RULE_LABEL, RULE_LABEL_FALLBACK, changeLine } from '../copy'
import type { AiText, ApproverChange, CaseDetailData, CaseEvent, CaseRequest, Escalation, EvidenceData, ReplyJudgment } from '../caseTypes'
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

/** 결재선 변경: 한 줄(가장 최근)만 접혀 있고, 펼치면 원문 목록 */
export function ChangeFold({ escalations, changes }: { escalations: Escalation[]; changes: ApproverChange[] }) {
  const other = changes.filter((c) => !c.reason.startsWith('상신'))
  const all = [
    ...escalations.map((e) => ({ from: e.from, to: e.to, at: e.at })),
    ...other.map((c) => ({ from: c.before.join('·'), to: c.after.join('·'), at: c.at.slice(0, 10) })),
  ]
  if (all.length === 0) return null
  const last = [...all].sort((a, b) => a.at.localeCompare(b.at))[all.length - 1]
  return (
    <Fold title={changeLine(last.from, last.to, last.at) + (all.length > 1 ? ` 외 ${all.length - 1}건` : '')}>
      <ChangeLines escalations={escalations} changes={changes} />
    </Fold>
  )
}

function interpretation(j: ReplyJudgment): string {
  const parts = [j.stance ?? '해석 없음']
  if (j.qty_limit !== null && j.qty_limit !== undefined) parts.push(`수량 한도 ${j.qty_limit.toLocaleString('ko-KR')}개`)
  if (j.next_date) parts.push(`다음 날짜 ${koDate(j.next_date)}`)
  return parts.join(' · ')
}

function humanText(j: ReplyJudgment): string {
  if (!j.needs_human) return '사람 확인 불필요'
  return j.human_confirmed ? `사람이 확인함${j.confirmed_by ? ` (${j.confirmed_by})` : ''}` : '사람 확인 필요'
}

/** 부서 요청과 회신. 회신마다 서버가 이어 준 AI 해석(judgment)과 사람 확인 정보를 붙인다. */
export function Requests({ requests }: { requests: CaseRequest[] }) {
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
            const j = p.judgment
            return (
              <div className="reply" key={p.id}>
                <p>
                  <Badge kind="회신" />
                  {p.text}
                  {p.attachments > 0 && <span className="muted"> · 첨부 {p.attachments}건</span>}
                </p>
                {j ? (
                  <p className="interp">
                    <Badge kind="AI" />
                    해석: {interpretation(j)} <span className="muted">· {j.model} · {humanText(j)}</span>
                  </p>
                ) : (
                  <p className="interp muted">해석 기록 없음</p>
                )}
              </div>
            )
          })}
        </li>
      ))}
    </ul>
  )
}

type AiProps = { title: string; bare?: boolean; text: AiText | null; canMake: boolean; making?: boolean; onMake?: () => void; emptyHint: string }

/** AI가 쓴 글(브리핑·반대 근거). AI 배지, 모델과 날짜, 낡았으면 다시 만들어야 한다는 문장. */
export function AiBlock({ title, bare, text, canMake, making, onMake, emptyHint }: AiProps) {
  return (
    <section className="ai">
      {!bare && <h3>{title}</h3>}
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

export function openTasks(detail: CaseDetailData) {
  return detail.tasks.filter((t) => t.status === '대기')
}

export function Tasks({ detail }: { detail: CaseDetailData }) {
  const open = openTasks(detail)
  if (open.length === 0) return null
  return (
    <>
      <ul className="tasks">
        {open.map((t) => (
          <li key={t.id}>
            {t.title.startsWith(t.dept) ? null : <><b>{t.dept}</b>{' '}</>}{t.title} <span className="muted">· 기한 {koDate(t.due)}</span>
          </li>
        ))}
      </ul>
    </>
  )
}

const FIRST_SENTENCE = /^.*?[.!?。](?=\s|$)/

/** 핵심 세 줄: 왜 이 사람이 결재하나 / 가장 큰 위험 / AI 의견. 이름표와 값만, 원문은 아래 접힌 칸에 있다 */
export function KeyLines({ detail, evidence, canMake, making, onMake }: { detail: CaseDetailData; evidence: EvidenceData | null; canMake: boolean; making: boolean; onMake: () => void }) {
  const hits = evidence ? [...evidence.rule.approver_hits, ...evidence.rule.phase2_approver_hits].filter((h) => !h.superseded) : []
  const tags = Array.from(new Set(hits.map((h) => RULE_LABEL[h.rule_id] ?? RULE_LABEL_FALLBACK))).slice(0, 2)
  const reds = evidence ? evidence.signals.filter((s) => s.level === 'red').slice(0, 3) : []
  const b = detail.briefing
  const first = b && b.ok ? (FIRST_SENTENCE.exec(b.text)?.[0] ?? b.text) : ''
  return (
    <dl className="keylines" aria-label="핵심">
      <div>
        <dt>왜 이 결재선</dt>
        <dd>{tags.length > 0 ? tags.map((t) => <span className="tag" key={t}>{t}</span>) : <span className="muted">{detail.rule.required_roles.join('·')}</span>}</dd>
      </div>
      <div>
        <dt>가장 큰 위험</dt>
        <dd>
          {!evidence ? (
            <span className="muted">불러오는 중…</span>
          ) : reds.length > 0 ? (
            reds.map((s) => (
              <span className="tag red" key={s.key}>
                {s.label} {signalValue(s)}
              </span>
            ))
          ) : (
            <span className="muted">나쁨으로 나온 신호가 없어요</span>
          )}
        </dd>
      </div>
      <div>
        <dt>AI 의견</dt>
        <dd>
          {first ? (
            <span>{first}</span>
          ) : (
            <span className="muted">아직 없어요</span>
          )}
          {canMake && (!b || b.stale || !b.ok) && (
            <button type="button" className="btn-sm" disabled={making} onClick={onMake}>
              {making ? '만드는 중…' : b ? 'AI 브리핑 다시 만들기' : 'AI 브리핑 만들기'}
            </button>
          )}
        </dd>
      </div>
    </dl>
  )
}
