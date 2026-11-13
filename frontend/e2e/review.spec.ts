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
