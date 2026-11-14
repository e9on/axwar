import { describe, it, expect, afterEach, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import App from './App'
import { fakeServer } from './test/fakeServer'
import { mountPage } from './test/pageMount'
import CaseDetailPage from './pages/CaseDetail'

const PEOPLE = [
  { name: 'Masil 대표', role: 'Masil 대표' },
  { name: '마케팅팀장', role: '마케팅팀' },
  { name: '캠페인 담당자', role: '캠페인 담당' },
  { name: '계약 담당자', role: '계약 담당' },
]
const DETAIL_PATH = (who: string) => `/api/cases/7?viewer=${encodeURIComponent(who)}`

const detailOf = (viewer: object, over: Record<string, unknown> = {}) => ({
  case: { id: 7, kind: '기안', ref_id: 'DEMO-PLAN-001', status: '승인 대기', open: true, stage: '1차 승인 대기', origin: '시연', title: '초혜핏 선케어 캠페인2 · 초혜핏 (시연용)', note: '시연용 가정: 원본 기안을 복사해 요청액만 바꿈', source_plan_id: 'PLAN-019' },
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
      replies: [
        {
          id: 1, text: '전량 가능합니다', attachments: 0, created_at: '2026-07-01',
          judgment: { id: 1, stance: '수용', qty_limit: null, next_date: null, needs_human: false, confidence: 1, model: 'fake-해석기', human_confirmed: false, confirmed_by: null },
        },
      ],
    },
  ],
  tasks: [],
  judgments: [],
  history: [
    { id: 1, sim_date: '2026-07-01', kind: '사건생성', actor: '시스템', detail: {} },
    { id: 2, sim_date: '2026-07-02', kind: '요청생성', actor: '시스템', detail: {} },
    { id: 3, sim_date: '2026-07-03', kind: '회신접수', actor: '부서', detail: {} },
    { id: 4, sim_date: '2026-09-04', kind: '상신', actor: '마케팅팀장', detail: { reason: '대표 확인' } },
  ],
  viewer: viewer,
  ...over,
})

const PREVIEW = { phase1_qty: 410, phase1_date: '2026-09-15', phase1_amount_krw: 5_100_000, phase2_qty: 233, phase2_date: '2026-10-06', phase2_amount_krw: 2_900_000 }
const MAY = {
  person: 'Masil 대표', role: 'Masil 대표', can_decide: true, can_escalate: true, can_escalate_phase2: false, can_decide_phase2: false,
  actions: ['승인', '분할승인', '거절'], blocked: [], actions_phase2: [], split_preview: PREVIEW,
}
const NOT = {
  person: '마케팅팀장', role: '마케팅팀', can_decide: false, can_escalate: false, can_escalate_phase2: false, can_decide_phase2: false,
  actions: [], blocked: [], actions_phase2: [], split_preview: null,
}
const SHORT_REASON = '재고 부족으로 1차 수량이 제한되는 건이라 분할 승인만 가능'
const MAY_SHORT = { ...MAY, actions: ['분할승인', '거절'], blocked: [{ action: '승인', reason: SHORT_REASON }] }
const MAY_P2 = { ...MAY, can_decide: false, can_decide_phase2: true, can_escalate: false, can_escalate_phase2: true, actions: [], actions_phase2: ['승인', '거절'], split_preview: null }

const D = (formula: string, over: object = {}) => ({ formula, inputs: [], sources: [], policies: [], ...over })
const EVIDENCE = {
  available: true,
  reason: null,
  influencer_id: 'INF-002',
  signals: [
    {
      key: 'forecast_gap', label: '예상 ROAS 괴리', value: 10.4, unit: 'multiple', compare: '명목 ROAS 최대 6.66', level: 'red', badge: '계산', judgment: '참고',
      exclude_reason: '예상 GMV 기반이라 판정에서 뺌',
      detail: D('예상 ROAS = 기안 예상 GMV ÷ 요청 예산', {
        inputs: [{ label: '요청 예산', value: 4807921 }, { label: '과대 예상', value: true }],
        sources: ['02_masil/marketing/mkt_budget_plan_ms.csv'],
      }),
    },
    {
      key: 'spend_concentration', label: '광고비 쏠림(HHI)', value: 2461.7, unit: 'score', compare: '기준 1800 초과', level: 'green', badge: '가정', judgment: '판정', exclude_reason: '',
      detail: D('HHI = 비중 제곱의 합', {
        policies: [{ key: 'signals.hhi_limit', value: 1800, source: '가정: 원본에 없음', description: '쏠림이 위험인 기준' }],
      }),
    },
    { key: 'repurchase', label: '재구매율', value: 0.12345, unit: 'ratio', compare: '기준 0.2', level: 'yellow', badge: '계산', judgment: '판정', exclude_reason: '', detail: D('재구매 ÷ 전체') },
    { key: 'cannibalization', label: '다른 채널 잠식', value: null, compare: '측정 불가', level: 'unmeasurable', badge: '계산', judgment: '판정', exclude_reason: '', detail: D('고객이 나뉘어 측정 불가') },
  ],
  key_indicators: [
    { key: 'real_roas', label: '실질 ROAS', value: 3.7, unit: 'multiple', rank: 1, of: 10, compare_label: null, compare_value: null, badge: '계산', detail: D('실질 ROAS 식') },
  ],
  cost_breakdown: {
    note: '표본 금액이라 실제 계약액과 곱하지 않음',
    rows: [{ key: 'gmv', label: '매출(GMV)', amount: 121676523, unit: 'krw', badge: '계산', detail: D('귀속 주문 GMV 합') }],
  },
  breakeven: { key: 'be', label: '본전에 필요한 기록 밖 판매', value: 0.256, unit: 'ratio', compare: '0이면 이미 본전 이상', level: 'green', badge: '계산', judgment: '판정', exclude_reason: '', detail: D('필요 비율 식') },
  attribution_note: '마지막 클릭 후 7일 기준',
  rule: {
    approver_hits: [
      { rule_id: 'escalation', text: '마케팅팀장이 Masil 대표에게 올림(승인 권고): 대표 확인이 필요함', source: '상신 기록', badge: '의견', detail: D('상신 기록') },
      { rule_id: 'plan_within_delegation', text: '건별 한도 이하라 마케팅팀 전결', source: 'approval_authority_policy.md', badge: '원본', superseded: true, detail: D('한도 비교') },
    ],
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

/** 접힌 칸을 모두 연다(근거·회신·기록은 기본으로 접혀 있다). 근거를 읽어 오는 중이면 칸이 생길 때까지 기다린다 */
async function openFolds() {
  await screen.findByRole('button', { name: /위험 신호/ })
  for (let n = 0; n < 20; n++) {
    const closed = Array.from(document.querySelectorAll<HTMLElement>('button[data-fold][aria-expanded="false"]'))
    if (closed.length === 0) return
    for (const b of closed) await userEvent.click(b)
  }
}

async function evidenceReady() {
  await openFolds()
  await screen.findByRole('button', { name: /예상 ROAS 괴리/ })
}

describe('건 상세', () => {
  it('근거마다_가정_표시만_남고_수준은_글자로_보인다', async () => {
    Setup(MAY, 'Masil 대표')
    mount('Masil 대표')
    await evidenceReady()
    const rows = document.querySelectorAll('.evidence .ebtn')
    expect(rows.length).toBeGreaterThanOrEqual(7)
    const evidence = within(document.querySelector('.evidence') as HTMLElement)
    expect(evidence.queryAllByText('계산')).toHaveLength(0)
    expect(evidence.getAllByText('가정').length).toBeGreaterThan(0)
    expect(evidence.queryAllByText('원본')).toHaveLength(0)
    // 수준은 색만이 아니라 글자로도
    expect(evidence.getByText('나쁨')).toBeInTheDocument()
    expect(evidence.getAllByText('좋음').length).toBeGreaterThan(0)
    expect(evidence.getAllByText('잴 수 없음').length).toBeGreaterThan(0)
    expect(screen.getByText(/표본 금액이라 실제 계약액과 곱하지 않음/)).toBeInTheDocument()
    expect(screen.getByText(/마지막 클릭 후 7일 기준/)).toBeInTheDocument()
  })

  it('근거_줄을_누르면_계산식_입력값_원본_정책이_펼쳐진다', async () => {
    Setup(MAY, 'Masil 대표')
    mount('Masil 대표')
    await openFolds()
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
    await openFolds()
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
    expect(await screen.findByText('Masil 대표의 결정을 기다리고 있어요.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '승인' })).toBeNull()
    expect(screen.queryByRole('button', { name: '거절' })).toBeNull()
  })

  it('승인을_누르면_POST_decision_후_다시_읽는다', async () => {
    const { calls } = Setup(MAY, 'Masil 대표', {
      'POST /api/cases/7/decision': { json: { changed: true, status: '승인 대기' } },
    })
    mount('Masil 대표')
    await userEvent.click(await screen.findByRole('button', { name: '승인' }))
    await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: '승인 확정' }))
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
    // 수량·금액·날짜는 서버 split_preview 값 그대로(facts.split의 400/243과 다른 값으로 확인)
    expect(within(dlg).getByText(/1차 410개/)).toBeInTheDocument()
    expect(within(dlg).getByText(/5,100,000원/)).toBeInTheDocument()
    expect(within(dlg).getByText(/9월 15일/)).toBeInTheDocument()
    expect(within(dlg).getByText(/2차로 넘어가는 수량 233개/)).toBeInTheDocument()
    expect(within(dlg).getByText(/2,900,000원/)).toBeInTheDocument()
    expect(within(dlg).getByText(/10월 6일/)).toBeInTheDocument()
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
    await openFolds()
    const box = Array.from(document.querySelectorAll<HTMLElement>('section.ai')).find((e) => e.textContent?.includes('재고가'))!
    expect(within(box).getByText('AI')).toHaveClass('ai')
    expect(within(box).getByText(/재고가 모자라 분할 승인이 안전합니다/)).toBeInTheDocument()
    expect(within(box).getByText(/claude-test-1 · 9월 4일/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /반대 근거/ })).toBeInTheDocument()
    expect(screen.queryByText(/사실이 바뀌어 다시 만들어야 함/)).toBeNull()
  })

  it('낡은_브리핑은_다시_만들어야_한다고_알리고_버튼이_다시_만든다', async () => {
    const stale = { text: '옛 글', ok: true, model: 'claude-test-1', sim_date: '2026-09-01', stale: true }
    const { calls } = Setup(MAY, 'Masil 대표', { 'POST /api/cases/7/briefing': { json: {} } }, { briefing: stale })
    mount('Masil 대표')
    await openFolds()
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
    await screen.findByText('Masil 대표의 결정을 기다리고 있어요.')
    expect(screen.queryByRole('button', { name: /AI 브리핑/ })).toBeNull()
  })

  it('회신에는_AI_해석_결과만_배지가_붙는다', async () => {
    Setup(MAY, 'Masil 대표')
    mount('Masil 대표')
    await openFolds()
    const text = await screen.findByText('전량 가능합니다')
    const reply = text.closest('.reply') as HTMLElement
    expect(within(reply).queryByText('회신')).toBeNull()
    expect(within(reply).getByText(/해석: 수용/)).toBeInTheDocument()
    expect(within(reply).getByText(/시연용 해석 · 사람 확인 불필요/)).toBeInTheDocument()
  })

  it('결재선_변경_이력이_보인다', async () => {
    Setup(MAY, 'Masil 대표')
    mount('Masil 대표')
    await openFolds()
    expect(screen.getByRole('button', { name: /결재선이 바뀌었어요 \(Masil 대표에서 Masil 대표·그룹 CEO로, 9월 5일\) 외 1건/ })).toBeInTheDocument()
    const list = await screen.findByRole('list', { name: '결재선 변경 이력' })
    expect(within(list).getByText(/마케팅팀에서 Masil 대표로, 상신\(승인 권고\): 대표 확인이 필요함/)).toBeInTheDocument()
    expect(within(list).getByText(/Masil 대표에서 Masil 대표·그룹 CEO로: 하회 구간이라 CEO 추가/)).toBeInTheDocument()
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

  it('시연_초기화로_연_원본_기안은_시연용_표시가_없다', async () => {
    Setup(MAY, 'Masil 대표', {}, {
      case: { id: 7, kind: '기안', ref_id: 'PLAN-001', status: '승인 대기', open: true, stage: '1차 승인 대기', origin: '시연', title: '혜인 기초 캠페인3 · 혜인', note: null, source_plan_id: null },
    })
    mount('Masil 대표')
    expect(await screen.findByRole('heading', { level: 1 })).toHaveTextContent('혜인 기초 캠페인3')
    expect(screen.queryByText('시연용 가정')).not.toBeInTheDocument()
  })

  it('서류_머리에_요청액과_집행일만', async () => {
    Setup(MAY, 'Masil 대표')
    mount('Masil 대표')
    await screen.findByRole('heading', { level: 1 })
    expect(screen.getByText('8,000,000원')).toBeInTheDocument()
    expect(screen.getByText('9월 14일')).toBeInTheDocument()
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
    await openFolds()
    expect(screen.getByRole('list', { name: '2차 결재란' })).toBeInTheDocument()
  })

  it('기본거부까지_남은_날은_지금_할_일_띠_문장에', async () => {
    Setup(MAY, 'Masil 대표')
    mount('Masil 대표')
    const now = await screen.findByRole('group', { name: '결정' })
    expect(now).toHaveTextContent('9월 7일까지 결정하지 않으면 9월 8일에 기본 거부돼요')
  })

  it('기본_거부_날이_지나면_서버_사정이_아닌_사용자_말투', async () => {
    fakeServer({
      'GET /api/people': { json: PEOPLE },
      'GET /api/clock': { json: { date: '2026-09-10', mode: '시연' } },
      [`GET ${DETAIL_PATH('Masil 대표')}`]: { json: detailOf(MAY) },
      'GET /api/cases/7/evidence': { json: EVIDENCE },
    })
    mount('Masil 대표')
    const clock = await screen.findByRole('group', { name: '결정' })
    expect(clock).toHaveTextContent(/기본 거부 날\(9월 8일\)이 지났어요/)
    expect(clock).toHaveTextContent(/기본 거부로 처리돼요/)
    expect(clock).not.toHaveTextContent(/서버/)
  })

  it('남은_작업은_부서_이름을_두_번_쓰지_않는다', async () => {
    const tasks = [
      { id: 1, dept: 'CS', title: 'CS 대비', status: '대기', due: '2026-09-08' },
      { id: 2, dept: '물류', title: '출고', status: '대기', due: '2026-09-09' },
    ]
    Setup(MAY, 'Masil 대표', {}, { tasks })
    mount('Masil 대표')
    await openFolds()
    const items = document.querySelectorAll('.tasks li')
    expect(items[0].textContent).not.toMatch(/CS\s*CS/)
    expect(items[0]).toHaveTextContent('CS 대비')
    expect(items[1]).toHaveTextContent('물류 출고')
  })

  it('끝난_건은_남은_날_대신_결과_문장', async () => {
    const closed = { rule: { approvers: [], hits: [], required_roles: ['마케팅팀'], approved_roles: [], pending_roles: [] }, case: { id: 7, kind: '기안', ref_id: 'P-1', status: '기본 거부', open: false, stage: '끝남', origin: '화면' } }
    Setup(NOT, '마케팅팀장', {}, closed)
    mount('마케팅팀장')
    const clock = await screen.findByRole('group', { name: '결정' })
    expect(clock).toHaveTextContent(/기본 거부 날\(9월 8일\)까지 승인이 없어 확정 보류됐어요/)
    const stamps = screen.getByRole('list', { name: '결재란' })
    expect(within(stamps).getByRole('listitem', { name: '마케팅팀: 기본 거부' })).toBeInTheDocument()
  })

  it('처리_기록은_접혀_있다가_펼치면_전체', async () => {
    Setup(MAY, 'Masil 대표')
    mount('Masil 대표')
    await userEvent.click(await screen.findByRole('button', { name: /처리 기록/ }))
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
    expect(await screen.findByText('건 7을 찾을 수 없음', { selector: '.missing p' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '메인으로 가서 다시 시작' })).toBeInTheDocument()
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
    mountPage(<CaseDetailPage />, `/cases/7?as=${encodeURIComponent('Masil 대표')}`, '/cases/:id')
    await screen.findByRole('button', { name: '승인' })
    await userEvent.click(screen.getByRole('button', { name: '다음 날로' }))
    await waitFor(() => expect(calls.filter((c) => c.path === DETAIL_PATH('Masil 대표')).length).toBe(2))
  })
})

describe('결정 버튼은 서버가 알려 준 것만', () => {
  it('막힌_승인은_버튼_대신_이유_문장이_보이고_눌리지_않는다', async () => {
    const { calls } = Setup(MAY_SHORT, 'Masil 대표')
    mount('Masil 대표')
    expect(await screen.findByText(new RegExp(SHORT_REASON))).toBeInTheDocument()
    const approve = screen.queryByRole('button', { name: '승인' })
    if (approve) {
      expect(approve).toBeDisabled()
      await userEvent.click(approve)
    }
    expect(calls.some((c) => c.method === 'POST')).toBe(false)
    expect(screen.getByRole('button', { name: /^분할 승인/ })).toBeEnabled()
    expect(screen.getByRole('button', { name: '거절' })).toBeEnabled()
  })

  it('분할_확인_창은_일반_승인이_막힌_이유를_보여_준다', async () => {
    Setup(MAY_SHORT, 'Masil 대표')
    mount('Masil 대표')
    await userEvent.click(await screen.findByRole('button', { name: /^분할 승인/ }))
    const dlg = screen.getByRole('dialog')
    expect(within(dlg).getByText(/일반 승인은 지금 할 수 없어요/)).toBeInTheDocument()
    expect(within(dlg).getByText(new RegExp(SHORT_REASON))).toBeInTheDocument()
  })

  it('actions에_없는_분할승인_버튼은_없다', async () => {
    Setup({ ...MAY, actions: ['승인', '거절'], split_preview: null }, 'Masil 대표')
    mount('Masil 대표')
    await screen.findByRole('button', { name: '승인' })
    expect(screen.queryByRole('button', { name: /^분할 승인/ })).toBeNull()
  })

  it('결정권자인데_actions가_비면_눌러_볼_버튼이_없다', async () => {
    Setup({ ...MAY, actions: [] }, 'Masil 대표')
    mount('Masil 대표')
    await screen.findByText(/승인이 필요해요/)
    expect(screen.queryByRole('button', { name: '승인' })).toBeNull()
    expect(screen.queryByRole('button', { name: '거절' })).toBeNull()
  })

  it('2차_승인_대기에서는_actions_phase2대로_phase2_decision으로_보낸다', async () => {
    const over = { case: { id: 7, kind: '기안', ref_id: 'P-1', status: '2차 승인 대기', open: false, stage: '2차 승인 대기', origin: '화면' } }
    const { calls } = Setup(MAY_P2, 'Masil 대표', { 'POST /api/cases/7/phase2/decision': { json: { changed: true, status: '2차 집행' } } }, over)
    mount('Masil 대표')
    await userEvent.click(await screen.findByRole('button', { name: '승인' }))
    expect(screen.queryByRole('button', { name: /^분할 승인/ })).toBeNull()
    await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: '승인 확정' }))
    await waitFor(() => expect(calls.find((c) => c.path === '/api/cases/7/phase2/decision')?.body).toEqual({ actor: 'Masil 대표', action: '승인', comment: '' }))
  })

  it('2차_상신은_stage_2차로_보낸다', async () => {
    const over = { case: { id: 7, kind: '기안', ref_id: 'P-1', status: '2차 승인 대기', open: false, stage: '2차 승인 대기', origin: '화면' } }
    const { calls } = Setup(MAY_P2, 'Masil 대표', { 'POST /api/cases/7/escalate': { json: { changed: true } } }, over)
    mount('Masil 대표')
    await userEvent.click(await screen.findByRole('button', { name: '위로 올리기' }))
    const dlg = screen.getByRole('dialog')
    await userEvent.click(within(dlg).getByRole('radio', { name: '승인 권고' }))
    await userEvent.type(within(dlg).getByRole('textbox'), '확인 바람')
    await userEvent.click(within(dlg).getByRole('button', { name: '올리기 확정' }))
    await waitFor(() => expect(calls.find((c) => c.path === '/api/cases/7/escalate')?.body).toEqual({ actor: 'Masil 대표', stage: '2차', opinion: '승인 권고', reason: '확인 바람' }))
  })

  it('2차_거절은_이유와_함께_phase2_decision', async () => {
    const over = { case: { id: 7, kind: '기안', ref_id: 'P-1', status: '2차 승인 대기', open: false, stage: '2차 승인 대기', origin: '화면' } }
    const { calls } = Setup(MAY_P2, 'Masil 대표', { 'POST /api/cases/7/phase2/decision': { json: { changed: true } } }, over)
    mount('Masil 대표')
    await userEvent.click(await screen.findByRole('button', { name: '거절' }))
    await userEvent.type(screen.getByRole('textbox'), '반품이 많아요')
    await userEvent.click(screen.getByRole('button', { name: '거절 확정' }))
    await waitFor(() => expect(calls.find((c) => c.path === '/api/cases/7/phase2/decision')?.body).toEqual({ actor: 'Masil 대표', action: '거절', comment: '반품이 많아요' }))
  })
})

describe('보내는 중', () => {
  it('다시_읽기가_끝날_때까지_결정_버튼이_모두_꺼지고_연타해도_한_번만_나간다', async () => {
    let release: () => void = () => {}
    const gate = new Promise<void>((r) => (release = r))
    let reads = 0
    const { calls } = Setup(MAY, 'Masil 대표', { 'POST /api/cases/7/decision': { json: { changed: true, status: '승인' } } })
    const base = globalThis.fetch as unknown as (i: RequestInfo | URL, n?: RequestInit) => Promise<Response>
    vi.stubGlobal('fetch', async (i: RequestInfo | URL, n?: RequestInit) => {
      if (String(i) === DETAIL_PATH('Masil 대표') && ++reads === 2) await gate
      return base(i, n)
    })
    mount('Masil 대표')
    await userEvent.click(await screen.findByRole('button', { name: '승인' }))
    const ok = within(screen.getByRole('dialog')).getByRole('button', { name: '승인 확정' })
    await userEvent.click(ok)
    await userEvent.click(ok)
    await userEvent.click(ok)
    await waitFor(() => expect(reads).toBe(2))
    expect(screen.getByRole('button', { name: '승인' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '거절' })).toBeDisabled()
    expect(screen.getByRole('button', { name: /^분할 승인/ })).toBeDisabled()
    expect(screen.getByRole('button', { name: '위로 올리기' })).toBeDisabled()
    expect(screen.getByText(/보내는 중/)).toBeInTheDocument()
    release()
    await waitFor(() => expect(screen.getByRole('button', { name: '승인' })).toBeEnabled())
    expect(calls.filter((c) => c.method === 'POST')).toHaveLength(1)
  })

  it('서버가_409로_막으면_그_문장이_알림으로_보이고_버튼이_다시_켜진다', async () => {
    Setup(MAY, 'Masil 대표', { 'POST /api/cases/7/decision': { status: 409, json: { detail: '이미 승인한 건이에요' } } })
    mount('Masil 대표')
    await userEvent.click(await screen.findByRole('button', { name: '승인' }))
    await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: '승인 확정' }))
    expect((await screen.findAllByText('이미 승인한 건이에요')).length).toBeGreaterThan(0)
    expect(within(screen.getByRole('dialog')).getByRole('button', { name: '승인 확정' })).toBeEnabled()
  })

  it('거절_상신_실패도_문장이_보인다', async () => {
    Setup(MAY, 'Masil 대표', {
      'POST /api/cases/7/decision': { status: 403, json: { detail: '승인권자가 아니에요' } },
      'POST /api/cases/7/escalate': { status: 409, json: { detail: '이미 올린 건이에요' } },
    })
    mount('Masil 대표')
    await userEvent.click(await screen.findByRole('button', { name: '거절' }))
    await userEvent.type(screen.getByRole('textbox'), '사유')
    await userEvent.click(screen.getByRole('button', { name: '거절 확정' }))
    const dlg = screen.getByRole('dialog')
    expect(await within(dlg).findByText('승인권자가 아니에요')).toBeInTheDocument()
    await userEvent.click(within(dlg).getByRole('button', { name: '취소' }))
    await userEvent.click(screen.getByRole('button', { name: '위로 올리기' }))
    const d2 = screen.getByRole('dialog')
    await userEvent.click(within(d2).getByRole('radio', { name: '승인 권고' }))
    await userEvent.type(within(d2).getByRole('textbox'), '사유')
    await userEvent.click(within(d2).getByRole('button', { name: '올리기 확정' }))
    expect(await within(d2).findByText('이미 올린 건이에요')).toBeInTheDocument()
  })
})

describe('대화창', () => {
  it('열면_첫_입력으로_초점이_가고_Esc로_닫히면_연_버튼으로_돌아온다', async () => {
    Setup(MAY, 'Masil 대표')
    mount('Masil 대표')
    const reject = await screen.findByRole('button', { name: '거절' })
    await userEvent.click(reject)
    const dlg = screen.getByRole('dialog')
    expect(within(dlg).getByRole('textbox')).toHaveFocus()
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(screen.getByRole('button', { name: '거절' })).toHaveFocus()
  })

  it('분할_확인_창은_확정_버튼으로_초점이_간다', async () => {
    Setup(MAY, 'Masil 대표')
    mount('Masil 대표')
    await userEvent.click(await screen.findByRole('button', { name: /^분할 승인/ }))
    expect(within(screen.getByRole('dialog')).getByRole('button', { name: '분할 승인 확정' })).toHaveFocus()
  })

  it('Tab은_창_안에서만_돈다', async () => {
    Setup(MAY, 'Masil 대표')
    mount('Masil 대표')
    await userEvent.click(await screen.findByRole('button', { name: '위로 올리기' }))
    const dlg = screen.getByRole('dialog')
    for (let i = 0; i < 8; i++) {
      await userEvent.tab()
      expect(dlg.contains(document.activeElement)).toBe(true)
    }
    for (let i = 0; i < 8; i++) {
      await userEvent.tab({ shift: true })
      expect(dlg.contains(document.activeElement)).toBe(true)
    }
  })
})

describe('회신 해석은 서버가 이은 judgment로', () => {
  const twoReplies = (a: unknown, b: unknown) => ({
    requests: [
      {
        id: 1, dept: '물류', purpose: '물류 처리 능력', text: '처리량을 알려 주세요', status: '처리됨', attach_required: false,
        replies: [
          { id: 1, text: '가능합니다', attachments: 0, created_at: '2026-07-01', judgment: a },
          { id: 2, text: '가능합니다', attachments: 0, created_at: '2026-07-02', judgment: b },
        ],
      },
    ],
  })
  const J = (id: number, stance: string, extra: object = {}) => ({
    id, stance, qty_limit: null, next_date: null, needs_human: false, confidence: 0.9, model: 'm', human_confirmed: false, confirmed_by: null, ...extra,
  })

  it('같은_글_두_회신도_각자_자기_해석', async () => {
    Setup(MAY, 'Masil 대표', {}, twoReplies(J(1, '수용'), J(2, '조건부', { qty_limit: 300 })))
    mount('Masil 대표')
    await openFolds()
    const replies = (await screen.findAllByText('가능합니다')).map((t) => t.closest('.reply') as HTMLElement)
    expect(within(replies[0]).getByText(/해석: 수용/)).toBeInTheDocument()
    expect(within(replies[0]).queryByText(/조건부/)).toBeNull()
    expect(within(replies[1]).getByText(/해석: 조건부 · 수량 한도 300개/)).toBeInTheDocument()
  })

  it('judgment가_null이면_해석_기록_없음', async () => {
    Setup(MAY, 'Masil 대표', {}, twoReplies(null, J(2, '수용')))
    mount('Masil 대표')
    await openFolds()
    const replies = (await screen.findAllByText('가능합니다')).map((t) => t.closest('.reply') as HTMLElement)
    expect(within(replies[0]).getByText('해석 기록 없음')).toBeInTheDocument()
  })

  it('사람_확인은_judgment의_human_confirmed와_확인한_사람만', async () => {
    Setup(MAY, 'Masil 대표', {}, twoReplies(J(1, '불명', { needs_human: true, human_confirmed: true, confirmed_by: '캠페인 담당자' }), J(2, '불명', { needs_human: true })))
    mount('Masil 대표')
    await openFolds()
    const replies = (await screen.findAllByText('가능합니다')).map((t) => t.closest('.reply') as HTMLElement)
    expect(within(replies[0]).getByText(/사람이 확인함 \(캠페인 담당자\)/)).toBeInTheDocument()
    expect(within(replies[1]).getByText(/사람 확인 필요/)).toBeInTheDocument()
    expect(within(replies[1]).queryByText(/확인함/)).toBeNull()
  })
})

describe('근거 값 단위', () => {
  it('단위에_따라_형식이_다르다', async () => {
    Setup(MAY, 'Masil 대표')
    mount('Masil 대표')
    await evidenceReady()
    const row = (name: RegExp) => screen.getByRole('button', { name })
    expect(row(/재구매율/)).toHaveTextContent('12.35%')
    expect(row(/예상 ROAS 괴리/)).toHaveTextContent('10.400')
    expect(row(/매출\(GMV\)/)).toHaveTextContent('121,676,523원')
    expect(row(/본전에 필요한/)).toHaveTextContent('25.60%')
    expect(row(/광고비 쏠림/)).toHaveTextContent('2,462')
  })
})

describe('결재선 이유', () => {
  it('상신_줄이_맨_위이고_옛_규칙_줄은_처음_판정으로_흐리다', async () => {
    Setup(MAY, 'Masil 대표')
    mount('Masil 대표')
    await evidenceReady()
    const rows = within(document.querySelector('.rule-box') as HTMLElement).getAllByRole('button')
    expect(rows[0]).toHaveTextContent('마케팅팀장이 Masil 대표에게 올림')
    expect(rows[0]).not.toHaveTextContent('처음 판정')
    expect(rows[1]).toHaveTextContent('처음 판정')
    expect(rows[1].closest('li')).toHaveAttribute('data-superseded', 'true')
  })

  it('옛_줄이_앞에_와도_상신_줄을_위로_올린다', async () => {
    const ev = JSON.parse(JSON.stringify(EVIDENCE))
    ev.rule.approver_hits.reverse()
    Setup(MAY, 'Masil 대표', { 'GET /api/cases/7/evidence': { json: ev } })
    mount('Masil 대표')
    await evidenceReady()
    const rows = within(document.querySelector('.rule-box') as HTMLElement).getAllByRole('button')
    expect(rows[0]).toHaveTextContent('올림')
  })
})

describe('낮은 항목', () => {
  it('열린_건인데_승인할_사람이_없으면_아직_열려_있다고_말한다', async () => {
    const open = { rule: { approvers: [], hits: [], required_roles: ['마케팅팀'], approved_roles: ['마케팅팀'], pending_roles: [] }, case: { id: 7, kind: '기안', ref_id: 'P-1', status: '승인 대기', open: true, stage: '1차 승인 대기', origin: '화면' } }
    Setup(NOT, '마케팅팀장', {}, open)
    mount('마케팅팀장')
    expect(await screen.findByText(/다른 회신이나 결정을 기다리고 있어요/)).toBeInTheDocument()
  })

  it('다른_종료_상태도_남은_칸에_상태가_적힌다', async () => {
    const closed = { rule: { approvers: [], hits: [], required_roles: ['마케팅팀', 'Masil 대표'], approved_roles: ['마케팅팀'], pending_roles: [] }, case: { id: 7, kind: '기안', ref_id: 'P-1', status: '1차 차단', open: false, stage: '끝남', origin: '화면' } }
    Setup(NOT, '마케팅팀장', {}, closed)
    mount('마케팅팀장')
    const stamps = await screen.findByRole('list', { name: '결재란' })
    expect(within(stamps).getByRole('listitem', { name: 'Masil 대표: 1차 차단' })).toBeInTheDocument()
  })

  it('대리_결재자는_자기_역할이_칸에_없어도_내_차례가_뜬다', async () => {
    const p2 = {
      plan: { qty: 100, date: '2026-10-05' }, approvers: ['그룹 CEO'], hits: [], required_roles: ['그룹 CEO'], pending_roles: ['그룹 CEO'], approved_roles: [],
      gate: { open: true }, deadline: null, deny_date: '2026-10-01', approval_deadline: null, decision: null, result: null,
    }
    const over = { case: { id: 7, kind: '기안', ref_id: 'P-1', status: '2차 승인 대기', open: false, stage: '2차 승인 대기', origin: '화면' }, phase2: p2 }
    Setup(MAY_P2, 'Masil 대표', {}, over)
    mount('Masil 대표')
    await openFolds()
    const stamps = await screen.findByRole('list', { name: '2차 결재란' })
    expect(within(stamps).getByRole('listitem', { name: '그룹 CEO: 내 차례' })).toBeInTheDocument()
  })

  it('시연_메모는_case_note에서_읽고_따로_기안을_읽지_않는다', async () => {
    const { calls } = Setup(MAY, 'Masil 대표')
    mount('Masil 대표')
    expect(await screen.findByText(/원본 기안을 복사해 요청액만 바꿈/)).toBeInTheDocument()
    expect(calls.some((c) => c.path.startsWith('/api/plans'))).toBe(false)
  })
})

const LAPSED_REASON = '기한이 지나 기본 거부 대상 — 결정할 수 없음(기본 거부 실행일 2026-09-08)'
const LAPSED = {
  ...MAY,
  can_decide: false,
  actions: [],
  split_preview: null,
  blocked: [
    { action: '승인', reason: LAPSED_REASON },
    { action: '분할승인', reason: LAPSED_REASON },
    { action: '거절', reason: LAPSED_REASON },
  ],
}

describe('승인 확인 창과 서버가 준 열린 여부·막힘', () => {
  it('승인은_확인_창을_거쳐_보낸다', async () => {
    const { calls } = Setup(MAY, 'Masil 대표', { 'POST /api/cases/7/decision': { json: { changed: true, status: '승인' } } })
    mount('Masil 대표')
    await userEvent.click(await screen.findByRole('button', { name: '승인' }))
    const dlg = screen.getByRole('dialog')
    expect(within(dlg).getByRole('heading', { name: /이 건을 승인합니다/ })).toBeInTheDocument()
    expect(within(dlg).getByText(/8,000,000원/)).toBeInTheDocument()
    expect(within(dlg).getByText(/2026년 9월 14일|9월 14일/)).toBeInTheDocument()
    // 수량은 화면이 단정하지 않는다(서버가 승인 뒤 정함)
    expect(within(dlg).getByText(/1차 수량은 승인 뒤/)).toBeInTheDocument()
    expect(dlg).not.toHaveTextContent(/전량/)
    expect(within(dlg).getByRole('button', { name: '승인 확정' })).toHaveFocus()
    expect(calls.some((c) => c.method === 'POST')).toBe(false)
    await userEvent.click(within(dlg).getByRole('button', { name: '승인 확정' }))
    await waitFor(() => expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ actor: 'Masil 대표', action: '승인', comment: '' }))
  })

  it('승인_확인_창에서_취소하면_보내지_않는다', async () => {
    const { calls } = Setup(MAY, 'Masil 대표')
    mount('Masil 대표')
    await userEvent.click(await screen.findByRole('button', { name: '승인' }))
    await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: '취소' }))
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(calls.some((c) => c.method === 'POST')).toBe(false)
  })

  it('기한_지난_건은_결정_버튼_대신_이유', async () => {
    Setup(LAPSED, 'Masil 대표')
    mount('Masil 대표')
    expect((await screen.findAllByText(new RegExp(LAPSED_REASON.slice(0, 20)))).length).toBeGreaterThan(0)
    expect(screen.queryByRole('button', { name: '승인' })).toBeNull()
    expect(screen.queryByRole('button', { name: '거절' })).toBeNull()
    expect(screen.queryByRole('button', { name: /^분할 승인/ })).toBeNull()
  })

  it('열린_여부는_case_open으로', async () => {
    const mk = (open: boolean, stage: string) => ({
      rule: { approvers: [], hits: [], required_roles: ['마케팅팀'], approved_roles: ['마케팅팀'], pending_roles: [] },
      case: { id: 7, kind: '기안', ref_id: 'P-1', status: '처음 보는 상태', open, stage, origin: '화면' },
    })
    Setup(NOT, '마케팅팀장', {}, mk(true, '회신 대기'))
    mount('마케팅팀장')
    expect(await screen.findByText(/다른 회신이나 결정을 기다리고 있어요/)).toBeInTheDocument()
  })

  it('끝난_건은_case_open_false로_결정이_끝났다고_말한다', async () => {
    const closed = {
      rule: { approvers: [], hits: [], required_roles: ['마케팅팀'], approved_roles: ['마케팅팀'], pending_roles: [] },
      case: { id: 7, kind: '기안', ref_id: 'P-1', status: '처음 보는 끝 상태', open: false, stage: '끝남', origin: '화면' },
    }
    Setup(NOT, '마케팅팀장', {}, closed)
    mount('마케팅팀장')
    expect(await screen.findByText(/처음 보는 끝 상태 상태예요/)).toBeInTheDocument()
  })

  it('2차_막힘은_blocked_phase2', async () => {
    const over = { case: { id: 7, kind: '기안', ref_id: 'P-1', status: '2차 승인 대기', open: false, stage: '2차 승인 대기', origin: '화면' } }
    const v = {
      ...MAY_P2,
      can_decide_phase2: false,
      actions_phase2: [],
      blocked: [{ action: '승인', reason: '1차 막힘 이유' }],
      blocked_phase2: [{ action: '승인', reason: '2차 기한이 지나 결정할 수 없음' }],
    }
    Setup(v, 'Masil 대표', {}, over)
    mount('Masil 대표')
    expect((await screen.findAllByText(/2차 기한이 지나 결정할 수 없음/)).length).toBeGreaterThan(0)
    expect(screen.queryByText(/1차 막힘 이유/)).toBeNull()
  })

  it('없어진_정책_항목은_펼침에서_없어졌다고_보인다', async () => {
    const ev = JSON.parse(JSON.stringify(EVIDENCE))
    ev.signals[0].detail.policies = [{ key: 'signals.old_key', value: null, source: null, missing: true, description: '없어진 정책 항목 — 설정에서 지워졌어요' }]
    Setup(MAY, 'Masil 대표', { 'GET /api/cases/7/evidence': { json: ev } })
    mount('Masil 대표')
    await openFolds()
    await userEvent.click(await screen.findByRole('button', { name: /예상 ROAS 괴리/ }))
    expect(screen.getAllByText(/없어진 정책 항목/).length).toBeGreaterThan(0)
    expect(screen.getByText('signals.old_key')).toBeInTheDocument()
  })

  it('위험_신호_요약은_결정에_쓰는_신호만_세고_참고용은_따로_센다', async () => {
    Setup(MAY, 'Masil 대표')
    mount('Masil 대표')
    expect(await screen.findByRole('button', { name: /위험 신호/ })).toHaveTextContent('나쁨 0건 · 주의 1건 · 좋음 1건 · 참고용 1건')
  })

  it('공지할_수_있는_사람에게만_1차_공지_단추가_있고_확인_뒤_보낸다', async () => {
    const CAMPAIGN = { ...NOT, person: '캠페인 담당자', role: '캠페인 담당', can_announce: true }
    const over = { facts: { ...detailOf(NOT).facts, phase1: { qty: 3000, date: '2026-07-27' } } }
    const { calls } = Setup(CAMPAIGN, '캠페인 담당자', { 'POST /api/cases/7/announce': { json: { changed: true, qty: 3000 } } }, over)
    mount('캠페인 담당자')
    await userEvent.click(await screen.findByRole('button', { name: '1차 공지' }))
    const dlg = screen.getByRole('dialog')
    expect(dlg).toHaveTextContent('3,000개')
    await userEvent.click(within(dlg).getByRole('button', { name: '공지 확정' }))
    await waitFor(() => expect(calls.filter((c) => c.method === 'POST' && c.path === '/api/cases/7/announce')).toHaveLength(1))
    expect(calls.find((c) => c.path === '/api/cases/7/announce')?.body).toEqual({ actor: '캠페인 담당자' })
  })

  it('공지할_수_없으면_1차_공지_단추가_없다', async () => {
    Setup({ ...NOT, can_announce: false }, '마케팅팀장')
    mount('마케팅팀장')
    await screen.findByText('Masil 대표의 결정을 기다리고 있어요.')
    expect(screen.queryByRole('button', { name: '1차 공지' })).toBeNull()
  })

  it('통보_초안은_줄바꿈해_보이고_발송할_수_있는_사람에게만_발송_단추', async () => {
    const OWNER = { ...NOT, person: '계약 담당자', role: '계약 담당', can_send_notice: true }
    const over = {
      case: { ...detailOf(NOT).case, kind: '계약', ref_id: 'INF-001', status: '통보 초안', stage: '통보', title: '혜인 전속계약' },
      facts: { annual_fixed_krw: 2_800_000_000, expiry: '2026-08-31', notice: { text: '혜인님께,\n성과 값은 공제 후 순액 기준으로 정산하는 안을 제안드립니다.', ok: true, model: 'fake' } },
    }
    const { calls } = Setup(OWNER, '계약 담당자', { 'POST /api/cases/7/send-notice': { json: { changed: true, status: '상대 회신 대기' } } }, over)
    mount('계약 담당자')
    const box = await screen.findByRole('region', { name: '조건변경 통보 초안' })
    expect(box).toHaveTextContent('공제 후 순액 기준')
    expect(within(box).getByText('AI')).toBeInTheDocument()
    await userEvent.click(within(box).getByRole('button', { name: '통보 발송' }))
    await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: '발송 확정' }))
    await waitFor(() => expect(calls.filter((c) => c.method === 'POST' && c.path === '/api/cases/7/send-notice')).toHaveLength(1))
    expect(calls.find((c) => c.path === '/api/cases/7/send-notice')?.body).toEqual({ actor: '계약 담당자' })
  })

  it('발송할_수_없는_사람은_통보_초안만_보고_단추는_없다', async () => {
    const over = {
      case: { ...detailOf(NOT).case, kind: '계약', ref_id: 'INF-001', status: '통보 초안', stage: '통보', title: '혜인 전속계약' },
      facts: { annual_fixed_krw: 2_800_000_000, expiry: '2026-08-31', notice: { text: '혜인님께', ok: true, model: 'fake' } },
    }
    Setup({ ...NOT, can_send_notice: false }, '마케팅팀장', {}, over)
    mount('마케팅팀장')
    expect(await screen.findByRole('region', { name: '조건변경 통보 초안' })).toHaveTextContent('혜인님께')
    expect(screen.queryByRole('button', { name: '통보 발송' })).toBeNull()
  })

  it('기본_거부로_끝난_건은_왜_그렇게_됐는지와_승인하지_않은_결재를_보인다', async () => {
    const over = {
      case: { ...detailOf(NOT).case, status: '확정 보류', open: false, stage: '끝' },
      rule: { approvers: ['CEO', '이사회'], hits: [], required_roles: ['CEO', '이사회'], approved_roles: ['CEO'], pending_roles: [] },
      history: [
        { id: 9, sim_date: '2026-07-14', kind: '상태변경', actor: '시스템', detail: { from: '승인 대기', to: '기본 거부', note: '마지막 승인일 7/13까지 승인 없음 — 확정 기한 7/17의 3일 전 기본 거부' } },
        { id: 10, sim_date: '2026-07-14', kind: '상태변경', actor: '시스템', detail: { from: '기본 거부', to: '확정 보류', note: '확정 보류(철회)' } },
      ],
    }
    Setup(NOT, '마케팅팀장', {}, over)
    mount('마케팅팀장')
    const why = await screen.findByRole('note', { name: '기본 거부된 이유' })
    expect(why).toHaveTextContent('마지막 승인일 7/13까지 승인 없음')
    expect(why).toHaveTextContent('승인하지 않은 결재: 이사회')
  })

  it('1차_결재가_끝나_2차로_넘어간_건에는_1차_기본_거부_날이_지났다고_하지_않는다', async () => {
    const over = { case: { ...detailOf(NOT).case, status: '2차 잠금', open: true, stage: '2차 관찰' }, deny_date: '2026-07-14', approval_deadline: '2026-07-13', rule: { ...detailOf(NOT).rule, approved_roles: ['마케팅팀', 'Masil 대표'], pending_roles: [] } }
    Setup(NOT, '마케팅팀장', {}, over)
    mount('마케팅팀장')
    const lead = await screen.findByRole('group', { name: '결정' })
    expect(lead).not.toHaveTextContent('기본 거부 날')
    expect(lead).toHaveTextContent('2차 잠금 상태예요')
  })
})
