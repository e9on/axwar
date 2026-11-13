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

const STEPS = [
  { action: '회신', plan: 'PLAN-014', date: '2026-07-03', dept: '물류', text: '전량 가능합니다', attachments: 0 },
  { action: '결정', plan: 'PLAN-014', actor: 'Masil 대표', decision: '승인', comment: '좋아요' },
  { action: '기준일', date: '2026-07-20' },
]
const SCENARIOS = [
  { name: 'scenario_1', title: '장면 1. 정상', description: '정상으로 승인되는 장면', summary: '7월 기안 PLAN-014 — 회신이 오면 대표가 승인해요.', plans: ['PLAN-014'], contracts: [], script: STEPS },
  { name: 'scenario_2', title: '장면 2. 조건 변경', description: '일부 허용', summary: '', plans: ['PLAN-020'], contracts: [], script: [STEPS[0]] },
]
const WAIT_NOW = { index: 1, action: '결정', actor: 'Masil 대표', target: 'PLAN-014', text: 'Masil 대표가 PLAN-014를 승인해요', ready: true, step: STEPS[1] }
const WAIT_LATER = { ...WAIT_NOW, ready: false }
const CASES = [{ id: 7, ref_id: 'PLAN-014', title: '7월 기안 — 혜인' }]

type Pos = { scenario: string | null; done: number; waiting: unknown; next_date: string | null; date: string; arrived: string[] }
type AdvanceReply = (to: string, pos: Pos) => Record<string, unknown>

/** 서버가 기억하는 시연 진행 위치(새로고침해도 유지). init으로 이미 진행한 상태에서 시작할 수 있다 */
function mount(mode = '시연', init: Partial<Pos> = {}, advanceReply?: AdvanceReply) {
  const pos: Pos = { scenario: null, done: 0, waiting: null, next_date: null, date: '2026-07-01', arrived: [], ...init }
  const stateReply = () => {
    const total = pos.scenario ? SCENARIOS.find((x) => x.name === pos.scenario)!.script.length : 0
    return {
      json: {
        scenario: pos.scenario, title: pos.scenario ? '장면' : null, summary: '', done: pos.done, total, finished: !!pos.scenario && pos.done >= total,
        next_step: null, date: pos.date, waiting: pos.waiting, next_date: pos.next_date, arrived: pos.arrived,
      },
    }
  }
  const server = fakeServer({
    'GET /api/people': { json: PEOPLE },
    'GET /api/cases': { json: CASES },
    'GET /api/clock': () => ({ json: { date: pos.date, mode } }),
    'GET /api/demo/scenarios': { json: SCENARIOS },
    'GET /api/demo/state': stateReply,
    'POST /api/demo/reset': () => {
      pos.scenario = 'scenario_1'
      pos.done = 0
      pos.waiting = WAIT_LATER
      pos.next_date = '2026-07-03'
      return { json: { scenario: 'scenario_1', case_ids: [1], date: '2026-07-01' } }
    },
    'POST /api/demo/advance': () => {
      const to = (server.calls.filter((c) => c.path === '/api/demo/advance').slice(-1)[0].body as { date: string }).date
      const custom = advanceReply?.(to, pos)
      if (custom) return { json: custom }
      pos.date = to
      pos.done = 1
      pos.waiting = WAIT_NOW
      pos.next_date = '2026-07-20'
      return { json: { date: to, applied: ['7/3 물류 회신이 도착했어요'], skipped: [], actions: [], waiting: WAIT_NOW, next_date: '2026-07-20' } }
    },
    'POST /api/demo/run': () => {
      pos.done = 3
      return { json: [{ action: '회신', actions: [], changed: true, status: '승인 대기' }] }
    },
    'POST /api/clock': { json: { date: '2026-09-04', mode: '시연', actions: [] } },
  })
  render(
    <MemoryRouter initialEntries={['/demo?as=' + encodeURIComponent('Masil 대표')]}>
      <App />
    </MemoryRouter>,
  )
  return server
}

async function start(advanceReply?: AdvanceReply) {
  const server = mount('시연', {}, advanceReply)
  await userEvent.click(await screen.findByRole('button', { name: /장면 1\. 정상/ }))
  const dlg = await screen.findByRole('dialog')
  await userEvent.click(within(dlg).getByRole('button', { name: '초기화하고 시작' }))
  await screen.findByRole('list', { name: '대본 단계' })
  return server
}

/** 단계 줄(결과 안의 작은 목록은 빼고 바로 아래 줄만) */
const stepItems = () => Array.from(screen.getByRole('list', { name: '대본 단계' }).children) as HTMLElement[]

afterEach(() => vi.unstubAllGlobals())

describe('시연 조작판', () => {
  it('시연_초기화와_장면선택', async () => {
    const { calls } = mount()
    expect(await screen.findByText('7월 기안 PLAN-014 — 회신이 오면 대표가 승인해요.')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /장면 1\. 정상/ }))
    let dlg = await screen.findByRole('dialog')
    expect(dlg).toHaveTextContent('시연 데이터가 지워져요')
    await userEvent.click(within(dlg).getByRole('button', { name: '취소' }))
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(calls.some((c) => c.path === '/api/demo/reset')).toBe(false)

    await userEvent.click(screen.getByRole('button', { name: /장면 1\. 정상/ }))
    dlg = await screen.findByRole('dialog')
    await userEvent.click(within(dlg).getByRole('button', { name: '초기화하고 시작' }))
    const steps = await screen.findByRole('list', { name: '대본 단계' })
    expect(calls).toContainEqual({ method: 'POST', path: '/api/demo/reset', body: { scenario: 'scenario_1' } })
    const items = within(steps).getAllByRole('listitem')
    expect(items).toHaveLength(3)
    expect(items[0]).toHaveTextContent('물류가 회신해요')
    expect(items[1]).toHaveTextContent('Masil 대표가 승인해요')
    expect(items[1]).not.toHaveTextContent('2026-07-20')
    expect(items[0]).not.toHaveTextContent('날짜 그대로')
    expect(calls.some((c) => c.method === 'GET' && c.path === '/api/demo/state')).toBe(true)
    expect(calls.filter((c) => c.path === '/api/clock' && c.method === 'GET').length).toBeGreaterThanOrEqual(2)
  })

  it('다음_날짜로_누르면_advance를_부르고_도착한_사건을_보인다', async () => {
    const { calls } = await start()
    await userEvent.click(await screen.findByRole('button', { name: /다음 날짜로.*7월 3일/ }))
    await waitFor(() => expect(calls).toContainEqual({ method: 'POST', path: '/api/demo/advance', body: { date: '2026-07-03' } }))
    expect(await screen.findByText(/7\/3 물류 회신이 도착했어요/)).toBeInTheDocument()
    // 다음 날짜 버튼은 서버가 준 next_date대로
    expect(await screen.findByRole('button', { name: /다음 날짜로.*7월 20일/ })).toBeInTheDocument()
    // 단계마다 play를 부르지 않는다
    expect(calls.some((c) => c.path === '/api/demo/play')).toBe(false)
  })

  it('결정이_기다리면_바로가기가_뜬다', async () => {
    const { calls } = await start()
    // 회신이 오기 전에는 바로가기가 없다
    expect(screen.queryByRole('button', { name: /로 바꿔 건 열기/ })).toBeNull()
    await userEvent.click(await screen.findByRole('button', { name: /다음 날짜로/ }))
    expect(await screen.findByText(/이제 Masil 대표가 결정할 차례예요/)).toBeInTheDocument()
    expect(screen.getByText(/Masil 대표가 PLAN-014를 승인해요/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Masil 대표로 바꿔 건 열기' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'GET' && c.path.startsWith('/api/cases/7'))).toBe(true))
  })

  it('한_단계씩_버튼이_없다', async () => {
    await start()
    expect(screen.queryByRole('button', { name: '다음 단계' })).toBeNull()
    // 끝까지는 시험용이라 접어 둔 곳 안에만 있다
    const more = screen.getByText('대본 끝까지 자동 진행').closest('details') as HTMLElement
    expect(more).not.toHaveAttribute('open')
    expect(more).toHaveTextContent('결정까지 자동')
  })

  it('결정하지_않고_넘기면_기본_거부_같은_조치를_보이고_다음_날짜는_next_date대로', async () => {
    const { calls } = await start((to, pos) => {
      pos.date = to
      pos.waiting = null
      pos.next_date = '2026-07-20'
      return {
        date: to, applied: [], skipped: ['판매 실적 — 아직 넣을 수 없음: 1차 집행 전'], waiting: null, next_date: '2026-07-20',
        actions: [{ date: '2026-07-14', case_id: 7, action: '기본 거부', targets: ['Masil 대표'], text: '결정하지 않아 7월 14일에 기본 거부됐어요' }],
      }
    })
    await userEvent.click(await screen.findByRole('button', { name: /다음 날짜로/ }))
    expect(await screen.findByText(/결정하지 않아 7월 14일에 기본 거부됐어요/)).toBeInTheDocument()
    expect(screen.getByText(/1차 집행 전/)).toBeInTheDocument()
    expect(screen.queryByText(/이제 .* 결정할 차례/)).toBeNull()
    expect(await screen.findByRole('button', { name: /다음 날짜로.*7월 20일/ })).toBeInTheDocument()
    expect(calls.filter((c) => c.path === '/api/demo/advance')).toHaveLength(1)
  })

  it('다음_날짜가_없으면_버튼이_잠긴다', async () => {
    mount('시연', { scenario: 'scenario_1', done: 3, next_date: null })
    expect(await screen.findByRole('button', { name: /다음 날짜로/ })).toBeDisabled()
  })

  it('날짜_띠의_점을_누르면_그_날짜로_advance한다', async () => {
    const { calls } = await start()
    const strip = await screen.findByRole('list', { name: '날짜 띠' })
    await userEvent.click(within(strip).getByRole('button', { name: /7월 20일/ }))
    await waitFor(() => expect(calls).toContainEqual({ method: 'POST', path: '/api/demo/advance', body: { date: '2026-07-20' } }))
    expect(calls.some((c) => c.path === '/api/clock' && c.method === 'POST')).toBe(false)
  })

  it('대본_끝까지_자동_진행은_run_한_번으로', async () => {
    const { calls } = await start()
    await userEvent.click(screen.getByText('대본 끝까지 자동 진행'))
    await userEvent.click(screen.getByRole('button', { name: '끝까지 진행' }))
    await waitFor(() => expect(calls).toContainEqual({ method: 'POST', path: '/api/demo/run', body: { scenario: 'scenario_1', from_step: 0 } }))
    await waitFor(() => expect(stepItems()[2]).toHaveAttribute('data-done', 'true'))
  })

  it('새로고침해도_서버가_기억한_진행_위치에서_이어진다', async () => {
    mount('시연', { scenario: 'scenario_1', done: 1, waiting: WAIT_NOW, next_date: '2026-07-20', date: '2026-07-03' })
    expect(await screen.findByText('1 / 3단계 진행')).toBeInTheDocument()
    expect(stepItems()[0]).toHaveAttribute('data-done', 'true')
    expect(stepItems()[1]).toHaveAttribute('data-done', 'false')
    expect(await screen.findByText(/이제 Masil 대표가 결정할 차례예요/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /다음 날짜로.*7월 20일/ })).toBeInTheDocument()
  })

  it('처음부터는_확인_뒤_다시_초기화한다', async () => {
    const { calls } = await start()
    await userEvent.click(screen.getByRole('button', { name: '처음부터' }))
    const dlg = await screen.findByRole('dialog')
    await userEvent.click(within(dlg).getByRole('button', { name: '초기화하고 시작' }))
    await waitFor(() => expect(calls.filter((c) => c.path === '/api/demo/reset')).toHaveLength(2))
  })

  it('진행_실패는_문장을_보이고_다시_누를_수_있다', async () => {
    fakeServer({
      'GET /api/people': { json: PEOPLE },
      'GET /api/clock': { json: { date: '2026-07-01', mode: '시연' } },
      'GET /api/demo/scenarios': { json: SCENARIOS },
      'GET /api/demo/state': { json: { scenario: 'scenario_1', title: '장면', summary: '', done: 0, total: 3, finished: false, next_step: null, date: '2026-07-01', waiting: WAIT_LATER, next_date: '2026-07-03', arrived: [] } },
      'POST /api/demo/advance': { status: 409, json: { detail: '서버 거절 문장' } },
    })
    render(
      <MemoryRouter initialEntries={['/demo']}>
        <App />
      </MemoryRouter>,
    )
    await userEvent.click(await screen.findByRole('button', { name: /다음 날짜로/ }))
    expect((await screen.findAllByText(/서버 거절 문장/)).length).toBeGreaterThan(0)
    expect(screen.getByRole('button', { name: /다음 날짜로/ })).toBeEnabled()
  })

  it('운영_모드에서는_시연_조작판이_없다', async () => {
    const { calls } = mount('운영')
    expect(await screen.findByText(/시연 모드에서만/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /장면 1\. 정상/ })).toBeNull()
    expect(screen.queryByRole('link', { name: '시연' })).toBeNull()
    expect(calls.some((c) => c.path === '/api/demo/scenarios')).toBe(false)
  })

  it('장면_목록_실패는_다시_시도', async () => {
    fakeServer({
      'GET /api/people': { json: PEOPLE },
      'GET /api/clock': { json: { date: '2026-07-01', mode: '시연' } },
      'GET /api/demo/state': { json: { scenario: null, title: null, done: 0, total: 0, finished: false, next_step: null, date: '2026-07-01' } },
      'GET /api/demo/scenarios': { status: 500, json: { detail: '대본을 못 읽음' } },
    })
    render(
      <MemoryRouter initialEntries={['/demo']}>
        <App />
      </MemoryRouter>,
    )
    expect((await screen.findAllByText(/대본을 못 읽음/)).length).toBeGreaterThan(0)
    expect(screen.getByRole('button', { name: '다시 시도' })).toBeInTheDocument()
  })
})
