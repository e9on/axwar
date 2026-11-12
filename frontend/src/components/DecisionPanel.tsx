import { useEffect, useId, useRef, useState } from 'react'
import { api } from '../api'
import { D_APPROVE, D_REJECT, D_SPLIT, OPEN_STATUSES, OPINIONS, S_PHASE2_WAIT } from '../decisions'
import { koDate } from '../date'
import { num, won } from '../format'
import type { CaseDetailData, SplitPreview } from '../caseTypes'
import './DecisionPanel.css'

type Props = {
  detail: CaseDetailData
  actor: string
  /** 보낸 뒤 상세를 다시 읽는다. 읽기가 끝나면 풀리는 약속을 돌려준다(그동안 결정 버튼은 잠긴다) */
  onDone: () => Promise<void>
}

type Dialog = 'split' | 'reject' | 'escalate' | null
type Reply = { changed?: boolean; message?: string; status?: string }
type Blocked = { action: string; reason: string }

function dateText(d: string | null | undefined): string {
  return d ? koDate(d) : '날짜 미정'
}

const FOCUSABLE = 'button:not([disabled]), textarea:not([disabled]), input:not([disabled])'

/** 분할 확인 창 안내: 수량·금액·날짜는 모두 서버가 준 split_preview 값 그대로(화면에서 계산하지 않음) */
function SplitDiff({ preview, approveBlocked }: { preview: SplitPreview; approveBlocked: Blocked | undefined }) {
  return (
    <div className="diff">
      {approveBlocked ? (
        <p>일반 승인은 지금 할 수 없어요: {approveBlocked.reason}</p>
      ) : (
        <p>
          <b>일반 승인</b>: 2차 없이 한 번에 집행해요.
        </p>
      )}
      <p>
        <b>분할 승인</b>: 1차 {num(preview.phase1_qty)}개({won(preview.phase1_amount_krw)}, {dateText(preview.phase1_date)}),{' '}
        {preview.phase2_qty > 0
          ? `2차로 넘어가는 수량 ${num(preview.phase2_qty)}개(${won(preview.phase2_amount_krw)}, ${dateText(preview.phase2_date)}). 2차는 1차 판매·반품 결과를 본 뒤 따로 승인받아요.`
          : '2차로 넘어가는 수량은 없어요.'}
      </p>
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
  const inflight = useRef(false)
  const dlgRef = useRef<HTMLDivElement>(null)
  const opener = useRef<HTMLElement | null>(null)

  useEffect(() => {
    if (!dialog) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && !busy && close()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  // 창 밖으로 초점이 새면 되돌린다(라디오 묶음처럼 Tab 순서를 브라우저가 건너뛰는 경우 포함)
  const shiftDown = useRef(false)
  useEffect(() => {
    if (!dialog) return
    const onFocusIn = (e: FocusEvent) => {
      const box = dlgRef.current
      if (!box || box.contains(e.target as Node)) return
      const items = Array.from(box.querySelectorAll<HTMLElement>(FOCUSABLE))
      ;(shiftDown.current ? items[items.length - 1] : items[0])?.focus()
    }
    const onKey = (e: KeyboardEvent) => {
      shiftDown.current = e.shiftKey
    }
    document.addEventListener('focusin', onFocusIn)
    document.addEventListener('keydown', onKey, true)
    return () => {
      document.removeEventListener('focusin', onFocusIn)
      document.removeEventListener('keydown', onKey, true)
    }
  }, [dialog])

  // 열리면 첫 입력(없으면 첫 버튼)으로 초점
  useEffect(() => {
    if (!dialog) return
    const box = dlgRef.current
    const first = box?.querySelector<HTMLElement>('[data-autofocus]') ?? box?.querySelector<HTMLElement>(FOCUSABLE)
    first?.focus()
  }, [dialog])

  // 닫히고 보내는 일도 끝났으면 연 버튼으로 초점 복귀
  useEffect(() => {
    if (dialog || busy || !opener.current) return
    const el = opener.current
    opener.current = null
    if (el.isConnected && !(el as HTMLButtonElement).disabled) el.focus()
  }, [dialog, busy])

  const phase2 = detail.case.status === S_PHASE2_WAIT
  const v = detail.viewer
  const canDecide = phase2 ? !!v?.can_decide_phase2 : !!v?.can_decide
  const canEscalate = phase2 ? !!v?.can_escalate_phase2 : !!v?.can_escalate
  const actions = canDecide ? ((phase2 ? v?.actions_phase2 : v?.actions) ?? []) : []
  const blocked: Blocked[] = canDecide && !phase2 ? (v?.blocked ?? []) : []
  const preview = v?.split_preview ?? null
  const pending = phase2 ? (detail.phase2?.pending_roles ?? []) : detail.rule.pending_roles
  const id = detail.case.id
  const showSplit = !phase2 && actions.includes(D_SPLIT) && !!preview
  const open = (d: Exclude<Dialog, null>) => {
    opener.current = document.activeElement as HTMLElement | null
    setDialog(d)
  }

  function close() {
    setDialog(null)
    setReason('')
    setOpinion('')
    setError(null)
  }

  function trapTab(e: React.KeyboardEvent) {
    if (e.key !== 'Tab') return
    const items = Array.from(dlgRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? [])
    if (items.length === 0) return
    const first = items[0]
    const last = items[items.length - 1]
    const at = document.activeElement
    if (e.shiftKey && (at === first || !dlgRef.current?.contains(at))) {
      e.preventDefault()
      last.focus()
    } else if (!e.shiftKey && (at === last || !dlgRef.current?.contains(at))) {
      e.preventDefault()
      first.focus()
    }
  }

  async function send(path: string, body: object) {
    if (inflight.current) return
    inflight.current = true
    setBusy(true)
    setError(null)
    try {
      const r = await api.post<Reply>(path, { actor, ...body })
      setNotice(r.changed === false ? (r.message ?? '바뀐 것이 없어요') : `보냈어요${r.status ? ` · ${r.status}` : ''}`)
      close()
      await onDone() // 다시 읽기가 끝날 때까지 버튼을 잠근다
    } catch (e) {
      setError((e as Error).message)
    } finally {
      inflight.current = false
      setBusy(false)
    }
  }

  const decisionPath = phase2 ? `/api/cases/${id}/phase2/decision` : `/api/cases/${id}/decision`
  const decide = (action: string, comment = '') => send(decisionPath, { action, comment })
  const escalate = () => send(`/api/cases/${id}/escalate`, { stage: phase2 ? '2차' : '1차', opinion, reason: reason.trim() })

  const open_ = OPEN_STATUSES.includes(detail.case.status)
  return (
    <div className="bar" role="group" aria-label="결정" aria-busy={busy}>
      {canDecide ? (
        <>
          <p>
            {v?.role}로 결재합니다
            {busy && <span className="muted"> · 보내는 중…</span>}
            {!busy && notice && <span className="muted"> · {notice}</span>}
          </p>
          {blocked.length > 0 && (
            <ul className="blocked" aria-label="지금 할 수 없는 결정">
              {blocked.map((b) => (
                <li key={b.action}>
                  <b>{b.action}</b>은 지금 할 수 없어요 · {b.reason}
                </li>
              ))}
            </ul>
          )}
          <div className="btns">
            {actions.includes(D_REJECT) && (
              <button type="button" className="btn deny" disabled={busy} onClick={() => open('reject')}>
                거절
              </button>
            )}
            {canEscalate && (
              <button type="button" className="btn" disabled={busy} onClick={() => open('escalate')}>
                위로 올리기
              </button>
            )}
            {showSplit && preview && (
              <button type="button" className="btn" disabled={busy} onClick={() => open('split')}>
                분할 승인 (1차 {num(preview.phase1_qty)}개)
              </button>
            )}
            {actions.includes(D_APPROVE) && (
              <button type="button" className="btn pri" disabled={busy} onClick={() => send(decisionPath, { action: D_APPROVE, comment: '' })}>
                승인
              </button>
            )}
          </div>
        </>
      ) : (
        <p>
          {pending.length > 0
            ? `승인권자: ${pending.join(' · ')}`
            : open_ || phase2
              ? `아직 열려 있는 건이에요 — 다른 회신이나 결정을 기다리고 있어요 (${detail.case.status})`
              : `결정이 끝난 건이에요 (${detail.case.status})`}
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
          <div className="dlg" role="dialog" aria-modal="true" aria-labelledby={`${uid}-t`} ref={dlgRef} onKeyDown={trapTab}>
            {dialog === 'split' && (
              <>
                <h2 id={`${uid}-t`}>분할 승인 확인</h2>
                {preview && <SplitDiff preview={preview} approveBlocked={blocked.find((b) => b.action === D_APPROVE)} />}
              </>
            )}
            {dialog === 'reject' && (
              <>
                <h2 id={`${uid}-t`}>거절 이유</h2>
                <label>
                  <span className="sr-only">거절 이유</span>
                  <textarea value={reason} onChange={(e) => setReason(e.target.value)} placeholder="거절하는 이유를 적어 주세요" rows={3} data-autofocus />
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
                      <input type="radio" name={`${uid}-op`} value={o} data-autofocus={o === OPINIONS[0] ? true : undefined} checked={opinion === o} onChange={() => setOpinion(o)} /> {o}
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
                <button type="button" className="btn pri" disabled={busy} data-autofocus onClick={() => decide(D_SPLIT)}>
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
