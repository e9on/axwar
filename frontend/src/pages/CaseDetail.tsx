import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api'
import { useClock } from '../state/clock'
import { useViewer } from '../state/viewer'
import { useLoad } from '../state/useLoad'
import { daysBetween, koDate } from '../date'
import { num, won } from '../format'
import { S_DEFAULT_DENY, S_PHASE2_WAIT } from '../decisions'
import type { CaseDetailData, EvidenceData } from '../caseTypes'
import ApprovalStamps from '../components/ApprovalStamps'
import Badge from '../components/Badge'
import DecisionPanel from '../components/DecisionPanel'
import EvidenceList from '../components/EvidenceList'
import LoadFailed from '../components/LoadFailed'
import { AiBlock, ChangeLines, History, Requests, Tasks } from '../components/CaseSections'
import './CaseDetail.css'

const KIND_CONTRACT = '계약' // 서버 건 종류 이름(backend flow.KIND_CONTRACT)
const ORIGIN_DEMO = '시연' // 서버 출처 이름

/** 분할 뒤 2차 금액이 조절돼 총 금액이 달라졌으면 조절 후 금액(서버 _resize_phase2와 같은 식) */
function adjustedAmount(d: CaseDetailData): number | null {
  const dec = d.phase2?.decision
  const base = d.facts.amount_krw
  if (typeof base !== 'number' || !dec || typeof dec.amount_before !== 'number' || typeof dec.amount_after !== 'number') return null
  if (dec.amount_before === dec.amount_after) return null
  return base - (dec.amount_before - dec.amount_after)
}

type ClockProps = { prefix?: string; waiting: boolean; status: string; today: string | null; deny: string | null; last: string | null }

/** 기본 거부까지 남은 날. 기다리는 중이면 큰 숫자(도장색)와 문장, 아니면 결과 문장. */
function DenyClock({ prefix = '', waiting, status, today, deny, last }: ClockProps) {
  if (!waiting) {
    return (
      <div className="clock" aria-label={`${prefix}남은 날`}>
        <p>
          {status === S_DEFAULT_DENY && deny
            ? `${prefix}기본 거부 날(${koDate(deny)})까지 승인이 없어 확정 보류됐어요.`
            : `${prefix}결정이 끝났어요. 지금 상태: ${status}`}
        </p>
      </div>
    )
  }
  if (!deny || !today) return null
  const days = daysBetween(today, deny)
  return (
    <div className="clock" aria-label={`${prefix}남은 날`}>
      <span className="big">{days < 0 ? '지남' : days === 0 ? '오늘' : `${days}일`}</span>
      <p>
        {days < 0 ? (
          <>
            {prefix}기본 거부 날 <b>{koDate(deny)}</b>이 지났어요. 서버가 기본 거부로 처리해야 해요.
          </>
        ) : (
          <>
            {prefix}승인이 없으면 <b>{koDate(deny)}에 기본 거부</b>로 확정 보류됩니다.
            {last && (
              <>
                {' '}마지막 승인일은 <b>{koDate(last)}</b>입니다.
              </>
            )}
          </>
        )}
      </p>
    </div>
  )
}

export default function CaseDetailPage() {
  const { id } = useParams()
  const { person, failed: viewerFailed, retry: retryViewer } = useViewer()
  const { version, date: today } = useClock()
  const [making, setMaking] = useState(false)

  const detailPath = person ? `/api/cases/${id}?viewer=${encodeURIComponent(person.name)}` : null
  const detail = useLoad<CaseDetailData>(detailPath, [version])
  const d = detail.data
  const evidence = useLoad<EvidenceData>(d ? `/api/cases/${id}/evidence` : null, [version])
  const isDemoPlan = !!d && d.case.origin === ORIGIN_DEMO && d.case.kind !== KIND_CONTRACT
  const registry = useLoad<{ raw?: { note?: string } }>(isDemoPlan ? `/api/plans/${d.case.ref_id}` : null, [])

  const reload = () => {
    detail.retry()
    evidence.retry()
  }

  const back = (
    <Link className="back" to={'/' + (person ? `?as=${encodeURIComponent(person.name)}` : '')}>
      ← 메인으로
    </Link>
  )

  if (viewerFailed) {
    return (
      <main className="page case">
        {back}
        <LoadFailed retry={retryViewer} message="보는 사람 목록을 불러오지 못했어요" />
      </main>
    )
  }
  if (!d) {
    return (
      <main className="page case">
        {back}
        {detail.error ? (
          detail.status === 404 ? (
            <p role="alert" className="missing">
              찾을 수 없는 건이에요. {detail.error}
            </p>
          ) : (
            <LoadFailed retry={detail.retry} message={`건 상세를 불러오지 못했어요. ${detail.error}`} />
          )
        ) : (
          <p role="status" className="muted">
            불러오는 중…
          </p>
        )}
      </main>
    )
  }

  const c = d.case
  const f = d.facts
  const contract = c.kind === KIND_CONTRACT
  const status = c.status
  const phase2Wait = status === S_PHASE2_WAIT
  const viewerRole = d.viewer?.role ?? null
  const adjusted = adjustedAmount(d)
  const shownDay = contract ? f.expiry : (f.phase1_date ?? f.settlement_date)
  const note = registry.data?.raw?.note

  const canMakeBriefing = !!d.viewer?.can_decide || !!d.viewer?.can_decide_phase2
  async function makeBriefing() {
    if (!person) return
    setMaking(true)
    try {
      await api.post(`/api/cases/${id}/briefing`, { actor: person.name })
      reload()
    } catch {
      // 알림 줄이 이미 보여 줌
    } finally {
      setMaking(false)
    }
  }

  return (
    <main className="page case">
      {back}
      <article className="doc">
        <div className="head">
          <div>
            <span className="no">
              {c.ref_id} · {c.kind}
            </span>
            <h1>{c.title || c.ref_id}</h1>
            {c.origin === ORIGIN_DEMO && (
              <p className="demo">
                <b className="demo-tag">시연용 가정</b> {note ?? '시연을 위해 만든 가상의 건이에요'}
              </p>
            )}
            <div className="facts">
              {contract ? (
                f.annual_fixed_krw !== undefined && (
                  <span>
                    연 고정 피 <b>{won(f.annual_fixed_krw)}</b>
                  </span>
                )
              ) : (
                f.amount_krw !== undefined && (
                  <span>
                    요청액 <b>{won(f.amount_krw)}</b>
                  </span>
                )
              )}
              {adjusted !== null && (
                <span>
                  조절 후 금액 <b>{won(adjusted)}</b>
                </span>
              )}
              {shownDay && (
                <span>
                  {contract ? '계약 만료' : '집행일'} <b>{koDate(shownDay)}</b>
                </span>
              )}
              {d.deadline && (
                <span>
                  {contract ? '통보 기한' : '확정 기한'} <b>{koDate(d.deadline)}</b>
                </span>
              )}
              <span>
                상태 <b>{status}</b>
              </span>
            </div>
          </div>
          <ApprovalStamps label="결재란" roles={d.rule.required_roles} approved={d.rule.approved_roles} mineRole={phase2Wait ? null : viewerRole} status={status} />
        </div>

        <ChangeLines escalations={d.escalations} changes={d.approver_changes} />

        <DenyClock
          waiting={d.rule.pending_roles.length > 0}
          status={status}
          today={today}
          deny={d.deny_date}
          last={d.approval_deadline}
        />

        {d.phase2 && (
          <section className="phase2" aria-labelledby="p2-h">
            <h3 id="p2-h">2차 집행</h3>
            {d.phase2.plan && (
              <p>
                2차 계획 <b>{num(d.phase2.plan.qty)}개</b>
                {d.phase2.plan.date && <> · {koDate(d.phase2.plan.date)}</>}
                {d.phase2.plan.amount_krw !== undefined && <> · {won(d.phase2.plan.amount_krw)}</>}
              </p>
            )}
            <p className="muted">
              {d.phase2.gate.open ? '2차 집행을 열 수 있어요' : `2차는 아직 열 수 없어요${d.phase2.gate.reasons?.length ? `: ${d.phase2.gate.reasons.join(', ')}` : ''}`}
            </p>
            {d.phase2.hits.length > 0 && (
              <ul className="phase2-hits">
                {d.phase2.hits.map((h, i) => (
                  <li key={i}>
                    <Badge kind={h.badge} />
                    {h.text}
                  </li>
                ))}
              </ul>
            )}
            {d.phase2.required_roles.length > 0 && (
              <ApprovalStamps
                label="2차 결재란"
                roles={d.phase2.required_roles}
                approved={d.phase2.approved_roles}
                mineRole={phase2Wait ? viewerRole : null}
                status={status}
              />
            )}
            {phase2Wait && (
              <DenyClock prefix="2차 " waiting={d.phase2.pending_roles.length > 0} status={status} today={today} deny={d.phase2.deny_date} last={d.phase2.approval_deadline} />
            )}
          </section>
        )}

        {evidence.data ? (
          <EvidenceList data={evidence.data} />
        ) : evidence.error ? (
          <LoadFailed retry={evidence.retry} message={`근거를 불러오지 못했어요. ${evidence.error}`} buttonName="근거 다시 시도" />
        ) : (
          <p role="status" className="muted">
            근거를 불러오는 중…
          </p>
        )}

        <h3>부서 요청과 회신</h3>
        <Requests requests={d.requests} judgments={d.judgments} />

        <AiBlock
          title="AI 브리핑"
          text={d.briefing}
          canMake={canMakeBriefing}
          making={making}
          onMake={makeBriefing}
          emptyHint="아직 AI 브리핑이 없어요. 결재할 수 있는 사람이 만들 수 있어요."
        />
        <AiBlock title="반대 근거" text={d.counterpoints} canMake={false} emptyHint="아직 반대 근거가 없어요." />

        <Tasks detail={d} />

        <h3>처리 기록</h3>
        <History events={d.history} />
      </article>
      <DecisionPanel detail={d} actor={person?.name ?? ''} onDone={reload} />
    </main>
  )
}
