import { fromTo } from '../copy'
import { useState } from 'react'
import { api } from '../api'
import { useViewer } from '../state/viewer'
import { useLoad } from '../state/useLoad'
import { usePermissions } from '../state/permissions'
import { anyValue, num } from '../format'
import { ASSUMPTION_PREFIX } from '../decisions'
import type { PolicyChangeRow, PolicyItem } from '../adminTypes'
import Badge from '../components/Badge'
import ModeControl from '../components/ModeControl'
import FormDialog from '../components/FormDialog'
import LoadFailed from '../components/LoadFailed'
import './Admin.css'

/** 입력한 글을 지금 값과 같은 종류로. 숫자 항목에 숫자가 아닌 글을 넣으면 글 그대로 보내 서버가 거절 문장을 준다 */
function coerce(input: string, current: unknown): unknown {
  const text = input.trim()
  if (typeof current === 'number') {
    const n = Number(text)
    return text !== '' && Number.isFinite(n) ? n : text
  }
  if (typeof current === 'boolean') return text === 'true' || text === '예'
  return text
}

function timeText(at: string): string {
  return at.slice(0, 16).replace('T', ' ')
}

function Editor({ item, onClose, onDone }: { item: PolicyItem; onClose: () => void; onDone: (message: string) => Promise<void> }) {
  const { person } = useViewer()
  const [value, setValue] = useState(anyValue(item.value) === '—' ? '' : String(item.value))
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const changed = value.trim() !== String(item.value ?? '')
  const ready = !!person && changed && reason.trim() !== ''

  async function send() {
    if (!person || busy) return
    setBusy(true)
    setError(null)
    try {
      const row = await api.put<PolicyItem>(`/api/policy/${item.key}`, { actor: person.name, value: coerce(value, item.value), reason: reason.trim() })
      await onDone(`${item.key} 바꿨어요: ${fromTo(anyValue(item.value), anyValue(row.value))}`)
    } catch (e) {
      setError((e as Error).message) // 권한·형식 오류는 서버 문장 그대로
      setBusy(false)
    }
  }

  return (
    <FormDialog title="정책 고치기" confirmLabel="바꾸기" busy={busy} confirmDisabled={!ready} error={error} onConfirm={send} onCancel={onClose}>
      <p className="now">
        <b>{item.key}</b>
        <br />
        {item.description}
      </p>
      <p className="now">
        지금 값 <b>{anyValue(item.value)}</b>
      </p>
      <label className="field">
        새 값
        <input type="text" value={value} onChange={(e) => setValue(e.target.value)} data-autofocus />
      </label>
      <label className="field">
        바꾸는 이유
        <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={3} placeholder="왜 바꾸는지 적어 주세요 (이력에 남아요)" />
      </label>
      <p className="hint">값의 형식은 서버가 확인해요. 바꿀 수 없는 사람이면 서버가 이유를 알려 줘요.</p>
    </FormDialog>
  )
}

export default function Policy() {
  const rows = useLoad<PolicyItem[]>('/api/policy', [])
  const history = useLoad<PolicyChangeRow[]>('/api/policy/history', [])
  const [q, setQ] = useState('')
  const [editing, setEditing] = useState<PolicyItem | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const perm = usePermissions().of('policy')
  const canEdit = !!perm?.allowed // 못 읽었거나 막혔으면 고치기를 열지 않는다

  async function done(message: string) {
    setEditing(null)
    setNotice(message)
    await Promise.all([rows.retry(), history.retry()])
  }

  const needle = q.trim().toLowerCase()
  const found = (rows.data ?? []).filter((r) => !needle || [r.key, r.description, r.source, anyValue(r.value)].join(' ').toLowerCase().includes(needle))

  return (
    <main className="admin">
      <h1>정책 설정</h1>
      <p className="lead">고칠 기준 값을 찾아 고치세요. 이유와 함께 이력에 남아요.</p>
      <ModeControl />
      {perm && !perm.allowed && <p className="note">{perm.reason ?? '이 사람은 정책을 고칠 수 없어요'}</p>}
      {notice && (
        <p className="note" role="status">
          {notice}
        </p>
      )}

      <section aria-label="정책 항목 영역">
        <h2>항목</h2>
        {rows.error ? (
          <LoadFailed retry={rows.retry} message={`정책을 불러오지 못했어요. ${rows.error}`} />
        ) : !rows.data ? (
          <p role="status" className="muted">
            불러오는 중…
          </p>
        ) : (
          <>
            <div className="bar-tools">
              <label>
                정책 검색
                <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="키·설명·출처" />
              </label>
              <span className="muted">{num(found.length)}개</span>
            </div>
            {found.length === 0 ? (
              <p className="muted">찾는 항목이 없어요</p>
            ) : (
              <ul className="ledger policy" aria-label="정책 항목">
                {found.map((r) => (
                  <li key={r.key}>
                    <div>
                      <span className="k">{r.key}</span>
                      <div className="sub">{r.description}</div>
                    </div>
                    <div>
                      <span className="label">값</span>
                      <span className="k">{anyValue(r.value)}</span>
                      {r.overridden && <div className="sub">기본값 {anyValue(r.file_value)}</div>}
                    </div>
                    <div>
                      {r.source.startsWith(ASSUMPTION_PREFIX) && <Badge kind="가정" />}
                      <span className="sub">{r.overridden ? r.effective_source : r.source}</span>
                    </div>
                    {canEdit && (
                      <div className="acts">
                        <button type="button" className="btn small" aria-label={`${r.key} 고치기`} onClick={() => setEditing(r)}>
                          고치기
                        </button>
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </section>

      <section aria-label="변경 이력 영역">
        <h2>변경 이력</h2>
        {history.error ? (
          <LoadFailed retry={history.retry} message={`변경 이력을 불러오지 못했어요. ${history.error}`} />
        ) : !history.data ? (
          <p role="status" className="muted">
            불러오는 중…
          </p>
        ) : history.data.length === 0 ? (
          <p className="muted">바뀐 적이 없어요</p>
        ) : (
          <ul className="ledger history" aria-label="변경 이력">
            {[...history.data].reverse().map((h) => (
              <li key={h.id}>
                <span className="sub">{timeText(h.at)}</span>
                <div>
                  <span className="k">{h.key}</span>
                  <div className="sub">{h.actor}</div>
                </div>
                <span>
                  {fromTo(anyValue(h.before), anyValue(h.after))}
                </span>
                <span>{h.reason ? h.reason : <span className="muted">이유 없음</span>}</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      {editing && <Editor key={editing.key} item={editing} onClose={() => setEditing(null)} onDone={done} />}
    </main>
  )
}
