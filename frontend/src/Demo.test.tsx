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
  { action: '회신', plan: 'PLAN-019', dept: '물류', text: '전량 가능합니다', attachments: 0 },
  { action: '회신', plan: 'PLAN-019', dept: 'SCM', text: '전량 허용합니다', attachments: 0 },
  { action: '결정', plan: 'PLAN-019', date: '2026-09-07', actor: 'Masil 대표', decision: '승인', comment: '좋아요' },
]
const SCENARIOS = [
  { name: 'scenario_1', title: '장면 1. 정상', description: '정상으로 승인되는 장면', plans: ['PLAN-019'], contracts: [], script: STEPS },
  { name: 'scenario_2', title: '장면 2. 조건 변경', description: '일부 허용', plans: ['PLAN-020'], contracts: [], script: [STEPS[0]] },
]
const OUT = [
  { action: '회신', actions: [], request_id: 1, case_id: 1, changed: true, status: '승인 대기', judgment: { stance: '수용' } },
  { action: '회신', actions: [], request_id: 2, case_id: 1, changed: false, status: '승인 대기', judgment: null },
  { action: '승인', actions: [{ date: '2026-09-07', case_id: 1, action: '조기경고', targets: ['Masil 대표'], text: '미승인 경고 문장' }], case_id: 1, status: '1차 집행', changed: true },
]

/** 서버가 기억하는 시연 진행 위치(새로고침해도 유지). init으로 이미 진행한 상태에서 시작할 수 있다 */
function mount(mode = '시연', init: { scenario: string | null; done: number } = { scenario: null, done: 0 }) {
  const pos = { ...init }
  const stateReply = () => {
    const total = pos.scenario ? SCENARIOS.find((x) => x.name === pos.scenario)!.script.length : 0
    return { json: { scenario: pos.scenario, title: pos.scenario ? '장면' : null, done: pos.done, total, finished: !!pos.scenario && pos.done >= total, next_step: null, date: '2026-07-01' } }
  }
  const server = fakeServer({
    'GET /api/people': { json: PEOPLE },
    'GET /api/clock': { json: { date: '2026-07-01', mode } },
    'GET /api/demo/scenarios': { json: SCENARIOS },
    'GET /api/demo/state': stateReply,
    'POST /api/demo/reset': () => {
      pos.scenario = 'scenario_1'
      pos.done = 0
      return { json: { scenario: 'scenario_1', case_ids: [1], date: '2026-07-01' } }
    },
    'POST /api/demo/play': () => {
      pos.done += 1
      return { json: OUT[server.calls.filter((c) => c.path === '/api/demo/play').length - 1] }
    },
    'POST /api/demo/run': () => {
      const from = pos.done
      pos.done = 3
      return { json: OUT.slice(from) }
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

async function start() {
  const server = mount()
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
    expect(await screen.findByText('정상으로 승인되는 장면')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /장면 1\. 정상/ }))
    // 확인 창: 취소하면 아무것도 보내지 않는다
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
    expect(items[0]).toHaveTextContent('1')
    expect(items[0]).toHaveTextContent('회신')
    expect(items[0]).toHaveTextContent('물류')
    expect(items[2]).toHaveTextContent('결정')
    expect(items[2]).toHaveTextContent('9월 7일')
    expect(items[2]).not.toHaveTextContent('2026-09-07')
    // 날짜·사람이 없는 단계는 그 칸을 비우고 "—"나 "날짜 그대로"를 쓰지 않는다
    expect(items[0]).not.toHaveTextContent('—')
    expect(items[0]).not.toHaveTextContent('날짜 그대로')
    expect(items[2]).toHaveTextContent('Masil 대표')
    // 초기화 뒤 진행 위치와 기준일을 서버에서 다시 읽는다(다른 화면이 새 날짜로 다시 읽게)
    expect(calls.some((c) => c.method === 'GET' && c.path === '/api/demo/state')).toBe(true)
    expect(calls.filter((c) => c.path === '/api/clock' && c.method === 'GET').length).toBeGreaterThanOrEqual(2)
  })

  it('한_단계_진행과_끝까지', async () => {
    const { calls } = await start()
    await userEvent.click(screen.getByRole('button', { name: '한 단계 진행' }))
    await waitFor(() => expect(calls).toContainEqual({ method: 'POST', path: '/api/demo/play', body: { step: STEPS[0] } }))
    await screen.findByRole('list', { name: '대본 단계' })
    const first = stepItems()[0]
    expect(await within(first).findByText('진행함')).toBeInTheDocument()
    expect(first).toHaveTextContent('건 상태: 승인 대기')
    expect(first).toHaveTextContent('AI 해석: 수용')

    // 끝까지: 서버가 알려 준 현재 위치(1)부터 남은 단계만 한 번에 보낸다(play를 되풀이하지 않음)
    await userEvent.click(screen.getByRole('button', { name: '끝까지' }))
    await waitFor(() => expect(calls).toContainEqual({ method: 'POST', path: '/api/demo/run', body: { scenario: 'scenario_1', from_step: 1 } }))
    expect(calls.filter((c) => c.path === '/api/demo/play')).toHaveLength(1)
    const last = stepItems()[2]
    expect(await within(last).findByText(/미승인 경고 문장/)).toBeInTheDocument()
    expect(last).toHaveTextContent('건 상태: 1차 집행')
    // 다 끝나면 진행 버튼이 잠긴다
    expect(screen.getByRole('button', { name: '한 단계 진행' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '끝까지' })).toBeDisabled()
  })

  it('처음부터_끝까지는_run_한_번으로', async () => {
    const { calls } = await start()
    await userEvent.click(screen.getByRole('button', { name: '끝까지' }))
    await waitFor(() => expect(calls).toContainEqual({ method: 'POST', path: '/api/demo/run', body: { scenario: 'scenario_1', from_step: 0 } }))
    await screen.findByRole('list', { name: '대본 단계' })
    await waitFor(() => expect(within(stepItems()[2]).getByText('진행함')).toBeInTheDocument())
    expect(calls.some((c) => c.path === '/api/demo/play')).toBe(false)
  })

  it('새로고침해도_서버가_기억한_진행_위치에서_이어진다', async () => {
    const { calls } = mount('시연', { scenario: 'scenario_1', done: 2 })
    expect(await screen.findByText('2 / 3단계 진행')).toBeInTheDocument()
    const items = stepItems()
    expect(within(items[0]).getByText('진행함')).toBeInTheDocument()
    expect(within(items[1]).getByText('진행함')).toBeInTheDocument()
    expect(within(items[2]).queryByText('진행함')).toBeNull()
    expect(within(items[2]).getByText('다음')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '한 단계 진행' }))
    await waitFor(() => expect(calls).toContainEqual({ method: 'POST', path: '/api/demo/play', body: { step: STEPS[2] } }))
    await screen.findByText('3 / 3단계 진행')
  })

  it('처음부터는_확인_뒤_다시_초기화한다', async () => {
    const { calls } = await start()
    await userEvent.click(screen.getByRole('button', { name: '한 단계 진행' }))
    await screen.findByText('진행함')
    await userEvent.click(screen.getByRole('button', { name: '처음부터' }))
    const dlg = await screen.findByRole('dialog')
    await userEvent.click(within(dlg).getByRole('button', { name: '초기화하고 시작' }))
    await waitFor(() => expect(calls.filter((c) => c.path === '/api/demo/reset')).toHaveLength(2))
    await waitFor(() => expect(screen.queryByText('진행함')).toBeNull())
  })

  it('기준일_바로_이동_버튼', async () => {
    const { calls } = await start()
    await userEvent.click(screen.getByRole('button', { name: /2026-09-07.*이동/ }))
    await waitFor(() => expect(calls).toContainEqual({ method: 'POST', path: '/api/clock', body: { date: '2026-09-07' } }))
  })

  it('진행_실패는_문장을_보이고_다시_누를_수_있다', async () => {
    fakeServer({
      'GET /api/people': { json: PEOPLE },
      'GET /api/clock': { json: { date: '2026-07-01', mode: '시연' } },
      'GET /api/demo/scenarios': { json: SCENARIOS },
      'GET /api/demo/state': { json: { scenario: 'scenario_1', title: '장면', done: 0, total: 3, finished: false, next_step: null, date: '2026-07-01' } },
      'POST /api/demo/reset': { json: { scenario: 'scenario_1', case_ids: [1], date: '2026-07-01' } },
      'POST /api/demo/play': { status: 409, json: { detail: '서버 거절 문장' } },
    })
    render(
      <MemoryRouter initialEntries={['/demo']}>
        <App />
      </MemoryRouter>,
    )
    await userEvent.click(await screen.findByRole('button', { name: /장면 1\. 정상/ }))
    await userEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: '초기화하고 시작' }))
    await userEvent.click(await screen.findByRole('button', { name: '한 단계 진행' }))
    expect((await screen.findAllByText(/서버 거절 문장/)).length).toBeGreaterThan(0)
    expect(screen.getByRole('button', { name: '한 단계 진행' })).toBeEnabled()
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
