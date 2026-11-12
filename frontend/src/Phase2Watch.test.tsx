import { describe, it, expect, afterEach, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import App from './App'
import { fakeServer } from './test/fakeServer'

const PEOPLE = [
  { name: '캠페인 담당자', role: '캠페인 담당' },
  { name: '마케팅팀장', role: '마케팅팀' },
  { name: 'Masil 대표', role: 'Masil 대표' },
  { name: '그룹 재무', role: '그룹' },
]
const POLICY = [
  { key: 'roles.campaign', value: '캠페인 담당', source: '가정', description: '' },
  { key: 'admin.review_inputters', value: '캠페인 담당,CS', source: '가정', description: '' },
  { key: 'admin.return_inputters', value: 'CS,캠페인 담당', source: '가정', description: '' },
  { key: 'split.stop_z', value: 1.645, source: '통계 관행: 정규분포 한쪽 95% 임계값', description: '반품률이 평소보다 이 z 값만큼 높으면 2차 집행 자동 보류' },
  { key: 'split.return_observe_days', value: 28, source: '가정: 원본에 없음. 1차 집행 뒤 반품이 거의 나타나는 기간을 4주로 봄', description: '2차 집행 전 1차 반품을 관찰하는 기간(일)' },
  { key: 'split.sellthrough_hold_ratio', value: 0.5, source: '가정: 원본에 없음', description: '1차 순판매가 1차 수량의 이 비율 미만이면 2차 보류' },
]
const detailPath = (who: string) => `/api/cases/9?viewer=${encodeURIComponent(who)}`

const GATE_LOCK = { open: false, auto_stopped: false, reasons: ['관찰 28일 미만(10일)'], actions: [], blocked: false }
const phase2Of = (over: Record<string, unknown> = {}) => ({
  plan: { qty: 1400, date: '2026-09-28', amount_krw: 4_000_000 },
  approvers: ['Masil 대표', '그룹'],
  hits: [],
  required_roles: ['Masil 대표', '그룹'],
  pending_roles: [],
  approved_roles: [],
  gate: GATE_LOCK,
  sales: null,
  returns: null,
  sellthrough: null,
  decision: null,
  deadline: '2026-09-28',
  deny_date: '2026-09-25',
  approval_deadline: '2026-09-24',
  exec: null,
  result: null,
  ...over,
})

const REVIEWS = [
  { id: 1, case_id: 9, product: '선크림', text: '사진이랑 색이 달라요', created_at: '2026-09-02' },
  { id: 2, case_id: 9, product: '선크림', text: '잘 발려요', created_at: '2026-09-02' },
]
const REVIEW_JUDGMENTS = [
  { id: 1, kind: '리뷰해석', model: 'fake-리뷰해석기', sim_date: '2026-09-02', input_summary: '선크림 리뷰: 사진이랑 색이 달라요', needs_human: false, confidence: 0.9, result: { reason: '색상불일치', sentiment: '부정', content_gap: true, confidence: 0.9 } },
  { id: 2, kind: '리뷰해석', model: 'fake-리뷰해석기', sim_date: '2026-09-02', input_summary: '선크림 리뷰: 잘 발려요', needs_human: false, confidence: 0.7, result: { reason: '기타', sentiment: '긍정', content_gap: false, confidence: 0.7 } },
]

const VIEW_NONE = { person: '', role: '', can_decide: false, can_escalate: false, can_escalate_phase2: false, can_decide_phase2: false, actions: [], blocked: [], actions_phase2: [], blocked_phase2: [], split_preview: null }

const detailOf = (who: string, role: string, status: string, over: Record<string, unknown> = {}) => ({
  case: { id: 9, kind: '기안', ref_id: 'DEMO-PLAN-001', status, open: true, stage: '2차 관찰', origin: '시연', title: '초혜핏 선케어 캠페인' },
  facts: { phase1: { qty: 2600, date: '2026-08-24' }, reviews: { total: 2, color: 1 }, color_review_flagged: true },
  phase2: phase2Of(),
  reviews: REVIEWS,
  judgments: REVIEW_JUDGMENTS,
  viewer: { ...VIEW_NONE, person: who, role },
  ...over,
})

function mount(who: string) {
  return render(
    <MemoryRouter initialEntries={[`/cases/9/phase2?as=${encodeURIComponent(who)}`]}>
      <App />
    </MemoryRouter>,
  )
}

type Opts = { who?: string; role?: string; status?: string; p2?: Record<string, unknown>; detail?: Record<string, unknown>; mode?: string; extra?: Record<string, never> }
function setup(o: Opts = {}) {
  const who = o.who ?? '캠페인 담당자'
  const role = o.role ?? '캠페인 담당'
  const status = o.status ?? '2차 잠금'
  const p2 = phase2Of(o.p2)
  return fakeServer({
    'GET /api/people': { json: PEOPLE },
    'GET /api/clock': { json: { date: '2026-09-03', mode: o.mode ?? '시연' } },
    'GET /api/policy': { json: POLICY },
    [`GET ${detailPath(who)}`]: { json: detailOf(who, role, status, { phase2: p2, ...o.detail }) },
    'GET /api/cases/9/phase2': { json: p2 },
    ...(o.extra ?? {}),
  })
}

afterEach(() => vi.unstubAllGlobals())

describe('2차 집행 관찰', () => {
  it('2차는_잠금_보류_열림을_보여준다', async () => {
    setup({ status: '2차 잠금' })
    const first = mount('캠페인 담당자')
    let box = await screen.findByRole('region', { name: '2차 잠금 상태' })
    expect(within(box).getByText('잠금')).toBeInTheDocument()
    expect(within(box).getByText(/관찰 28일 미만\(10일\)/)).toBeInTheDocument()
    first.unmount()
    vi.unstubAllGlobals()

    setup({
      status: '2차 보류',
      p2: {
        gate: { open: false, auto_stopped: true, reasons: ['단순변심 반품률 8.0%이 기준 5.1% 초과'], actions: ['2차 자동 보류'], blocked: false },
        returns: { change_of_mind: 208, color: 10, date: '2026-09-02' },
      },
    })
    const second = mount('캠페인 담당자')
    box = await screen.findByRole('region', { name: '2차 잠금 상태' })
    expect(within(box).getByText('보류')).toBeInTheDocument()
    expect(within(box).getByText(/단순변심 반품률 8.0%이 기준 5.1% 초과/)).toBeInTheDocument()
    second.unmount()
    vi.unstubAllGlobals()

    setup({ status: '2차 승인 대기', p2: { gate: { open: true, auto_stopped: false, reasons: [], actions: [], blocked: false } } })
    mount('캠페인 담당자')
    box = await screen.findByRole('region', { name: '2차 잠금 상태' })
    expect(within(box).getByText('열림')).toBeInTheDocument()
    expect(within(box).getByText(/막는 이유가 없어요/)).toBeInTheDocument()
  })

  it('불러오는_중과_실패와_빈_상태', async () => {
    setup({ status: '1차 집행', detail: { phase2: null }, p2: { plan: null, approvers: null, gate: { open: false, auto_stopped: false, reasons: ['2차 집행 없음'], actions: [], blocked: false } } })
    mount('캠페인 담당자')
    expect(screen.getByText('불러오는 중…')).toBeInTheDocument()
    expect(await screen.findByText(/2차 집행이 없는 건이에요/)).toBeInTheDocument()
  })

  it('읽기_실패는_다시_시도', async () => {
    setup({ extra: { 'GET /api/cases/9/phase2': { status: 500, json: { detail: '서버 고장' } } } as never })
    mount('캠페인 담당자')
    expect((await screen.findAllByText(/서버 고장/)).length).toBeGreaterThan(0)
    expect(screen.getByRole('button', { name: '다시 시도' })).toBeInTheDocument()
  })

  it('리뷰_신호에_AI_해석_사유_감정_확신도가_보인다', async () => {
    setup()
    mount('캠페인 담당자')
    const box = await screen.findByRole('region', { name: '리뷰 신호' })
    const b = within(box)
    expect(b.getByText('사진이랑 색이 달라요')).toBeInTheDocument()
    expect(b.getByText('색상불일치')).toBeInTheDocument()
    expect(b.getByText('부정')).toBeInTheDocument()
    expect(b.getByText(/확신도 90%/)).toBeInTheDocument()
    expect(b.getByText(/2건 중 색상불일치 1건/)).toBeInTheDocument()
  })

  it('반품률과_기준을_함께_보인다', async () => {
    setup({
      status: '2차 보류',
      p2: {
        gate: { open: false, auto_stopped: true, reasons: ['단순변심 반품률 8.0%이 기준 5.1% 초과'], actions: ['2차 자동 보류'], blocked: false },
        returns: { change_of_mind: 208, color: 26, date: '2026-09-02' },
      },
    })
    mount('캠페인 담당자')
    const box = await screen.findByRole('region', { name: '반품' })
    const b = within(box)
    // 1차 주문 2,600건 기준 208건 = 8.00%, 26건 = 1.00%
    const mind = b.getByRole('row', { name: /단순변심/ })
    expect(within(mind).getByText('208건')).toBeInTheDocument()
    expect(within(mind).getByText('8.00%')).toBeInTheDocument()
    expect(within(mind).getByText(/기준 5.1% 초과/)).toBeInTheDocument()
    const color = b.getByRole('row', { name: /색상불만/ })
    expect(within(color).getByText('1.00%')).toBeInTheDocument()
    expect(within(color).getByText(/기준 이내/)).toBeInTheDocument()
    // 관찰 기간 보정, 통계 기준
    expect(b.getByText(/1차 집행 후 10일/)).toBeInTheDocument()
    expect(b.getByText(/관찰 기간 28일/)).toBeInTheDocument()
    expect(b.getByText(/z = 1.645/)).toBeInTheDocument()
    expect(b.getByText(/정규분포 한쪽 95% 임계값/)).toBeInTheDocument()
    expect(b.getByText(/2차 자동 보류/)).toBeInTheDocument()
  })

  it('판매율과_중단_기준을_보인다', async () => {
    setup({
      status: '2차 보류',
      p2: {
        gate: { open: true, auto_stopped: false, reasons: [], actions: [], blocked: false },
        sales: { orders: 1000, returns: 100, net: 900, date: '2026-09-02' },
        sellthrough: { rate: 0.346, orders: 1000, returns: 100, net: 900, p1_qty: 2600, hold_ratio: 0.5, qty_before: 1400, amount_before: 4_000_000, outcome: '보류', qty_after: 1400, amount_after: 4_000_000, at: '2026-09-02' },
      },
    })
    mount('캠페인 담당자')
    const box = await screen.findByRole('region', { name: '판매율' })
    const b = within(box)
    expect(b.getByText('34.6%')).toBeInTheDocument()
    expect(b.getByText(/하한 50.0%/)).toBeInTheDocument()
    expect(b.getByText(/900개/)).toBeInTheDocument()
    expect(b.getByText(/2차 보류/)).toBeInTheDocument()
  })

  it('판매율로_조절된_2차_수량을_보인다', async () => {
    setup({
      status: '2차 승인 대기',
      p2: {
        sales: { orders: 2600, returns: 50, net: 2550, date: '2026-08-24' },
        sellthrough: { rate: 0.85, orders: 2600, returns: 50, net: 2550, p1_qty: 3000, hold_ratio: 0.5, qty_before: 1400, amount_before: 4_000_000, outcome: '조절', qty_after: 1190, amount_after: 3_400_000, at: '2026-08-24' },
        gate: { open: true, auto_stopped: false, reasons: [], actions: [], blocked: false },
      },
    })
    mount('캠페인 담당자')
    const b = within(await screen.findByRole('region', { name: '판매율' }))
    expect(b.getByText(/1,400개 → 1,190개/)).toBeInTheDocument()
    expect(b.getByText(/조절/)).toBeInTheDocument()
  })

  it('2차_계속_취소는_권한_있을_때만', async () => {
    const hold = {
      gate: { open: true, auto_stopped: false, reasons: [], actions: [], blocked: false },
      sellthrough: { rate: 0.2, orders: 600, returns: 80, net: 520, p1_qty: 2600, hold_ratio: 0.5, qty_before: 1400, amount_before: 4_000_000, outcome: '보류', qty_after: 1400, amount_after: 4_000_000, at: '2026-09-02' },
      sales: { orders: 600, returns: 80, net: 520, date: '2026-09-02' },
    }
    // 권한 없는 사람: 버튼이 없고 이유 문장
    const none = setup({ who: '마케팅팀장', role: '마케팅팀', status: '2차 보류', p2: hold })
    const first = mount('마케팅팀장')
    await screen.findByRole('region', { name: '2차 잠금 상태' })
    await screen.findByRole('region', { name: '판매율' })
    expect(screen.queryByRole('button', { name: '2차 계속' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '2차 취소' })).not.toBeInTheDocument()
    expect(none.calls.some((c) => c.method === 'POST')).toBe(false)
    first.unmount()
    vi.unstubAllGlobals()

    // 담당 역할: 계속·취소
    const { calls } = setup({
      status: '2차 보류',
      p2: hold,
      extra: {
        'POST /api/cases/9/phase2/cancel': { json: { case_id: 9, choice: '2차 취소', status: '1차 집행' } },
        'POST /api/cases/9/phase2/continue': { json: { case_id: 9, choice: '2차 계속', status: '2차 잠금' } },
      } as never,
    })
    mount('캠페인 담당자')
    await userEvent.click(await screen.findByRole('button', { name: '2차 취소' }))
    const dlg = screen.getByRole('group', { name: '2차 취소' })
    expect(within(dlg).getByRole('button', { name: '취소 확정' })).toBeDisabled() // 이유가 필요
    await userEvent.type(within(dlg).getByLabelText('이유'), '판매가 너무 낮음')
    await userEvent.click(within(dlg).getByRole('button', { name: '취소 확정' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true))
    const cancel = calls.find((c) => c.method === 'POST')
    expect(cancel?.path).toBe('/api/cases/9/phase2/cancel')
    expect(cancel?.body).toEqual({ actor: '캠페인 담당자', reason: '판매가 너무 낮음' })
    // 보낸 뒤 상세를 다시 읽는다
    await waitFor(() => expect(calls.filter((c) => c.path === '/api/cases/9/phase2').length).toBeGreaterThanOrEqual(2))
  })

  it('2차_계속은_수량과_이유를_보낸다', async () => {
    const { calls } = setup({
      status: '2차 보류',
      p2: {
        gate: { open: true, auto_stopped: false, reasons: [], actions: [], blocked: false },
        sellthrough: { rate: 0.2, orders: 600, returns: 80, net: 520, p1_qty: 2600, hold_ratio: 0.5, qty_before: 1400, amount_before: 4_000_000, outcome: '보류', qty_after: 1400, amount_after: 4_000_000, at: '2026-09-02' },
      },
      extra: { 'POST /api/cases/9/phase2/continue': { json: { case_id: 9, choice: '2차 계속', status: '2차 잠금' } } } as never,
    })
    mount('캠페인 담당자')
    await userEvent.click(await screen.findByRole('button', { name: '2차 계속' }))
    const dlg = screen.getByRole('group', { name: '2차 계속' })
    const confirm = within(dlg).getByRole('button', { name: '계속 확정' })
    expect(confirm).toBeDisabled()
    await userEvent.type(within(dlg).getByLabelText('2차 수량'), '700')
    await userEvent.type(within(dlg).getByLabelText('이유'), '재고는 충분함')
    await userEvent.click(confirm)
    await waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true))
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ actor: '캠페인 담당자', qty: 700, reason: '재고는 충분함' })
  })

  it('서버_거부_문장을_그대로_보이고_다시_보낼_수_있다', async () => {
    setup({
      status: '2차 보류',
      p2: { sellthrough: { rate: 0.2, orders: 600, returns: 80, net: 520, p1_qty: 2600, hold_ratio: 0.5, qty_before: 1400, amount_before: 4_000_000, outcome: '보류', qty_after: 1400, amount_after: 4_000_000, at: '2026-09-02' } },
      extra: { 'POST /api/cases/9/phase2/cancel': { status: 403, json: { detail: '캠페인 담당자(캠페인 담당)는 2차 보류를 판단할 수 없음' } } } as never,
    })
    mount('캠페인 담당자')
    await userEvent.click(await screen.findByRole('button', { name: '2차 취소' }))
    const dlg = screen.getByRole('group', { name: '2차 취소' })
    await userEvent.type(within(dlg).getByLabelText('이유'), '사유')
    await userEvent.click(within(dlg).getByRole('button', { name: '취소 확정' }))
    const alerts = await screen.findAllByRole('alert')
    expect(alerts.some((a) => a.textContent?.includes('2차 보류를 판단할 수 없음'))).toBe(true)
    expect(within(dlg).getByRole('button', { name: '취소 확정' })).toBeEnabled()
  })

  it('반품_보류는_2차_승인권자에게_예외_승인_칸', async () => {
    const { calls } = setup({
      who: 'Masil 대표',
      role: 'Masil 대표',
      status: '2차 보류',
      p2: { gate: { open: false, auto_stopped: true, reasons: ['단순변심 반품률 8.0%이 기준 5.1% 초과'], actions: ['2차 자동 보류'], blocked: false } },
      extra: { 'POST /api/cases/9/phase2/exception': { json: { case_id: 9, choice: '예외 승인', status: '2차 잠금' } } } as never,
    })
    mount('Masil 대표')
    await userEvent.click(await screen.findByRole('button', { name: '예외 승인' }))
    const dlg = screen.getByRole('group', { name: '예외 승인' })
    await userEvent.type(within(dlg).getByLabelText('2차 수량'), '900')
    await userEvent.type(within(dlg).getByLabelText('이유'), '반품 원인이 일회성')
    await userEvent.click(within(dlg).getByRole('button', { name: '예외 승인 확정' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true))
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ actor: 'Masil 대표', qty: 900, reason: '반품 원인이 일회성' })
    // 담당 역할이 아니면 계속·취소는 없다
    expect(screen.queryByRole('button', { name: '2차 계속' })).not.toBeInTheDocument()
  })

  it('입력_칸은_입력_권한_역할에게만_운영_모드', async () => {
    setup({ mode: '운영', who: '마케팅팀장', role: '마케팅팀' })
    const first = mount('마케팅팀장')
    await screen.findByRole('region', { name: '2차 잠금 상태' })
    expect(screen.queryByRole('region', { name: '입력' })).not.toBeInTheDocument()
    first.unmount()
    vi.unstubAllGlobals()

    setup({ mode: '운영' })
    mount('캠페인 담당자')
    const box = await screen.findByRole('region', { name: '입력' })
    expect(within(box).getByRole('button', { name: '리뷰 저장' })).toBeInTheDocument()
    expect(within(box).getByRole('button', { name: '반품 저장' })).toBeInTheDocument()
    expect(within(box).getByRole('button', { name: '판매 실적 저장' })).toBeInTheDocument()
  })

  it('시연_모드는_누구나_리뷰와_반품을_입력하되_판매_실적은_담당_역할만', async () => {
    setup({ who: '마케팅팀장', role: '마케팅팀' })
    mount('마케팅팀장')
    const box = await screen.findByRole('region', { name: '입력' })
    expect(within(box).getByRole('button', { name: '리뷰 저장' })).toBeInTheDocument()
    expect(within(box).getByRole('button', { name: '반품 저장' })).toBeInTheDocument()
    expect(within(box).queryByRole('button', { name: '판매 실적 저장' })).not.toBeInTheDocument()
  })

  it('반품과_판매_실적을_저장하면_actor를_담아_보낸다', async () => {
    const { calls } = setup({
      extra: {
        'POST /api/cases/9/returns': { json: { case_id: 9, status: '2차 잠금', gate: { open: false, auto_stopped: false, reasons: [], actions: [], blocked: false } } },
        'POST /api/cases/9/sales': { json: { case_id: 9, status: '2차 잠금' } },
        'POST /api/cases/9/reviews': { json: { case_id: 9, status: '2차 잠금', gate: { open: false, auto_stopped: false, reasons: [], actions: [], blocked: false } } },
      } as never,
    })
    mount('캠페인 담당자')
    const box = await screen.findByRole('region', { name: '입력' })
    const b = within(box)
    await userEvent.type(b.getByLabelText('단순변심 건수'), '20')
    await userEvent.type(b.getByLabelText('색상불만 건수'), '30')
    await userEvent.click(b.getByRole('button', { name: '반품 저장' }))
    await waitFor(() => expect(calls.some((c) => c.path === '/api/cases/9/returns')).toBe(true))
    expect(calls.find((c) => c.path === '/api/cases/9/returns')?.body).toEqual({ change_of_mind: 20, color: 30, actor: '캠페인 담당자' })

    await userEvent.type(b.getByLabelText('주문 수'), '2600')
    await userEvent.type(b.getByLabelText('반품 수'), '50')
    await userEvent.click(b.getByRole('button', { name: '판매 실적 저장' }))
    await waitFor(() => expect(calls.some((c) => c.path === '/api/cases/9/sales')).toBe(true))
    expect(calls.find((c) => c.path === '/api/cases/9/sales')?.body).toEqual({ actor: '캠페인 담당자', orders: 2600, returns: 50 })

    await userEvent.type(b.getByLabelText('제품'), '선크림')
    await userEvent.type(b.getByLabelText('리뷰 내용'), '색이 달라요')
    await userEvent.click(b.getByRole('button', { name: '리뷰 저장' }))
    await waitFor(() => expect(calls.some((c) => c.path === '/api/cases/9/reviews')).toBe(true))
    expect(calls.find((c) => c.path === '/api/cases/9/reviews')?.body).toEqual({ reviews: [{ product: '선크림', text: '색이 달라요' }], actor: '캠페인 담당자' })
  })

  it('2차_승인_대기면_결정은_건_상세로_안내', async () => {
    setup({
      status: '2차 승인 대기',
      who: 'Masil 대표',
      role: 'Masil 대표',
      p2: { gate: { open: true, auto_stopped: false, reasons: [], actions: [], blocked: false } },
      detail: { case: { id: 9, kind: '기안', ref_id: 'DEMO-PLAN-001', status: '2차 승인 대기', open: true, stage: '2차 승인 대기', origin: '시연', title: 't' }, viewer: { ...VIEW_NONE, person: 'Masil 대표', role: 'Masil 대표', can_decide_phase2: true, actions_phase2: ['승인', '거절'] } },
    })
    mount('Masil 대표')
    const link = await screen.findByRole('link', { name: /건 상세에서 2차 결정/ })
    expect(link).toHaveAttribute('href', '/cases/9?as=' + encodeURIComponent('Masil 대표'))
  })
})
