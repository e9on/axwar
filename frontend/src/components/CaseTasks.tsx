import { useState } from 'react'
import { api } from '../api'
import { koDate } from '../date'
import { num } from '../format'
import type { CaseDetailData } from '../caseTypes'
import Badge from './Badge'
import FormDialog from './FormDialog'
import './CaseTasks.css'

type Props = { detail: CaseDetailData; actor: string; onDone: () => Promise<void> }

/** 보내고 다시 읽기. 실패하면 창 안에 서버 문장을 보인다 */
function useSend(onDone: () => Promise<void>) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  async function send(path: string, body: object): Promise<boolean> {
    setBusy(true)
    setError(null)
    try {
      await api.post(path, body)
      await onDone()
      return true
    } catch (e) {
      setError((e as Error).message)
      return false
    } finally {
      setBusy(false)
    }
  }
  return { busy, error, setError, send }
}

/** 1차 공지: 캠페인 담당이 승인된 1차 수량을 소비자에게 알린다. 단추는 서버가 지금 공지할 수 있다고 할 때만(can_announce) */
export function AnnounceAction({ detail, actor, onDone }: Props) {
  const [open, setOpen] = useState(false)
  const { busy, error, setError, send } = useSend(onDone)
  if (!detail.viewer?.can_announce) return null
  const phase1 = detail.facts.phase1 ?? null
  return (
    <section className="case-task" aria-label="1차 공지">
      <p>
        승인된 1차 수량을 공지할 차례예요.
        {phase1 && <> 1차 <b>{num(phase1.qty)}개</b>{phase1.date && <> · {koDate(phase1.date)}</>}</>}
      </p>
      <button type="button" className="btn pri" onClick={() => setOpen(true)}>
        1차 공지
      </button>
      {open && (
        <FormDialog
          title="1차 수량을 공지합니다"
          confirmLabel="공지 확정"
          busy={busy}
          error={error}
          onConfirm={async () => (await send(`/api/cases/${detail.case.id}/announce`, { actor })) && setOpen(false)}
          onCancel={() => { setOpen(false); setError(null) }}
        >
          <p>{phase1 ? `${num(phase1.qty)}개를 공지하면 그 수량만큼 재고와 물류를 먼저 잡아 둬요. 공지한 수량은 바꿀 수 없어요.` : '공지하면 1차 수량만큼 재고와 물류를 먼저 잡아 둬요.'}</p>
        </FormDialog>
      )}
    </section>
  )
}

/** 조건변경 통보 초안(기본 거부된 계약). 누구나 읽고, 발송은 서버가 허락한 사람만(can_send_notice) */
export function NoticeDraft({ detail, actor, onDone }: Props) {
  const [open, setOpen] = useState(false)
  const { busy, error, setError, send } = useSend(onDone)
  const notice = detail.facts.notice ?? null
  if (!notice) return null
  const sent = !!notice.sent_text
  const lines = (notice.sent_text ?? notice.text ?? '').split('\n').filter((l) => l.trim())
  return (
    <section className="case-task notice" aria-label="조건변경 통보 초안">
      <h3>
        조건변경 통보 {sent ? '(발송함)' : '초안'} {!sent && <Badge kind="AI" />}
      </h3>
      {notice.ok || sent ? (
        <div className="notice-text">{lines.map((l, i) => <p key={i}>{l}</p>)}</div>
      ) : (
        <p className="muted">AI가 초안을 만들지 못했어요. 통보문을 직접 써서 보내야 해요.</p>
      )}
      {!sent && notice.ok && detail.viewer?.can_send_notice && (
        <button type="button" className="btn pri" onClick={() => setOpen(true)}>
          통보 발송
        </button>
      )}
      {open && (
        <FormDialog
          title="조건변경 통보를 보냅니다"
          confirmLabel="발송 확정"
          busy={busy}
          error={error}
          onConfirm={async () => (await send(`/api/cases/${detail.case.id}/send-notice`, { actor })) && setOpen(false)}
          onCancel={() => { setOpen(false); setError(null) }}
        >
          <p>위 초안을 인플루언서 측에 보내고 회신을 기다려요. 보낸 뒤에는 되돌릴 수 없어요.</p>
        </FormDialog>
      )}
    </section>
  )
}
