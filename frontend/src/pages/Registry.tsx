import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { useViewer } from '../state/viewer'
import { useLoad } from '../state/useLoad'
import { actionLine, num, won } from '../format'
import type { ContractRow, PlanImport, PlanRow, RegisterReply, ServerAction } from '../adminTypes'
import FormDialog from '../components/FormDialog'
import LoadFailed from '../components/LoadFailed'
import './Admin.css'

/** 입력 칸. name은 서버 등록부 항목 이름(backend store 기안·계약 항목) */
type Spec = { name: string; label: string; kind: 'text' | 'int' | 'date' | 'bool'; required?: boolean; locked?: boolean; hint?: string }

const OPEN_HINT = '건을 열려면 필요'
const PLAN_SPECS: Spec[] = [
  { name: 'plan_id', label: '기안 번호', kind: 'text', required: true, locked: true },
  { name: 'campaign_id', label: '캠페인', kind: 'text' },
  { name: 'influencer_id', label: '인플루언서', kind: 'text' },
  { name: 'channel', label: '채널', kind: 'text' },
  { name: 'requested_budget_krw', label: '요청액(원)', kind: 'int', hint: OPEN_HINT },
  { name: 'expected_gmv_krw', label: '예상 매출(원)', kind: 'int' },
  { name: 'settlement_date', label: '정산일', kind: 'date', hint: OPEN_HINT },
  { name: 'contract_deadline', label: '계약 확정 기한', kind: 'date', hint: OPEN_HINT },
]
const CONTRACT_SPECS: Spec[] = [
  { name: 'influencer_code', label: '인플루언서 코드', kind: 'text', required: true },
  { name: 'influencer_name', label: '이름', kind: 'text', required: true },
  { name: 'annual_fixed_krw', label: '연 고정비(원)', kind: 'int', required: true },
  { name: 'performance_fee_text', label: '성과 보수 조건', kind: 'text' },
  { name: 'notice_deadline', label: '통보 기한', kind: 'date', required: true },
  { name: 'expiry_date', label: '만료일', kind: 'date', required: true },
  { name: 'auto_renew', label: '자동 갱신', kind: 'bool' },
  { name: 'source_doc', label: '근거 문서', kind: 'text', locked: true },
]

/** 서버 출처 구분 → 화면 이름 */
const ORIGIN_LABEL: Record<string, string> = { 가져오기: '원본', 화면: '화면 등록', 시연: '시연' }

type Values = Record<string, string | boolean>
type Target = { kind: 'plan' | 'contract'; row: PlanRow | ContractRow | null }
type Notice = { title: string; lines: string[]; caseId?: number }

function initialValues(specs: Spec[], row: Record<string, unknown> | null): Values {
  const out: Values = {}
  for (const s of specs) {
    const v = row?.[s.name]
    out[s.name] = s.kind === 'bool' ? Boolean(v) : v === null || v === undefined ? '' : String(v)
  }
  return out
}

/** 입력을 서버로 보낼 항목으로. 비운 칸은 빼고, 고칠 때는 바뀐 항목만 */
function buildFields(specs: Spec[], values: Values, row: Record<string, unknown> | null): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const s of specs) {
    if (row && s.locked) continue
    const raw = values[s.name]
    if (s.kind === 'bool') {
      if (row ? Boolean(row[s.name]) !== raw : raw === true) out[s.name] = raw
      continue
    }
    const text = String(raw).trim()
    if (text === '') continue
    if (row && String(row[s.name] ?? '') === text) continue
    const n = Number(text)
    out[s.name] = s.kind === 'int' && Number.isFinite(n) ? n : text // 숫자가 아니면 글 그대로 보내 서버가 거절 문장을 준다
  }
  return out
}

function RowForm({ target, actor, onClose, onDone }: { target: Target; actor: string; onClose: () => void; onDone: (n: Notice) => Promise<void> }) {
  const plan = target.kind === 'plan'
  const specs = plan ? PLAN_SPECS : CONTRACT_SPECS
  const row = target.row as Record<string, unknown> | null
  const [values, setValues] = useState<Values>(() => initialValues(specs, row))
  const [openCase, setOpenCase] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fields = buildFields(specs, values, row)
  const missing = specs.some((s) => s.required && !row && String(values[s.name]).trim() === '')
  const ready = row ? Object.keys(fields).length > 0 : !missing
  const idText = row ? String(plan ? (row as unknown as PlanRow).plan_id : (row as unknown as ContractRow).influencer_code) : ''
  const label = plan ? '기안' : '계약'

  async function send() {
    if (busy) return
    setBusy(true)
    setError(null)
    try {
      if (!row) {
        const r = await api.post<RegisterReply>(plan ? '/api/plans' : '/api/contracts', { actor, fields, open_case: openCase })
        const id = r.plan_id ?? r.influencer_code ?? ''
        const lines = r.case_id !== null ? [] : r.open_error ? [`등록은 됐지만 건은 열지 못했어요: ${r.open_error}`] : []
        await onDone({ title: `${label} ${id}을(를) 등록했어요`, lines, caseId: r.case_id ?? undefined })
      } else {
        const path = plan ? `/api/plans/${encodeURIComponent(idText)}` : `/api/contracts/${(row as unknown as ContractRow).id}`
        const r = await api.put<{ actions: ServerAction[] }>(path, { actor, fields })
        await onDone({ title: `${label} ${idText}을(를) 고쳤어요`, lines: (r.actions ?? []).map(actionLine) })
      }
    } catch (e) {
      setError((e as Error).message)
      setBusy(false)
    }
  }

  return (
    <FormDialog
      title={row ? `${idText} 수정` : `새 ${label} 등록`}
      confirmLabel={row ? '고치기' : '등록'}
      busy={busy}
      confirmDisabled={!ready}
      error={error}
      onConfirm={send}
      onCancel={onClose}
    >
      {specs.map((s, i) => {
        const locked = !!row && !!s.locked
        const text = `${s.label}${s.required && !row ? ' (필수)' : ''}`
        if (s.kind === 'bool')
          return (
            <label key={s.name} className="field check">
              <input type="checkbox" checked={values[s.name] === true} onChange={(e) => setValues({ ...values, [s.name]: e.target.checked })} />
              {s.label}
            </label>
          )
        return (
          <label key={s.name} className="field">
            {text}
            <input
              type={s.kind === 'date' ? 'date' : 'text'}
              inputMode={s.kind === 'int' ? 'numeric' : undefined}
              value={String(values[s.name])}
              disabled={locked}
              data-autofocus={i === 0 && !locked ? true : undefined}
              onChange={(e) => setValues({ ...values, [s.name]: e.target.value })}
            />
            {s.hint && !row && <span className="hint">{s.hint}</span>}
          </label>
        )
      })}
      {!row && (
        <label className="field check">
          <input type="checkbox" checked={openCase} onChange={(e) => setOpenCase(e.target.checked)} />
          등록하고 바로 건 열기
        </label>
      )}
    </FormDialog>
  )
}

function originLabel(o: string): string {
  return ORIGIN_LABEL[o] ?? o
}

export default function Registry() {
  const { person } = useViewer()
  const plans = useLoad<PlanRow[]>('/api/plans', [])
  const contracts = useLoad<ContractRow[]>('/api/contracts', [])
  const [form, setForm] = useState<Target | null>(null)
  const [notice, setNotice] = useState<Notice | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const guard = useRef(false)
  const actor = person?.name ?? ''

  async function reload() {
    await Promise.all([plans.retry(), contracts.retry()])
  }

  /** 서버에 한 번 보내는 일. 보내는 동안 다른 버튼을 잠그고, 실패하면 서버 문장을 보인다 */
  async function run(job: () => Promise<Notice | null>) {
    if (guard.current || !actor) return
    guard.current = true
    setBusy(true)
    setError(null)
    try {
      const n = await job()
      if (n) setNotice(n)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      guard.current = false
      setBusy(false)
    }
  }

  const openCase = (kind: 'plan' | 'contract', id: string) =>
    run(async () => {
      const path = kind === 'plan' ? `/api/plans/${encodeURIComponent(id)}/open` : `/api/contracts/${encodeURIComponent(id)}/open`
      const r = await api.post<{ case_id: number }>(path, { actor })
      return { title: `${id}의 건을 열었어요`, lines: [], caseId: r.case_id }
    })

  const importPlans = () =>
    run(async () => {
      const r = await api.post<PlanImport>('/api/import/plans', { actor })
      const lines = [
        `새로 ${num(r.added)}건 · 갱신 ${num(r.updated)}건 · 변동 없음 ${num(r.unchanged)}건`,
        ...r.skipped.map((s) => `${s.plan_id}: ${s.reason}${s.source_changed.length > 0 ? ` (원본이 달라진 항목: ${s.source_changed.join(', ')})` : ''}`),
        ...r.warnings,
        ...r.actions.map(actionLine),
      ]
      await reload()
      return { title: '기안 원본 가져오기 결과', lines }
    })

  const importContracts = () =>
    run(async () => {
      const r = await api.post<{ count: number; actions: ServerAction[] }>('/api/import/contracts', { actor })
      await reload()
      return { title: '계약 통보 가져오기 결과', lines: [`계약 통보 ${num(r.count)}건을 가져왔어요`, ...r.actions.map(actionLine)] }
    })

  const sync = () =>
    run(async () => {
      const r = await api.post<{ actions: ServerAction[] }>('/api/sync', { actor })
      await reload()
      return { title: '원본 다시 맞추기 결과', lines: r.actions.length > 0 ? r.actions.map(actionLine) : ['바뀐 것이 없어요'] }
    })

  async function formDone(n: Notice) {
    setForm(null)
    setNotice(n)
    await reload()
  }

  const lock = busy || !actor
  return (
    <main className="admin">
      <h1>기안·계약 등록</h1>
      <p className="lead">판정할 기안과 계약을 등록부에 넣어요. 누가 할 수 있는지는 서버가 정해요.</p>

      <div className="bar-tools">
        <button type="button" className="btn pri" disabled={lock} onClick={() => setForm({ kind: 'plan', row: null })}>
          새 기안
        </button>
        <button type="button" className="btn pri" disabled={lock} onClick={() => setForm({ kind: 'contract', row: null })}>
          새 계약
        </button>
        <button type="button" className="btn" disabled={lock} onClick={importPlans}>
          기안 원본 가져오기
        </button>
        <button type="button" className="btn" disabled={lock} onClick={importContracts}>
          계약 통보 가져오기
        </button>
        <button type="button" className="btn" disabled={lock} onClick={sync}>
          원본 다시 맞추기
        </button>
        {busy && <span className="muted">보내는 중…</span>}
      </div>
      {error && (
        <p className="err" role="alert">
          {error}
        </p>
      )}
      {notice && (
        <div className="note" role="status">
          <p>
            <b>{notice.title}</b>
            {notice.caseId !== undefined && (
              <>
                {' '}
                <Link to={`/cases/${notice.caseId}${person ? `?as=${encodeURIComponent(person.name)}` : ''}`}>건 #{notice.caseId} 보기</Link>
              </>
            )}
          </p>
          {notice.lines.length > 0 && (
            <ul>
              {notice.lines.map((l, i) => (
                <li key={i}>{l}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      <section aria-label="기안 영역">
        <h2>기안</h2>
        {plans.error ? (
          <LoadFailed retry={plans.retry} message={`기안을 불러오지 못했어요. ${plans.error}`} />
        ) : !plans.data ? (
          <p className="muted">불러오는 중…</p>
        ) : plans.data.length === 0 ? (
          <p className="muted">등록된 기안이 없어요</p>
        ) : (
          <ul className="ledger plans" aria-label="기안 목록">
            {plans.data.map((p) => (
              <li key={p.id}>
                <div>
                  <span className="k">{p.plan_id}</span>
                  <span className="origin">{originLabel(p.origin)}</span>
                </div>
                <div className="sub">{[p.campaign_id, p.influencer_id, p.channel].filter(Boolean).join(' · ') || '캠페인·인플루언서 미정'}</div>
                <div className="sub">
                  요청액 {p.requested_budget_krw !== null ? won(p.requested_budget_krw) : '미정'}
                  {p.expected_gmv_krw !== null && <> · 예상 매출 {won(p.expected_gmv_krw)}</>}
                </div>
                <div className="sub">
                  정산일 {p.settlement_date ?? '미정'} · 확정 기한 {p.contract_deadline ?? '미정'}
                </div>
                <div className="acts">
                  <button type="button" className="btn small" disabled={lock} onClick={() => setForm({ kind: 'plan', row: p })}>
                    수정
                  </button>
                  <button type="button" className="btn small" disabled={lock} onClick={() => openCase('plan', p.plan_id)}>
                    건 열기
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-label="계약 영역">
        <h2>계약</h2>
        {contracts.error ? (
          <LoadFailed retry={contracts.retry} message={`계약을 불러오지 못했어요. ${contracts.error}`} />
        ) : !contracts.data ? (
          <p className="muted">불러오는 중…</p>
        ) : contracts.data.length === 0 ? (
          <p className="muted">등록된 계약이 없어요</p>
        ) : (
          <ul className="ledger contracts" aria-label="계약 목록">
            {contracts.data.map((c) => (
              <li key={c.id}>
                <div>
                  <span className="k">{c.influencer_code}</span>
                  <span className="origin">{originLabel(c.origin)}</span>
                </div>
                <div className="sub">{c.influencer_name}</div>
                <div className="sub">
                  연 고정비 {won(c.annual_fixed_krw)}
                  {c.auto_renew && ' · 자동 갱신'}
                </div>
                <div className="sub">
                  통보 기한 {c.notice_deadline} · 만료일 {c.expiry_date}
                </div>
                <div className="acts">
                  <button type="button" className="btn small" disabled={lock} onClick={() => setForm({ kind: 'contract', row: c })}>
                    수정
                  </button>
                  <button type="button" className="btn small" disabled={lock} onClick={() => openCase('contract', c.influencer_code)}>
                    건 열기
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      {form && <RowForm key={`${form.kind}-${form.row ? 'edit' : 'new'}`} target={form} actor={actor} onClose={() => setForm(null)} onDone={formDone} />}
    </main>
  )
}
