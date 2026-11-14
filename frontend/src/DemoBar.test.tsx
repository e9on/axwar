import { describe, it, expect, afterEach, beforeEach, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import App from './App'
import { fakeServer } from './test/fakeServer'
import { visibleText } from './test/visibleText'

const PEOPLE = [
  { name: '마케팅팀장', role: '마케팅팀' },
  { name: 'Masil 대표', role: 'Masil 대표' },
]
const STEPS = [
  { action: '회신', plan: 'PLAN-014', date: '2026-07-03', dept: '물류', text: '전량 가능합니다', attachments: 0 },
  { action: '결정', plan: 'PLAN-014', actor: 'Masil 대표', decision: '승인', comment: '좋아요' },
  { action: '기준일', date: '2026-07-20' },
]
const SCENARIOS = [{ name: 'scenario_1', title: '장면 1. 정상', description: '정상 승인', summary: '7월 기안', plans: ['PLAN-014'], contracts: [], script: STEPS }]
const WAIT_LATER = { index: 1, action: '결정', actor: 'Masil 대표', target: 'PLAN-014', text: '승인해요', ready: false, step: STEPS[1] }
const WAIT_NOW = { ...WAIT_LATER, ready: true }
const TODO = { '승인 대기': [{ case_id: 7, ref_id: 'PLAN-014', title: '7월 기안', kind: '승인' }] }

type Pos = { scenario: string | null; waiting: unknown; next_date: string | null; date: string; arrived: string[]; outcome?: string[] }

/** 서버가 기억하는 진행 위치를 흉내 낸다. advance는 날짜만 옮기고 7월 3일에 물류 회신이 와 결정을 기다린다 */
function mount(url: string, init: Partial<Pos> = {}, advance?: (to: string, pos: Pos) => Record<string, unknown> | undefined) {
  const pos: Pos = { scenario: null, waiting: null, next_date: null, date: '2026-07-01', arrived: [], ...init }
  const server = fakeServer({
    'GET /api/people': { json: PEOPLE },
    'GET /api/cases': { json: [{ id: 7, ref_id: 'PLAN-014', title: '7월 기안' }] },
    'GET /api/todo/*': { json: TODO },
    'GET /api/calendar': { json: [] },
    'GET /api/clock': () => ({ json: { date: pos.date, mode: '시연' } }),
    'GET /api/demo/scenarios': { json: SCENARIOS },
    'GET /api/demo/state': () => ({
      json: { scenario: pos.scenario, title: pos.scenario ? '장면 1. 정상' : null, summary: '', done: 0, total: 3, finished: false, next_step: null, date: pos.date, waiting: pos.waiting, next_date: pos.next_date, arrived: pos.arrived, outcome: pos.outcome },
    }),
    'POST /api/demo/reset': () => {
      Object.assign(pos, { scenario: 'scenario_1', waiting: WAIT_LATER, next_date: '2026-07-03', date: '2026-07-01', arrived: [] })
      return { json: { scenario: 'scenario_1', case_ids: [7], date: '2026-07-01' } }
    },
    'POST /api/demo/advance': () => {
      const to = (server.calls.filter((c) => c.path === '/api/demo/advance').slice(-1)[0].body as { date: string }).date
      const custom = advance?.(to, pos)
      if (custom) return { json: custom }
      pos.date = to
      if (to >= '2026-07-03') {
        pos.waiting = WAIT_NOW
        pos.next_date = '2026-07-20'
        return { json: { date: to, applied: ['7/3 물류 회신이 도착했어요'], skipped: [], actions: [], waiting: WAIT_NOW, next_date: '2026-07-20' } }
      }
      return { json: { date: to, applied: [], skipped: [], actions: [], waiting: WAIT_LATER, next_date: '2026-07-03' } }
    },
  })
  render(
    <MemoryRouter initialEntries={[url]}>
      <App />
    </MemoryRouter>,
  )
  return { server, pos }
}

const advances = (calls: { path: string; body?: unknown }[]) => calls.filter((c) => c.path === '/api/demo/advance').map((c) => (c.body as { date: string }).date)
const viewer = () => (screen.getByLabelText('보는 사람') as HTMLSelectElement).value

async function startFromPanel() {
  await userEvent.click(await screen.findByRole('button', { name: /장면 1\. 정상/ }))
  await userEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: '초기화하고 시작' }))
}

beforeEach(() => vi.stubEnv('VITE_DEMO_TICK_MS', '10'))
afterEach(() => {
  vi.unstubAllGlobals()
  vi.unstubAllEnvs()
})

describe('메인의 시연 막대', () => {
  it('시작하면_메인으로_간다', async () => {
    mount('/demo?as=' + encodeURIComponent('마케팅팀장'))
    await startFromPanel()
    const bar = await screen.findByRole('region', { name: '시연 진행' })
    expect(within(bar).getByText('7월 1일 (수)')).toBeInTheDocument()
    expect(within(bar).getByText('장면 1. 정상')).toBeInTheDocument()
    expect(screen.getByRole('region', { name: '할 일' })).toBeInTheDocument() // 메인 화면
    expect(screen.queryByRole('heading', { name: '시연 조작판' })).toBeNull()
    // 보는 사람은 첫 결정권자
    await waitFor(() => expect(viewer()).toBe('Masil 대표'))
  })

  it('괄호_조사가_없다', async () => {
    mount('/', { scenario: 'scenario_1', waiting: WAIT_NOW, next_date: '2026-07-20' })
    const bar = await screen.findByRole('region', { name: '시연 진행' })
    await within(bar).findByRole('button', { name: 'Masil 대표로 바꾸기' })
    expect(visibleText(document.body)).not.toMatch(/\((?:으|이|가|을|를|은|는|와|과)\)/)
  })

  it('진행은_하루씩_advance', async () => {
    const { server } = mount('/?as=' + encodeURIComponent('마케팅팀장'), { scenario: 'scenario_1', waiting: WAIT_LATER, next_date: '2026-07-03' })
    await userEvent.click(await screen.findByRole('button', { name: '▶ 진행' }))
    await waitFor(() => expect(advances(server.calls)).toEqual(['2026-07-02', '2026-07-03']))
    // 날짜가 하루씩만 넘어가고, 멈춘 뒤에는 더 부르지 않는다
    await new Promise((r) => setTimeout(r, 80))
    expect(advances(server.calls)).toEqual(['2026-07-02', '2026-07-03'])
    expect(await screen.findByText(/7\/3 물류 회신이 도착했어요/)).toBeInTheDocument()
  })

  it('다음_날과_다음_일까지', async () => {
    const { server } = mount('/', { scenario: 'scenario_1', waiting: WAIT_LATER, next_date: '2026-07-03' })
    await userEvent.click(await screen.findByRole('button', { name: '다음 날' }))
    await waitFor(() => expect(advances(server.calls)).toEqual(['2026-07-02']))
    await userEvent.click(await screen.findByRole('button', { name: '다음 일까지' }))
    await waitFor(() => expect(advances(server.calls)).toEqual(['2026-07-02', '2026-07-03']))
  })

  it('waiting이면_멈추고_결정권자로_바꾼다', async () => {
    const { server } = mount('/?as=' + encodeURIComponent('마케팅팀장'), { scenario: 'scenario_1', waiting: WAIT_LATER, next_date: '2026-07-03' })
    await userEvent.click(await screen.findByRole('button', { name: '▶ 진행' }))
    const bar = screen.getByRole('region', { name: '시연 진행' })
    expect(await within(bar).findByText(/Masil 대표의 승인이 필요해요 — 아래 할 일을 눌러 결정하세요/)).toBeInTheDocument()
    await waitFor(() => expect(viewer()).toBe('Masil 대표'))
    expect(within(bar).getByRole('button', { name: '▶ 진행' })).toBeInTheDocument() // 멈춤이 아니라 다시 진행
    // 해당 할 일 줄이 강조된다
    const row = await screen.findByRole('button', { name: /PLAN-014 열기/ })
    expect(row.closest('li')).toHaveAttribute('data-waiting', 'true')
    const n = advances(server.calls).length
    await new Promise((r) => setTimeout(r, 60))
    expect(advances(server.calls)).toHaveLength(n)
  })

  it('결정하지_않고_넘기면_서버_문장이_알림_줄에_뜬다', async () => {
    mount('/', { scenario: 'scenario_1', waiting: WAIT_NOW, next_date: '2026-07-20', date: '2026-07-03' }, (to, pos) => {
      pos.date = to
      return {
        date: to, applied: [], skipped: [], waiting: WAIT_NOW, next_date: '2026-07-20',
        actions: [{ date: to, case_id: 7, action: '경고', targets: ['Masil 대표'], text: '결정이 늦어지고 있어요' }],
      }
    })
    await userEvent.click(await screen.findByRole('button', { name: '다음 날' }))
    const notice = await screen.findByRole('status', { name: '이번에 일어난 일' })
    expect(notice).toHaveTextContent('결정이 늦어지고 있어요')
  })

  it('결정_뒤_돌아오면_이어가기_안내', async () => {
    const { pos } = mount('/?as=' + encodeURIComponent('Masil 대표'), { scenario: 'scenario_1', waiting: WAIT_LATER, next_date: '2026-07-03' })
    await userEvent.click(await screen.findByRole('button', { name: '▶ 진행' }))
    await screen.findByText(/승인이 필요해요/)
    // 건 상세에서 결정한 것처럼 서버 위치를 바꾸고 다른 화면에 갔다 온다
    pos.waiting = null
    await userEvent.click(screen.getByRole('link', { name: '시연' }))
    await userEvent.click(await screen.findByRole('button', { name: '메인으로' }))
    expect(await screen.findByText('결정했어요. ▶ 진행을 눌러 이어 가세요')).toBeInTheDocument()
  })

  it('끝나면_장면이_끝났어요', async () => {
    mount('/', { scenario: 'scenario_1', waiting: null, next_date: '2026-07-20', date: '2026-07-19' }, (to, pos) => {
      pos.date = to
      pos.next_date = null
      return { date: to, applied: ['7/20 기준일이 되어 1차 집행을 확인했어요'], skipped: [], actions: [], waiting: null, next_date: null }
    })
    await userEvent.click(await screen.findByRole('button', { name: '▶ 진행' }))
    expect(await screen.findByText('장면이 끝났어요')).toBeInTheDocument()
    const bar = screen.getByRole('region', { name: '시연 진행' })
    expect(bar).toHaveTextContent('7/20 기준일이 되어 1차 집행을 확인했어요')
    expect(within(bar).getByRole('button', { name: '처음부터' })).toBeInTheDocument()
    expect(within(bar).getByRole('button', { name: '▶ 진행' })).toBeDisabled()
  })

  it('끝난_장면을_다시_열어도_끝났어요', async () => {
    mount('/', { scenario: 'scenario_1', waiting: null, next_date: null, date: '2026-07-20', arrived: ['7/3 물류 회신', '7/20 기준일'] })
    expect(await screen.findByText('장면이 끝났어요')).toBeInTheDocument()
    expect(screen.getByRole('region', { name: '시연 진행' })).toHaveTextContent('7/20 기준일')
  })

  it('끝나면_마지막_도착_사건_대신_장면_건들의_지금_상태를_결과로_보인다', async () => {
    mount('/', { scenario: 'scenario_1', waiting: null, next_date: null, date: '2026-07-20', arrived: ['7/3 물류 회신이 도착함'], outcome: ['PLAN-014 1차 집행'] })
    expect(await screen.findByText('장면이 끝났어요')).toBeInTheDocument()
    const bar = screen.getByRole('region', { name: '시연 진행' })
    expect(bar).toHaveTextContent('결과: PLAN-014 1차 집행')
    expect(bar).not.toHaveTextContent('7/3 물류 회신이 도착함')
  })

  it('결정이_남았지만_마감_전이면_언제_멈추는지와_먼저_할_수_있다는_것을_보인다', async () => {
    mount('/', { scenario: 'scenario_1', waiting: { ...WAIT_LATER, due: '2026-07-16' }, next_date: '2026-07-16', date: '2026-07-05' })
    const bar = await screen.findByRole('region', { name: '시연 진행' })
    await waitFor(() => expect(bar).toHaveTextContent('Masil 대표 승인 마감 7월 16일'))
    expect(bar).toHaveTextContent('할 일에서 먼저 할 수 있어요')
  })

  it('마지막_승인일에_결재가_남았는데_진행하면_기본_거부된다고_확인을_받는다', async () => {
    const { server } = mount('/', { scenario: 'scenario_1', waiting: { ...WAIT_NOW, due: '2026-07-16' }, next_date: '2026-07-20', date: '2026-07-16' })
    const bar = await screen.findByRole('region', { name: '시연 진행' })
    await userEvent.click(within(bar).getByRole('button', { name: '▶ 진행' }))
    const dlg = await screen.findByRole('dialog')
    expect(dlg).toHaveTextContent('오늘이 마지막 승인일')
    expect(dlg).toHaveTextContent('내일 기본 거부')
    await userEvent.click(within(dlg).getByRole('button', { name: '취소' }))
    expect(server.calls.filter((c) => c.path === '/api/demo/advance')).toHaveLength(0)
    await userEvent.click(within(bar).getByRole('button', { name: '다음 날' }))
    await userEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: '그래도 진행' }))
    await waitFor(() => expect(server.calls.filter((c) => c.path === '/api/demo/advance')).toHaveLength(1))
  })

  it('장면이_없으면_막대가_없다', async () => {
    mount('/')
    await screen.findByRole('region', { name: '할 일' })
    expect(screen.queryByRole('region', { name: '시연 진행' })).toBeNull()
  })
})
