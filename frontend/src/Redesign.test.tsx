import { describe, it, expect, afterEach, vi } from 'vitest'
import { render, screen, within, waitFor } from '@testing-library/react'
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
  key_indicators: [{ key: 'real_roas', label: '실질 ROAS', value: 3.7, unit: 'multiple', rank: 1, of: 10, compare_label: null, compare_value: null, badge: '계산', detail: D }],
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

function mountCase(viewer: object, who: string, over: Record<string, unknown> = {}, evidence: object = EVIDENCE) {
  fakeServer({
    'GET /api/people': { json: PEOPLE },
    'GET /api/clock': { json: { date: '2026-09-05', mode: '시연' } },
    [`GET ${DETAIL_PATH(who)}`]: { json: detailOf(viewer, over) },
    'GET /api/cases/7/evidence': { json: evidence },
  })
  return render(
    <MemoryRouter initialEntries={[`/cases/7?as=${encodeURIComponent(who)}`]}>
      <App />
    </MemoryRouter>,
  )
}

afterEach(() => vi.unstubAllGlobals())

describe('건 상세 개편', () => {
  it('가장_큰_위험에는_참고_신호를_넣지_않고_실질_ROAS를_보인다', async () => {
    mountCase(MAY, 'Masil 대표')
    const core = await screen.findByRole('group', { name: '가장 큰 위험' })
    await waitFor(() => expect(core).toHaveTextContent('실질 ROAS'))
    expect(core).not.toHaveTextContent('예상 ROAS 괴리')
  })

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
      'GET /api/demo/state': { json: { scenario: 'scenario_2', title: SCENES[0].title, done, total: 4, finished: false, next_step: SCENES[0].script[done], date: '2026-07-01', next_date: '2026-07-14', waiting: { index: 1, action: '결정', actor: '그룹 CEO', target: 'PLAN-001', text: '그룹 CEO가 분할 승인해요', ready: true, step: SCENES[0].script[1] } } },
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
    // 결정이 기다리면 그 사람으로 바꿔 건을 여는 안내
    expect(await screen.findByText(/이제 그룹 CEO가 결정할 차례예요/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /그룹 CEO로 바꿔 건 열기/ })).toBeInTheDocument()
  })

  it('화면에_금지어가_없다_시연', async () => {
    mountDemo(1)
    await screen.findByRole('list', { name: '대본 단계' })
    expect(findForbidden(visibleText(document.body))).toEqual([])
  })
})

const AI_OK = (text: string, model = 'claude') => ({ text, ok: true, model, sim_date: '2026-09-04', stale: false })
const BADGE_TEXTS = () => Array.from(document.querySelectorAll('.b')).map((e) => e.textContent)

describe('배지 정리와 AI 의견', () => {
  it('기본_화면에_원본_계산_배지가_없다', async () => {
    mountCase(MAY, 'Masil 대표')
    await screen.findByRole('button', { name: /위험 신호/ })
    for (const name of [/결재 이유/, /위험 신호/, /핵심 지표/, /비용 분해/]) await userEvent.click(screen.getByRole('button', { name }))
    await screen.findByRole('button', { name: /예상 ROAS 괴리/ })
    const texts = BADGE_TEXTS()
    for (const t of ['원본', '계산', '회신', '의견']) expect(texts).not.toContain(t)
  })

  it('가정_표시는_남는다', async () => {
    const asm = { ...EVIDENCE, signals: [{ ...EVIDENCE.signals[1], badge: '가정' }, EVIDENCE.signals[0]] }
    mountCase(MAY, 'Masil 대표', {}, asm)
    await userEvent.click(await screen.findByRole('button', { name: /위험 신호/ }))
    await screen.findByRole('button', { name: /쿠폰 중복 비중/ })
    expect(BADGE_TEXTS()).toContain('가정')
    expect(screen.getAllByText('가정 = 원본에 없어 정한 값')).toHaveLength(1)
  })

  it('AI_의견은_줄바꿈되고_권고_줄만_핵심에', async () => {
    const text = '권고: 분할 승인\n이유: 재고가 모자라요\n주의: 둘째 수량은 판매 뒤 결정'
    mountCase(MAY, 'Masil 대표', { briefing: AI_OK(text, 'fake-model') })
    const core = await screen.findByRole('group', { name: '가장 큰 위험' })
    const keylines = core.closest('dl') as HTMLElement
    const ai = within(keylines).getByText('AI 의견').nextElementSibling as HTMLElement
    expect(ai).toHaveTextContent('분할 승인')
    expect(ai).not.toHaveTextContent('재고가 모자라요')
    await userEvent.click(screen.getByRole('button', { name: /AI 브리핑/ }))
    const head = await screen.findByText('이유:')
    expect(head.tagName).toBe('B')
    const para = head.closest('p') as HTMLElement
    expect(para).toHaveTextContent('재고가 모자라요')
    expect(screen.getByText('주의:')).toBeInTheDocument()
    expect(screen.getByText('권고:')).toBeInTheDocument()
    expect(screen.getByText(/시연용 해석/)).toBeInTheDocument()
  })

  it('반대_근거도_머리말이_굵다', async () => {
    mountCase(MAY, 'Masil 대표', { counterpoints: AI_OK('반대로 결정하려면: 재고를 먼저 채워요\n확인할 것: 입고일') })
    await userEvent.click(await screen.findByRole('button', { name: /반대 근거/ }))
    expect((await screen.findByText('반대로 결정하려면:')).tagName).toBe('B')
    expect(screen.getByText('확인할 것:').tagName).toBe('B')
  })

  it('옛_긴_AI_글은_줄여_보인다', async () => {
    const long = '가'.repeat(300)
    mountCase(MAY, 'Masil 대표', { briefing: AI_OK(long) })
    await userEvent.click(await screen.findByRole('button', { name: /AI 브리핑/ }))
    const more = await screen.findByRole('button', { name: '더 보기' })
    expect(screen.queryByText(long)).toBeNull()
    await userEvent.click(more)
    expect(await screen.findByText(long)).toBeInTheDocument()
  })
})

const EXPLAIN_EVIDENCE = {
  ...EVIDENCE,
  signals: [
    { key: 'a', label: '예상 ROAS 괴리', value: 10.4, unit: 'multiple', compare: '기준 ≤ 1.5 z=2.1 ROAS', level: 'red', badge: '계산', judgment: '판정', exclude_reason: '', explain: '예상 매출이 실제 기록보다 크게 부풀려져 있어서 나쁘게 봤어요.', detail: { ...D, formula: '예상 ROAS = 예상 GMV ÷ 예산' } },
    { key: 'b', label: '쿠폰 중복 비중', value: null, unit: 'ratio', compare: '측정 불가', level: 'unmeasurable', badge: '계산', judgment: '판정', exclude_reason: '', explain: '쿠폰 기록이 없어 잴 수 없었어요.', detail: D },
  ],
  key_indicators: [{ ...EVIDENCE.key_indicators[0], explain: '광고비 대비 실제 매출이 열 곳 중 가장 좋아요.' }],
  cost_breakdown: { note: '표본', rows: [{ key: 'g', label: '매출(GMV)', amount: 1000, unit: 'krw', badge: '계산', explain: '이 캠페인이 만든 매출은 1,000원이에요.', detail: D }] },
  rule: { ...EVIDENCE.rule, approver_hits: [{ ...EVIDENCE.rule.approver_hits[0], text: '하회 구간', explain: '집행일이 기준 아래 구간에 걸려 대표 결재가 필요해요.' }] },
}

async function openAllFolds() {
  await screen.findByRole('button', { name: /위험 신호/ })
  for (let n = 0; n < 10; n++) {
    const closed = Array.from(document.querySelectorAll<HTMLElement>('button[data-fold][aria-expanded="false"]'))
    if (closed.length === 0) return
    for (const b of closed) await userEvent.click(b)
  }
}

describe('근거 줄을 말로 보이기', () => {
  it('근거_줄은_결론과_설명_문장으로_보인다', async () => {
    mountCase(MAY, 'Masil 대표', {}, EXPLAIN_EVIDENCE)
    await openAllFolds()
    const row = (await screen.findByRole('button', { name: /예상 ROAS 괴리/ })).closest('li') as HTMLElement
    expect(within(row).getByText('나쁨')).toBeInTheDocument()
    expect(within(row).getByText('예상 ROAS 괴리').tagName).toBe('B')
    expect(within(row).getByText('예상 매출이 실제 기록보다 크게 부풀려져 있어서 나쁘게 봤어요.')).toBeVisible()
    expect(row).not.toHaveTextContent('z=')
    expect(row).not.toHaveTextContent('≤')
    const cant = screen.getByText('쿠폰 중복 비중').closest('li') as HTMLElement
    expect(within(cant).getByText('잴 수 없음')).toBeInTheDocument()
    expect(screen.getByText('집행일이 기준 아래 구간에 걸려 대표 결재가 필요해요.')).toBeVisible()
    expect(screen.getByText('이 캠페인이 만든 매출은 1,000원이에요.')).toBeVisible()
    expect(screen.getByText('광고비 대비 실제 매출이 열 곳 중 가장 좋아요.')).toBeVisible()
  })

  it('지표_근거가_위험_신호와_같은_설명이면_결재_이유에서는_한_줄로_줄인다', async () => {
    const same = '혜인 캠페인 주문 100건 중 약 18건에 쿠폰이 겹쳐 쓰였어요. 훨씬 많아서 나빠요.'
    const ev = {
      ...EXPLAIN_EVIDENCE,
      signals: [{ ...EXPLAIN_EVIDENCE.signals[1], key: 'coupon_stacking', label: '쿠폰 중복 비중', level: 'red', explain: same }],
      rule: {
        ...EXPLAIN_EVIDENCE.rule,
        indicator_hits: [{ rule_id: 'coupon_stacking', text: '쿠폰 중복 비중', source: 'x.md', badge: '원본', explain: same, detail: D }],
      },
    }
    mountCase(MAY, 'Masil 대표', {}, ev)
    await openAllFolds()
    // 위험 신호 줄에는 설명이 한 번, 결재 이유 줄에는 설명 대신 요약 한 줄
    expect(screen.getAllByText(same)).toHaveLength(1)
    expect(screen.getByText('성과 지표가 나빠 결재가 더 붙었어요')).toBeVisible()
  })

  it('지표_근거_설명이_신호와_다르면_그대로_보인다', async () => {
    const ev = {
      ...EXPLAIN_EVIDENCE,
      rule: { ...EXPLAIN_EVIDENCE.rule, indicator_hits: [{ rule_id: 'x', text: '다른 지표', source: 'x.md', badge: '원본', explain: '이 줄만의 설명이에요.', detail: D }] },
    }
    mountCase(MAY, 'Masil 대표', {}, ev)
    await openAllFolds()
    expect(screen.getByText('이 줄만의 설명이에요.')).toBeVisible()
    expect(screen.queryByText('성과 지표가 나빠 결재가 더 붙었어요')).toBeNull()
  })

  it('계산_근거는_펼쳐야_보인다', async () => {
    mountCase(MAY, 'Masil 대표', {}, EXPLAIN_EVIDENCE)
    await openAllFolds()
    const btn = await screen.findByRole('button', { name: /예상 ROAS 괴리/ })
    const panel = document.getElementById(btn.getAttribute('aria-controls') as string) as HTMLElement
    expect(panel).not.toBeVisible()
    expect(within(panel).getByText('계산 근거', { ignore: 'none' })).not.toBeVisible()
    await userEvent.click(btn)
    expect(within(panel).getByText('계산 근거')).toBeVisible()
    expect(within(panel).getByText(/예상 ROAS = 예상 GMV ÷ 예산/)).toBeVisible()
  })

  it('explain_없으면_값만', async () => {
    mountCase(MAY, 'Masil 대표', {}, { ...EXPLAIN_EVIDENCE, signals: [{ ...EXPLAIN_EVIDENCE.signals[0], explain: undefined }] })
    await openAllFolds()
    const row = (await screen.findByRole('button', { name: /예상 ROAS 괴리/ })).closest('li') as HTMLElement
    expect(row).toHaveTextContent('10.400')
    expect(row).not.toHaveTextContent('z=')
    expect(row).not.toHaveTextContent('≤')
    expect(row).not.toHaveTextContent('ROAS 괴리 ROAS')
  })

  it('표_머리가_없다', async () => {
    mountCase(MAY, 'Masil 대표', {}, EXPLAIN_EVIDENCE)
    await openAllFolds()
    await screen.findByRole('button', { name: /예상 ROAS 괴리/ })
    const ev = document.querySelector('.evidence') as HTMLElement
    expect(ev.querySelector('.ehead')).toBeNull()
    expect(within(ev).queryByText('비교·근거')).toBeNull()
  })
})
