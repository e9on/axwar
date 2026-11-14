import { describe, it, expect, afterEach, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import App from './App'
import { fakeServer } from './test/fakeServer'

const PEOPLE = [{ name: 'Masil 대표', role: 'Masil 대표' }]

const EVENTS = [
  { id: 1, ts: '2026-11-13T05:06:55+00:00', sim_date: '2026-07-01', case_id: null, kind: '초기화', actor: '시연', detail: {} },
  { id: 2, ts: '2026-11-13T05:06:56+00:00', sim_date: '2026-07-01', case_id: 3, kind: '상태변경', actor: '시스템', detail: { from: '기안', to: '회신 대기', note: '물류 회신 요청' } },
  { id: 3, ts: '2026-11-13T05:06:57+00:00', sim_date: '2026-07-02', case_id: 4, kind: '상태변경', actor: 'Masil 대표', detail: { from: '승인 대기', to: '1차 집행' } },
  { id: 4, ts: '2026-11-13T05:06:58+00:00', sim_date: '2026-07-02', case_id: 4, kind: '작업생성', actor: '시스템', detail: { dept: '물류', title: '물류 출고' } },
]

const ASSUMPTIONS = [
  { key: 'deadline.early_warning_days', value: 5, source: '가정: 원본에 없음. 기한 5일 전부터 알림', description: '조기 경고 시작일', overridden: false, file_value: 5, effective_source: '가정: 원본에 없음. 기한 5일 전부터 알림' },
  { key: 'split.stop_z', value: 2, source: '가정: 통계 중단 기준', description: '통계 중단 기준', overridden: true, file_value: 3, effective_source: '설정 화면 변경: Masil 대표' },
  { key: 'approval.item_limit_krw', value: 1000, source: 'approval_authority_policy.md', description: '건별 한도', overridden: false, file_value: 1000, effective_source: 'approval_authority_policy.md' },
]

const USAGE = {
  mode: 'fake', spent_usd: 0.0123, spent_today_usd: 0.001, total_cap_usd: 1.0, daily_cap_usd: 0.3, pending_reservations: [], calls_total: 1, by_kind: {},
  calls: [{ id: 1, ts: '2026-11-13T05:10:00+00:00', day: '2026-11-13', case_id: 3, kind: '회신해석', model: 'fake-model', in_tok: 120, out_tok: 30, usd: 0.0012, confidence: 0.85, summary: '물류 회신: 전량 가능', state: '정산' }],
}

function mount(events = EVENTS) {
  fakeServer({
    'GET /api/people': { json: PEOPLE },
    'GET /api/clock': { json: { date: '2026-07-01', mode: '시연' } },
    'GET /api/events': { json: events },
    'GET /api/assumptions': { json: ASSUMPTIONS },
    'GET /api/ai/usage': { json: USAGE },
  })
  render(
    <MemoryRouter initialEntries={['/log?as=' + encodeURIComponent('Masil 대표')]}>
      <App />
    </MemoryRouter>,
  )
}

afterEach(() => vi.unstubAllGlobals())

describe('처리 기록·가정 목록', () => {
  it('기록이_길면_처음_몇_줄만_보이고_더_보기로_늘린다', async () => {
    const many = Array.from({ length: 45 }, (_, i) => ({ id: 100 + i, ts: '2026-11-13T05:06:55+00:00', sim_date: '2026-07-01', case_id: null, kind: '초기화', actor: '시연', detail: {} }))
    mount(many)
    const list = await screen.findByRole('list', { name: '처리 기록' })
    expect(within(list).getAllByRole('listitem')).toHaveLength(20)
    await userEvent.click(screen.getByRole('button', { name: '더 보기' }))
    expect(within(screen.getByRole('list', { name: '처리 기록' })).getAllByRole('listitem')).toHaveLength(40)
    await userEvent.click(screen.getByRole('button', { name: '더 보기' }))
    expect(within(screen.getByRole('list', { name: '처리 기록' })).getAllByRole('listitem')).toHaveLength(45)
    expect(screen.queryByRole('button', { name: '더 보기' })).toBeNull()
  })

  it('처리_기록_거르기', async () => {
    mount()
    const list = await screen.findByRole('list', { name: '처리 기록' })
    expect(within(list).getAllByRole('listitem')).toHaveLength(4)
    // 이전/이후 상태와 건 링크
    const moved = within(list).getAllByRole('listitem').find((li) => li.textContent?.includes('회신 대기')) as HTMLElement
    expect(moved).toHaveTextContent('기안에서 회신 대기로')
    expect(moved).toHaveTextContent('시스템')
    expect(within(moved).getByRole('link', { name: /건 #3/ })).toHaveAttribute('href', expect.stringContaining('/cases/3'))

    await userEvent.selectOptions(screen.getByLabelText('종류로 거르기'), '상태변경')
    expect(within(screen.getByRole('list', { name: '처리 기록' })).getAllByRole('listitem')).toHaveLength(2)

    await userEvent.selectOptions(screen.getByLabelText('건으로 거르기'), '4')
    const rows = within(screen.getByRole('list', { name: '처리 기록' })).getAllByRole('listitem')
    expect(rows).toHaveLength(1)
    expect(rows[0]).toHaveTextContent('승인 대기에서 1차 집행으로')

    await userEvent.selectOptions(screen.getByLabelText('종류로 거르기'), '')
    await userEvent.selectOptions(screen.getByLabelText('건으로 거르기'), '')
    expect(within(screen.getByRole('list', { name: '처리 기록' })).getAllByRole('listitem')).toHaveLength(4)
  })

  it('거른_결과가_없으면_빈_상태', async () => {
    mount()
    await screen.findByRole('list', { name: '처리 기록' })
    await userEvent.selectOptions(screen.getByLabelText('종류로 거르기'), '초기화')
    await userEvent.selectOptions(screen.getByLabelText('건으로 거르기'), '4')
    expect(screen.getByText('조건에 맞는 기록이 없어요')).toBeInTheDocument()
  })

  it('가정_목록이_보인다', async () => {
    mount()
    await userEvent.click(await screen.findByRole('button', { name: '가정 목록' }))
    const list = await screen.findByRole('list', { name: '가정 목록' })
    const rows = within(list).getAllByRole('listitem')
    expect(rows).toHaveLength(3)
    expect(rows[0]).toHaveTextContent('1')
    expect(rows[0]).toHaveTextContent('조기 경고 시작일')
    expect(rows[0]).toHaveTextContent('가정')
    expect(rows[0]).toHaveTextContent('기한 5일 전부터 알림')
    // 값을 설정에서 바꾼 항목은 바뀐 것을 보인다
    expect(rows[1]).toHaveTextContent('기본값 3')

    await userEvent.type(screen.getByLabelText('가정 검색'), '통계')
    expect(within(screen.getByRole('list', { name: '가정 목록' })).getAllByRole('listitem')).toHaveLength(1)
    await userEvent.clear(screen.getByLabelText('가정 검색'))
    await userEvent.type(screen.getByLabelText('가정 검색'), '없는말')
    expect(screen.getByText('찾는 가정이 없어요')).toBeInTheDocument()
  })

  it('AI_호출_내역', async () => {
    mount()
    await userEvent.click(await screen.findByRole('button', { name: 'AI 호출 내역' }))
    const list = await screen.findByRole('list', { name: 'AI 호출 내역' })
    const row = within(list).getByRole('listitem')
    expect(row).toHaveTextContent('fake-model')
    expect(row).toHaveTextContent('85%')
    expect(row).toHaveTextContent('$0.0012')
    expect(row).toHaveTextContent('120')
    expect(row).toHaveTextContent('건 #3')
    expect(screen.getByText(/\$0\.0123/)).toBeInTheDocument()
  })

  it('기록을_못_읽으면_다시_시도', async () => {
    fakeServer({
      'GET /api/people': { json: PEOPLE },
      'GET /api/clock': { json: { date: '2026-07-01', mode: '시연' } },
      'GET /api/events': { status: 500, json: { detail: '기록 고장' } },
    })
    render(
      <MemoryRouter initialEntries={['/log']}>
        <App />
      </MemoryRouter>,
    )
    expect((await screen.findAllByText(/기록 고장/)).length).toBeGreaterThan(0)
    expect(screen.getByRole('button', { name: '다시 시도' })).toBeInTheDocument()
  })
})
