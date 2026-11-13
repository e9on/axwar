import { defineConfig, devices } from '@playwright/test'
import { rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

// 시험용 서버는 임시 DB로 직접 띄우고 끝에 끈다. 화면 개발 서버는 /api 를 8000 으로 넘긴다(vite.config.ts).
const BACKEND_PORT = 8000
const FRONT_PORT = 5199
const db = join(tmpdir(), 'axwar-e2e.db')
if (!process.env.TEST_WORKER_INDEX) {
  // 일꾼 프로세스가 아니라 시험을 시작하는 쪽에서만 지운다
  for (const f of [db, `${db}-wal`, `${db}-shm`]) rmSync(f, { force: true })
}

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1, // 서버 하나·DB 하나를 같이 쓰므로 장면을 차례로
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: [['list']],
  use: {
    baseURL: `http://127.0.0.1:${FRONT_PORT}`,
    locale: 'ko-KR',
    viewport: { width: 1440, height: 900 },
    trace: 'off',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } } }],
  webServer: [
    {
      command: `uv run --python 3.11 uvicorn app.api.main:build_app --factory --host 127.0.0.1 --port ${BACKEND_PORT}`,
      cwd: '../backend',
      env: { AXWAR_DB: db, AXWAR_AI: 'fake', AXWAR_MODE: '시연' },
      url: `http://127.0.0.1:${BACKEND_PORT}/healthz`,
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: `npx vite --host 127.0.0.1 --port ${FRONT_PORT} --strictPort`,
      url: `http://127.0.0.1:${FRONT_PORT}`,
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
})
