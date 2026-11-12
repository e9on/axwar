import { describe, it, expect, afterEach, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, useLocation } from 'react-router-dom'
import App from './App'
import { fakeServer } from './test/fakeServer'

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

  it('기준일_이동_버튼이_POST_clock을_부른다', async () => {
    const { calls } = fakeServer({
      'GET /api/people': { json: PEOPLE },
      'GET /api/clock': { json: { date: '2026-07-12', mode: '시연' } },
      'POST /api/clock': { json: { date: '2026-07-13', mode: '시연', actions: [] } },
    })
    mount('/')
    await userEvent.click(await screen.findByRole('button', { name: '하루 뒤로' }))
    await waitFor(() =>
      expect(calls).toContainEqual({ method: 'POST', path: '/api/clock', body: { date: '2026-07-13' } }),
    )
    expect(await screen.findByText(/2026-07-13/)).toBeInTheDocument()
  })

  it('운영_모드에서는_기준일_이동이_없다', async () => {
    fakeServer({
      'GET /api/people': { json: PEOPLE },
      'GET /api/clock': { json: { date: '2026-07-12', mode: '운영' } },
    })
    mount('/')
    expect(await screen.findByText(/2026-07-12/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '하루 뒤로' })).toBeNull()
    expect(screen.queryByLabelText('이동할 날짜')).toBeNull()
  })

  it('API_오류는_한국어_알림으로_보인다', async () => {
    fakeServer({
      'GET /api/people': { json: PEOPLE },
      'GET /api/clock': { status: 500, json: { detail: '기준일을 읽지 못했어요' } },
    })
    mount('/')
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('기준일을 읽지 못했어요')
    await userEvent.click(screen.getByRole('button', { name: '알림 닫기' }))
    expect(screen.queryByRole('alert')).toBeNull()
  })
})
