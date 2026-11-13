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

const ROWS = [
  { key: 'deadline.early_warning_days', value: 5, source: '가정: 원본에 없음', description: '조기 경고 시작일', overridden: false, file_value: 5, effective_source: '가정: 원본에 없음' },
  { key: 'approval.item_limit_krw', value: 1000, source: 'approval_authority_policy.md 캠페인', description: '건별 한도', overridden: false, file_value: 1000, effective_source: 'approval_authority_policy.md 캠페인' },
  { key: 'roles.campaign', value: '캠페인 담당', source: '가정: 역할 이름', description: '캠페인 담당 역할', overridden: true, file_value: '캠페인', effective_source: '설정 화면 변경: Masil 대표' },
]
const HISTORY = [
  { id: 1, key: 'roles.campaign', before: '캠페인', after: '캠페인 담당', actor: 'Masil 대표', at: '2026-11-12T01:02:03+00:00', reason: '조직 이름이 바뀜' },
  { id: 2, key: 'deadline.early_warning_days', before: 4, after: 5, actor: '그룹 CEO', at: '2026-11-13T04:05:06+00:00', reason: '' },
]

function mount(extra: Record<string, never> = {}, as = 'Masil 대표') {
  const server = fakeServer({
    'GET /api/people': { json: PEOPLE },
    'GET /api/clock': { json: { date: '2026-07-01', mode: '시연' } },
    'GET /api/policy': { json: ROWS },
    'GET /api/policy/history': { json: HISTORY },
    ...extra,
  })
  render(
    <MemoryRouter initialEntries={['/policy?as=' + encodeURIComponent(as)]}>
      <App />
    </MemoryRouter>,
  )
  return server
}

afterEach(() => vi.unstubAllGlobals())

describe('정책 설정', () => {
  it('항목_값_출처와_가정_배지가_보인다', async () => {
    mount()
    const list = await screen.findByRole('list', { name: '정책 항목' })
    const rows = within(list).getAllByRole('listitem')
    expect(rows).toHaveLength(3)
    expect(rows[0]).toHaveTextContent('deadline.early_warning_days')
    expect(rows[0]).toHaveTextContent('조기 경고 시작일')
    expect(rows[0]).toHaveTextContent('5')
    expect(rows[0]).toHaveTextContent('가정')
    expect(rows[1]).not.toHaveTextContent('가정')
    expect(rows[1]).toHaveTextContent('approval_authority_policy.md')
    expect(rows[2]).toHaveTextContent('설정 화면 변경: Masil 대표')
    expect(rows[2]).toHaveTextContent('기본값 캠페인')
    await userEvent.type(screen.getByLabelText('정책 검색'), '한도')
    expect(within(screen.getByRole('list', { name: '정책 항목' })).getAllByRole('listitem')).toHaveLength(1)
  })

  it('정책_변경은_이유가_있어야_보낸다', async () => {
    const { calls } = mount({
      'PUT /api/policy/deadline.early_warning_days': { json: { ...ROWS[0], value: 6, overridden: true } },
    } as never)
    await userEvent.click(await screen.findByRole('button', { name: 'deadline.early_warning_days 고치기' }))
    const dlg = await screen.findByRole('dialog')
    const send = within(dlg).getByRole('button', { name: '바꾸기' })
    const value = within(dlg).getByLabelText('새 값')
    await userEvent.clear(value)
    await userEvent.type(value, '6')
    expect(send).toBeDisabled() // 이유가 없으면 못 보낸다
    await userEvent.type(within(dlg).getByLabelText('바꾸는 이유'), '  ')
    expect(send).toBeDisabled() // 공백만으로는 이유가 아니다
    await userEvent.type(within(dlg).getByLabelText('바꾸는 이유'), '경고를 하루 일찍 받고 싶음')
    expect(send).toBeEnabled()
    await userEvent.click(send)
    await waitFor(() =>
      expect(calls).toContainEqual({
        method: 'PUT',
        path: '/api/policy/deadline.early_warning_days',
        body: { actor: 'Masil 대표', value: 6, reason: '경고를 하루 일찍 받고 싶음' },
      }),
    )
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    // 보낸 뒤 목록과 이력을 다시 읽는다
    expect(calls.filter((c) => c.path === '/api/policy' && c.method === 'GET').length).toBeGreaterThanOrEqual(2)
    expect(calls.filter((c) => c.path === '/api/policy/history').length).toBeGreaterThanOrEqual(2)
  })

  it('글자_값은_글자로_보낸다', async () => {
    const { calls } = mount({ 'PUT /api/policy/roles.campaign': { json: ROWS[2] } } as never)
    await userEvent.click(await screen.findByRole('button', { name: 'roles.campaign 고치기' }))
    const dlg = await screen.findByRole('dialog')
    await userEvent.clear(within(dlg).getByLabelText('새 값'))
    await userEvent.type(within(dlg).getByLabelText('새 값'), '홍보 담당')
    await userEvent.type(within(dlg).getByLabelText('바꾸는 이유'), '이름 변경')
    await userEvent.click(within(dlg).getByRole('button', { name: '바꾸기' }))
    await waitFor(() =>
      expect(calls).toContainEqual({ method: 'PUT', path: '/api/policy/roles.campaign', body: { actor: 'Masil 대표', value: '홍보 담당', reason: '이름 변경' } }),
    )
  })

  it('권한이_없으면_서버_문장을_창_안에_보이고_닫지_않는다', async () => {
    mount(
      {
        'PUT /api/policy/deadline.early_warning_days': { status: 409, json: { detail: '마케팅팀장(마케팅팀)는 정책을(를) 바꿀 수 없음 — Masil 대표·CEO만' } },
      } as never,
      '마케팅팀장',
    )
    await userEvent.click(await screen.findByRole('button', { name: 'deadline.early_warning_days 고치기' }))
    const dlg = await screen.findByRole('dialog')
    await userEvent.clear(within(dlg).getByLabelText('새 값'))
    await userEvent.type(within(dlg).getByLabelText('새 값'), '9')
    await userEvent.type(within(dlg).getByLabelText('바꾸는 이유'), '해 보기')
    await userEvent.click(within(dlg).getByRole('button', { name: '바꾸기' }))
    expect(await within(dlg).findByText(/바꿀 수 없음 — Masil 대표·CEO만/)).toBeInTheDocument()
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(within(dlg).getByRole('button', { name: '바꾸기' })).toBeEnabled() // 고쳐서 다시 보낼 수 있다
  })

  it('값을_안_바꾸면_못_보낸다', async () => {
    mount()
    await userEvent.click(await screen.findByRole('button', { name: 'deadline.early_warning_days 고치기' }))
    const dlg = await screen.findByRole('dialog')
    await userEvent.type(within(dlg).getByLabelText('바꾸는 이유'), '이유')
    expect(within(dlg).getByRole('button', { name: '바꾸기' })).toBeDisabled()
    await userEvent.click(within(dlg).getByRole('button', { name: '취소' }))
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('정책_변경_이력', async () => {
    mount()
    const hist = await screen.findByRole('list', { name: '변경 이력' })
    const rows = within(hist).getAllByRole('listitem')
    expect(rows).toHaveLength(2)
    // 최신이 위
    expect(rows[0]).toHaveTextContent('deadline.early_warning_days')
    expect(rows[0]).toHaveTextContent('그룹 CEO')
    expect(rows[0]).toHaveTextContent('4 → 5')
    expect(rows[0]).toHaveTextContent('이유 없음')
    expect(rows[1]).toHaveTextContent('Masil 대표')
    expect(rows[1]).toHaveTextContent('캠페인 → 캠페인 담당')
    expect(rows[1]).toHaveTextContent('조직 이름이 바뀜')
  })

  it('바뀐_적_없으면_이력_빈_상태', async () => {
    mount({ 'GET /api/policy/history': { json: [] } } as never)
    expect(await screen.findByText('바뀐 적이 없어요')).toBeInTheDocument()
  })

  it('정책을_못_읽으면_다시_시도', async () => {
    mount({ 'GET /api/policy': { status: 500, json: { detail: '정책 고장' } } } as never)
    expect((await screen.findAllByText(/정책 고장/)).length).toBeGreaterThan(0)
    expect(screen.getAllByRole('button', { name: '다시 시도' }).length).toBeGreaterThan(0)
  })
})
