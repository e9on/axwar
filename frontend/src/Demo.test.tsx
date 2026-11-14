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

/** 조작판에서 장면 1을 시작한다(시작하면 메인으로 간다) */
async function start(advanceReply?: AdvanceReply) {
  const server = mount('시연', {}, advanceReply)
  await userEvent.click(await screen.findByRole('button', { name: /장면 1\. 정상/ }))
  const dlg = await screen.findByRole('dialog')
  await userEvent.click(within(dlg).getByRole('button', { name: '초기화하고 시작' }))
  await screen.findByRole('region', { name: '시연 진행' })
  return server
}

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
    await screen.findByRole('region', { name: '시연 진행' })
    expect(calls).toContainEqual({ method: 'POST', path: '/api/demo/reset', body: { scenario: 'scenario_1' } })
    expect(calls.some((c) => c.method === 'GET' && c.path === '/api/demo/state')).toBe(true)
  })

  it('시작하면_첫_결정권자로_바꿔_메인으로_간다', async () => {
    await start()
    expect((screen.getByLabelText('보는 사람') as HTMLSelectElement).value).toBe('Masil 대표')
    expect(screen.queryByRole('heading', { name: '시연 조작판' })).toBeNull()
  })

  it('조작판에는_진행_기능이_없고_메인으로_안내한다', async () => {
    mount('시연', { scenario: 'scenario_1', done: 1, waiting: WAIT_NOW, next_date: '2026-07-20', date: '2026-07-03' })
    expect(await screen.findByText(/지금 진행 중인 장면/)).toBeInTheDocument()
    expect(screen.getByText('메인에서 진행하세요.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '메인으로' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '처음부터' })).toBeInTheDocument()
    for (const gone of [/다음 날짜로/, '다음 날로', '날짜로 이동', '끝까지 진행', '다음 단계']) {
      expect(screen.queryByRole('button', { name: gone })).toBeNull()
    }
    expect(screen.queryByRole('list', { name: '날짜 띠' })).toBeNull()
    expect(screen.queryByRole('list', { name: '대본 단계' })).toBeNull()
  })

  it('메인으로_버튼은_메인에_막대를_보인다', async () => {
    mount('시연', { scenario: 'scenario_1', done: 1, waiting: WAIT_NOW, next_date: '2026-07-20', date: '2026-07-03' })
    await userEvent.click(await screen.findByRole('button', { name: '메인으로' }))
    expect(await screen.findByRole('region', { name: '시연 진행' })).toBeInTheDocument()
  })

  it('처음부터는_확인_뒤_다시_초기화한다', async () => {
    const { calls } = mount('시연', { scenario: 'scenario_1', done: 1, waiting: WAIT_NOW, next_date: '2026-07-20', date: '2026-07-03' })
    await userEvent.click(await screen.findByRole('button', { name: '처음부터' }))
    const dlg = await screen.findByRole('dialog')
    await userEvent.click(within(dlg).getByRole('button', { name: '초기화하고 시작' }))
    await waitFor(() => expect(calls.filter((c) => c.path === '/api/demo/reset')).toHaveLength(1))
  })

  it('시작_실패는_문장을_보인다', async () => {
    fakeServer({
      'GET /api/people': { json: PEOPLE },
      'GET /api/clock': { json: { date: '2026-07-01', mode: '시연' } },
      'GET /api/demo/scenarios': { json: SCENARIOS },
      'GET /api/demo/state': { json: { scenario: null, title: null, done: 0, total: 0, finished: false, next_step: null, date: '2026-07-01' } },
      'POST /api/demo/reset': { status: 409, json: { detail: '서버 거절 문장' } },
    })
    render(
      <MemoryRouter initialEntries={['/demo']}>
        <App />
      </MemoryRouter>,
    )
    await userEvent.click(await screen.findByRole('button', { name: /장면 1\. 정상/ }))
    await userEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: '초기화하고 시작' }))
    expect((await screen.findAllByText(/서버 거절 문장/)).length).toBeGreaterThan(0)
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
