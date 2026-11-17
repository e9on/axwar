import { useEffect, useId, useRef, type FormEvent, type ReactNode } from 'react'
import './DecisionPanel.css'

const FOCUSABLE = 'button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled])'

type Props = {
  title: string
  /** 보내는 버튼 이름 */
  confirmLabel: string
  /** 보내는 버튼 모양: 기본은 주 버튼, deny는 되돌리기 어려운 일(도장색) */
  tone?: 'pri' | 'deny'
  confirmDisabled?: boolean
  busy?: boolean
  /** 서버가 준 오류 문장(창 안에 그대로) */
  error?: string | null
  onConfirm: () => void
  onCancel: () => void
  children: ReactNode
}

/** 확인 창. 열리면 첫 입력으로 초점이 가고, 창 밖으로 초점이 나가지 않으며, Esc나 취소로 닫으면
 *  연 버튼으로 초점이 돌아간다. 보내는 중에는 닫히지 않는다. 안의 입력에서 Enter를 치면 보낸다. */
export default function FormDialog({ title, confirmLabel, tone = 'pri', confirmDisabled = false, busy = false, error, onConfirm, onCancel, children }: Props) {
  const uid = useId()
  const box = useRef<HTMLDivElement>(null)
  const opener = useRef<HTMLElement | null>(document.activeElement as HTMLElement | null)
  const busyRef = useRef(busy)
  busyRef.current = busy
  const cancelRef = useRef(onCancel)
  cancelRef.current = onCancel

  useEffect(() => {
    const el = box.current
    const first = el?.querySelector<HTMLElement>('[data-autofocus]') ?? el?.querySelector<HTMLElement>(FOCUSABLE)
    first?.focus()
    const back = opener.current
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !busyRef.current) cancelRef.current()
    }
    // 창 밖으로 초점이 새면 되돌린다
    const onFocusIn = (e: FocusEvent) => {
      if (!el || el.contains(e.target as Node)) return
      el.querySelector<HTMLElement>(FOCUSABLE)?.focus()
    }
    window.addEventListener('keydown', onKey)
    document.addEventListener('focusin', onFocusIn)
    return () => {
      window.removeEventListener('keydown', onKey)
      document.removeEventListener('focusin', onFocusIn)
      if (back?.isConnected) back.focus()
    }
  }, [])

  function trapTab(e: React.KeyboardEvent) {
    if (e.key !== 'Tab') return
    const items = Array.from(box.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? [])
    if (items.length === 0) return
    const at = document.activeElement
    if (e.shiftKey && at === items[0]) {
      e.preventDefault()
      items[items.length - 1].focus()
    } else if (!e.shiftKey && at === items[items.length - 1]) {
      e.preventDefault()
      items[0].focus()
    }
  }

  function submit(e: FormEvent) {
    e.preventDefault()
    if (!busy && !confirmDisabled) onConfirm()
  }

  return (
    <div className="dlg-back">
      <div className="dlg" role="dialog" aria-modal="true" aria-labelledby={`${uid}-t`} ref={box} onKeyDown={trapTab}>
        <form onSubmit={submit} aria-busy={busy}>
          <h2 id={`${uid}-t`}>{title}</h2>
          {children}
          {error && (
            <p className="err" role="alert">
              {error}
            </p>
          )}
          <div className="btns">
            <button type="button" className="btn" disabled={busy} onClick={onCancel}>
              취소
            </button>
            <button type="submit" className={`btn ${tone}`} disabled={busy || confirmDisabled}>
              {confirmLabel}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
