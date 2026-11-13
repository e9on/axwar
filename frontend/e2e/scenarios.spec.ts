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
    await page.getByRole('button', { name: '다음 단계' }).click()
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
  const scope = column ? todo.locator(`li[data-column="${column}"]`) : todo
  await scope.getByRole('button', { name: new RegExp(`${ref} 열기`) }).first().click()
  await expect(page).toHaveURL(/\/cases\/\d+/)
}

test('scenario_1: 물류·SCM 회신 뒤 Masil 대표가 근거를 보고 승인한다', async ({ page, problems }) => {
  void problems
  await startScene(page, '장면 1\\. 정상')
  await playSteps(page, 2, 3) // 물류 회신, SCM 회신 (세 번째 단계 = 승인은 화면에서 직접)

  await viewAs(page, 'Masil 대표')
  await goHome(page)
  await openTodo(page, 'PLAN-019', '승인 대기')

  // 첫 화면(1440x900) 안에 지금 할 일 문장과 버튼이 보인다
  const now = page.getByRole('group', { name: '결정' })
  await expect(now).toContainText('승인이 필요해요')
  const box = await now.boundingBox()
  expect(box!.y + box!.height).toBeLessThanOrEqual(900)
  await expect(now.getByRole('button', { name: '승인', exact: true })).toBeInViewport()

  // 근거 칸은 접혀 있다. 펼치고 한 줄을 눌러 계산식을 본다
  const evidence = page.locator('.evidence')
  await evidence.getByRole('button', { name: /위험 신호/ }).click()
  const row = evidence.locator('.ebtn').first()
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
    await page.getByRole('button', { name: '다음 단계' }).click()
    await expect(page.getByText(`${i} / 10단계 진행`)).toBeVisible()
  }
  await page.goBack() // 건 상세로 돌아와 다시 읽힌다
  await page.getByRole('button', { name: /^2차 집행/ }).click()
  await expect(page.getByText(/2차 계획 [\d,]+개/)).toBeVisible()
})

test('scenario_3: 승인 없이 기본 거부 날이 되면 기본 거부와 통보 초안이 보인다', async ({ page, problems }) => {
  void problems
  await startScene(page, '장면 3\\. 정보 부족·승인 없음')
  await playSteps(page, 2, 4) // 7/12, 7/14 기준일 이동

  await viewAs(page, '계약 담당자')
  await goHome(page)
  await expect(page.getByText('7월 14일').first()).toBeVisible()
  await openTodo(page, 'INF-001')
  await expect(page.getByRole('group', { name: '결정' })).toContainText('통보 초안')
  await expect(page.getByRole('group', { name: '결정' })).toContainText('통보 발송')
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
  const col = page.getByRole('region', { name: '할 일' }).locator('li[data-column="승인 대기"]')
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
  await page.getByRole('region', { name: '진행' }).getByText('자세히').click()
  await expect(page.getByRole('region', { name: '진행' }).locator('.scene-desc')).toContainText('SCM이 전량 허용하고 Masil 대표가 승인하면')
})

test('scenario_2_exception: 반품 기준 숫자와 예외 승인 뒤 상태가 2차 관찰에 서버 값으로 보인다', async ({ page, problems }) => {
  void problems
  await startScene(page, '장면 2 변형\\. 2차 반품 자동 보류 — .*')
  await page.getByRole('button', { name: '끝까지' }).click()
  await expect(page.getByText(/^13 \/ 13단계 진행$/)).toBeVisible()

  // 새로고침해도 서버가 기억한 진행 위치가 그대로다
  await page.reload()
  await expect(page.getByText(/^13 \/ 13단계 진행$/)).toBeVisible()
  await expect(page.getByRole('button', { name: '다음 단계' })).toBeDisabled()

  const id = await page.evaluate(async () => {
    const list = (await (await fetch('/api/cases')).json()) as { id: number; ref_id: string }[]
    return list.find((c) => c.ref_id === 'PLAN-001')?.id
  })
  await page.goto(`/cases/${id}/phase2?as=${encodeURIComponent('Masil 대표')}`)

  const box = page.getByRole('region', { name: '반품' })
  await expect(box).toContainText('단순변심')
  const color = box.getByRole('button', { name: /색상불만/ })
  await expect(color).toContainText('150건')
  await expect(color).toContainText('5.00%')
  await expect(color).toContainText('한계')
  await expect(color).toContainText('초과')
  await expect(box).toContainText('예외 승인을 받은 건')
  await expect(box).toContainText('관찰')
  // 근거를 펼치면 계산식과 원본 파일이 보인다
  await color.click()
  const row = box.locator('.erow', { hasText: '색상불만' })
  await expect(row.getByText('계산식')).toBeVisible()
  await expect(row.getByText('mkt_returns_ms.csv')).toBeVisible()
  await expect(page.getByRole('region', { name: '리뷰 신호' })).toBeVisible()
})

test('메인: 하회 구간 이름표가 표시 칸과 겹치지 않는다', async ({ page, problems }) => {
  void problems
  // 일정이 많이 쌓인 장면 끝(표시가 하회 구간 띠 안까지 들어오는 상태)에서 잰다
  await startScene(page, '장면 2 변형\\. 2차 반품 자동 보류 — .*')
  await page.getByRole('button', { name: '끝까지' }).click()
  await expect(page.getByText(/^13 \/ 13단계 진행$/)).toBeVisible()
  await page.goto('/')
  await expect(page.getByTestId('band').first()).toBeVisible()
  await expect(page.locator('.dot').first()).toBeVisible()
  const overlaps = await page.evaluate(() => {
    const hit = (a: DOMRect, b: DOMRect) => a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom
    const labels = Array.from(document.querySelectorAll('[data-testid="band"] span')).map((e) => e.getBoundingClientRect())
    const others = Array.from(document.querySelectorAll('.dot, .today span')).map((e) => e.getBoundingClientRect())
    return labels.flatMap((l) => others.filter((o) => hit(l, o)).map(() => 1)).length
  })
  expect(overlaps).toBe(0)
})

test('768px: 위쪽 막대는 두 줄 이내', async ({ page, problems }) => {
  void problems
  await page.setViewportSize({ width: 768, height: 900 })
  await page.goto('/')
  await expect(page.locator('.top .brand')).toBeVisible()
  const rows = await page.evaluate(() => {
    const centers: number[] = []
    document.querySelectorAll('.top .brand, .top .nav a, .top .who label, .top .clock-box, .top .clock-move button, .top .clock-move input').forEach((e) => {
      const r = e.getBoundingClientRect()
      centers.push(r.top + r.height / 2)
    })
    centers.sort((a, b) => a - b)
    let count = 0
    let last = -Infinity
    for (const t of centers) {
      if (t - last > 12) count += 1 // 가운데 높이가 12px 안쪽이면 같은 줄
      last = t
    }
    return count
  })
  expect(rows).toBeLessThanOrEqual(2)
})

test('정책 화면: 모드 전환 불가 이유가 한 줄로 잘리지 않고 보인다', async ({ page, problems }) => {
  void problems
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/policy')
  await viewAs(page, '마케팅팀장')
  const line = page.getByRole('region', { name: '모드' })
  await expect(line.locator('.muted')).toBeVisible()
  const fits = await line.locator('.muted').evaluate((el) => el.scrollWidth <= el.clientWidth + 1)
  expect(fits, '이유 문장이 잘리지 않아야 해요').toBe(true)
  await expect(line.getByRole('button', { name: '모드 전환' })).toHaveCount(0)
})
