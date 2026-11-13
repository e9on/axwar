import { describe, it, expect, afterEach, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import App from './App'
import { fakeServer } from './test/fakeServer'
import { visibleText } from './test/visibleText'
import { findForbidden } from './copy'

const PEOPLE = [
  { name: 'Masil 대표', role: 'Masil 대표' },
  { name: '그룹 CEO', role: '그룹 CEO' },
  { name: '마케팅팀장', role: '마케팅팀' },
]
const DIRTY = 'covenant 규정 설계 8장 fake(대본) 판정에는 쓰지 않음 → 승인해야 함'
const DETAIL_PATH = (who: string) => `/api/cases/7?viewer=${encodeURIComponent(who)}`

const detailOf = (viewer: object, over: Record<string, unknown> = {}) => ({
  case: { id: 7, kind: '기안', ref_id: 'PLAN-001', status: '승인 대기', open: true, stage: '1차 승인 대기', origin: '원본', title: '혜인 기초 캠페인3 · 혜인', note: null },
  facts: { amount_krw: 8_000_000, settlement_date: '2026-09-14', phase1_date: '2026-09-14', deadline: '2026-09-11' },
  rule: { approvers: ['Masil 대표'], hits: [], required_roles: ['마케팅팀', 'Masil 대표'], approved_roles: ['마케팅팀'], pending_roles: ['Masil 대표'] },
  phase2: null,
  deadline: '2026-09-11',
  deny_date: '2026-09-08',
  approval_deadline: '2026-09-07',
  escalations: [],
  briefing: { text: '재고가 모자라 분할 승인이 안전합니다. 둘째 문장입니다.', ok: true, model: 'm', sim_date: '2026-09-04', stale: false },
  counterpoints: null,
  approver_changes: [{ before: ['마케팅팀'], after: ['Masil 대표'], reason: DIRTY, at: '2026-09-05' }],
  requests: [],
  tasks: [],
  judgments: [],
  history: [],
  viewer,
  ...over,
})

const D = { formula: '식', inputs: [], sources: [], policies: [] }
const EVIDENCE = {
  available: true,
  reason: null,
  signals: [
    { key: 'a', label: '예상 ROAS 괴리', value: 10.4, unit: 'multiple', compare: DIRTY, level: 'red', badge: '계산', judgment: '참고', exclude_reason: '', detail: D },
    { key: 'b', label: '쿠폰 중복 비중', value: 0.17, unit: 'ratio', compare: '기준 이하', level: 'green', badge: '계산', judgment: '판정', exclude_reason: '', detail: D },
  ],
  key_indicators: [{ key: 'k', label: '실질 ROAS', value: 3.7, unit: 'multiple', rank: 1, of: 10, compare_label: null, compare_value: null, badge: '계산', detail: D }],
  cost_breakdown: { note: '표본', rows: [{ key: 'g', label: '매출(GMV)', amount: 1000, unit: 'krw', badge: '계산', detail: D }] },
  breakeven: null,
  attribution_note: '',
  rule: {
    approver_hits: [{ rule_id: 'covenant_window', text: `집행일이 하회 구간 안이라 ${DIRTY}`, source: 'x.md', badge: '원본', detail: D }],
    indicator_hits: [],
    phase2_approver_hits: [],
  },
}
const MAY = {
  person: 'Masil 대표', role: 'Masil 대표', can_decide: true, can_escalate: true, can_escalate_phase2: false, can_decide_phase2: false,
  actions: ['승인', '분할승인', '거절'], blocked: [],
  actions_phase2: [],
  split_preview: { phase1_qty: 410, phase1_date: '2026-09-15', phase1_amount_krw: 5_100_000, phase2_qty: 233, phase2_date: '2026-10-06', phase2_amount_krw: 2_900_000 },
}
const NOT = { ...MAY, person: '마케팅팀장', role: '마케팅팀', can_decide: false, can_escalate: false, actions: [], split_preview: null }
const SHORT = '재고 부족으로 1차 수량이 제한돼요'
const MAY_SHORT = { ...MAY, actions: ['분할승인', '거절'], blocked: [{ action: '승인', reason: SHORT }] }

function mountCase(viewer: object, who: string, over: Record<string, unknown> = {}) {
  fakeServer({
    'GET /api/people': { json: PEOPLE },
    'GET /api/clock': { json: { date: '2026-09-05', mode: '시연' } },
    [`GET ${DETAIL_PATH(who)}`]: { json: detailOf(viewer, over) },
    'GET /api/cases/7/evidence': { json: EVIDENCE },
  })
  return render(
    <MemoryRouter initialEntries={[`/cases/7?as=${encodeURIComponent(who)}`]}>
      <App />
    </MemoryRouter>,
  )
}

afterEach(() => vi.unstubAllGlobals())

describe('건 상세 개편', () => {
  it('건_상세_첫_화면에_지금_할_일과_버튼', async () => {
    mountCase(MAY, 'Masil 대표')
    const now = await screen.findByRole('group', { name: '결정' })
    expect(now).toHaveTextContent('승인이 필요해요. 9월 7일까지 결정하지 않으면 9월 8일에 기본 거부돼요.')
    for (const name of ['승인', /^분할 승인/, '거절', '위로 올리기']) expect(within(now).getByRole('button', { name })).toBeInTheDocument()
    // 근거 칸보다 먼저(머리 바로 아래) 있다
    const fold = await screen.findByRole('button', { name: /위험 신호/ })
    expect(now.compareDocumentPosition(fold) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    // 결정 막대는 화면에 고정되지 않는다
    expect(now.className).not.toMatch(/fixed/)
  })

  it('막혔으면_이유_한_줄', async () => {
    mountCase(MAY_SHORT, 'Masil 대표')
    const now = await screen.findByRole('group', { name: '결정' })
    expect(within(now).getByRole('list', { name: '지금 할 수 없는 결정' })).toHaveTextContent(SHORT)
  })

  it('결정권이_없으면_기다리는_사람', async () => {
    mountCase(NOT, '마케팅팀장')
    const now = await screen.findByRole('group', { name: '결정' })
    expect(now).toHaveTextContent('Masil 대표의 결정을 기다리고 있어요')
    expect(within(now).queryByRole('button', { name: '승인' })).toBeNull()
  })

  it('근거_칸은_기본으로_접힘', async () => {
    mountCase(MAY, 'Masil 대표')
    for (const name of ['위험 신호', '핵심 지표', '비용 분해', '부서 회신', '처리 기록']) {
      const b = await screen.findByRole('button', { name: new RegExp(name) })
      expect(b).toHaveAttribute('aria-expanded', 'false')
    }
    expect(screen.queryByText('예상 ROAS 괴리')).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: /위험 신호/ }))
    expect(await screen.findByRole('button', { name: /예상 ROAS 괴리/ })).toBeInTheDocument()
  })

  it('화면에_금지어가_없다_건_상세', async () => {
    mountCase(MAY, 'Masil 대표')
    await screen.findByRole('group', { name: '결정' })
    await screen.findByRole('button', { name: /위험 신호/ })
    expect(findForbidden(visibleText(document.body))).toEqual([])
    // 펼치기 전에는 원문이 없고, 결재선 변경은 한 줄로만 보인다
    expect(screen.getByText(/결재선이 바뀌었어요/)).toBeInTheDocument()
  })
})

describe('위쪽 막대와 메인 개편', () => {
  const todo = {
    person: 'Masil 대표', role: 'Masil 대표',
    '승인 대기': [{ case_id: 7, kind: '기안', ref_id: 'PLAN-001', title: '혜인 기초 캠페인3 · 혜인', approval_deadline: '2026-09-07', stage: '1차' }],
    '기한 임박': [], '권한 이동': [], 알림: [{ case_id: 7, kind: '마감 알림', ref_id: 'PLAN-001', title: '혜인 기초 캠페인3 · 혜인', text: `내일 기본 거부돼요. ${DIRTY}` }],
    '회신 대기': [{ case_id: 8, kind: '기안', ref_id: 'PLAN-002', title: '다른 건', deadline: '2026-09-10', text: '회신해 주세요' }], 작업: [],
  }
  function mountHome(mode = '시연') {
    fakeServer({
      'GET /api/people': { json: PEOPLE },
      'GET /api/clock': { json: { date: '2026-09-05', mode } },
      'GET /api/todo/Masil%20%EB%8C%80%ED%91%9C': { json: todo },
      'GET /api/calendar': { json: [] },
      'GET /api/cases': { json: [] },
      'GET /api/demo/scenarios': { json: [] },
      'GET /api/demo/state': { json: { scenario: null, title: null, done: 0, total: 0, finished: false, next_step: null, date: '2026-09-05' } },
    })
    return render(
      <MemoryRouter initialEntries={['/?as=Masil+%EB%8C%80%ED%91%9C']}>
        <App />
      </MemoryRouter>,
    )
  }

  it('할_일_줄은_무엇을_건이름_기한_버튼', async () => {
    mountHome()
    const list = await screen.findByRole('list', { name: '할 일 목록' })
    expect(screen.getByRole('heading', { name: '할 일 3건' })).toBeInTheDocument()
    const first = within(list).getAllByRole('listitem')[0]
    expect(first).toHaveTextContent('승인해 주세요')
    expect(first).toHaveTextContent('혜인 기초 캠페인3 · 혜인')
    expect(first).toHaveTextContent('9월 7일까지')
    expect(within(first).getByRole('button', { name: /열기/ })).toBeInTheDocument()
    const reply = within(list).getAllByRole('listitem').find((li) => li.textContent?.includes('회신해 주세요'))!
    expect(within(reply).getByRole('button', { name: /회신하기/ })).toBeInTheDocument()
    // 번호는 건 이름보다 작은 보조
    expect(first.querySelector('.ref')).toHaveTextContent('PLAN-001')
  })

  it('기준일_이동은_시연_조작판에만', async () => {
    mountHome()
    await screen.findByRole('list', { name: '할 일 목록' })
    expect(screen.queryByRole('button', { name: '다음 날로' })).toBeNull()
    expect(screen.queryByLabelText('이동할 날짜')).toBeNull()
    expect(screen.queryByRole('button', { name: '모드 전환' })).toBeNull()
    expect(screen.getByText('9월 5일')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('link', { name: '시연' }))
    expect(await screen.findByRole('button', { name: '다음 날로' })).toBeInTheDocument()
    expect(screen.getByLabelText('이동할 날짜')).toBeInTheDocument()
  })

  it('화면에_금지어가_없다_메인', async () => {
    mountHome()
    await screen.findByRole('list', { name: '할 일 목록' })
    expect(findForbidden(visibleText(document.body))).toEqual([])
  })
})

describe('시연 조작판 개편', () => {
  const SCENES = [
    {
      name: 'scenario_2', title: '장면 2. 조건 변경 — SCM 일부 허용', description: `집행일이 하회 구간이라 ${DIRTY}.`, plans: ['PLAN-001'], contracts: [],
      script: [
        { action: '회신', plan: 'PLAN-001', dept: '물류', text: '가능' },
        { action: '결정', plan: 'PLAN-001', actor: '그룹 CEO', decision: '분할승인' },
        { action: '기준일', date: '2026-07-14' },
        { action: '판매', plan: 'PLAN-001', actor: '캠페인 담당자', orders: 1, returns: 0 },
      ],
    },
  ]
  function mountDemo(done = 1) {
    fakeServer({
      'GET /api/people': { json: PEOPLE },
      'GET /api/clock': { json: { date: '2026-07-01', mode: '시연' } },
      'GET /api/demo/scenarios': { json: SCENES },
      'GET /api/demo/state': { json: { scenario: 'scenario_2', title: SCENES[0].title, done, total: 4, finished: false, next_step: SCENES[0].script[done], date: '2026-07-01' } },
      'GET /api/cases': { json: [{ id: 7, kind: '기안', ref_id: 'PLAN-001', title: '혜인 기초 캠페인3 · 혜인', status: '승인 대기' }] },
    })
    return render(
      <MemoryRouter initialEntries={['/demo?as=Masil+%EB%8C%80%ED%91%9C']}>
        <App />
      </MemoryRouter>,
    )
  }

  it('시연_단계는_문장으로', async () => {
    mountDemo(1)
    const steps = await screen.findByRole('list', { name: '대본 단계' })
    const items = within(steps).getAllByRole('listitem')
    expect(items[0]).toHaveTextContent('물류가 회신해요')
    expect(items[1]).toHaveTextContent('그룹 CEO가 분할 승인해요')
    expect(items[2]).toHaveTextContent('기준일을 7월 14일로 옮겨요')
    expect(items[3]).toHaveTextContent('캠페인 담당자가 판매 실적을 넣어요')
    // 진행한 단계는 체크, 다음 단계는 강조
    expect(items[0]).toHaveAttribute('data-done', 'true')
    expect(items[1]).toHaveAttribute('data-next', 'true')
    // 다음이 결정이면 그 사람으로 바꿔 건을 여는 안내
    expect(screen.getByText(/이제 그룹 CEO로 바꿔 혜인 기초 캠페인3 · 혜인을 열어 보세요/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /그룹 CEO로 바꿔 열기/ })).toBeInTheDocument()
  })

  it('화면에_금지어가_없다_시연', async () => {
    mountDemo(1)
    await screen.findByRole('list', { name: '대본 단계' })
    expect(findForbidden(visibleText(document.body))).toEqual([])
  })
})
