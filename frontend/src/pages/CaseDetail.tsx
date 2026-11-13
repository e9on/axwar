import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api'
import { useClock } from '../state/clock'
import { useViewer } from '../state/viewer'
import { useLoad } from '../state/useLoad'
import { koDate } from '../date'
import { num, won } from '../format'
import { KIND_CONTRACT, ST_PHASE2_WAIT } from '../decisions'
import type { CaseDetailData, EvidenceData } from '../caseTypes'
import ApprovalStamps from '../components/ApprovalStamps'
import Badge from '../components/Badge'
import DecisionPanel from '../components/DecisionPanel'
import EvidenceList from '../components/EvidenceList'
import LoadFailed from '../components/LoadFailed'
import Fold from '../components/Fold'
import { AiBlock, ChangeFold, History, KeyLines, Requests, Tasks, openTasks } from '../components/CaseSections'
import { aiHeadline } from '../aiText'
import './CaseDetail.css'

const ORIGIN_DEMO = '시연' // 서버 출처 이름

/** 분할 뒤 2차 금액이 조절돼 총 금액이 달라졌으면 조절 후 금액(서버 _resize_phase2와 같은 식) */
function adjustedAmount(d: CaseDetailData): number | null {
  const dec = d.phase2?.decision
  const base = d.facts.amount_krw
  if (typeof base !== 'number' || !dec || typeof dec.amount_before !== 'number' || typeof dec.amount_after !== 'number') return null
  if (dec.amount_before === dec.amount_after) return null
  return base - (dec.amount_before - dec.amount_after)
}

function firstLine(text: string): string {
  return aiHeadline(text)
}

function requestSummary(d: CaseDetailData): string {
  if (d.requests.length === 0) return '요청 없음'
  const replies = d.requests.reduce((n, r) => n + r.replies.length, 0)
  return `요청 ${d.requests.length}건 · 회신 ${replies}건`
}

function phase2Summary(d: CaseDetailData): string {
  const p = d.phase2
  if (!p) return ''
  if (p.plan) return `2차 ${num(p.plan.qty)}개${p.plan.date ? ` · ${koDate(p.plan.date)}` : ''}`
  return p.gate.open ? '열 수 있어요' : '아직 열 수 없어요'
}

function historySummary(d: CaseDetailData): string {
  const last = d.history[d.history.length - 1]
  return last ? `${d.history.length}건 · 마지막 ${koDate(last.sim_date)}` : '기록 없음'
}

export default function CaseDetailPage() {
  const { id } = useParams()
  const { person, failed: viewerFailed, retry: retryViewer } = useViewer()
  const { version } = useClock()
  const [making, setMaking] = useState(false)

  const detailPath = person ? `/api/cases/${id}?viewer=${encodeURIComponent(person.name)}` : null
  const detail = useLoad<CaseDetailData>(detailPath, [version])
  const d = detail.data
  const evidence = useLoad<EvidenceData>(d ? `/api/cases/${id}/evidence` : null, [version])

  /** 상세와 근거를 다시 읽는다. 둘 다 끝나면 풀린다(결정 버튼이 그때까지 잠긴다) */
  const reload = async () => {
    await Promise.all([detail.retry(), evidence.retry()])
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
  const phase2Wait = c.stage === ST_PHASE2_WAIT
  const viewerRole = d.viewer?.role ?? null
  const adjusted = adjustedAmount(d)
  const shownDay = contract ? f.expiry : (f.phase1_date ?? f.settlement_date)
  const note = c.note

  const canMakeBriefing = !!d.viewer?.can_decide || !!d.viewer?.can_decide_phase2
  async function makeBriefing() {
    if (!person) return
    setMaking(true)
    try {
      await api.post(`/api/cases/${id}/briefing`, { actor: person.name })
      await reload()
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
            {c.origin === ORIGIN_DEMO && note && (
              <details className="demo">
                <summary>
                  <b className="demo-tag">시연용 가정</b>
                </summary>
                <p>{note}</p>
              </details>
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
            </div>
          </div>
          <ApprovalStamps label="결재란" roles={d.rule.required_roles} approved={d.rule.approved_roles} viewerRole={viewerRole} canAct={!phase2Wait && !!d.viewer?.can_decide} status={status} stage={c.stage} />
        </div>

        <DecisionPanel detail={d} actor={person?.name ?? ''} onDone={reload} />

        <KeyLines detail={d} evidence={evidence.data} canMake={canMakeBriefing} making={making} onMake={makeBriefing} />

        <ChangeFold escalations={d.escalations} changes={d.approver_changes} />

        {evidence.data ? (
          <EvidenceList data={evidence.data} />
        ) : evidence.error ? (
          <LoadFailed retry={evidence.retry} message={`근거를 불러오지 못했어요. ${evidence.error}`} buttonName="근거 다시 시도" />
        ) : (
          <p role="status" className="muted">
            근거를 불러오는 중…
          </p>
        )}

        <Fold title="부서 회신" summary={requestSummary(d)}>
          <Requests requests={d.requests} />
        </Fold>

        {d.phase2 && (
          <Fold title="2차 집행" summary={phase2Summary(d)}>
            <section className="phase2" aria-label="2차 집행 내용">
              <p>
                <Link to={`/cases/${id}/phase2` + (person ? `?as=${encodeURIComponent(person.name)}` : '')}>2차 집행 관찰 화면 열기</Link>
              </p>
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
                  viewerRole={viewerRole}
                  canAct={phase2Wait && !!d.viewer?.can_decide_phase2}
                  status={status}
                  stage={c.stage}
                />
              )}
            </section>
          </Fold>
        )}

        {d.counterpoints && (
          <Fold title="반대 근거" summary={firstLine(d.counterpoints.text)}>
            <AiBlock bare title="반대 근거" text={d.counterpoints} canMake={false} emptyHint="아직 반대 근거가 없어요." />
          </Fold>
        )}

        {d.briefing && (
          <Fold title="AI 브리핑" summary={firstLine(d.briefing.text)}>
            <AiBlock bare title="AI 브리핑" text={d.briefing} canMake={false} emptyHint="아직 AI 브리핑이 없어요." />
          </Fold>
        )}

        {openTasks(d).length > 0 && (
          <Fold title="남은 작업" summary={`${openTasks(d).length}건`}>
            <Tasks detail={d} />
          </Fold>
        )}

        <Fold title="처리 기록" summary={historySummary(d)}>
          <History events={d.history} />
        </Fold>
      </article>
    </main>
  )
}
