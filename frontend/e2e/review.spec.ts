import { test, expect } from '@playwright/test'
import { join } from 'node:path'

// 디자인 리뷰용 스크린샷: REVIEW_SHOTS=1 npm run e2e -- review 로만 돈다(보통 e2e 에서는 건너뜀).
// 1440·768·390 폭마다 모든 화면을 찍고, 가로 스크롤이 없는지도 같이 확인한다.
test.skip(!process.env.REVIEW_SHOTS, 'REVIEW_SHOTS=1 일 때만')

const OUT = join(process.cwd(), '..', '작업노트', '화면확인')
const WIDTHS = [1440, 768, 390]

test('모든 화면 스크린샷과 가로 스크롤 점검', async ({ page, request }) => {
  test.setTimeout(180_000)
  const api = 'http://127.0.0.1:8000'
  await request.post(`${api}/api/demo/reset`, { data: { scenario: 'scenario_2' } })
  await request.post(`${api}/api/demo/run`, { data: { scenario: 'scenario_2' } })
  const cases = (await (await request.get(`${api}/api/cases`)).json()) as { id: number; ref_id: string }[]
  const id = cases.find((c) => c.ref_id === 'PLAN-001')?.id
  expect(id).toBeTruthy()

  const screens: [string, string][] = [
    ['메인', `/?as=${encodeURIComponent('캠페인 담당자')}`],
    ['건상세', `/cases/${id}?as=${encodeURIComponent('Masil 대표')}`],
    ['회신', `/replies?as=${encodeURIComponent('물류 담당자')}`],
    ['2차', `/cases/${id}/phase2?as=${encodeURIComponent('캠페인 담당자')}`],
    ['시연', '/demo'],
    ['기록', '/log'],
    ['정책', '/policy'],
    ['등록', '/registry'],
  ]
  const overflow: string[] = []
  for (const w of WIDTHS) {
    await page.setViewportSize({ width: w, height: 900 })
    for (const [name, url] of screens) {
      await page.goto(url)
      await page.waitForLoadState('networkidle')
      await page.screenshot({ path: join(OUT, `리뷰_${name}_${w}.png`), fullPage: true })
      const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
      if (over > 0) overflow.push(`${name} ${w}px: ${over}px 넘침`)
    }
  }
  expect(overflow).toEqual([])
})

test('키보드: Tab 으로 가는 곳마다 초점 표시가 보인다', async ({ page, request }) => {
  test.setTimeout(120_000)
  const api = 'http://127.0.0.1:8000'
  await request.post(`${api}/api/demo/reset`, { data: { scenario: 'scenario_2' } })
  await request.post(`${api}/api/demo/run`, { data: { scenario: 'scenario_2' } })
  const cases = (await (await request.get(`${api}/api/cases`)).json()) as { id: number; ref_id: string }[]
  const id = cases.find((c) => c.ref_id === 'PLAN-001')?.id
  const urls = ['/', `/cases/${id}?as=${encodeURIComponent('Masil 대표')}`, '/replies', '/demo', '/log', '/policy', '/registry']
  const missing: string[] = []
  for (const u of urls) {
    await page.goto(u)
    await page.waitForLoadState('networkidle')
    for (let i = 0; i < 45; i++) {
      await page.keyboard.press('Tab')
      const r = await page.evaluate(() => {
        const e = document.activeElement as HTMLElement | null
        if (!e || e === document.body) return null
        const cs = getComputedStyle(e)
        const visible = (cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0) || (cs.boxShadow !== 'none' && cs.boxShadow !== '')
        return { visible, label: `${e.tagName}:${(e.getAttribute('aria-label') ?? e.textContent ?? '').trim().slice(0, 20)}` }
      })
      if (r && !r.visible) missing.push(`${u.split('?')[0]} ${r.label}`)
    }
  }
  expect([...new Set(missing)]).toEqual([])
})

test('PR #33 검토 반영 스크린샷(마무리_* 덮어쓰기)', async ({ page, request }) => {
  test.setTimeout(180_000)
  const api = 'http://127.0.0.1:8000'
  const shot = (name: string) => page.screenshot({ path: join(OUT, `마무리_${name}.png`), fullPage: true })
  await page.setViewportSize({ width: 1440, height: 900 })

  // 승인 확인 창: 장면 1을 두 단계 진행해 승인만 남긴 상태
  await request.post(`${api}/api/demo/reset`, { data: { scenario: 'scenario_1' } })
  await request.post(`${api}/api/demo/run`, { data: { scenario: 'scenario_1', upto: 2 } })
  const list = (await (await request.get(`${api}/api/cases`)).json()) as { id: number; ref_id: string }[]
  const first = list.find((c) => c.ref_id === 'PLAN-019')
  expect(first).toBeTruthy()
  await page.goto(`/cases/${first!.id}?as=${encodeURIComponent('Masil 대표')}`)
  await page.getByRole('group', { name: '결정' }).getByRole('button', { name: '승인', exact: true }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await shot('승인확인창_1440')
  await page.keyboard.press('Escape')

  // 메인·시연 조작판·2차(끝난 건)
  await request.post(`${api}/api/demo/reset`, { data: { scenario: 'scenario_2' } })
  await request.post(`${api}/api/demo/run`, { data: { scenario: 'scenario_2' } })
  const cases = (await (await request.get(`${api}/api/cases`)).json()) as { id: number; ref_id: string }[]
  const id = cases.find((c) => c.ref_id === 'PLAN-001')?.id
  expect(id).toBeTruthy()
  await page.goto(`/?as=${encodeURIComponent('캠페인 담당자')}`)
  await page.waitForLoadState('networkidle')
  await shot('메인_1440')
  await page.goto('/demo')
  await page.waitForLoadState('networkidle')
  await shot('시연_1440')
  await page.goto(`/cases/${id}/phase2?as=${encodeURIComponent('캠페인 담당자')}`)
  await page.waitForLoadState('networkidle')
  await shot('2차_1440')
})

test('화면 개편(#33) 스크린샷: 개편_*', async ({ page, request }) => {
  test.setTimeout(180_000)
  const api = 'http://127.0.0.1:8000'
  // 장면 2를 한 단계(물류 회신)만 진행: 그룹 CEO에게 분할 승인 차례가 온 상태
  await request.post(`${api}/api/demo/reset`, { data: { scenario: 'scenario_2' } })
  await request.post(`${api}/api/demo/run`, { data: { scenario: 'scenario_2', from_step: 0, upto: 1 } })
  const cases = (await (await request.get(`${api}/api/cases`)).json()) as { id: number; ref_id: string }[]
  const id = cases.find((c) => c.ref_id === 'PLAN-001')?.id
  expect(id).toBeTruthy()
  const ceo = encodeURIComponent('그룹 CEO')
  const shot = (name: string, full = true) => page.screenshot({ path: join(OUT, `개편_${name}.png`), fullPage: full })
  const go = async (url: string) => {
    await page.goto(url)
    await page.waitForLoadState('networkidle')
  }
  for (const w of [1440, 768, 390]) {
    await page.setViewportSize({ width: w, height: 900 })
    if (w !== 768) {
      await go(`/?as=${ceo}`)
      await shot(`메인_${w}`)
      await go('/demo')
      await shot(`시연_${w}`)
    }
    await go(`/cases/${id}?as=${ceo}`)
    await shot(`건상세_${w}`)
    if (w === 1440) await shot('건상세_첫화면_1440', false)
    const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
    expect(over, `${w}px 가로 스크롤`).toBeLessThanOrEqual(0)
  }
})

test('배지 정리(#33) 스크린샷: 배지정리_*', async ({ page, request }) => {
  test.setTimeout(180_000)
  const api = 'http://127.0.0.1:8000'
  await request.post(`${api}/api/demo/reset`, { data: { scenario: 'scenario_2' } })
  await request.post(`${api}/api/demo/run`, { data: { scenario: 'scenario_2', from_step: 0, upto: 1 } })
  const cases = (await (await request.get(`${api}/api/cases`)).json()) as { id: number; ref_id: string }[]
  const id = cases.find((c) => c.ref_id === 'PLAN-001')?.id
  expect(id).toBeTruthy()
  await request.post(`${api}/api/cases/${id}/briefing`, { data: { actor: '그룹 CEO' } })
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto(`/cases/${id}?as=${encodeURIComponent('그룹 CEO')}`)
  await page.waitForLoadState('networkidle')
  await page.screenshot({ path: join(OUT, '배지정리_첫화면_1440.png') })
  await page.getByRole('button', { name: /위험 신호/ }).click()
  await page.getByRole('button', { name: /AI 브리핑/ }).first().click()
  await page.screenshot({ path: join(OUT, '배지정리_근거펼침_1440.png'), fullPage: true })
})

test('말로 설명(#33) 스크린샷: 말로설명_* (서버 explain이 아직 없어 응답에 가짜 문장을 끼워 그림)', async ({ page, request }) => {
  test.setTimeout(180_000)
  const api = 'http://127.0.0.1:8000'
  await request.post(`${api}/api/demo/reset`, { data: { scenario: 'scenario_2' } })
  await request.post(`${api}/api/demo/run`, { data: { scenario: 'scenario_2', from_step: 0, upto: 1 } })
  const cases = (await (await request.get(`${api}/api/cases`)).json()) as { id: number; ref_id: string }[]
  const id = cases.find((c) => c.ref_id === 'PLAN-001')?.id
  expect(id).toBeTruthy()
  await page.route('**/api/cases/*/evidence', async (route) => {
    const res = await route.fetch()
    const body = await res.json()
    const say = (l: { label?: string; level?: string; explain?: string }) => {
      if (l.explain) return
      l.explain = l.level === 'red' ? `${l.label}이(가) 기준보다 많이 벗어나 있어서 결과가 나빠요. (시험용 가짜 문장)` : `${l.label}은(는) 기준 안에 있어서 결과가 좋아요. (시험용 가짜 문장)`
    }
    for (const s of body.signals ?? []) say(s)
    for (const k of body.key_indicators ?? []) say(k)
    await route.fulfill({ response: res, json: body })
  })
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto(`/cases/${id}?as=${encodeURIComponent('그룹 CEO')}`)
  await page.waitForLoadState('networkidle')
  await page.getByRole('button', { name: /위험 신호/ }).click()
  await page.getByRole('button', { name: /핵심 지표/ }).click()
  await page.screenshot({ path: join(OUT, '말로설명_위험신호_1440.png'), fullPage: true })
})
