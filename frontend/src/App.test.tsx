import { describe, it, expect, afterEach, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, useLocation } from 'react-router-dom'
import App from './App'
import { fakeServer, permissionsReply, PERMISSIONS_ROUTE } from './test/fakeServer'

const PEOPLE = [
  { name: '그룹 CEO', role: '그룹 CEO' },
  { name: 'Masil 대표', role: 'Masil 대표' },
  { name: '마케팅팀장', role: '마케팅팀장' },
]

function Probe() {
  const loc = useLocation()
  return <output data-testid="url">{loc.pathname + loc.search}</output>
}

function mount(url: string) {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <App />
      <Probe />
    </MemoryRouter>,
  )
}

afterEach(() => vi.unstubAllGlobals())

describe('화면 골격', () => {
  it('서비스_이름은_Approval_Planner', async () => {
    fakeServer({
      'GET /api/people': { json: PEOPLE },
      'GET /api/clock': { json: { date: '2026-07-12', mode: '시연' } },
    })
    mount('/')
    expect(await screen.findByText('Approval Planner')).toBeTruthy()
  })

  it('보는_사람을_바꾸면_URL이_바뀐다', async () => {
    fakeServer({
      'GET /api/people': { json: PEOPLE },
      'GET /api/clock': { json: { date: '2026-07-12', mode: '시연' } },
    })
    mount('/')
    const select = await screen.findByLabelText('보는 사람')
    await userEvent.selectOptions(select, 'Masil 대표')
    await waitFor(() => expect(screen.getByTestId('url').textContent).toBe('/?as=Masil+%EB%8C%80%ED%91%9C'))
  })

  it('URL의_as로_보는_사람이_정해진다', async () => {
    fakeServer({
      'GET /api/people': { json: PEOPLE },
      'GET /api/clock': { json: { date: '2026-07-12', mode: '시연' } },
    })
    mount('/?as=' + encodeURIComponent('마케팅팀장'))
    const select = (await screen.findByLabelText('보는 사람')) as HTMLSelectElement
    await waitFor(() => expect(select.value).toBe('마케팅팀장'))
  })

  it('위쪽_막대는_기준일만_보이고_이동_버튼이_없다', async () => {
    fakeServer({
      'GET /api/people': { json: PEOPLE },
      'GET /api/clock': { json: { date: '2026-07-12', mode: '시연' } },
    })
    mount('/demo')
    expect((await screen.findAllByText('7월 12일')).length).toBeGreaterThan(0)
    expect(screen.queryByRole('button', { name: '다음 날로' })).toBeNull()
    expect(screen.queryByLabelText('이동할 날짜')).toBeNull()
  })

  it('운영_모드에서는_기준일_이동이_없다', async () => {
    fakeServer({
      'GET /api/people': { json: PEOPLE },
      'GET /api/clock': { json: { date: '2026-07-12', mode: '운영' } },
    })
    mount('/')
    expect(await screen.findByText('7월 12일')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '다음 날로' })).toBeNull()
    expect(screen.queryByLabelText('이동할 날짜')).toBeNull()
  })

  it('API_오류는_한국어_알림으로_보인다', async () => {
    fakeServer({
      'GET /api/people': { json: PEOPLE },
      'GET /api/clock': { status: 500, json: { detail: '기준일을 읽지 못했어요' } },
      [PERMISSIONS_ROUTE]: permissionsReply(),
      ['GET /api/todo/' + encodeURIComponent('그룹 CEO')]: { json: {} }, // 메인이 함께 부르는 길
      'GET /api/calendar': { json: [] },
    })
    mount('/')
    const alert = (await screen.findAllByRole('alert'))[0]
    expect(alert).toHaveTextContent('기준일을 읽지 못했어요')
    await userEvent.click(screen.getByRole('button', { name: '알림 닫기' }))
    expect(screen.queryByRole('alert')).toBeNull()
  })
})

const POLICY = { 'GET /api/policy': { json: [] }, 'GET /api/policy/history': { json: [] } }

describe('화면 이동과 모드 전환', () => {
  const clockOf = (mode: string) => ({ date: '2026-07-12', mode })

  it('화면_이동_링크와_지금_화면_표시', async () => {
    fakeServer({
      'GET /api/people': { json: PEOPLE },
      'GET /api/clock': { json: clockOf('시연') },
    })
    mount('/log?as=' + encodeURIComponent('마케팅팀장'))
    const nav = await screen.findByRole('navigation', { name: '화면 이동' })
    for (const name of ['메인', '회신', '기록', '정책', '등록', '시연']) {
      expect(await within(nav).findByRole('link', { name })).toBeInTheDocument()
    }
    expect(within(nav).getByRole('link', { name: '기록' })).toHaveAttribute('aria-current', 'page')
    expect(within(nav).getByRole('link', { name: '메인' })).not.toHaveAttribute('aria-current')
    // 보는 사람이 링크에 따라간다
    expect(within(nav).getByRole('link', { name: '정책' })).toHaveAttribute('href', '/policy?as=' + encodeURIComponent('마케팅팀장'))
  })

  it('접는_메뉴_버튼이_화면_이동을_여닫는다', async () => {
    fakeServer({
      'GET /api/people': { json: PEOPLE },
      'GET /api/clock': { json: clockOf('시연') },
    })
    // 휴대폰 폭으로 본다
    vi.stubGlobal('matchMedia', (query: string) => ({ matches: true, media: query, addEventListener: () => {}, removeEventListener: () => {} }))
    mount('/')
    const button = await screen.findByRole('button', { name: '메뉴' })
    expect(screen.queryByRole('link', { name: '정책' })).toBeNull() // 접혀 있다
    expect(button).toHaveAttribute('aria-expanded', 'false')
    await userEvent.click(button)
    expect(button).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('link', { name: '정책' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('link', { name: '정책' }))
    expect(button).toHaveAttribute('aria-expanded', 'false') // 이동하면 접힌다
  })

  it('운영_모드에서는_시연_링크가_없다', async () => {
    fakeServer({
      'GET /api/people': { json: PEOPLE },
      'GET /api/clock': { json: clockOf('운영') },
      ...POLICY,
    })
    mount('/policy')
    await screen.findByText(/운영 모드/)
    expect(screen.queryByRole('link', { name: '시연' })).toBeNull()
    expect(screen.getByRole('link', { name: '정책' })).toBeInTheDocument()
  })

  it('모드_전환은_확인_뒤_PUT_mode', async () => {
    let mode = '시연'
    const { calls } = fakeServer({
      'GET /api/people': { json: PEOPLE },
      'GET /api/clock': () => ({ json: clockOf(mode) }),
      [PERMISSIONS_ROUTE]: permissionsReply(),
      'PUT /api/mode': () => {
        mode = '운영'
        return { json: { mode } }
      },
    })
    mount('/policy?as=' + encodeURIComponent('Masil 대표'))
    await userEvent.click(await screen.findByRole('button', { name: '모드 전환' }))
    const dlg = await screen.findByRole('dialog')
    expect(dlg).toHaveTextContent('운영 모드로')
    await userEvent.click(within(dlg).getByRole('button', { name: '취소' }))
    expect(calls.some((c) => c.method === 'PUT')).toBe(false)

    await userEvent.click(screen.getByRole('button', { name: '모드 전환' }))
    await userEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: '운영 모드로 바꾸기' }))
    await waitFor(() => expect(calls).toContainEqual({ method: 'PUT', path: '/api/mode', body: { actor: 'Masil 대표', mode: '운영' } }))
    // 바꾼 뒤 기준일·모드를 다시 읽어 시연 링크가 사라진다
    await waitFor(() => expect(screen.queryByRole('link', { name: '시연' })).toBeNull())
    expect(screen.getByRole('region', { name: '모드' })).toHaveTextContent('운영 모드')
  })

  it('모드_전환_거부는_서버_문장을_창에_보인다', async () => {
    fakeServer({
      'GET /api/people': { json: PEOPLE },
      'GET /api/clock': { json: clockOf('시연') },
      ...POLICY,
      [PERMISSIONS_ROUTE]: permissionsReply(),
      'PUT /api/mode': { status: 409, json: { detail: '마케팅팀장(마케팅팀)는 실행 모드을(를) 바꿀 수 없음 — Masil 대표·CEO만' } },
    })
    mount('/policy?as=' + encodeURIComponent('마케팅팀장'))
    await userEvent.click(await screen.findByRole('button', { name: '모드 전환' }))
    const dlg = await screen.findByRole('dialog')
    await userEvent.click(within(dlg).getByRole('button', { name: '운영 모드로 바꾸기' }))
    expect(await within(dlg).findByText(/바꿀 수 없음/)).toBeInTheDocument()
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })

  it('모드_전환_권한이_없으면_버튼_대신_서버_이유가_보인다', async () => {
    const reason = '마케팅팀장(마케팅팀)는 실행 모드을(를) 바꿀 수 없음 — Masil 대표·CEO만'
    fakeServer({
      'GET /api/people': { json: PEOPLE },
      'GET /api/clock': { json: clockOf('시연') },
      ...POLICY,
      [PERMISSIONS_ROUTE]: permissionsReply({ mode: reason }),
    })
    mount('/policy?as=' + encodeURIComponent('마케팅팀장'))
    expect(await screen.findByText(/Masil 대표·CEO만/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '모드 전환' })).toBeNull()
  })

  it('권한을_못_읽는_동안에는_모드_전환_버튼을_보이지_않는다', async () => {
    fakeServer({
      'GET /api/people': { json: PEOPLE },
      'GET /api/clock': { json: clockOf('시연') },
      ...POLICY,
    })
    mount('/policy?as=' + encodeURIComponent('Masil 대표'))
    await screen.findByText(/시연 모드/)
    expect(screen.queryByRole('button', { name: '모드 전환' })).toBeNull()
  })
})
