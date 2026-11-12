import { describe, it, expect, afterEach, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import App from './App'
import { fakeServer } from './test/fakeServer'

const PEOPLE = [
  { name: 'Masil 대표', role: 'Masil 대표' },
  { name: '마케팅팀장', role: '마케팅팀' },
]
const DETAIL_PATH = (who: string) => `/api/cases/7?viewer=${encodeURIComponent(who)}`

const detailOf = (viewer: object, over: Record<string, unknown> = {}) => ({
  case: { id: 7, kind: '기안', ref_id: 'DEMO-PLAN-001', status: '승인 대기', origin: '시연', title: '초혜핏 선케어 캠페인2 · 초혜핏 (시연용)' },
  facts: {
    amount_krw: 8_000_000,
    plan_total_krw: 8_000_000,
    settlement_date: '2026-09-14',
    phase1_date: '2026-09-14',
    deadline: '2026-09-11',
    split: { phase1_qty: 400, phase1_date: '2026-09-14', phase2_qty: 243, phase2_date: '2026-10-05' },
    stock: { day_qty: 643, share: 643, want: 643, shortage: true },
    volume: { units: 160857 },
  },
  rule: { approvers: ['Masil 대표'], hits: [], required_roles: ['마케팅팀', 'Masil 대표'], approved_roles: ['마케팅팀'], pending_roles: ['Masil 대표'] },
  phase2: null,
  deadline: '2026-09-11',
  deny_date: '2026-09-08',
  approval_deadline: '2026-09-07',
  escalations: [
    { stage: '1차', from: '마케팅팀', to: 'Masil 대표', actor: '마케팅팀장', opinion: '승인 권고', reason: '대표 확인이 필요함', at: '2026-09-04', active: true },
  ],
  briefing: { text: '재고가 모자라 분할 승인이 안전합니다.', ok: true, model: 'claude-test-1', sim_date: '2026-09-04', stale: false },
  counterpoints: { text: '표본이 적어요.', ok: true, model: 'claude-test-1', sim_date: '2026-09-04', stale: false },
  approver_changes: [
    { before: ['마케팅팀'], after: ['Masil 대표'], reason: '상신: 마케팅팀가 Masil 대표에게 올림', at: '2026-09-04' },
    { before: ['Masil 대표'], after: ['Masil 대표', '그룹 CEO'], reason: '하회 구간이라 CEO 추가', at: '2026-09-05' },
  ],
  approvals: [],
  requests: [
    {
      id: 1, dept: '물류', purpose: '물류 처리 능력', text: '처리량을 알려 주세요', status: '처리됨', attach_required: false,
      replies: [{ id: 1, text: '전량 가능합니다', attachments: 0, created_at: '2026-07-01' }],
    },
  ],
  tasks: [],
  judgments: [
    { id: 1, kind: '회신해석', model: 'fake-해석기', sim_date: '2026-07-01', input_summary: '물류 회신: 전량 가능합니다', needs_human: false, confidence: 1, result: { stance: '수용' } },
  ],
  history: [
    { id: 1, sim_date: '2026-07-01', kind: '사건생성', actor: '시스템', detail: {} },
    { id: 2, sim_date: '2026-07-02', kind: '요청생성', actor: '시스템', detail: {} },
    { id: 3, sim_date: '2026-07-03', kind: '회신접수', actor: '부서', detail: {} },
    { id: 4, sim_date: '2026-09-04', kind: '상신', actor: '마케팅팀장', detail: { reason: '대표 확인' } },
  ],
  viewer: viewer,
  ...over,
})

const MAY = { person: 'Masil 대표', role: 'Masil 대표', can_decide: true, can_escalate: true, can_escalate_phase2: false, can_decide_phase2: false }
const NOT = { person: '마케팅팀장', role: '마케팅팀', can_decide: false, can_escalate: false, can_escalate_phase2: false, can_decide_phase2: false }

const D = (formula: string, over: object = {}) => ({ formula, inputs: [], sources: [], policies: [], ...over })
const EVIDENCE = {
  available: true,
  reason: null,
  influencer_id: 'INF-002',
  signals: [
    {
      key: 'forecast_gap', label: '예상 ROAS 괴리', value: 10.4, compare: '명목 ROAS 최대 6.66', level: 'red', badge: '계산', judgment: '참고',
      exclude_reason: '예상 GMV 기반이라 판정에서 뺌',
      detail: D('예상 ROAS = 기안 예상 GMV ÷ 요청 예산', {
        inputs: [{ label: '요청 예산', value: 4807921 }, { label: '과대 예상', value: true }],
        sources: ['02_masil/marketing/mkt_budget_plan_ms.csv'],
      }),
    },
    {
      key: 'spend_concentration', label: '광고비 쏠림(HHI)', value: 2461.7, compare: '기준 1800 초과', level: 'green', badge: '가정', judgment: '판정', exclude_reason: '',
      detail: D('HHI = 비중 제곱의 합', {
        policies: [{ key: 'signals.hhi_limit', value: 1800, source: '가정: 원본에 없음', description: '쏠림이 위험인 기준' }],
      }),
    },
    { key: 'cannibalization', label: '다른 채널 잠식', value: null, compare: '측정 불가', level: 'unmeasurable', badge: '계산', judgment: '판정', exclude_reason: '', detail: D('고객이 나뉘어 측정 불가') },
  ],
  key_indicators: [
    { key: 'real_roas', label: '실질 ROAS', value: 3.7, rank: 1, of: 10, compare_label: null, compare_value: null, badge: '계산', detail: D('실질 ROAS 식') },
  ],
  cost_breakdown: {
    note: '표본 금액이라 실제 계약액과 곱하지 않음',
    rows: [{ key: 'gmv', label: '매출(GMV)', amount: 121676523, badge: '계산', detail: D('귀속 주문 GMV 합') }],
  },
  breakeven: { key: 'be', label: '본전에 필요한 기록 밖 판매', value: 0, compare: '0이면 이미 본전 이상', level: 'green', badge: '계산', judgment: '판정', exclude_reason: '', detail: D('필요 비율 식') },
  attribution_note: '마지막 클릭 후 7일 기준',
  rule: {
    approver_hits: [{ rule_id: 'plan_within_delegation', text: '건별 한도 이하라 마케팅팀 전결', source: 'approval_authority_policy.md', badge: '원본', detail: D('한도 비교') }],
    indicator_hits: [],
    phase2_approver_hits: [],
  },
}

function Setup(viewer: object, who: string, extra: Record<string, { status?: number; json?: unknown }> = {}, over: Record<string, unknown> = {}) {
  return fakeServer({
    'GET /api/people': { json: PEOPLE },
    'GET /api/clock': { json: { date: '2026-09-05', mode: '시연' } },
    [`GET ${DETAIL_PATH(who)}`]: { json: detailOf(viewer, over) },
    'GET /api/cases/7/evidence': { json: EVIDENCE },
    'GET /api/plans/DEMO-PLAN-001': { json: { raw: { note: '시연용 가정: 원본 기안을 복사해 요청액만 바꿈' } } },
    ...extra,
  })
}

function mount(who: string) {
  return render(
    <MemoryRouter initialEntries={[`/cases/7?as=${encodeURIComponent(who)}`]}>
      <App />
    </MemoryRouter>,
  )
}

afterEach(() => vi.unstubAllGlobals())

async function evidenceReady() {
  await screen.findByRole('button', { name: /예상 ROAS 괴리/ })
}

describe('건 상세', () => {
  it('근거마다_배지가_보인다', async () => {
    Setup(MAY, 'Masil 대표')
    mount('Masil 대표')
    await evidenceReady()
    const rows = document.querySelectorAll('.evidence .ebtn')
    expect(rows.length).toBeGreaterThanOrEqual(7)
    rows.forEach((r) => expect(r.querySelector('.b')).not.toBeNull())
    const evidence = within(document.querySelector('.evidence') as HTMLElement)
    expect(evidence.getAllByText('계산').length).toBeGreaterThan(0)
    expect(evidence.getAllByText('가정').length).toBeGreaterThan(0)
    expect(evidence.getAllByText('원본').length).toBeGreaterThan(0)
    // 수준은 색만이 아니라 글자로도
    expect(evidence.getByText('나쁨')).toBeInTheDocument()
    expect(evidence.getByText('좋음')).toBeInTheDocument()
    expect(evidence.getAllByText('측정 불가').length).toBeGreaterThan(0)
    expect(screen.getByText(/표본 금액이라 실제 계약액과 곱하지 않음/)).toBeInTheDocument()
    expect(screen.getByText(/마지막 클릭 후 7일 기준/)).toBeInTheDocument()
  })

  it('근거_줄을_누르면_계산식_입력값_원본_정책이_펼쳐진다', async () => {
    Setup(MAY, 'Masil 대표')
    mount('Masil 대표')
    const gap = await screen.findByRole('button', { name: /예상 ROAS 괴리/ })
    expect(gap).toHaveAttribute('aria-expanded', 'false')
    await userEvent.click(gap)
    expect(gap).toHaveAttribute('aria-expanded', 'true')
    const panel = document.getElementById(gap.getAttribute('aria-controls') as string) as HTMLElement
    expect(panel).toBeVisible()
    const p = within(panel)
    expect(p.getByText(/예상 ROAS = 기안 예상 GMV ÷ 요청 예산/)).toBeInTheDocument()
    expect(p.getByText('요청 예산')).toBeInTheDocument()
    expect(p.getByText('4,807,921')).toBeInTheDocument()
    expect(p.getByText('mkt_budget_plan_ms.csv').tagName).toBe('B') // 파일 이름만 굵게
    expect(p.getByText(/02_masil\/marketing\//)).toBeInTheDocument() // 경로는 흐리게
    expect(p.getByText(/판정에서 뺀 이유/)).toBeInTheDocument()

    const hhi = screen.getByRole('button', { name: /광고비 쏠림/ })
    await userEvent.click(hhi)
    const hp = within(document.getElementById(hhi.getAttribute('aria-controls') as string) as HTMLElement)
    expect(hp.getByText('signals.hhi_limit')).toBeInTheDocument()
    expect(hp.getByText(/출처: 가정: 원본에 없음/)).toBeInTheDocument()
    expect(hp.getByText('쏠림이 위험인 기준')).toBeInTheDocument()
    expect(hp.getByText('1,800')).toBeInTheDocument()
    // 한 번에 여러 줄이 펼쳐진다
    expect(gap).toHaveAttribute('aria-expanded', 'true')
  })

  it('다시_누르면_접힌다_키보드로도', async () => {
    Setup(MAY, 'Masil 대표')
    mount('Masil 대표')
    const gap = await screen.findByRole('button', { name: /예상 ROAS 괴리/ })
    gap.focus()
    await userEvent.keyboard('{Enter}')
    expect(gap).toHaveAttribute('aria-expanded', 'true')
    await userEvent.keyboard('{Enter}')
    expect(gap).toHaveAttribute('aria-expanded', 'false')
    expect(document.getElementById(gap.getAttribute('aria-controls') as string)).not.toBeVisible()
    await userEvent.keyboard(' ')
    expect(gap).toHaveAttribute('aria-expanded', 'true')
    await userEvent.click(gap)
    expect(gap).toHaveAttribute('aria-expanded', 'false')
  })

  it('승인권자가_아니면_버튼_대신_승인권자_이름', async () => {
    Setup(NOT, '마케팅팀장')
    mount('마케팅팀장')
    expect(await screen.findByText('승인권자: Masil 대표')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '승인' })).toBeNull()
    expect(screen.queryByRole('button', { name: '거절' })).toBeNull()
  })

  it('승인을_누르면_POST_decision_후_다시_읽는다', async () => {
    const { calls } = Setup(MAY, 'Masil 대표', {
      'POST /api/cases/7/decision': { json: { changed: true, status: '승인 대기' } },
    })
    mount('Masil 대표')
    await userEvent.click(await screen.findByRole('button', { name: '승인' }))
    await waitFor(() => expect(calls.filter((c) => c.method === 'POST' && c.path === '/api/cases/7/decision')).toHaveLength(1))
    const post = calls.find((c) => c.method === 'POST' && c.path === '/api/cases/7/decision')
    expect(post?.body).toEqual({ actor: 'Masil 대표', action: '승인', comment: '' })
    const detailCalls = () => calls.filter((c) => c.method === 'GET' && c.path === DETAIL_PATH('Masil 대표')).length
    await waitFor(() => expect(detailCalls()).toBe(2))
  })

  it('분할승인은_차이를_보여주고_확인을_받는다', async () => {
    const { calls } = Setup(MAY, 'Masil 대표', {
      'POST /api/cases/7/decision': { json: { changed: true, status: '분할 승인' } },
    })
    mount('Masil 대표')
    await userEvent.click(await screen.findByRole('button', { name: /^분할 승인/ }))
    const dlg = screen.getByRole('dialog')
    expect(within(dlg).getByText(/일반 승인/)).toBeInTheDocument()
    expect(within(dlg).getByText(/1차에 643개/)).toBeInTheDocument()
    expect(within(dlg).getByText(/1차 400개/)).toBeInTheDocument()
    expect(within(dlg).getByText(/2차로 넘어가는 수량 243개/)).toBeInTheDocument()
    expect(calls.some((c) => c.method === 'POST')).toBe(false)
    await userEvent.click(within(dlg).getByRole('button', { name: '분할 승인 확정' }))
    await waitFor(() => expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ actor: 'Masil 대표', action: '분할승인', comment: '' }))
  })

  it('거절은_이유가_있어야_보낸다', async () => {
    const { calls } = Setup(MAY, 'Masil 대표', { 'POST /api/cases/7/decision': { json: { changed: true, status: '거절' } } })
    mount('Masil 대표')
    await userEvent.click(await screen.findByRole('button', { name: '거절' }))
    const dlg = screen.getByRole('dialog')
    const ok = within(dlg).getByRole('button', { name: '거절 확정' })
    expect(ok).toBeDisabled()
    await userEvent.type(within(dlg).getByRole('textbox'), '지표가 나빠요')
    expect(ok).toBeEnabled()
    await userEvent.click(ok)
    await waitFor(() => expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ actor: 'Masil 대표', action: '거절', comment: '지표가 나빠요' }))
  })

  it('상신은_의견과_이유가_있어야_보낸다', async () => {
    const { calls } = Setup(MAY, 'Masil 대표', { 'POST /api/cases/7/escalate': { json: { changed: true } } })
    mount('Masil 대표')
    await userEvent.click(await screen.findByRole('button', { name: '위로 올리기' }))
    const dlg = screen.getByRole('dialog')
    const ok = within(dlg).getByRole('button', { name: '올리기 확정' })
    expect(ok).toBeDisabled()
    await userEvent.type(within(dlg).getByRole('textbox'), '권한을 넘어요')
    expect(ok).toBeDisabled() // 의견이 아직 없음
    await userEvent.click(within(dlg).getByRole('radio', { name: '반대 권고' }))
    expect(ok).toBeEnabled()
    await userEvent.click(ok)
    await waitFor(() =>
      expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ actor: 'Masil 대표', stage: '1차', opinion: '반대 권고', reason: '권한을 넘어요' }),
    )
  })

  it('AI_글에는_AI_배지와_모델', async () => {
    Setup(MAY, 'Masil 대표')
    mount('Masil 대표')
    const h = await screen.findByRole('heading', { name: 'AI 브리핑' })
    const box = h.parentElement as HTMLElement
    expect(within(box).getByText('AI')).toHaveClass('ai')
    expect(within(box).getByText(/재고가 모자라 분할 승인이 안전합니다/)).toBeInTheDocument()
    expect(within(box).getByText(/claude-test-1 · 9월 4일/)).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '반대 근거' })).toBeInTheDocument()
    expect(screen.queryByText(/사실이 바뀌어 다시 만들어야 함/)).toBeNull()
  })

  it('낡은_브리핑은_다시_만들어야_한다고_알리고_버튼이_다시_만든다', async () => {
    const stale = { text: '옛 글', ok: true, model: 'claude-test-1', sim_date: '2026-09-01', stale: true }
    const { calls } = Setup(MAY, 'Masil 대표', { 'POST /api/cases/7/briefing': { json: {} } }, { briefing: stale })
    mount('Masil 대표')
    expect(await screen.findByText('사실이 바뀌어 다시 만들어야 함')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'AI 브리핑 다시 만들기' }))
    await waitFor(() => expect(calls.find((c) => c.path === '/api/cases/7/briefing')?.body).toEqual({ actor: 'Masil 대표' }))
  })

  it('브리핑이_없으면_결재할_사람에게만_만들기_버튼', async () => {
    Setup(MAY, 'Masil 대표', {}, { briefing: null, counterpoints: null })
    mount('Masil 대표')
    expect(await screen.findByRole('button', { name: 'AI 브리핑 만들기' })).toBeInTheDocument()
  })

  it('브리핑이_없고_권한도_없으면_버튼이_없다', async () => {
    Setup(NOT, '마케팅팀장', {}, { briefing: null, counterpoints: null })
    mount('마케팅팀장')
    await screen.findByText('승인권자: Masil 대표')
    expect(screen.queryByRole('button', { name: /AI 브리핑/ })).toBeNull()
  })

  it('회신에는_회신_배지와_AI_해석_결과', async () => {
    Setup(MAY, 'Masil 대표')
    mount('Masil 대표')
    const text = await screen.findByText('전량 가능합니다')
    const reply = text.closest('.reply') as HTMLElement
    expect(within(reply).getByText('회신')).toHaveClass('reply')
    expect(within(reply).getByText(/해석: 수용/)).toBeInTheDocument()
    expect(within(reply).getByText(/fake-해석기 · 사람 확인 불필요/)).toBeInTheDocument()
  })

  it('결재선_변경_이력이_보인다', async () => {
    Setup(MAY, 'Masil 대표')
    mount('Masil 대표')
    const list = await screen.findByRole('list', { name: '결재선 변경 이력' })
    expect(within(list).getByText(/마케팅팀 → Masil 대표, 상신\(승인 권고\): 대표 확인이 필요함/)).toBeInTheDocument()
    expect(within(list).getByText(/Masil 대표 → Masil 대표·그룹 CEO: 하회 구간이라 CEO 추가/)).toBeInTheDocument()
    expect(within(list).getAllByRole('listitem')).toHaveLength(2) // 상신은 한 번만
  })

  it('결재란은_승인한_칸에_도장_내_차례_표시', async () => {
    Setup(MAY, 'Masil 대표')
    mount('Masil 대표')
    const stamps = await screen.findByRole('list', { name: '결재란' })
    expect(within(stamps).getByRole('listitem', { name: '마케팅팀: 승인함' })).toBeInTheDocument()
    expect(within(stamps).getByText('마케팅')).toHaveClass('seal')
    const mine = within(stamps).getByRole('listitem', { name: 'Masil 대표: 내 차례' })
    expect(mine).toBeInTheDocument()
  })

  it('시연_기안은_시연용_가정_표시', async () => {
    Setup(MAY, 'Masil 대표')
    mount('Masil 대표')
    expect(await screen.findByText('시연용 가정')).toBeInTheDocument()
    expect(await screen.findByText(/원본 기안을 복사해 요청액만 바꿈/)).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('초혜핏 선케어 캠페인2')
  })

  it('서류_머리에_요청액_집행일_확정_기한', async () => {
    Setup(MAY, 'Masil 대표')
    mount('Masil 대표')
    await screen.findByRole('heading', { level: 1 })
    expect(screen.getByText('8,000,000원')).toBeInTheDocument()
    expect(screen.getByText('9월 14일')).toBeInTheDocument()
    expect(screen.getByText('9월 11일')).toBeInTheDocument()
    expect(screen.queryByText(/조절 후 금액/)).toBeNull()
  })

  it('2차_조절로_금액이_달라지면_조절_후_금액', async () => {
    const phase2 = {
      plan: { qty: 100, date: '2026-10-05', amount_krw: 1_000_000 }, approvers: ['Masil 대표'], hits: [], required_roles: ['Masil 대표'],
      pending_roles: [], approved_roles: [], gate: { open: false, auto_stopped: false, reasons: ['관찰 기간'] }, deadline: null, deny_date: null,
      approval_deadline: null, decision: { amount_before: 3_000_000, amount_after: 1_000_000 }, result: null,
    }
    Setup(NOT, '마케팅팀장', {}, { phase2 })
    mount('마케팅팀장')
    expect(await screen.findByText('6,000,000원')).toBeInTheDocument()
    expect(screen.getByText(/조절 후 금액/)).toBeInTheDocument()
    expect(screen.getByRole('list', { name: '2차 결재란' })).toBeInTheDocument()
  })

  it('기본거부까지_남은_날', async () => {
    Setup(MAY, 'Masil 대표')
    mount('Masil 대표')
    const clock = await screen.findByLabelText('남은 날')
    expect(within(clock).getByText('3일')).toBeInTheDocument()
    expect(within(clock).getByText(/9월 8일에 기본 거부/)).toBeInTheDocument()
    expect(within(clock).getByText(/마지막 승인일은/)).toBeInTheDocument()
    expect(within(clock).getByText('9월 7일')).toBeInTheDocument()
  })

  it('끝난_건은_남은_날_대신_결과_문장', async () => {
    const closed = { rule: { approvers: [], hits: [], required_roles: ['마케팅팀'], approved_roles: [], pending_roles: [] }, case: { id: 7, kind: '기안', ref_id: 'P-1', status: '기본 거부', origin: '화면' } }
    Setup(NOT, '마케팅팀장', {}, closed)
    mount('마케팅팀장')
    const clock = await screen.findByLabelText('남은 날')
    expect(within(clock).getByText(/기본 거부 날\(9월 8일\)까지 승인이 없어 확정 보류됐어요/)).toBeInTheDocument()
    const stamps = screen.getByRole('list', { name: '결재란' })
    expect(within(stamps).getByRole('listitem', { name: '마케팅팀: 기본 거부' })).toBeInTheDocument()
    expect(screen.getByText(/결정이 끝난 건이에요/)).toBeInTheDocument()
  })

  it('처리_기록은_접혀_있다가_펼치면_전체', async () => {
    Setup(MAY, 'Masil 대표')
    mount('Masil 대표')
    await screen.findByRole('heading', { name: '처리 기록' })
    expect(screen.queryByText('사건생성')).toBeNull()
    expect(screen.getByText('상신', { selector: 'b' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '전체 4건 펼치기' }))
    expect(screen.getByText('사건생성')).toBeInTheDocument()
  })

  it('없는_건은_안내_문장', async () => {
    fakeServer({
      'GET /api/people': { json: PEOPLE },
      'GET /api/clock': { json: { date: '2026-09-05', mode: '시연' } },
      [`GET ${DETAIL_PATH('Masil 대표')}`]: { status: 404, json: { detail: '건 7을 찾을 수 없음' } },
    })
    mount('Masil 대표')
    expect(await screen.findByText(/찾을 수 없는 건이에요/)).toBeInTheDocument()
  })

  it('근거를_못_읽으면_그_칸에만_다시_시도', async () => {
    Setup(MAY, 'Masil 대표', { 'GET /api/cases/7/evidence': { status: 500, json: { detail: '계산 실패' } } })
    mount('Masil 대표')
    expect(await screen.findByText(/근거를 불러오지 못했어요/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '근거 다시 시도' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '승인' })).toBeInTheDocument()
  })

  it('기준일이_바뀌면_다시_읽는다', async () => {
    const { calls } = Setup(MAY, 'Masil 대표', { 'POST /api/clock': { json: { date: '2026-09-06', mode: '시연' } } })
    mount('Masil 대표')
    await screen.findByRole('button', { name: '승인' })
    await userEvent.click(screen.getByRole('button', { name: '다음 날로' }))
    await waitFor(() => expect(calls.filter((c) => c.path === DETAIL_PATH('Masil 대표')).length).toBe(2))
    expect(await screen.findByText('2일')).toBeInTheDocument()
  })
})
