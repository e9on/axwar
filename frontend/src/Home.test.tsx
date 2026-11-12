import { describe, it, expect, afterEach, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, useLocation } from 'react-router-dom'
import App from './App'
import { fakeServer } from './test/fakeServer'

const PEOPLE = [
  { name: '마케팅팀장', role: '마케팅팀장' },
  { name: 'Masil 대표', role: 'Masil 대표' },
]
const TODO_PATH = '/api/todo/' + encodeURIComponent('마케팅팀장')

const EMPTY_TODO = { person: '마케팅팀장', role: '마케팅팀장', '승인 대기': [], '기한 임박': [], '회신 대기': [], 작업: [], '권한 이동': [], 알림: [] }
const item = (case_id: number, ref_id: string, extra: object = {}) => ({
  case_id, kind: '기안', ref_id, status: '승인 대기', deadline: '2026-07-20', deny_date: '2026-07-17', approval_deadline: '2026-07-16', ...extra,
})

const ev = (date: string, kind: string, label: string, case_id: number | null, roles: string[], end: string | null = null) => ({
  date, end, kind, label, case_id, roles,
})
const CALENDAR = [
  ev('2026-07-01', '집행일', '지난 집행일', 9, []),
  ev('2026-07-15', '알림', 'P-1 마지막 승인일', 1, ['마케팅팀장']),
  ev('2026-07-16', '확정 기한', 'P-1 확정 기한', 1, ['마케팅팀장']),
  ev('2026-07-16', '확정 기한', 'P-2 확정 기한', 2, ['Masil 대표']),
  ev('2026-07-20', '하회 구간', '현금 하회 구간 7/20~8/10', null, [], '2026-08-10'),
  ev('2026-07-30', '집행일', 'P-3 집행일', 3, ['캠페인 담당']),
]

function Probe() {
  const loc = useLocation()
  return <output data-testid="url">{loc.pathname + loc.search}</output>
}
function mount(url = '/?as=' + encodeURIComponent('마케팅팀장')) {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <App />
      <Probe />
    </MemoryRouter>,
  )
}
function routes(todo: object = EMPTY_TODO, calendar: object[] = CALENDAR) {
  return {
    'GET /api/people': { json: PEOPLE },
    'GET /api/clock': { json: { date: '2026-07-12', mode: '시연' } },
    ['GET ' + TODO_PATH]: { json: todo },
    'GET /api/calendar': { json: calendar },
  }
}
function narrow(matches: boolean) {
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches, media: query, addEventListener: () => undefined, removeEventListener: () => undefined,
    addListener: () => undefined, removeListener: () => undefined, onchange: null, dispatchEvent: () => false,
  }))
}

afterEach(() => vi.unstubAllGlobals())

describe('메인 화면', () => {
  it('할일은_칸별로_나뉘고_빈_칸은_숨는다', async () => {
    fakeServer(routes({
      ...EMPTY_TODO,
      '승인 대기': [item(1, 'P-1')],
      작업: [item(2, 'P-2', { task_id: 5, title: '물량 입력', detail: '', due: '2026-07-14' })],
      알림: [item(1, 'P-1', { kind: '마감 알림', stage: '1차', text: '내일 기본 거부돼요' })],
    }))
    mount()
    expect(await screen.findByRole('heading', { name: '승인 대기' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '작업' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '알림' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: '회신 대기' })).toBeNull()
    expect(screen.queryByRole('heading', { name: '권한 이동' })).toBeNull()
    expect(screen.getByText('내일 기본 거부돼요')).toBeInTheDocument()
    const heads = screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent)
    expect(heads).toEqual(['승인 대기', '알림', '작업'])
  })

  it('할_일이_모두_없으면_한_줄', async () => {
    fakeServer(routes())
    mount()
    expect(await screen.findByText('지금 할 일이 없어요')).toBeInTheDocument()
  })

  it('할일_줄을_누르면_건_상세로_간다', async () => {
    fakeServer(routes({ ...EMPTY_TODO, '승인 대기': [item(7, 'P-7')] }))
    mount()
    await userEvent.click(await screen.findByRole('button', { name: /P-7/ }))
    await waitFor(() => expect(screen.getByTestId('url').textContent).toMatch(/^\/cases\/7\?as=/))
  })

  it('내_차례_일정만_강조된다', async () => {
    fakeServer(routes())
    mount()
    const mine = await screen.findByRole('button', { name: /P-1 확정 기한/ })
    expect(mine).toHaveAttribute('data-mine', 'true')
    expect(screen.getByRole('button', { name: /P-2 확정 기한/ })).toHaveAttribute('data-mine', 'false')
    expect(screen.getByRole('button', { name: /P-3 집행일/ })).toHaveAttribute('data-mine', 'false')
    expect(screen.getByRole('button', { name: /P-1 마지막 승인일/ })).toHaveAttribute('data-alert', 'true')
  })

  it('일정을_누르면_건_상세로_간다', async () => {
    fakeServer(routes())
    mount()
    await userEvent.click(await screen.findByRole('button', { name: /P-2 확정 기한/ }))
    await waitFor(() => expect(screen.getByTestId('url').textContent).toMatch(/^\/cases\/2\?as=/))
  })

  it('하회_구간이_띠로_보인다', async () => {
    fakeServer(routes())
    mount()
    const band = await screen.findByTestId('band')
    expect(within(band).getByText('현금 하회 구간 7/20~8/10')).toBeInTheDocument()
    expect(screen.getByTestId('today')).toBeInTheDocument()
  })

  it('겹치는_일정은_다른_줄로_간다', async () => {
    fakeServer(routes(EMPTY_TODO, [
      ev('2026-07-15', '알림', 'P-1 마지막 승인일', 1, []),
      ev('2026-07-15', '집행일', 'P-4 집행일', 4, []),
      ev('2026-09-30', '집행일', 'P-5 집행일', 5, []),
    ]))
    mount()
    const a = await screen.findByRole('button', { name: /P-1 마지막 승인일/ })
    const b = screen.getByRole('button', { name: /P-4 집행일/ })
    const far = screen.getByRole('button', { name: /P-5 집행일/ })
    expect(a.dataset.row).not.toBe(b.dataset.row)
    expect(far.dataset.row).toBe('0')
  })

  it('같은_날_같은_종류가_많으면_묶는다', async () => {
    fakeServer(routes(EMPTY_TODO, [1, 2, 3].map((n) => ev('2026-07-16', '확정 기한', `P-${n} 확정 기한`, n, []))))
    mount()
    expect(await screen.findByRole('button', { name: /확정 기한 3건/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /P-1 확정 기한/ })).toBeNull()
  })

  it('좁은_화면에서는_날짜_목록', async () => {
    narrow(true)
    fakeServer(routes())
    mount()
    const list = await screen.findByRole('list', { name: '날짜 목록' })
    expect(within(list).getByRole('button', { name: /P-1 확정 기한/ })).toBeInTheDocument()
    expect(within(list).queryByRole('button', { name: /지난 집행일/ })).toBeNull()
    expect(screen.queryByTestId('today')).toBeNull()
    expect(screen.getByTestId('band')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '지난 일정 보기' }))
    expect(within(list).getByRole('button', { name: /지난 집행일/ })).toBeInTheDocument()
  })

  it('기준일이_바뀌면_다시_읽는다', async () => {
    const { calls } = fakeServer({
      ...routes(),
      'POST /api/clock': { json: { date: '2026-07-13', mode: '시연', actions: [] } },
    })
    mount()
    await screen.findByRole('button', { name: /P-1 확정 기한/ })
    const count = (path: string) => calls.filter((c) => c.method === 'GET' && c.path === path).length
    expect(count(TODO_PATH)).toBe(1)
    await userEvent.click(screen.getByRole('button', { name: '다음 날로' }))
    await waitFor(() => expect(count(TODO_PATH)).toBe(2))
    expect(count('/api/calendar')).toBe(2)
  })

  it('불러오지_못하면_칸에_다시_시도가_보인다', async () => {
    let fail = true
    fakeServer({
      ...routes(),
      ['GET ' + TODO_PATH]: () => (fail ? { status: 500, json: { detail: '내부 오류' } } : { json: { ...EMPTY_TODO, '승인 대기': [item(1, 'P-1')] } }),
    })
    mount()
    expect(await screen.findAllByText('불러오지 못했어요')).not.toHaveLength(0)
    fail = false
    await userEvent.click(screen.getAllByRole('button', { name: '다시 시도' })[0])
    expect(await screen.findByRole('heading', { name: '승인 대기' })).toBeInTheDocument()
  })
})
