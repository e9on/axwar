import { useId, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api'
import { useClock } from '../state/clock'
import { useViewer } from '../state/viewer'
import { useLoad } from '../state/useLoad'
import { usePreview } from '../state/preview'
import { koDate } from '../date'
import { num, pct, unitValue, won } from '../format'
import { ACT_CANCEL, ACT_CONTINUE, ACT_EXCEPTION, ACT_RETURN, ACT_REVIEW, ACT_SALES, S_PHASE2_HOLD, SELL_ADJUST, SELL_HOLD, SELL_SOLDOUT, ST_PHASE2_WAIT } from '../decisions'
import type { Gate, ObserveCase, Phase2Observe } from '../replyTypes'
import LoadFailed from '../components/LoadFailed'
import { Row } from '../components/EvidenceList'
import '../components/EvidenceList.css'
import './Phase2Watch.css'

/** 잠금 상태 글자: 보류(자동 보류·판매율 보류) / 열림 / 잠금 */
function lockState(status: string, gate: Gate): '잠금' | '보류' | '열림' {
  if (status === S_PHASE2_HOLD || gate.auto_stopped) return '보류'
  return gate.open ? '열림' : '잠금'
}

function LockBox({ status, gate }: { status: string; gate: Gate }) {
  const state = lockState(status, gate)
  return (
    <section className="obs" aria-label="2차 잠금 상태">
      <h3>2차 잠금 상태</h3>
      <p className="lockline">
        <strong className="lock" data-state={state}>
          {state}
        </strong>
        <span className="muted">건 상태 {status}</span>
      </p>
      {gate.reasons.length === 0 ? (
        <p className="muted">지금은 2차를 막는 이유가 없어요.</p>
      ) : (
        <ul className="reasons">
          {gate.reasons.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      )}
    </section>
  )
}

function ReviewBox({ c, p2 }: { c: ObserveCase; p2: Phase2Observe }) {
  const preview = usePreview(p2.reviews)
  const total = c.facts.reviews
  return (
    <section className="obs" aria-label="리뷰 신호">
      <h3>리뷰 신호</h3>
      {total && (
        <p>
          리뷰 {num(total.total)}건 중 색상불일치 {num(total.color)}건
        </p>
      )}
      {p2.reviews.length === 0 ? (
        <p className="muted">아직 입력된 리뷰가 없어요</p>
      ) : (
        <>
          <ul className="lines">
            {preview.visible.map((r) => {
              const j = r.judgment
              return (
                <li key={r.id}>
                  <p>
                    <b>{r.product}</b> · <span>{r.text}</span>
                  </p>
                  {j === null ? (
                    <p className="sub muted">AI 해석 기록 없음</p>
                  ) : j.ok ? (
                    <p className="sub">
                      AI 해석:{' '}
                      <span className="tag">{j.reason ?? '사유 없음'}</span> <span className="tag">{j.sentiment ?? '감정 없음'}</span>
                      {j.content_gap && <span className="tag">콘텐츠 차이</span>}
                      {j.confidence !== null ? ` · 확신도 ${pct(j.confidence)}` : ' · 확신도 없음'}
                      {j.needs_human && ' · 사람 확인 필요'} · {j.model}
                    </p>
                  ) : (
                    <p className="sub over">
                      해석 실패 — 사람 확인 필요<span className="muted"> · {j.error}</span>
                    </p>
                  )}
                </li>
              )
            })}
          </ul>
          {preview.hasMore && (
            <button type="button" className="btn small" onClick={preview.more}>
              더 보기
            </button>
          )}
        </>
      )}
    </section>
  )
}

/** 반품 관찰: 서버가 계산한 기준선·한계값·건수·비율을 그대로 보이고, 줄을 누르면 계산 근거가 펼쳐진다 */
function ReturnBox({ p2 }: { p2: Phase2Observe }) {
  const uid = useId()
  const [open, setOpen] = useState<Set<string>>(new Set())
  const toggle = (id: string) =>
    setOpen((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  const rc = p2.returns_check
  const obs = rc.observation
  return (
    <section className="obs" aria-label="반품">
      <h3>반품</h3>
      {!rc.entered ? (
        <p className="muted">1차 반품 건수가 아직 입력되지 않았어요</p>
      ) : (
        <div className="evidence">
          <ul className="elist">
            {rc.items.map((it) => {
              const id = `${uid}-${it.label}`.replace(/:/g, '')
              return (
                <Row key={it.label} id={id} open={open.has(id)} toggle={toggle} detail={it.detail} kind="indicator">
                  <span className="ecell">{it.label}</span>
                  <span className="ecell n">
                    {num(it.count)}건 · {it.rate === null ? '계산 불가' : unitValue(it.rate, it.unit)}
                  </span>
                  <span className="ecell cmp">
                    {it.limit !== null && `한계 ${unitValue(it.limit, it.unit)}`}
                    {it.baseline !== null && ` · 기준선 ${unitValue(it.baseline, it.unit)} · `}
                    <span className={it.over ? 'over' : undefined}>{it.over ? '초과' : '기준 이내'}</span>
                  </span>
                </Row>
              )
            })}
          </ul>
        </div>
      )}
      <p className="sub">
        1차 집행 수량 {num(rc.phase1_qty)}개{rc.sales_orders !== null && ` · 판매 실적 주문 ${num(rc.sales_orders)}건`}
        {p2.returns && ` · 입력일 ${koDate(p2.returns.date)}`}
      </p>
      <p className="sub">
        관찰 {obs.elapsed_days ?? '—'}일 / {obs.required_days}일 {obs.done ? '(끝남)' : '(진행 중)'}
      </p>
      <p className="sub">{obs.adjustment}</p>
      <p className="sub">통계 기준: 평소 반품률(기준선)보다 z = {num(rc.z)} 이상 높으면 자동 보류해요</p>
      {rc.exception_applied && <p className="sub">예외 승인을 받은 건이라 초과여도 2차를 막지 않아요</p>}
      <p className="stop">
        <b>중단 기준</b> {p2.gate.auto_stopped ? '충족 — 2차 자동 보류' : '충족하지 않음'}
      </p>
    </section>
  )
}

function SellBox({ p2 }: { p2: Phase2Observe }) {
  const s = p2.sellthrough
  const sales = p2.sales
  return (
    <section className="obs" aria-label="판매율">
      <h3>판매율</h3>
      {!sales && !s ? (
        <p className="muted">1차 판매 실적이 아직 입력되지 않았어요</p>
      ) : (
        <>
          {sales && (
            <p>
              1차 판매: 순판매 <b>{num(sales.net)}개</b> <span className="muted">(주문 {num(sales.orders)} − 반품 {num(sales.returns)} · {koDate(sales.date)})</span>
            </p>
          )}
          {s && (
            <>
              <p>
                판매율 <b>{pct(s.rate, 1)}</b> <span className="muted">· 하한 {pct(s.hold_ratio, 1)}</span>
              </p>
              <p className="outcome">
                {s.outcome === SELL_ADJUST && `판매율에 맞춰 2차 수량 ${num(s.qty_before)}개 → ${num(s.qty_after)}개로 조절 (${won(s.amount_before)} → ${won(s.amount_after)})`}
                {s.outcome === SELL_HOLD && `하한에 못 미쳐 2차를 자동으로 줄이지 않고 2차 보류 — 사람이 판단해요`}
                {s.outcome === SELL_SOLDOUT && `1차 전량 판매(품절) — 2차 계획 ${num(s.qty_before)}개 유지${s.excess ? `, 넘친 수요 ${num(s.excess)}개` : ''}`}
              </p>
            </>
          )}
        </>
      )}
      {p2.decision && (
        <p className="decided">
          <b>담당 판단</b> {p2.decision.choice} · {p2.decision.actor} · {koDate(p2.decision.at)} — {p2.decision.reason}
          {p2.decision.qty_before !== p2.decision.qty_after && ` (2차 ${num(p2.decision.qty_before)}개 → ${num(p2.decision.qty_after)}개)`}
        </p>
      )}
    </section>
  )
}

type Judge = 'cancel' | 'continue' | 'exception'
const JUDGE: Record<Judge, { name: string; confirm: string; path: string; qty: boolean }> = {
  cancel: { name: '2차 취소', confirm: '취소 확정', path: 'cancel', qty: false },
  continue: { name: '2차 계속', confirm: '계속 확정', path: 'continue', qty: true },
  exception: { name: '예외 승인', confirm: '예외 승인 확정', path: 'exception', qty: true },
}
/** 서버 동작 이름 → 판단 칸. 서버가 허용한 동작만 버튼이 된다 */
const JUDGE_ACTIONS: [string, Judge][] = [
  [ACT_CONTINUE, 'continue'],
  [ACT_CANCEL, 'cancel'],
  [ACT_EXCEPTION, 'exception'],
]

/** 2차 보류 판단 칸: 계속·취소·예외 승인. 어떤 버튼이 보이는지는 서버(viewer.actions)가 정한다. */
function JudgeBox({ caseId, actor, buttons, planQty, busy, onDone }: { caseId: string; actor: string; buttons: Judge[]; planQty: number | null; busy: boolean; onDone: (note: string) => Promise<void> }) {
  const [open, setOpen] = useState<Judge | null>(null)
  const [reason, setReason] = useState('')
  const [qty, setQty] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const guard = useRef(false)
  const spec = open ? JUDGE[open] : null
  const ready = !!reason.trim() && (!spec?.qty || (qty !== '' && Number.isInteger(Number(qty)) && Number(qty) >= 1))

  async function send() {
    if (!spec || !ready || guard.current) return
    guard.current = true
    setSending(true)
    setError(null)
    try {
      const body = spec.qty ? { actor, qty: Number(qty), reason: reason.trim() } : { actor, reason: reason.trim() }
      const got = await api.post<{ choice?: string; status?: string }>(`/api/cases/${caseId}/phase2/${spec.path}`, body)
      setOpen(null)
      setReason('')
      setQty('')
      await onDone(`${got.choice ?? spec.name}으로 판단했어요${got.status ? ` · 건 상태 ${got.status}` : ''}`)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      guard.current = false
      setSending(false)
    }
  }

  return (
    <div className="jbox">
      <div className="btns">
        {buttons.map((b) => (
          <button key={b} type="button" className={`btn${b === 'cancel' ? ' deny' : ''}`} disabled={busy || sending} aria-expanded={open === b} onClick={() => { setOpen(b); setError(null) }}>
            {JUDGE[b].name}
          </button>
        ))}
      </div>
      {spec && (
        <div role="group" aria-label={spec.name} className="jform">
          {spec.qty && (
            <label>
              2차 수량
              <input type="number" min={1} max={planQty ?? undefined} value={qty} onChange={(e) => setQty(e.target.value)} />
            </label>
          )}
          {spec.qty && planQty !== null && <p className="muted hint">1 이상, 계획 2차 {num(planQty)}개 이하로 적어요</p>}
          <label>
            이유
            <textarea rows={2} value={reason} onChange={(e) => setReason(e.target.value)} />
          </label>
          {error && (
            <p role="alert" className="err">
              {error}
            </p>
          )}
          <div className="btns">
            <button type="button" className="btn pri" disabled={!ready || sending || busy} onClick={() => void send()}>
              {sending ? '보내는 중…' : spec.confirm}
            </button>
            <button type="button" className="btn" disabled={sending} onClick={() => setOpen(null)}>
              닫기
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

/** 입력 칸 하나(리뷰·반품·판매 실적). 보내는 동안 잠그고 서버 문장을 그대로 보인다. */
function InputForm({ title, button, ready, busy, onSend, children }: { title: string; button: string; ready: boolean; busy: boolean; onSend: () => Promise<void>; children: React.ReactNode }) {
  const [error, setError] = useState<string | null>(null)
  const [sending, setSending] = useState(false)
  const guard = useRef(false)
  async function submit() {
    if (guard.current || !ready) return
    guard.current = true
    setSending(true)
    setError(null)
    try {
      await onSend()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      guard.current = false
      setSending(false)
    }
  }
  return (
    <form
      className="iform"
      onSubmit={(e) => {
        e.preventDefault()
        void submit()
      }}
    >
      <h4>{title}</h4>
      {children}
      {error && (
        <p role="alert" className="err">
          {error}
        </p>
      )}
      <button type="submit" className="btn" disabled={!ready || sending || busy}>
        {sending ? '저장하는 중…' : button}
      </button>
    </form>
  )
}

export default function Phase2Watch() {
  const { id } = useParams()
  const { person, failed: viewerFailed, retry: retryViewer } = useViewer()
  const { version } = useClock()
  const [notice, setNotice] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [review, setReview] = useState({ product: '', text: '' })
  const [ret, setRet] = useState({ mind: '', color: '' })
  const [sale, setSale] = useState({ orders: '', returns: '' })

  const detail = useLoad<ObserveCase>(person ? `/api/cases/${id}?viewer=${encodeURIComponent(person.name)}` : null, [version])
  const observe = useLoad<Phase2Observe>(person ? `/api/cases/${id}/phase2?viewer=${encodeURIComponent(person.name)}` : null, [version])
  const d = detail.data
  const p2 = observe.data

  const reload = async () => {
    await Promise.all([detail.retry(), observe.retry()])
  }
  const asQuery = person ? `?as=${encodeURIComponent(person.name)}` : ''
  const back = (
    <Link className="back" to={`/cases/${id}${asQuery}`}>
      ← 건 상세로
    </Link>
  )

  if (viewerFailed) {
    return (
      <main className="page p2page">
        {back}
        <LoadFailed retry={retryViewer} message="보는 사람 목록을 불러오지 못했어요" />
      </main>
    )
  }
  if (!d || !p2) {
    const err = detail.error ?? observe.error
    return (
      <main className="page p2page">
        {back}
        {err ? (
          <LoadFailed retry={reload} message={`2차 집행 관찰을 불러오지 못했어요. ${err}`} />
        ) : (
          <p role="status" className="muted">
            불러오는 중…
          </p>
        )}
      </main>
    )
  }

  const status = d.case.status
  const actor = person?.name ?? ''
  // 누가 무엇을 할 수 있는지는 서버(viewer)가 판정한다. 화면은 역할 이름을 모른다.
  const v = p2.viewer
  const known = !!v && !v.error
  const allowed = (action: string) => !!v?.actions.includes(action)
  const reasonOf = (action: string) => v?.blocked.find((b) => b.action === action)?.reason
  const hold = status === S_PHASE2_HOLD && !p2.decision
  const buttons = JUDGE_ACTIONS.filter(([a]) => allowed(a)).map(([, j]) => j)
  const holdReasons = Array.from(new Set(JUDGE_ACTIONS.flatMap(([a]) => reasonOf(a) ?? [])))
  const inputs = [
    { action: ACT_REVIEW, label: '리뷰' },
    { action: ACT_RETURN, label: '반품' },
    { action: ACT_SALES, label: '판매 실적' },
  ].map((x) => ({ ...x, ok: allowed(x.action), reason: reasonOf(x.action) }))

  /** 보낸 뒤 상세·관찰을 다시 읽고, 끝날 때까지 다른 보내기를 막는다 */
  async function run(note: string, send: () => Promise<unknown>) {
    setBusy(true)
    setNotice(null)
    try {
      await send()
      await reload()
      setNotice(note)
    } finally {
      setBusy(false)
    }
  }

  const planQty = p2.plan?.qty ?? null
  const phase2Wait = status === ST_PHASE2_WAIT
  const decideReasons = Array.from(new Set((v?.blocked_phase2 ?? []).map((b) => b.reason)))

  return (
    <main className="page p2page">
      {back}
      <article className="doc">
        <div className="phead">
          <span className="no">{d.case.ref_id} · 2차 집행 관찰</span>
          <h1>{d.case.title || d.case.ref_id}</h1>
          {p2.plan ? (
            <div className="facts">
              <span>
                2차 계획 <b>{num(p2.plan.qty)}개</b>
              </span>
              {p2.plan.date && (
                <span>
                  집행일 <b>{koDate(p2.plan.date)}</b>
                </span>
              )}
              {p2.plan.amount_krw !== undefined && (
                <span>
                  금액 <b>{won(p2.plan.amount_krw)}</b>
                </span>
              )}
              {p2.required_roles.length > 0 && (
                <span>
                  2차 승인권자 <b>{p2.required_roles.join(' · ')}</b>
                </span>
              )}
              {p2.pending_roles.length > 0 && (
                <span>
                  승인 대기 <b>{p2.pending_roles.join(' · ')}</b>
                </span>
              )}
            </div>
          ) : null}
        </div>

        {!p2.plan ? (
          <p className="muted">2차 집행이 없는 건이에요. 1차만 진행하거나 2차가 취소됐어요.</p>
        ) : (
          <>
            <LockBox status={status} gate={p2.gate} />
            <ReviewBox c={d} p2={p2} />
            <ReturnBox p2={p2} />
            <SellBox p2={p2} />

            {v?.error && (
              <section className="obs" aria-label="보는 사람">
                <h3>보는 사람</h3>
                <p className="err">{v.error}</p>
                <p className="muted">그래서 이 사람이 할 수 있는 동작은 알 수 없어요. 위의 읽기 정보는 그대로 볼 수 있어요.</p>
              </section>
            )}

            {phase2Wait && known && (v.can_decide_phase2 || decideReasons.length > 0) && (
              <section className="obs" aria-label="2차 결정">
                <h3>2차 결정</h3>
                {v.can_decide_phase2 ? (
                  <p>
                    <Link to={`/cases/${id}${asQuery}`}>건 상세에서 2차 결정을 내려요</Link>
                  </p>
                ) : (
                  decideReasons.map((r) => (
                    <p key={r} className="muted">
                      {r}
                    </p>
                  ))
                )}
              </section>
            )}

            {hold && known && (
              <section className="obs" aria-label="2차 판단">
                <h3>2차 판단</h3>
                {buttons.length > 0 && (
                  <JudgeBox
                    caseId={id ?? ''}
                    actor={actor}
                    buttons={buttons}
                    planQty={planQty}
                    busy={busy}
                    onDone={async (note) => {
                      await reload()
                      setNotice(note)
                    }}
                  />
                )}
                {holdReasons.map((r) => (
                  <p key={r} className="muted">
                    {r}
                  </p>
                ))}
              </section>
            )}

            {known && (
              <section className="obs p2inputs" aria-label="입력">
                <h3>입력</h3>
                <p className="muted">누가 입력할 수 있는지는 서버가 판단해요.</p>
                {inputs
                  .filter((x) => !x.ok && x.reason)
                  .map((x) => (
                    <p key={x.action} className="muted">
                      {x.label}: {x.reason}
                    </p>
                  ))}
                <div className="iforms">
                  {inputs[0].ok && (
                    <InputForm
                      title="리뷰"
                      button="리뷰 저장"
                      busy={busy}
                      ready={!!review.product.trim() && !!review.text.trim()}
                      onSend={() =>
                        run('리뷰를 저장하고 AI가 해석했어요', async () => {
                          await api.post(`/api/cases/${id}/reviews`, { reviews: [{ product: review.product.trim(), text: review.text.trim() }], actor })
                          setReview({ product: '', text: '' })
                        })
                      }
                    >
                      <label>
                        제품
                        <input value={review.product} onChange={(e) => setReview({ ...review, product: e.target.value })} />
                      </label>
                      <label>
                        리뷰 내용
                        <textarea rows={2} value={review.text} onChange={(e) => setReview({ ...review, text: e.target.value })} />
                      </label>
                    </InputForm>
                  )}
                  {inputs[1].ok && (
                    <InputForm
                      title="반품"
                      button="반품 저장"
                      busy={busy}
                      ready={ret.mind !== '' && ret.color !== ''}
                      onSend={() =>
                        run('반품 건수를 저장했어요', async () => {
                          await api.post(`/api/cases/${id}/returns`, { change_of_mind: Number(ret.mind), color: Number(ret.color), actor })
                          setRet({ mind: '', color: '' })
                        })
                      }
                    >
                      <label>
                        단순변심 건수
                        <input type="number" min={0} value={ret.mind} onChange={(e) => setRet({ ...ret, mind: e.target.value })} />
                      </label>
                      <label>
                        색상불만 건수
                        <input type="number" min={0} value={ret.color} onChange={(e) => setRet({ ...ret, color: e.target.value })} />
                      </label>
                    </InputForm>
                  )}
                  {inputs[2].ok && (
                    <InputForm
                      title="판매 실적"
                      button="판매 실적 저장"
                      busy={busy}
                      ready={sale.orders !== '' && sale.returns !== ''}
                      onSend={() =>
                        run('판매 실적을 저장했어요', async () => {
                          await api.post(`/api/cases/${id}/sales`, { actor, orders: Number(sale.orders), returns: Number(sale.returns) })
                          setSale({ orders: '', returns: '' })
                        })
                      }
                    >
                      <label>
                        주문 수
                        <input type="number" min={0} value={sale.orders} onChange={(e) => setSale({ ...sale, orders: e.target.value })} />
                      </label>
                      <label>
                        반품 수
                        <input type="number" min={0} value={sale.returns} onChange={(e) => setSale({ ...sale, returns: e.target.value })} />
                      </label>
                    </InputForm>
                  )}
                </div>
              </section>
            )}
            {notice && (
              <p role="status" className="notice-ok">
                {notice}
              </p>
            )}
          </>
        )}
      </article>
    </main>
  )
}
