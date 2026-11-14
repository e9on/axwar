import type { ReactNode } from 'react'
import { render } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { ClockProvider, useClock } from '../state/clock'
import { addDays } from '../date'
import { ViewerProvider } from '../state/viewer'
import { DemoRunProvider } from '../state/demoRun'

/** 기준일 이동은 시연 조작판에만 있으므로, 화면이 기준일 변화에 다시 읽는지 볼 때 쓰는 시험용 버튼 */
function Advance() {
  const { advance, date } = useClock()
  return (
    <button type="button" onClick={() => date && advance(addDays(date, 1))}>
      다음 날로
    </button>
  )
}

/** 앱 전체 대신 화면 하나만 같은 상태 층 안에 올리고, 기준일을 옮기는 시험용 버튼을 곁들인다 */
export function mountPage(page: ReactNode, url: string, path = '*') {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <ViewerProvider>
        <ClockProvider>
          <DemoRunProvider>
            <Routes>
              <Route path={path} element={page} />
            </Routes>
            <Advance />
          </DemoRunProvider>
        </ClockProvider>
      </ViewerProvider>
    </MemoryRouter>,
  )
}
