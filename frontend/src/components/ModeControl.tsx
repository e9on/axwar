import { useState } from 'react'
import { api } from '../api'
import { useClock } from '../state/clock'
import { useViewer } from '../state/viewer'
import { usePermissions } from '../state/permissions'
import { DEMO_MODE, OPERATION_MODE } from '../decisions'
import FormDialog from './FormDialog'

/** 모드 전환 확인 창. 누가 바꿀 수 있는지는 서버가 정하고, 거절 문장은 창 안에 그대로 보인다 */
function ModeSwitch({ onClose }: { onClose: () => void }) {
  const { person } = useViewer()
  const { mode, refresh } = useClock()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const next = mode === DEMO_MODE ? OPERATION_MODE : DEMO_MODE

  async function send() {
    if (!person || busy) return
    setBusy(true)
    setError(null)
    try {
      await api.put('/api/mode', { actor: person.name, mode: next })
      await refresh() // 기준일·모드를 다시 읽어 시연 링크와 기준일 이동이 맞게 바뀐다
      onClose()
    } catch (e) {
      setError((e as Error).message)
      setBusy(false)
    }
  }

  return (
    <FormDialog title="모드 전환" confirmLabel={`${next} 모드로 바꾸기`} tone="deny" busy={busy} confirmDisabled={!person} error={error} onConfirm={send} onCancel={onClose}>
      <p>
        지금은 <b>{mode} 모드</b>예요. <b>{next} 모드로</b> 바꿀까요?
      </p>
      <p className="hint">
        {next === OPERATION_MODE
          ? '운영 모드에서는 기준일을 옮기거나 시연 조작판을 쓸 수 없어요.'
          : '시연 모드에서는 시연 조작판과 기준일 이동을 쓸 수 있어요.'}
      </p>
    </FormDialog>
  )
}

/** 정책 화면 안의 모드 줄: 지금 모드와 전환 버튼(권한은 서버가 정함, 못 읽는 동안은 버튼을 열지 않음) */
export default function ModeControl() {
  const { mode } = useClock()
  const [switching, setSwitching] = useState(false)
  const perm = usePermissions().of('mode')
  if (!mode) return null
  return (
    <section className="mode-line" aria-label="모드">
      <span>
        지금은 <b>{mode} 모드</b>예요.
      </span>
      {perm?.allowed && (
        <button type="button" className="btn small" onClick={() => setSwitching(true)}>
          모드 전환
        </button>
      )}
      {perm && !perm.allowed && <span className="muted">{perm.reason ?? '이 사람은 모드를 바꿀 수 없어요'}</span>}
      {switching && <ModeSwitch onClose={() => setSwitching(false)} />}
    </section>
  )
}
