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

const detailPath = (who: string) => `/api/cases/9?viewer=${encodeURIComponent(who)}`
const observePath = (who: string) => `/api/cases/9/phase2?viewer=${encodeURIComponent(who)}`

const GATE_LOCK = { open: false, auto_stopped: false, reasons: ['관찰 28일 미만(10일)'], actions: [], blocked: false }
const DETAIL = {
  formula: '한계값 = 기준선 + z × √(기준선 × (1 − 기준선) ÷ 1차 집행 수량)',
  inputs: [
    { label: '기준선(평소 반품률)', value: 0.0438, unit: 'ratio' },
    { label: '1차 집행 수량(건 기록)', value: 3000 },
  ],
  sources: ['02_masil/marketing/mkt_orders_ms.csv'],
  policies: [{ key: 'split.stop_z', value: 1.645, source: '통계 관행: 정규분포 한쪽 95% 임계값', description: 'z 값' }],
}
const RETURNS_CHECK = {
  entered: true,
  phase1_qty: 3000,
  sales_orders: 2600,
  z: 1.645,
  exception_applied: false,
  observation: { required_days: 28, elapsed_days: 10, done: false, adjustment: '보정 없음 — 관찰 기간이 끝날 때까지 2차를 열지 않고 판정을 미룸' },
  items: [
    { label: '단순변심', baseline: 0.0438, phase1_qty: 3000, limit: 0.04999, count: 100, rate: 0.0333, over: false, unit: 'ratio', detail: DETAIL },
    { label: '색상불만', baseline: 0.0377, phase1_qty: 3000, limit: 0.04338, count: 150, rate: 0.05, over: true, unit: 'ratio', detail: DETAIL },
  ],
}
const viewerOf = (who: string, role: string, actions: string[], blocked: { action: string; reason: string }[] = [], over: Record<string, unknown> = {}) => ({
  person: who, role, actions, blocked, actions_phase2: [], blocked_phase2: [], can_decide_phase2: false, ...over,
})
const INPUTS = ['리뷰 입력', '반품 입력', '판매 실적 입력']

const REVIEWS = [
  { id: 1, case_id: 9, product: '선크림', text: '사진이랑 색이 달라요', created_at: '2026-09-02', judgment: { ok: true, id: 1, reason: '색상불일치', sentiment: '부정', content_gap: true, confidence: 0.9, needs_human: false, model: 'fake-리뷰해석기' } },
  { id: 2, case_id: 9, product: '선크림', text: '잘 발려요', created_at: '2026-09-02', judgment: { ok: true, id: 2, reason: '기타', sentiment: '긍정', content_gap: false, confidence: 0.7, needs_human: false, model: 'fake-리뷰해석기' } },
]

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
  reviews: REVIEWS,
  returns_check: RETURNS_CHECK,
  viewer: viewerOf('캠페인 담당자', '캠페인 담당', INPUTS),
  ...over,
})

const detailOf = (status: string, over: Record<string, unknown> = {}) => ({
  case: { id: 9, kind: '기안', ref_id: 'DEMO-PLAN-001', status, open: true, stage: '2차 관찰', origin: '시연', title: '초혜핏 선케어 캠페인' },
  facts: { phase1: { qty: 2600, date: '2026-08-24' }, reviews: { total: 2, color: 1 }, color_review_flagged: true },
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
  const p2 = phase2Of({ viewer: viewerOf(who, role, INPUTS), ...o.p2 })
  return fakeServer({
    'GET /api/people': { json: PEOPLE },
    'GET /api/clock': { json: { date: '2026-09-03', mode: o.mode ?? '시연' } },
    [`GET ${detailPath(who)}`]: { json: detailOf(status, o.detail) },
    [`GET ${observePath(who)}`]: { json: p2 },
    ...(o.extra ?? {}),
  })
}

const HOLD_SELL = {
  gate: { open: true, auto_stopped: false, reasons: [], actions: [], blocked: false },
  sellthrough: { rate: 0.2, orders: 600, returns: 80, net: 520, p1_qty: 2600, hold_ratio: 0.5, qty_before: 1400, amount_before: 4_000_000, outcome: '보류', qty_after: 1400, amount_after: 4_000_000, at: '2026-09-02' },
  sales: { orders: 600, returns: 80, net: 520, date: '2026-09-02' },
}

afterEach(() => vi.unstubAllGlobals())

const HOLD_BLOCK = { open: false, auto_stopped: true, reasons: ['색상불만 반품률 5.0%이 기준 4.3% 초과'], actions: ['2차 자동 보류'], blocked: false }

describe('2차 집행 관찰', () => {
  it('2차는_잠금_보류_열림을_보여준다', async () => {
    setup({ status: '2차 잠금' })
    const first = mount('캠페인 담당자')
    let box = await screen.findByRole('region', { name: '2차 잠금 상태' })
    expect(within(box).getByText('잠금')).toBeInTheDocument()
    expect(within(box).getByText(/관찰 28일 미만\(10일\)/)).toBeInTheDocument()
    first.unmount()
    vi.unstubAllGlobals()

    setup({ status: '2차 보류', p2: { gate: HOLD_BLOCK } })
    const second = mount('캠페인 담당자')
    box = await screen.findByRole('region', { name: '2차 잠금 상태' })
    expect(within(box).getByText('보류')).toBeInTheDocument()
    expect(within(box).getByText(/색상불만 반품률 5.0%이 기준 4.3% 초과/)).toBeInTheDocument()
    second.unmount()
    vi.unstubAllGlobals()

    setup({ status: '2차 승인 대기', p2: { gate: { open: true, auto_stopped: false, reasons: [], actions: [], blocked: false } } })
    mount('캠페인 담당자')
    box = await screen.findByRole('region', { name: '2차 잠금 상태' })
    expect(within(box).getByText('열림')).toBeInTheDocument()
    expect(within(box).getByText(/막는 이유가 없어요/)).toBeInTheDocument()
  })

  it('2차_관찰은_보는_사람을_붙여_읽는다', async () => {
    const { calls } = setup()
    mount('캠페인 담당자')
    await screen.findByRole('region', { name: '2차 잠금 상태' })
    expect(calls.some((c) => c.method === 'GET' && c.path === observePath('캠페인 담당자'))).toBe(true)
    // 사람이 정해지기 전에 viewer 없이 읽지 않는다
    expect(calls.some((c) => c.path === '/api/cases/9/phase2')).toBe(false)
  })

  it('불러오는_중과_실패와_빈_상태', async () => {
    setup({ status: '1차 집행', p2: { plan: null, approvers: null, gate: { open: false, auto_stopped: false, reasons: ['2차 집행 없음'], actions: [], blocked: false } } })
    mount('캠페인 담당자')
    expect(screen.getByText('불러오는 중…')).toBeInTheDocument()
    expect(await screen.findByText(/2차 집행이 없는 건이에요/)).toBeInTheDocument()
  })

  it('읽기_실패는_다시_시도', async () => {
    setup({ extra: { [`GET ${observePath('캠페인 담당자')}`]: { status: 500, json: { detail: '서버 고장' } } } as never })
    mount('캠페인 담당자')
    expect((await screen.findAllByText(/서버 고장/)).length).toBeGreaterThan(0)
    expect(screen.getByRole('button', { name: '다시 시도' })).toBeInTheDocument()
  })

  it('리뷰_신호는_서버가_연결한_해석을_보인다', async () => {
    const reviews = [
      // 같은 글이 두 번: 글 비교가 아니라 서버가 준 해석 그대로
      { ...REVIEWS[0], id: 1 },
      { id: 3, case_id: 9, product: '선크림', text: '사진이랑 색이 달라요', created_at: '2026-09-02', judgment: { ok: true, id: 3, reason: '배송', sentiment: '중립', content_gap: false, confidence: 0.4, needs_human: true, model: 'fake-리뷰해석기' } },
      { id: 4, case_id: 9, product: '선크림', text: '냄새가 이상해요', created_at: '2026-09-02', judgment: { ok: false, error: 'AI 응답 형식 오류' } },
      { id: 5, case_id: 9, product: '선크림', text: '옛날 리뷰', created_at: '2026-08-02', judgment: null },
    ]
    setup({ p2: { reviews } })
    mount('캠페인 담당자')
    const box = await screen.findByRole('region', { name: '리뷰 신호' })
    const b = within(box)
    const rows = b.getAllByRole('listitem')
    expect(rows).toHaveLength(4)
    expect(within(rows[0]).getByText('색상불일치')).toBeInTheDocument()
    expect(within(rows[0]).getByText('부정')).toBeInTheDocument()
    expect(within(rows[0]).getByText(/확신도 90%/)).toBeInTheDocument()
    expect(within(rows[1]).getByText('배송')).toBeInTheDocument()
    expect(within(rows[1]).getByText(/사람 확인 필요/)).toBeInTheDocument()
    expect(within(rows[2]).getByText(/해석 실패 — 사람 확인 필요/)).toBeInTheDocument()
    expect(within(rows[3]).getByText(/AI 해석 기록 없음/)).toBeInTheDocument()
    expect(b.getByText(/2건 중 색상불일치 1건/)).toBeInTheDocument()
  })

  it('리뷰가_많으면_처음_몇_줄만_보이고_더_보기로_늘린다', async () => {
    const many = Array.from({ length: 25 }, (_, i) => ({ ...REVIEWS[1], id: 100 + i, text: `리뷰 ${i + 1}` }))
    setup({ p2: { reviews: many } })
    mount('캠페인 담당자')
    const box = await screen.findByRole('region', { name: '리뷰 신호' })
    expect(within(box).getAllByRole('listitem')).toHaveLength(20)
    await userEvent.click(within(box).getByRole('button', { name: '더 보기' }))
    expect(within(box).getAllByRole('listitem')).toHaveLength(25)
    expect(within(box).queryByRole('button', { name: '더 보기' })).toBeNull()
  })

  it('반품은_서버_기준으로_보이고_화면에서_나누지_않는다', async () => {
    setup({ status: '2차 보류', p2: { gate: HOLD_BLOCK } })
    mount('캠페인 담당자')
    const box = await screen.findByRole('region', { name: '반품' })
    const b = within(box)
    // 건 상세의 1차 수량(2,600)으로 나누면 3.85%지만 서버 값은 3.33%
    const mind = b.getByRole('button', { name: /단순변심/ })
    expect(mind).toHaveTextContent('100건')
    expect(mind).toHaveTextContent('3.33%')
    expect(mind).toHaveTextContent('기준 이내')
    const color = b.getByRole('button', { name: /색상불만/ })
    expect(color).toHaveTextContent('150건')
    expect(color).toHaveTextContent('5.00%')
    expect(color).toHaveTextContent('한계 4.34%')
    expect(color).toHaveTextContent('초과')
    expect(b.getByText(/1차 집행 수량 3,000개/)).toBeInTheDocument()
    expect(b.getByText(/판매 실적 주문 2,600건/)).toBeInTheDocument()
    expect(b.getByText(/관찰 10일 \/ 28일/)).toBeInTheDocument()
    expect(b.getByText(/보정 없음/)).toBeInTheDocument()
    expect(b.getByText(/z = 1.645/)).toBeInTheDocument()
    expect(b.getByText(/2차 자동 보류/)).toBeInTheDocument()
  })

  it('반품_줄을_누르면_계산식과_입력값과_원본이_펼쳐진다', async () => {
    setup({ status: '2차 보류', p2: { gate: HOLD_BLOCK } })
    mount('캠페인 담당자')
    const box = await screen.findByRole('region', { name: '반품' })
    const color = within(box).getByRole('button', { name: /색상불만/ })
    expect(color).toHaveAttribute('aria-expanded', 'false')
    await userEvent.click(color)
    expect(color).toHaveAttribute('aria-expanded', 'true')
    expect(within(box).getAllByText(/한계값 = 기준선 \+ z/).length).toBeGreaterThan(0)
    expect(within(box).getAllByText('mkt_orders_ms.csv').length).toBeGreaterThan(0)
    expect(within(box).getAllByText('4.38%').length).toBeGreaterThan(0) // 비율 단위 입력값
  })

  it('예외_승인을_받은_건과_반품_미입력을_설명한다', async () => {
    setup({ p2: { returns_check: { ...RETURNS_CHECK, exception_applied: true } } })
    const first = mount('캠페인 담당자')
    expect(await screen.findByText(/예외 승인을 받은 건/)).toBeInTheDocument()
    first.unmount()
    vi.unstubAllGlobals()

    setup({ p2: { returns_check: { ...RETURNS_CHECK, entered: false } } })
    mount('캠페인 담당자')
    expect(await screen.findByText(/1차 반품 건수가 아직 입력되지 않았어요/)).toBeInTheDocument()
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

  it('2차_계속_취소_버튼은_서버가_준_동작으로만_정해진다', async () => {
    const reason = '마케팅팀장(마케팅팀)는 2차 보류를 판단할 수 없음 — 캠페인 담당(또는 방치로 올려 받은 사람)만'
    // 서버가 막은 사람: 버튼이 없고 서버 이유 문장
    const none = setup({
      who: '마케팅팀장',
      role: '마케팅팀',
      status: '2차 보류',
      p2: { ...HOLD_SELL, viewer: viewerOf('마케팅팀장', '마케팅팀', ['리뷰 입력', '반품 입력'], [{ action: '2차 계속', reason }, { action: '2차 취소', reason }, { action: '판매 실적 입력', reason: '캠페인 담당만' }]) },
    })
    const first = mount('마케팅팀장')
    await screen.findByRole('region', { name: '2차 잠금 상태' })
    const box = await screen.findByRole('region', { name: '2차 판단' })
    expect(within(box).getAllByText(/2차 보류를 판단할 수 없음/).length).toBeGreaterThan(0)
    expect(screen.queryByRole('button', { name: '2차 계속' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '2차 취소' })).not.toBeInTheDocument()
    expect(none.calls.some((c) => c.method === 'POST')).toBe(false)
    first.unmount()
    vi.unstubAllGlobals()

    // 역할 이름이 전혀 달라도 서버가 허용한 동작이면 버튼이 보인다 (화면은 역할 이름을 모른다)
    const { calls } = setup({
      who: '마케팅팀장',
      role: '아무 역할',
      status: '2차 보류',
      p2: { ...HOLD_SELL, viewer: viewerOf('마케팅팀장', '아무 역할', ['2차 계속', '2차 취소']) },
      extra: {
        'POST /api/cases/9/phase2/cancel': { json: { case_id: 9, choice: '2차 취소', status: '1차 집행' } },
      } as never,
    })
    mount('마케팅팀장')
    await userEvent.click(await screen.findByRole('button', { name: '2차 취소' }))
    const dlg = screen.getByRole('group', { name: '2차 취소' })
    expect(within(dlg).getByRole('button', { name: '취소 확정' })).toBeDisabled() // 이유가 필요
    await userEvent.type(within(dlg).getByLabelText('이유'), '판매가 너무 낮음')
    await userEvent.click(within(dlg).getByRole('button', { name: '취소 확정' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true))
    const cancel = calls.find((c) => c.method === 'POST')
    expect(cancel?.path).toBe('/api/cases/9/phase2/cancel')
    expect(cancel?.body).toEqual({ actor: '마케팅팀장', reason: '판매가 너무 낮음' })
    // 보낸 뒤 다시 읽는다
    await waitFor(() => expect(calls.filter((c) => c.path === observePath('마케팅팀장')).length).toBeGreaterThanOrEqual(2))
    // 알림 문장은 받침에 맞는 조사로(2차 취소 + 로)
    expect(await screen.findByText(/2차 취소로 판단했어요/)).toBeInTheDocument()
    expect(screen.queryByText(/취소으로/)).toBeNull()
  })

  it('끝난_건은_열림_대신_끝남이고_입력_칸이_없다', async () => {
    setup({
      status: '완료',
      detail: { case: { id: 9, kind: '기안', ref_id: 'DEMO-PLAN-001', status: '완료', open: false, stage: '끝남', origin: '시연', title: '초혜핏 선케어 캠페인' } },
      p2: { gate: { open: true, auto_stopped: false, reasons: [], actions: [], blocked: false } },
    })
    mount('캠페인 담당자')
    const box = await screen.findByRole('region', { name: '2차 잠금 상태' })
    expect(within(box).getByText('끝남')).toBeInTheDocument()
    expect(within(box).queryByText('열림')).toBeNull()
    expect(screen.queryByRole('button', { name: '리뷰 저장' })).toBeNull()
    expect(screen.queryByRole('button', { name: '반품 저장' })).toBeNull()
    expect(screen.queryByRole('button', { name: '판매 실적 저장' })).toBeNull()
  })

  it('반품_줄은_한계값이_없어도_이음표가_앞에_붙지_않는다', async () => {
    const rc = { ...RETURNS_CHECK, items: [{ ...RETURNS_CHECK.items[0], limit: null }] }
    setup({ status: '2차 보류', p2: { gate: HOLD_BLOCK, returns_check: rc } })
    mount('캠페인 담당자')
    const box = await screen.findByRole('region', { name: '반품' })
    const row = within(box).getByText('단순변심').closest('li') as HTMLElement
    expect(row.textContent).not.toMatch(/\s·\s*기준선/)
    expect(row.textContent).not.toMatch(/·\s*$/)
  })

  it('2차_계속은_수량과_이유를_보낸다', async () => {
    const { calls } = setup({
      status: '2차 보류',
      p2: { ...HOLD_SELL, viewer: viewerOf('캠페인 담당자', '캠페인 담당', ['2차 계속', '2차 취소', ...INPUTS]) },
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
      p2: { ...HOLD_SELL, viewer: viewerOf('캠페인 담당자', '캠페인 담당', ['2차 계속', '2차 취소']) },
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

  it('예외_승인_칸도_서버_동작으로만', async () => {
    const { calls } = setup({
      who: 'Masil 대표',
      role: 'Masil 대표',
      status: '2차 보류',
      p2: {
        gate: HOLD_BLOCK,
        viewer: viewerOf('Masil 대표', 'Masil 대표', ['예외 승인', '리뷰 입력', '반품 입력'], [{ action: '2차 계속', reason: '반품 보류는 2차 계속을 할 수 없음' }, { action: '2차 취소', reason: '캠페인 담당만' }, { action: '판매 실적 입력', reason: '캠페인 담당만' }]),
      },
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
    expect(screen.queryByRole('button', { name: '2차 계속' })).not.toBeInTheDocument()
    expect(screen.getByText(/반품 보류는 2차 계속을 할 수 없음/)).toBeInTheDocument()
  })

  it('입력_칸은_서버가_허용한_동작만_열고_막힌_것은_이유를_보인다', async () => {
    setup({
      mode: '운영',
      who: '마케팅팀장',
      role: '마케팅팀',
      p2: { viewer: viewerOf('마케팅팀장', '마케팅팀', [], [{ action: '리뷰 입력', reason: '마케팅팀장(마케팅팀)는 리뷰를 입력할 수 없음' }, { action: '반품 입력', reason: '마케팅팀장(마케팅팀)는 반품을 입력할 수 없음' }, { action: '판매 실적 입력', reason: '캠페인 담당만' }]) },
    })
    const first = mount('마케팅팀장')
    await screen.findByRole('region', { name: '2차 잠금 상태' })
    const closed = await screen.findByRole('region', { name: '입력' })
    expect(within(closed).queryByRole('button')).toBeNull()
    expect(within(closed).getByText(/리뷰를 입력할 수 없음/)).toBeInTheDocument()
    expect(within(closed).getByText(/캠페인 담당만/)).toBeInTheDocument()
    first.unmount()
    vi.unstubAllGlobals()

    // 시연 모드에서 리뷰·반품은 열리고 판매 실적만 막힘 (역할이 아니라 서버 답)
    setup({
      who: '마케팅팀장',
      role: '마케팅팀',
      p2: { viewer: viewerOf('마케팅팀장', '마케팅팀', ['리뷰 입력', '반품 입력'], [{ action: '판매 실적 입력', reason: '캠페인 담당만' }]) },
    })
    mount('마케팅팀장')
    const box = await screen.findByRole('region', { name: '입력' })
    expect(within(box).getByRole('button', { name: '리뷰 저장' })).toBeInTheDocument()
    expect(within(box).getByRole('button', { name: '반품 저장' })).toBeInTheDocument()
    expect(within(box).queryByRole('button', { name: '판매 실적 저장' })).not.toBeInTheDocument()
    expect(within(box).getByText(/캠페인 담당만/)).toBeInTheDocument()
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

  it('2차_승인_대기면_결정은_건_상세로_안내하고_링크_끝에_화살표가_없다', async () => {
    setup({
      status: '2차 승인 대기',
      who: 'Masil 대표',
      role: 'Masil 대표',
      p2: {
        gate: { open: true, auto_stopped: false, reasons: [], actions: [], blocked: false },
        viewer: viewerOf('Masil 대표', 'Masil 대표', [], [], { can_decide_phase2: true, actions_phase2: ['승인', '거절'] }),
      },
    })
    mount('Masil 대표')
    const link = await screen.findByRole('link', { name: /건 상세에서 2차 결정/ })
    expect(link).toHaveAttribute('href', '/cases/9?as=' + encodeURIComponent('Masil 대표'))
    expect(link.textContent).not.toMatch(/→/)
  })

  it('2차_승인_거절은_서버의_actions_phase2만_본다', async () => {
    setup({
      status: '2차 승인 대기',
      who: 'Masil 대표',
      role: 'Masil 대표',
      p2: {
        gate: { open: true, auto_stopped: false, reasons: [], actions: [], blocked: false },
        viewer: viewerOf('Masil 대표', 'Masil 대표', [], [], { can_decide_phase2: false, actions_phase2: [], blocked_phase2: [{ action: '승인', reason: '마지막 승인일이 지나 승인할 수 없음' }] }),
      },
    })
    mount('Masil 대표')
    await screen.findByRole('region', { name: '2차 잠금 상태' })
    expect(screen.queryByRole('link', { name: /건 상세에서 2차 결정/ })).toBeNull()
    expect(await screen.findByText(/마지막 승인일이 지나 승인할 수 없음/)).toBeInTheDocument()
  })

  it('모르는_보는_사람이면_보는_사람_부분만_오류로_보인다', async () => {
    setup({
      p2: { viewer: { person: '캠페인 담당자', role: null, error: '등록되지 않은 사람이에요', actions: [], blocked: [], actions_phase2: [], blocked_phase2: [], can_decide_phase2: false } },
    })
    mount('캠페인 담당자')
    expect(await screen.findByRole('region', { name: '2차 잠금 상태' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: '반품' })).toBeInTheDocument()
    expect(screen.getAllByText(/등록되지 않은 사람이에요/).length).toBeGreaterThan(0)
    expect(screen.queryByRole('button', { name: '리뷰 저장' })).toBeNull()
  })
})
