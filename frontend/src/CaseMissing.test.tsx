import { describe, it, expect, afterEach, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import App from './App'
import { fakeServer } from './test/fakeServer'

const MSG = '이 건을 찾을 수 없어요. 시연을 다시 시작했거나 서버가 새로 켜져 데이터가 처음으로 돌아갔을 수 있어요. 메인에서 할 일을 다시 열어 주세요. (건 번호 7)'

afterEach(() => vi.unstubAllGlobals())

describe('없는 건', () => {
  it('없는_건은_이유를_한_번만_보이고_메인으로_가는_버튼', async () => {
    fakeServer({
      'GET /api/people': { json: [{ name: 'Masil 대표', role: 'Masil 대표' }] },
      'GET /api/clock': { json: { date: '2026-07-03', mode: '시연' } },
      [`GET /api/cases/7?viewer=${encodeURIComponent('Masil 대표')}`]: { status: 404, json: { detail: MSG } },
      'GET /api/cases/7/evidence': { status: 404, json: { detail: MSG } },
    })
    render(
      <MemoryRouter initialEntries={[`/cases/7?as=${encodeURIComponent('Masil 대표')}`]}>
        <App />
      </MemoryRouter>,
    )
    const box = await screen.findByText(/이 건을 찾을 수 없어요/, { selector: '.missing *, .missing' })
    expect(box.textContent).not.toMatch(/찾을 수 없는 건이에요/)
    expect(screen.getByRole('link', { name: '메인으로 가서 다시 시작' })).toBeInTheDocument()
  })
})
