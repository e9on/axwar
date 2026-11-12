import { useEffect, useId, useState } from 'react'
import { api } from '../api'
import { D_APPROVE, D_REJECT, D_SPLIT, OPINIONS, S_PHASE2_WAIT } from '../decisions'
import { koDate } from '../date'
import { num } from '../format'
import type { CaseDetailData } from '../caseTypes'
import './DecisionPanel.css'

type Props = {
  detail: CaseDetailData
  actor: string
  /** 보낸 뒤 상세를 다시 읽는다 */
  onDone: () => void
}

type Dialog = 'split' | 'reject' | 'escalate' | null
type Reply = { changed?: boolean; message?: string; status?: string }

/** 일반 승인이 열 1차 수량: 서버(_finalize)와 같은 식 — 하루 수량과 물류 몫 중 작은 쪽 */
function plainQty(f: CaseDetailData['facts']): number | null {
  const st = f.stock
  const day = st?.day_qty || f.volume?.units || null
  if (day === null) return null
  return st?.share !== undefined && st?.share !== null && st?.day_qty ? Math.min(day, st.share) : day
}

function dateText(d: string | null | undefined): string {
  return d ? koDate(d) : '날짜 미정'
}

function SplitDiff({ facts }: { facts: CaseDetailData['facts'] }) {
  const s = facts.split
  if (!s) return null
  const plain = plainQty(facts)
  return (
    <div className="diff">
      <p>
        <b>일반 승인</b>: 1차에 {plain === null ? '기안 물량 전체(수량 미정)' : `${num(plain)}개`}를 {dateText(facts.phase1_date ?? s.phase1_date)}에 집행하고, 2차는 없어요.
      </p>
      <p>
        <b>분할 승인</b>: 1차 {num(s.phase1_qty)}개({dateText(s.phase1_date)}), 2차로 넘어가는 수량 {num(s.phase2_qty)}개(
        {dateText(s.phase2_date)}). 2차는 1차 판매·반품 결과를 본 뒤 따로 승인받아요.
      </p>
      {facts.stock?.shortage && <p className="muted">이 건은 재고가 모자라 수량이 나뉘어요(필요 {num(facts.stock.want ?? 0)}개).</p>}
    </div>
  )
}

export default function DecisionPanel({ detail, actor, onDone }: Props) {
  const uid = useId()
  const [dialog, setDialog] = useState<Dialog>(null)
  const [reason, setReason] = useState('')
  const [opinion, setOpinion] = useState<string>('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  useEffect(() => {
    if (!dialog) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && close()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  const phase2 = detail.case.status === S_PHASE2_WAIT
  const v = detail.viewer
  const canDecide = phase2 ? !!v?.can_decide_phase2 : !!v?.can_decide
  const canEscalate = phase2 ? !!v?.can_escalate_phase2 : !!v?.can_escalate
  const pending = phase2 ? (detail.phase2?.pending_roles ?? []) : detail.rule.pending_roles
  const id = detail.case.id
  const hasSplit = !phase2 && !!detail.facts.split

  function close() {
    setDialog(null)
    setReason('')
    setOpinion('')
    setError(null)
  }

  async function send(path: string, body: object) {
    setBusy(true)
    setError(null)
    try {
      const r = await api.post<Reply>(path, { actor, ...body })
      setNotice(r.changed === false ? (r.message ?? '바뀐 것이 없어요') : `보냈어요${r.status ? ` · ${r.status}` : ''}`)
      close()
      onDone()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const decisionPath = phase2 ? `/api/cases/${id}/phase2/decision` : `/api/cases/${id}/decision`
  const decide = (action: string, comment = '') => send(decisionPath, { action, comment })
  const escalate = () => send(`/api/cases/${id}/escalate`, { stage: phase2 ? '2차' : '1차', opinion, reason: reason.trim() })

  return (
    <div className="bar" role="group" aria-label="결정">
      {canDecide ? (
        <>
          <p>{v?.role}로 결재합니다{notice && <span className="muted"> · {notice}</span>}</p>
          <div className="btns">
            <button type="button" className="btn deny" disabled={busy} onClick={() => setDialog('reject')}>
              거절
            </button>
            {canEscalate && (
              <button type="button" className="btn" disabled={busy} onClick={() => setDialog('escalate')}>
                위로 올리기
              </button>
            )}
            {hasSplit && (
              <button type="button" className="btn" disabled={busy} onClick={() => setDialog('split')}>
                분할 승인{detail.facts.split ? ` (1차 ${num(detail.facts.split.phase1_qty)}개)` : ''}
              </button>
            )}
            <button type="button" className="btn pri" disabled={busy} onClick={() => decide(D_APPROVE)}>
              승인
            </button>
          </div>
        </>
      ) : (
        <p>
          {pending.length > 0 ? `승인권자: ${pending.join(' · ')}` : `결정이 끝난 건이에요 (${detail.case.status})`}
          {notice && <span className="muted"> · {notice}</span>}
        </p>
      )}
      {error && !dialog && (
        <p className="err" role="alert">
          {error}
        </p>
      )}

      {dialog && (
        <div className="dlg-back">
          <div className="dlg" role="dialog" aria-modal="true" aria-labelledby={`${uid}-t`}>
            {dialog === 'split' && (
              <>
                <h2 id={`${uid}-t`}>분할 승인 확인</h2>
                <SplitDiff facts={detail.facts} />
              </>
            )}
            {dialog === 'reject' && (
              <>
                <h2 id={`${uid}-t`}>거절 이유</h2>
                <label>
                  <span className="sr-only">거절 이유</span>
                  <textarea value={reason} onChange={(e) => setReason(e.target.value)} placeholder="거절하는 이유를 적어 주세요" rows={3} autoFocus />
                </label>
              </>
            )}
            {dialog === 'escalate' && (
              <>
                <h2 id={`${uid}-t`}>위로 올리기</h2>
                <fieldset>
                  <legend>의견</legend>
                  {OPINIONS.map((o) => (
                    <label key={o} className="opt">
                      <input type="radio" name={`${uid}-op`} value={o} checked={opinion === o} onChange={() => setOpinion(o)} /> {o}
                    </label>
                  ))}
                </fieldset>
                <label>
                  <span className="sr-only">올리는 이유</span>
                  <textarea value={reason} onChange={(e) => setReason(e.target.value)} placeholder="올리는 이유를 적어 주세요" rows={3} />
                </label>
              </>
            )}
            {error && (
              <p className="err" role="alert">
                {error}
              </p>
            )}
            <div className="btns">
              <button type="button" className="btn" disabled={busy} onClick={close}>
                취소
              </button>
              {dialog === 'split' && (
                <button type="button" className="btn pri" disabled={busy} onClick={() => decide(D_SPLIT)}>
                  분할 승인 확정
                </button>
              )}
              {dialog === 'reject' && (
                <button type="button" className="btn deny" disabled={busy || !reason.trim()} onClick={() => decide(D_REJECT, reason.trim())}>
                  거절 확정
                </button>
              )}
              {dialog === 'escalate' && (
                <button type="button" className="btn pri" disabled={busy || !opinion || !reason.trim()} onClick={escalate}>
                  올리기 확정
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
