import { test as base, expect, type Page } from '@playwright/test'

/** 장면마다 서버 오류(5xx)·콘솔 오류·잡히지 않은 예외가 없어야 한다 */
const test = base.extend<{ problems: string[] }>({
  problems: async ({ page }, use) => {
    const list: string[] = []
    page.on('console', (m) => m.type() === 'error' && list.push(`콘솔: ${m.text()}`))
    page.on('pageerror', (e) => list.push(`예외: ${e.message}`))
    page.on('response', (r) => r.status() >= 500 && list.push(`서버 ${r.status()}: ${r.url()}`))
    await use(list)
    expect(list, '장면 중 오류가 없어야 해요').toEqual([])
  },
})

async function startScene(page: Page, title: string) {
  await page.goto('/demo')
  const exact = new RegExp(`^${title}$`)
  await page.locator('.scene').filter({ has: page.locator('.k', { hasText: exact }) }).click()
  await page.getByRole('dialog').getByRole('button', { name: '초기화하고 시작' }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.getByText(/^0 \/ \d+단계 진행$/)).toBeVisible()
}

async function playSteps(page: Page, count: number, total: number) {
  for (let i = 1; i <= count; i++) {
    await page.getByRole('button', { name: '한 단계 진행' }).click()
    await expect(page.getByText(`${i} / ${total}단계 진행`)).toBeVisible()
  }
}

async function viewAs(page: Page, name: string) {
  await page.getByLabel('보는 사람').selectOption(name)
  await expect(page.getByLabel('보는 사람')).toHaveValue(name)
}

async function goHome(page: Page) {
  await page.getByRole('navigation', { name: '화면 이동' }).getByRole('link', { name: '메인' }).click()
}

async function openTodo(page: Page, ref: string, column?: string) {
  const todo = page.getByRole('region', { name: '할 일' })
  const scope = column ? todo.locator('.col', { has: page.getByRole('heading', { name: column }) }) : todo
  await scope.getByRole('button', { name: new RegExp(ref) }).first().click()
  await expect(page).toHaveURL(/\/cases\/\d+/)
}

test('scenario_1: 물류·SCM 회신 뒤 Masil 대표가 근거를 보고 승인한다', async ({ page, problems }) => {
  void problems
  await startScene(page, '장면 1\\. 정상')
  await playSteps(page, 2, 3) // 물류 회신, SCM 회신 (세 번째 단계 = 승인은 화면에서 직접)

  await viewAs(page, 'Masil 대표')
  await goHome(page)
  await openTodo(page, 'PLAN-019', '승인 대기')

  // 근거 한 줄을 펼쳐 계산식을 본다
  const evidence = page.locator('.evidence')
  const row = evidence.getByRole('button', { expanded: false }).first()
  await row.click()
  await expect(evidence.getByText('계산식').first()).toBeVisible()

  await page.getByRole('group', { name: '결정' }).getByRole('button', { name: '승인', exact: true }).click()
  const dlg = page.getByRole('dialog')
  await expect(dlg).toContainText('이 건을 승인합니다')
  await dlg.getByRole('button', { name: '승인 확정' }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)

  await expect(page.getByText(/보냈어요/)).toBeVisible()
  await expect(page.getByText(/1차 집행|승인 완료/).first()).toBeVisible()
})

test('scenario_2: 재고 부족으로 막힌 이유를 보고 분할 승인한다', async ({ page, problems }) => {
  void problems
  await startScene(page, '장면 2\\. 조건 변경 — SCM 일부 허용')
  await playSteps(page, 1, 10) // 물류 회신

  await viewAs(page, '그룹 CEO')
  await goHome(page)
  await openTodo(page, 'PLAN-001')

  const decide = page.getByRole('group', { name: '결정' })
  await expect(decide.getByRole('list', { name: '지금 할 수 없는 결정' })).toContainText('지금 할 수 없어요')

  await decide.getByRole('button', { name: /^분할 승인/ }).click()
  const dlg = page.getByRole('dialog')
  await expect(dlg).toContainText('분할 승인 확인')
  await expect(dlg).toContainText(/1차 [\d,]+개/)
  await expect(dlg).toContainText('원')
  await dlg.getByRole('button', { name: '분할 승인 확정' }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.getByText(/보냈어요/)).toBeVisible()

  // 시연 조작판으로 이어서 진행(이사회 분할 승인 → SCM 일부 허용 → 재승인 둘). 이미 한 CEO 승인 단계는 서버가 건너뛴다
  await page.getByRole('navigation', { name: '화면 이동' }).getByRole('link', { name: '시연' }).click()
  for (let i = 2; i <= 6; i++) {
    await page.getByRole('button', { name: '한 단계 진행' }).click()
    await expect(page.getByText(`${i} / 10단계 진행`)).toBeVisible()
  }
  await page.goBack() // 건 상세로 돌아와 다시 읽힌다
  await expect(page.getByRole('heading', { name: '2차 집행' })).toBeVisible()
  await expect(page.getByText(/2차 계획 [\d,]+개/)).toBeVisible()
})

test('scenario_3: 승인 없이 기본 거부 날이 되면 기본 거부와 통보 초안이 보인다', async ({ page, problems }) => {
  void problems
  await startScene(page, '장면 3\\. 정보 부족·승인 없음')
  await playSteps(page, 2, 4) // 7/12, 7/14 기준일 이동

  await viewAs(page, '계약 담당자')
  await goHome(page)
  await expect(page.getByText('2026-07-14').first()).toBeVisible()
  await openTodo(page, 'INF-001')
  await expect(page.getByText(/기본 거부/).first()).toBeVisible()
  await expect(page.getByText(/조건변경 통보|통보 초안/).first()).toBeVisible()
})

test('scenario_1_escalate: 마케팅팀장이 위로 올리면 Masil 대표 결재선에 들어간다', async ({ page, problems }) => {
  void problems
  await startScene(page, '장면 1 변형\\. 상신 — .*')
  await playSteps(page, 2, 4) // 물류·SCM 회신

  await viewAs(page, '마케팅팀장')
  await goHome(page)
  await openTodo(page, 'DEMO-PLAN-001', '승인 대기')

  await page.getByRole('group', { name: '결정' }).getByRole('button', { name: '위로 올리기' }).click()
  const dlg = page.getByRole('dialog')
  await dlg.getByRole('radio', { name: '승인 권고' }).check()
  await dlg.getByPlaceholder('올리는 이유를 적어 주세요').fill('대표 확인이 필요해 올립니다')
  await dlg.getByRole('button', { name: '올리기 확정' }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.getByText(/보냈어요/)).toBeVisible()

  // Masil 대표의 승인 대기에 올라온 문장과 함께 보인다
  await viewAs(page, 'Masil 대표')
  await goHome(page)
  const col = page.getByRole('region', { name: '할 일' }).locator('.col', { has: page.getByRole('heading', { name: '승인 대기' }) })
  await expect(col).toContainText('DEMO-PLAN-001')
  await expect(col).toContainText('마케팅팀에서 올림')
})

test('시연 조작판: 장면 설명은 두 줄로 줄여 보이고, 고른 장면의 전체 설명은 진행 칸에 있다', async ({ page, problems }) => {
  void problems
  await page.goto('/demo')
  const subs = page.locator('.scene .sub')
  await expect(subs.first()).toBeVisible()
  const heights = await subs.evaluateAll((els) => els.map((e) => e.getBoundingClientRect().height))
  const line = await subs.first().evaluate((e) => parseFloat(getComputedStyle(e).lineHeight))
  for (const h of heights) expect(h).toBeLessThanOrEqual(line * 2 + 2)

  await startScene(page, '장면 1\. 정상')
  await expect(page.getByRole('region', { name: '진행' }).locator('.scene-desc')).toContainText('SCM이 전량 허용하고 Masil 대표가 승인하면')
})
