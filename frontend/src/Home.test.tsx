import { describe, it, expect, afterEach, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, useLocation } from 'react-router-dom'
import App from './App'
import css from './pages/Home.css?raw'
import { DOT_PAD_PX } from './timelineLayout'
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

  it('할일_줄_이름은_서버_title이고_번호는_작게_따로_보인다', async () => {
    fakeServer(routes({
      ...EMPTY_TODO,
      '승인 대기': [item(1, 'PLAN-019', { title: '봄 선케어 캠페인 · 혜인' }), item(3, 'PLAN-020')],
      작업: [item(2, 'PLAN-021', { task_id: 5, title: '물량 입력', detail: '', due: '2026-07-14' })],
    }))
    mount()
    const named = await screen.findByRole('button', { name: /봄 선케어 캠페인 · 혜인/ })
    expect(within(named).getByText('봄 선케어 캠페인 · 혜인')).toHaveClass('name')
    expect(within(named).getByText('PLAN-019')).toHaveClass('ref')
    // title이 없으면 번호가 이름이고 같은 글을 두 번 쓰지 않는다
    const bare = screen.getByRole('button', { name: /PLAN-020/ })
    expect(within(bare).getAllByText('PLAN-020')).toHaveLength(1)
    expect(within(bare).getByText('PLAN-020')).toHaveClass('name')
    // 작업은 서버가 title에 작업 이름을 준다
    const task = screen.getByRole('button', { name: /물량 입력/ })
    expect(within(task).getByText('물량 입력')).toHaveClass('name')
    expect(within(task).getByText('PLAN-021')).toHaveClass('ref')
  })

  it('회신_대기_링크_끝에_화살표가_없다', async () => {
    fakeServer(routes({ ...EMPTY_TODO, '회신 대기': [item(4, 'P-4')] }))
    mount()
    const link = await screen.findByRole('link', { name: /회신 입력으로 가기/ })
    expect(link.textContent).not.toMatch(/→/)
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

  it('하회_구간_이름표는_표시_줄_위의_전용_줄을_쓰도록_표시된다', async () => {
    fakeServer(routes())
    mount()
    await screen.findByTestId('band')
    // 띠가 있을 때만 이름표 줄만큼 표시 시작 위치를 내린다(실제 겹침은 브라우저 e2e에서 잰다)
    expect(document.querySelector('.track-wrap')).toHaveAttribute('data-bands', 'true')
    expect(css).toMatch(/\.track-wrap\[data-bands="true"\]\s*\{[^}]*--tl-top/)
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
  it('일정_표시의_접근_이름에_날짜와_내용이_있다', async () => {
    fakeServer(routes())
    mount()
    expect(await screen.findByRole('button', { name: /7월 16일.*P-2 확정 기한/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /7월 15일.*P-1 마지막 승인일.*내 차례.*알림/ })).toBeInTheDocument()
  })

  it('눈금이_정확한_날짜_위치에_있다', async () => {
    fakeServer(routes())
    mount()
    await screen.findByRole('button', { name: /P-2 확정 기한/ })
    const ticks = screen.getAllByTestId('tick')
    const lefts = ticks.map((t) => parseFloat((t as HTMLElement).style.left))
    // 범위 7/1~9/1(62일)에서 7/16은 15일째
    expect(lefts.some((l) => Math.abs(l - (15 / 62) * 100) < 0.001)).toBe(true)
  })

  it('하회_띠의_시작과_폭이_끝날을_포함한다', async () => {
    fakeServer(routes())
    mount()
    const band = await screen.findByTestId('band')
    expect(parseFloat(band.style.left)).toBeCloseTo((19 / 62) * 100, 3)
    expect(parseFloat(band.style.width)).toBeCloseTo((22 / 62) * 100, 3)
  })

  it('기준일을_읽지_못하면_다시_시도가_보인다', async () => {
    let fail = true
    fakeServer({
      ...routes(),
      'GET /api/clock': () => (fail ? { status: 500, json: { detail: '내부 오류' } } : { json: { date: '2026-07-12', mode: '시연' } }),
    })
    mount()
    expect(await screen.findByText('기준일을 불러오지 못했어요')).toBeInTheDocument()
    fail = false
    await userEvent.click(screen.getByRole('button', { name: '기준일 다시 시도' }))
    expect(await screen.findByRole('button', { name: /P-1 확정 기한/ })).toBeInTheDocument()
  })

  it('보는_사람을_읽지_못하면_할_일_칸에_다시_시도가_보인다', async () => {
    let fail = true
    fakeServer({
      ...routes(),
      'GET /api/people': () => (fail ? { status: 500, json: { detail: '내부 오류' } } : { json: PEOPLE }),
    })
    mount()
    expect(await screen.findByText('보는 사람을 불러오지 못했어요')).toBeInTheDocument()
    fail = false
    await userEvent.click(screen.getByRole('button', { name: '보는 사람 다시 시도' }))
    expect(await screen.findByText('지금 할 일이 없어요')).toBeInTheDocument()
  })

  it('보는_사람을_바꾸면_할_일을_다시_읽는다', async () => {
    const other = '/api/todo/' + encodeURIComponent('Masil 대표')
    const { calls } = fakeServer({
      ...routes({ ...EMPTY_TODO, '승인 대기': [item(1, 'P-1')] }),
      ['GET ' + other]: { json: { ...EMPTY_TODO, 작업: [item(2, 'P-2', { title: '물량 입력', due: '2026-07-14' })] } },
    })
    mount()
    expect(await screen.findByRole('heading', { name: '승인 대기' })).toBeInTheDocument()
    await userEvent.selectOptions(screen.getByLabelText('보는 사람'), 'Masil 대표')
    expect(await screen.findByRole('heading', { name: '작업' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: '승인 대기' })).toBeNull()
    expect(calls.filter((c) => c.path === other)).toHaveLength(1)
  })

  it('마감_알림만_도장색으로_표시된다', async () => {
    fakeServer(routes({
      ...EMPTY_TODO,
      알림: [
        item(1, 'P-1', { kind: '마감 알림', stage: '1차', text: '내일 기본 거부돼요' }),
        item(2, 'P-2', { kind: '일반 알림', stage: '1차', text: '참고하세요' }),
      ],
    }))
    mount()
    expect((await screen.findByText('내일 기본 거부돼요')).dataset.seal).toBe('true')
    expect(screen.getByText('참고하세요').dataset.seal).toBe('false')
  })

  it('기준일을_바꿔도_묶음_펼침이_유지된다', async () => {
    const { calls } = fakeServer({
      ...routes(EMPTY_TODO, [1, 2, 3].map((n) => ev('2026-07-16', '확정 기한', `P-${n} 확정 기한`, n, []))),
      'POST /api/clock': { json: { date: '2026-07-13', mode: '시연', actions: [] } },
    })
    mount()
    await userEvent.click(await screen.findByRole('button', { name: /확정 기한 3건/ }))
    expect(screen.getByRole('list', { name: /목록/ })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '다음 날로' }))
    await waitFor(() => expect(calls.filter((c) => c.path === '/api/calendar')).toHaveLength(2))
    expect(screen.getByRole('list', { name: /목록/ })).toBeInTheDocument()
    expect(screen.queryByText('불러오는 중')).toBeNull()
  })

  it('긴_일정_이름은_접근_이름에_전체가_있고_폭_추정_여백이_CSS와_같은_값이다', async () => {
    const long = 'P-9 마지막 승인일 내일 기본 거부 됩니다 꼭 확인하세요'
    fakeServer(routes(EMPTY_TODO, [ev('2026-07-15', '알림', long, 9, [])]))
    mount()
    const b = await screen.findByRole('button', { name: new RegExp(long) })
    const track = b.parentElement as HTMLElement
    expect(track.style.getPropertyValue('--dot-px')).toBe(`${DOT_PAD_PX}px`)
  })

  it('오늘_이후_일정이_없으면_안내가_보인다', async () => {
    narrow(true)
    fakeServer(routes(EMPTY_TODO, [ev('2026-07-01', '집행일', '지난 집행일', 9, [])]))
    mount()
    expect(await screen.findByText('오늘 이후 일정이 없어요')).toBeInTheDocument()
  })

  it('좁은_화면_내_차례와_알림은_접근_이름에도_드러난다', async () => {
    narrow(true)
    fakeServer(routes())
    mount()
    const list = await screen.findByRole('list', { name: '날짜 목록' })
    expect(within(list).getByRole('button', { name: /P-1 마지막 승인일.*내 차례/ })).toBeInTheDocument()
  })

  it('제목_단계가_h1_h2_h3_순서다', async () => {
    fakeServer(routes({ ...EMPTY_TODO, '승인 대기': [item(1, 'P-1')] }))
    mount()
    await screen.findByRole('heading', { name: '승인 대기' })
    expect(screen.getByRole('heading', { level: 1 })).toBeInTheDocument()
    expect(screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent)).toEqual(['일정', '할 일'])
  })

  it('스타일: 초점이_잘리지_않고_지난_일정은_투명도를_쓰지_않는다', () => {
    expect(css.length).toBeGreaterThan(100)
    expect(css).not.toMatch(/\.track\s*\{[^}]*overflow:\s*hidden/)
    expect(css).not.toMatch(/data-past[^}]*opacity/)
  })
})
