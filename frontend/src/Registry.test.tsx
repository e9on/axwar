import { describe, it, expect, afterEach, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import App from './App'
import { fakeServer } from './test/fakeServer'

const PEOPLE = [
  { name: '캠페인 담당자', role: '캠페인 담당' },
  { name: '계약 담당자', role: '계약 담당' },
]

const PLANS = [
  { id: 1, plan_id: 'PLAN-019', campaign_id: 'CMP-0005', influencer_id: 'INF-002', channel: '자사몰', requested_budget_krw: 4800000, expected_gmv_krw: 50000000, settlement_date: '2026-09-14', contract_deadline: '2026-09-11', source_file: 'a.csv', raw: {}, origin: '가져오기' },
  { id: 2, plan_id: 'DEMO-PLAN-001', campaign_id: null, influencer_id: null, channel: null, requested_budget_krw: 8000000, expected_gmv_krw: null, settlement_date: '2026-09-14', contract_deadline: '2026-09-11', source_file: '', raw: {}, origin: '시연' },
]
const CONTRACTS = [
  { id: 1, influencer_code: 'INF-001', influencer_name: '혜인', annual_fixed_krw: 2800000, performance_fee_text: '성과 피', notice_deadline: '2026-07-17', expiry_date: '2026-08-31', auto_renew: true, source_doc: 'x.md', origin: '화면' },
]

function mount(extra: Record<string, unknown> = {}) {
  const server = fakeServer({
    'GET /api/people': { json: PEOPLE },
    'GET /api/clock': { json: { date: '2026-07-01', mode: '시연' } },
    'GET /api/plans': { json: PLANS },
    'GET /api/contracts': { json: CONTRACTS },
    ...(extra as Record<string, never>),
  })
  render(
    <MemoryRouter initialEntries={['/registry?as=' + encodeURIComponent('캠페인 담당자')]}>
      <App />
    </MemoryRouter>,
  )
  return server
}

afterEach(() => vi.unstubAllGlobals())

describe('기안·계약 등록', () => {
  it('목록에_출처가_보인다', async () => {
    mount()
    const plans = await screen.findByRole('list', { name: '기안 목록' })
    const rows = within(plans).getAllByRole('listitem')
    expect(rows).toHaveLength(2)
    expect(rows[0]).toHaveTextContent('PLAN-019')
    expect(rows[0]).toHaveTextContent('원본')
    expect(rows[1]).toHaveTextContent('시연')
    const contracts = await screen.findByRole('list', { name: '계약 목록' })
    const c = within(contracts).getByRole('listitem')
    expect(c).toHaveTextContent('INF-001')
    expect(c).toHaveTextContent('혜인')
    expect(c).toHaveTextContent('화면 등록')
  })

  it('기안_등록_폼_보내기와_서버_오류', async () => {
    let n = 0
    const { calls } = mount({
      'POST /api/plans': () => (++n === 1 ? { status: 422, json: { detail: 'requested_budget_krw는 정수여야 함: abc' } } : { status: 201, json: { plan_id: 'PLAN-900', case_id: 9, open_error: null } }),
    })
    await userEvent.click(await screen.findByRole('button', { name: '새 기안' }))
    const dlg = await screen.findByRole('dialog', { name: '새 기안 등록' })
    const send = within(dlg).getByRole('button', { name: '등록' })
    expect(send).toBeDisabled() // 기안 번호가 없으면 못 보낸다
    await userEvent.type(within(dlg).getByLabelText(/기안 번호/), 'PLAN-900')
    await userEvent.type(within(dlg).getByLabelText(/요청액/), '4000000')
    await userEvent.type(within(dlg).getByLabelText(/정산일/), '2026-09-14')
    await userEvent.type(within(dlg).getByLabelText(/계약 확정 기한/), '2026-09-11')
    expect(send).toBeEnabled()
    await userEvent.click(send)
    await waitFor(() =>
      expect(calls).toContainEqual({
        method: 'POST',
        path: '/api/plans',
        body: { actor: '캠페인 담당자', open_case: true, fields: { plan_id: 'PLAN-900', requested_budget_krw: 4000000, settlement_date: '2026-09-14', contract_deadline: '2026-09-11' } },
      }),
    )
    // 서버 오류 문장을 그대로 보이고 창은 열려 있다
    expect(await within(dlg).findByText(/정수여야 함/)).toBeInTheDocument()
    expect(screen.getByRole('dialog', { name: '새 기안 등록' })).toBeInTheDocument()
    // 고쳐서 다시 보내면 등록되고 건 링크가 나온다
    await userEvent.click(within(dlg).getByRole('button', { name: '등록' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    const done = await screen.findByRole('status')
    expect(done).toHaveTextContent('PLAN-900')
    expect(within(done).getByRole('link', { name: /건 #9/ })).toHaveAttribute('href', expect.stringContaining('/cases/9'))
    expect(calls.filter((c) => c.path === '/api/plans' && c.method === 'GET').length).toBeGreaterThanOrEqual(2)
  })

  it('건을_열지_못해도_등록은_됐다고_알린다', async () => {
    mount({ 'POST /api/plans': { status: 201, json: { plan_id: 'PLAN-901', case_id: null, open_error: '기안 PLAN-901에 비어 있는 항목: [settlement_date]' } } })
    await userEvent.click(await screen.findByRole('button', { name: '새 기안' }))
    const dlg = await screen.findByRole('dialog')
    await userEvent.type(within(dlg).getByLabelText(/기안 번호/), 'PLAN-901')
    await userEvent.click(within(dlg).getByRole('button', { name: '등록' }))
    const done = await screen.findByRole('status')
    expect(done).toHaveTextContent('등록은 됐지만 건은 열지 못했어요')
    expect(done).toHaveTextContent('비어 있는 항목')
  })

  it('계약_등록_폼', async () => {
    const { calls } = mount({ 'POST /api/contracts': { status: 201, json: { contract_id: 2, influencer_code: 'INF-009', case_id: 11, open_error: null } } })
    await userEvent.click(await screen.findByRole('button', { name: '새 계약' }))
    const dlg = await screen.findByRole('dialog', { name: '새 계약 등록' })
    const send = within(dlg).getByRole('button', { name: '등록' })
    expect(send).toBeDisabled()
    await userEvent.type(within(dlg).getByLabelText(/인플루언서 코드/), 'INF-009')
    await userEvent.type(within(dlg).getByLabelText(/이름/), '민서')
    await userEvent.type(within(dlg).getByLabelText(/연 고정비/), '3000000')
    await userEvent.type(within(dlg).getByLabelText(/통보 기한/), '2026-10-01')
    await userEvent.type(within(dlg).getByLabelText(/만료일/), '2026-12-31')
    await userEvent.click(within(dlg).getByLabelText('자동 갱신'))
    await userEvent.click(send)
    await waitFor(() =>
      expect(calls).toContainEqual({
        method: 'POST',
        path: '/api/contracts',
        body: {
          actor: '캠페인 담당자',
          open_case: true,
          fields: { influencer_code: 'INF-009', influencer_name: '민서', annual_fixed_krw: 3000000, notice_deadline: '2026-10-01', expiry_date: '2026-12-31', auto_renew: true },
        },
      }),
    )
    expect(await screen.findByRole('link', { name: /건 #11/ })).toBeInTheDocument()
  })

  it('수정은_바뀐_항목만_보낸다', async () => {
    const { calls } = mount({ 'PUT /api/plans/DEMO-PLAN-001': { json: { plan_id: 'DEMO-PLAN-001', actions: [] } } })
    const rows = within(await screen.findByRole('list', { name: '기안 목록' })).getAllByRole('listitem')
    await userEvent.click(within(rows[1]).getByRole('button', { name: '수정' }))
    const dlg = await screen.findByRole('dialog', { name: 'DEMO-PLAN-001 수정' })
    expect(within(dlg).getByRole('button', { name: '고치기' })).toBeDisabled() // 바뀐 게 없음
    expect(within(dlg).getByLabelText(/기안 번호/)).toBeDisabled() // 식별 항목은 못 고침
    const budget = within(dlg).getByLabelText(/요청액/)
    await userEvent.clear(budget)
    await userEvent.type(budget, '9000000')
    await userEvent.click(within(dlg).getByRole('button', { name: '고치기' }))
    await waitFor(() =>
      expect(calls).toContainEqual({ method: 'PUT', path: '/api/plans/DEMO-PLAN-001', body: { actor: '캠페인 담당자', fields: { requested_budget_krw: 9000000 } } }),
    )
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  })

  it('건_열기', async () => {
    const { calls } = mount({
      'POST /api/plans/PLAN-019/open': { json: { plan_id: 'PLAN-019', case_id: 5 } },
      'POST /api/contracts/INF-001/open': { json: { influencer_code: 'INF-001', case_id: 6 } },
    })
    const rows = within(await screen.findByRole('list', { name: '기안 목록' })).getAllByRole('listitem')
    await userEvent.click(within(rows[0]).getByRole('button', { name: '건 열기' }))
    await waitFor(() => expect(calls).toContainEqual({ method: 'POST', path: '/api/plans/PLAN-019/open', body: { actor: '캠페인 담당자' } }))
    expect(await screen.findByRole('link', { name: /건 #5/ })).toHaveAttribute('href', expect.stringContaining('/cases/5'))

    const crow = within(await screen.findByRole('list', { name: '계약 목록' })).getByRole('listitem')
    await userEvent.click(within(crow).getByRole('button', { name: '건 열기' }))
    await waitFor(() => expect(calls).toContainEqual({ method: 'POST', path: '/api/contracts/INF-001/open', body: { actor: '캠페인 담당자' } }))
    expect(await screen.findByRole('link', { name: /건 #6/ })).toBeInTheDocument()
  })

  it('건_열기_거부는_서버_문장', async () => {
    mount({ 'POST /api/plans/PLAN-019/open': { status: 409, json: { detail: '등록부를 바꿀 수 없음 — 캠페인 담당만' } } })
    const rows = within(await screen.findByRole('list', { name: '기안 목록' })).getAllByRole('listitem')
    await userEvent.click(within(rows[0]).getByRole('button', { name: '건 열기' }))
    expect((await screen.findAllByText(/등록부를 바꿀 수 없음/)).length).toBeGreaterThan(0)
    expect(within(rows[0]).getByRole('button', { name: '건 열기' })).toBeEnabled()
  })

  it('가져오기와_원본_다시_맞추기', async () => {
    const { calls } = mount({
      'POST /api/import/plans': { json: { added: 24, updated: 1, unchanged: 0, skipped: [{ plan_id: 'PLAN-001', reason: '화면에서 고친 기안이라 덮어쓰지 않음', source_changed: ['requested_budget_krw'] }], warnings: ['경고 문장'], actions: [] } },
      'POST /api/import/contracts': { json: { count: 1, contract_ids: [1], actions: [] } },
      'POST /api/sync': { json: { actions: [{ date: '2026-07-01', case_id: 1, action: '재판정', text: '다시 맞춤' }] } },
    })
    await userEvent.click(await screen.findByRole('button', { name: '기안 원본 가져오기' }))
    await waitFor(() => expect(calls).toContainEqual({ method: 'POST', path: '/api/import/plans', body: { actor: '캠페인 담당자' } }))
    const r = await screen.findByRole('status')
    expect(r).toHaveTextContent('새로 24건')
    expect(r).toHaveTextContent('갱신 1건')
    expect(r).toHaveTextContent('PLAN-001')
    expect(r).toHaveTextContent('덮어쓰지 않음')
    expect(r).toHaveTextContent('경고 문장')

    await userEvent.click(screen.getByRole('button', { name: '계약 통보 가져오기' }))
    await waitFor(() => expect(calls).toContainEqual({ method: 'POST', path: '/api/import/contracts', body: { actor: '캠페인 담당자' } }))
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('계약 통보 1건'))

    await userEvent.click(screen.getByRole('button', { name: '원본 다시 맞추기' }))
    await waitFor(() => expect(calls).toContainEqual({ method: 'POST', path: '/api/sync', body: { actor: '캠페인 담당자' } }))
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('다시 맞춤'))
  })

  it('목록_실패는_다시_시도', async () => {
    mount({ 'GET /api/plans': { status: 500, json: { detail: '기안 고장' } } })
    expect((await screen.findAllByText(/기안 고장/)).length).toBeGreaterThan(0)
    expect(screen.getAllByRole('button', { name: '다시 시도' }).length).toBeGreaterThan(0)
  })

  it('빈_목록', async () => {
    mount({ 'GET /api/plans': { json: [] }, 'GET /api/contracts': { json: [] } })
    expect(await screen.findByText('등록된 기안이 없어요')).toBeInTheDocument()
    expect(screen.getByText('등록된 계약이 없어요')).toBeInTheDocument()
  })
})
