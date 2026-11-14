import { describe, it, expect, afterEach, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import App from './App'
import { mountPage } from './test/pageMount'
import RepliesPage from './pages/Replies'
import { fakeServer } from './test/fakeServer'

const PEOPLE = [
  { name: '물류 담당자', role: '물류' },
  { name: '캠페인 담당자', role: '캠페인 담당' },
]
const MINE = '/api/requests?dept=' + encodeURIComponent('물류')

const row = (id: number, over: Record<string, unknown> = {}) => ({
  id, request_id: id, case_id: 7, dept: '물류', purpose: '물류 처리 능력', text: '처리량을 알려 주세요', status: '대기',
  attach_required: false, created_at: '2026-09-01', ref_id: 'DEMO-PLAN-001', case_status: '회신 대기', ...over,
})

const caseOf = (over: Record<string, unknown> = {}, requests?: unknown[]) => ({
  case: { id: 7, kind: '기안', ref_id: 'DEMO-PLAN-001', status: '회신 대기', open: true, stage: '회신 대기', origin: '시연', title: '초혜핏 선케어 캠페인' },
  facts: { phase1_date: '2026-09-14', settlement_date: '2026-09-14', deadline: '2026-09-11' },
  deadline: '2026-09-11',
  deny_date: '2026-09-08',
  approval_deadline: '2026-09-07',
  requests: requests ?? [{ id: 5, dept: '물류', purpose: '물류 처리 능력', text: '처리량을 알려 주세요', status: '대기', attach_required: false, replies: [] }],
  tasks: [],
  ...over,
})

const RESULT = {
  request_id: 5, case_id: 7, ignored: false, needs_human: false, changed: true, status: '승인 대기',
  judgment: { stance: '조건부수용', qty_limit: 3000, next_date: '2026-09-20', needs_human: false, confidence: 0.85, model: 'fake-해석기' },
}

function mount() {
  return render(
    <MemoryRouter initialEntries={['/replies?as=' + encodeURIComponent('물류 담당자')]}>
      <App />
    </MemoryRouter>,
  )
}

function base(extra: Record<string, unknown> = {}) {
  return fakeServer({
    'GET /api/people': { json: PEOPLE },
    'GET /api/clock': { json: { date: '2026-09-05', mode: '시연' } },
    [`GET ${MINE}`]: { json: [row(5)] },
    'GET /api/human-checks': { json: [] },
    'GET /api/cases/7': { json: caseOf() },
    ...(extra as Record<string, never>),
  })
}

afterEach(() => vi.unstubAllGlobals())

describe('회신 입력', () => {
  it('내_부서_요청을_상태별로_나눠_보인다', async () => {
    base({
      [`GET ${MINE}`]: { json: [row(5), row(6, { status: '사람 확인', text: '확인 필요한 문장' }), row(4, { status: '처리됨', text: '끝난 요청' })] },
    })
    mount()
    const list = await screen.findByRole('region', { name: '내 부서 요청' })
    expect(await within(list).findByRole('heading', { name: /대기/ })).toBeInTheDocument()
    expect(within(list).getByRole('heading', { name: /사람 확인/ })).toBeInTheDocument()
    expect(within(list).getByRole('heading', { name: /완료/ })).toBeInTheDocument()
    expect(within(list).getByText('끝난 요청')).toBeInTheDocument()
  })

  it('요청이_없으면_빈_상태', async () => {
    base({ [`GET ${MINE}`]: { json: [] } })
    mount()
    expect(await screen.findByText(/우리 부서에 온 요청이 없어요/)).toBeInTheDocument()
  })

  it('목록_실패는_다시_시도', async () => {
    base({ [`GET ${MINE}`]: { status: 500, json: { detail: '서버 고장' } } })
    mount()
    expect((await screen.findAllByText(/서버 고장/)).length).toBeGreaterThan(0)
    expect(screen.getByRole('button', { name: '다시 시도' })).toBeInTheDocument()
  })

  it('회신을_저장하면_AI_해석과_바뀐_상태가_보인다', async () => {
    let saved = false
    const { calls } = base({
      'GET /api/cases/7': () => ({
        json: saved
          ? caseOf({ case: { id: 7, kind: '기안', ref_id: 'DEMO-PLAN-001', status: '승인 대기', open: true, stage: '1차 승인 대기', origin: '시연' }, facts: { phase1_date: '2026-09-15', deadline: '2026-09-11' }, tasks: [{ id: 1, dept: '캠페인 담당', title: '물량 입력', due: '2026-09-06', status: '대기', detail: '' }] })
          : caseOf(),
      }),
      'POST /api/requests/5/reply': () => {
        saved = true
        return { json: RESULT }
      },
    })
    mount()
    await userEvent.click(await screen.findByRole('button', { name: /DEMO-PLAN-001/ }))
    // 요청 문장·기한·건 상세 링크
    expect(await screen.findByText('처리량을 알려 주세요', { selector: '.ask' })).toBeInTheDocument()
    expect(screen.getByText(/9월 11일/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /건 상세/ })).toHaveAttribute('href', '/cases/7?as=' + encodeURIComponent('물류 담당자'))

    await userEvent.type(screen.getByLabelText('회신 내용'), '3,000개까지 가능합니다')
    await userEvent.click(screen.getByRole('button', { name: '회신 저장' }))

    const result = await screen.findByRole('region', { name: '저장 결과' })
    const r = within(result)
    expect(r.getByText('조건부수용')).toBeInTheDocument()
    expect(r.getByText('3,000개')).toBeInTheDocument()
    expect(r.getByText('9월 20일')).toBeInTheDocument()
    expect(r.getByText('85%')).toBeInTheDocument()
    expect(r.getByText('fake-해석기')).toBeInTheDocument()
    expect(r.getByText(/사람 확인 필요/)).toBeInTheDocument()
    expect(r.getByText('아니오')).toBeInTheDocument()
    // 바뀐 상태: 건 상태, 새 작업, 집행일 변경
    await waitFor(() => expect(r.getByText(/회신 대기에서 승인 대기로/)).toBeInTheDocument())
    expect(r.getByText(/물량 입력/)).toBeInTheDocument()
    expect(r.getByText(/9월 14일에서 9월 15일로/)).toBeInTheDocument()
    const post = calls.find((c) => c.method === 'POST')
    expect(post?.path).toBe('/api/requests/5/reply')
    expect(post?.body).toEqual({ actor: '물류 담당자', text: '3,000개까지 가능합니다', attachments: 0 })
  })

  it('보내는_동안_저장_버튼이_잠긴다', async () => {
    let release: () => void = () => {}
    const wait = new Promise<void>((done) => (release = done))
    const { calls } = base({ 'POST /api/requests/5/reply': { json: RESULT, wait } })
    mount()
    await userEvent.click(await screen.findByRole('button', { name: /DEMO-PLAN-001/ }))
    await userEvent.type(await screen.findByLabelText('회신 내용'), '가능')
    const save = screen.getByRole('button', { name: '회신 저장' })
    await userEvent.click(save)
    await userEvent.click(save)
    expect(screen.getByRole('button', { name: /저장하는 중/ })).toBeDisabled()
    release()
    await screen.findByRole('region', { name: '저장 결과' })
    expect(calls.filter((c) => c.method === 'POST')).toHaveLength(1)
  })

  it('내용이_비면_저장할_수_없다', async () => {
    base()
    mount()
    await userEvent.click(await screen.findByRole('button', { name: /DEMO-PLAN-001/ }))
    expect(await screen.findByRole('button', { name: '회신 저장' })).toBeDisabled()
  })

  it('필수첨부_없으면_경고', async () => {
    base({ [`GET ${MINE}`]: { json: [row(5, { attach_required: true })] } })
    mount()
    await userEvent.click(await screen.findByRole('button', { name: /DEMO-PLAN-001/ }))
    expect(await screen.findByText(/첨부가 필요한 요청이에요/)).toBeInTheDocument()
    await userEvent.clear(screen.getByLabelText('첨부 개수'))
    await userEvent.type(screen.getByLabelText('첨부 개수'), '2')
    expect(screen.queryByText(/첨부가 필요한 요청이에요/)).not.toBeInTheDocument()
  })

  it('서버가_거부하면_그_문장을_그대로_보인다', async () => {
    base({ 'POST /api/requests/5/reply': { status: 403, json: { detail: '캠페인 담당자(캠페인 담당)는 이 요청에 회신할 수 없음 — 회신 대상: 물류' } } })
    mount()
    await userEvent.click(await screen.findByRole('button', { name: /DEMO-PLAN-001/ }))
    await userEvent.type(await screen.findByLabelText('회신 내용'), '가능')
    await userEvent.click(screen.getByRole('button', { name: '회신 저장' }))
    const alerts = await screen.findAllByRole('alert')
    expect(alerts.some((a) => a.textContent?.includes('이 요청에 회신할 수 없음 — 회신 대상: 물류'))).toBe(true)
    // 실패 뒤엔 다시 보낼 수 있다
    expect(screen.getByRole('button', { name: '회신 저장' })).toBeEnabled()
  })

  it('사람_확인_칸에서_확인하면_resolve', async () => {
    const human = row(9, { dept: 'SCM', purpose: '재고 사용', text: '안전재고를 쓸 수 있나요', status: '사람 확인', case_status: '회신 대기' })
    const { calls } = base({
      'GET /api/human-checks': { json: [human] },
      'GET /api/cases/7': {
        json: caseOf({}, [
          {
            id: 9, dept: 'SCM', purpose: '재고 사용', text: '안전재고를 쓸 수 있나요', status: '사람 확인', attach_required: false,
            replies: [{ id: 3, text: '애매하게 가능', attachments: 0, created_at: '2026-09-04', judgment: { id: 4, stance: '조건부수용', qty_limit: null, next_date: null, needs_human: true, confidence: 0.4, model: 'fake-해석기', human_confirmed: false, confirmed_by: null } }],
          },
        ]),
      },
      'POST /api/requests/9/resolve': { json: { ...RESULT, request_id: 9 } },
    })
    mount()
    const box = await screen.findByRole('region', { name: '사람 확인이 필요한 회신' })
    await userEvent.click(await within(box).findByRole('button', { name: /DEMO-PLAN-001/ }))
    // 원래 회신과 AI 해석
    expect(await screen.findByText('애매하게 가능')).toBeInTheDocument()
    expect(screen.getByText(/확신도 40%/)).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('확인 내용'), '3,000개까지로 확인')
    await userEvent.click(screen.getByRole('button', { name: '확인 저장' }))
    await screen.findByRole('region', { name: '저장 결과' })
    const post = calls.find((c) => c.method === 'POST')
    expect(post?.path).toBe('/api/requests/9/resolve')
    expect(post?.body).toEqual({ actor: '물류 담당자', text: '3,000개까지로 확인', attachments: 0 })
  })

  it('권한이_없으면_서버_문장을_그대로_보인다', async () => {
    const human = row(9, { dept: 'SCM', status: '사람 확인' })
    base({
      'GET /api/human-checks': { json: [human] },
      'GET /api/cases/7': { json: caseOf({}, [{ id: 9, dept: 'SCM', purpose: '재고 사용', text: '문의', status: '사람 확인', attach_required: false, replies: [] }]) },
      'POST /api/requests/9/resolve': { status: 403, json: { detail: '물류 담당자(물류)는 이 사람 확인을 처리할 수 없음 — 캠페인 담당(또는 방치로 올려 받은 사람)만' } },
    })
    mount()
    const box = await screen.findByRole('region', { name: '사람 확인이 필요한 회신' })
    await userEvent.click(await within(box).findByRole('button', { name: /DEMO-PLAN-001/ }))
    await userEvent.type(await screen.findByLabelText('확인 내용'), '확인')
    await userEvent.click(screen.getByRole('button', { name: '확인 저장' }))
    const alerts = await screen.findAllByRole('alert')
    expect(alerts.some((a) => a.textContent?.includes('캠페인 담당(또는 방치로 올려 받은 사람)만'))).toBe(true)
  })

  it('기준일이_바뀌면_목록을_다시_읽는다', async () => {
    const { calls } = base({ 'POST /api/clock': { json: { date: '2026-09-06', mode: '시연' } } })
    mountPage(<RepliesPage />, '/replies?as=' + encodeURIComponent('물류 담당자'), '/replies')
    await screen.findByRole('button', { name: /DEMO-PLAN-001/ })
    expect(calls.filter((c) => c.path === MINE)).toHaveLength(1)
    await userEvent.click(screen.getByRole('button', { name: '다음 날로' }))
    await waitFor(() => expect(calls.filter((c) => c.path === MINE)).toHaveLength(2))
  })
})
