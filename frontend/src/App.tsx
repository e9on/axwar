import { useState } from 'react'
import { Link, Route, Routes } from 'react-router-dom'
import { ClockProvider, useClock } from './state/clock'
import { ViewerProvider, useViewer } from './state/viewer'
import { addDays, withWeekday } from './date'
import { DEMO_MODE } from './decisions'
import Notices from './Notices'
import Home from './pages/Home'
import CaseDetail from './pages/CaseDetail'
import Replies from './pages/Replies'
import Phase2Watch from './pages/Phase2Watch'
import './App.css'


function TopBar() {
  const { person, setPerson, people } = useViewer()
  const { date, mode, advance } = useClock()
  const [target, setTarget] = useState('')
  const demo = mode === DEMO_MODE
  const asQuery = person ? `?as=${encodeURIComponent(person.name)}` : ''

  return (
    <header className="top">
      <span className="brand">Approval Planner</span>
      <nav className="nav" aria-label="화면 이동">
        <Link to={'/' + asQuery}>메인</Link>
        <Link to={'/replies' + asQuery}>회신 입력</Link>
      </nav>
      <div className="who">
        <label>
          보는 사람
          <select value={person?.name ?? ''} onChange={(e) => setPerson(e.target.value)}>
            {people.map((p) => (
              <option key={p.name} value={p.name}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
        <span className="clock-box">
          기준일 <span className="date">{date ? withWeekday(date) : '불러오는 중'}</span>
          {mode && <span className="mode">{mode} 모드</span>}
        </span>
        {demo && date && (
          <span className="clock-move">
            <button type="button" onClick={() => advance(addDays(date, 1))} title="기준일을 하루 뒤(다음 날)로 옮겨요">
              다음 날로
            </button>
            <input type="date" aria-label="이동할 날짜" value={target} onChange={(e) => setTarget(e.target.value)} />
            <button type="button" disabled={!target} onClick={() => advance(target)}>
              날짜로 이동
            </button>
          </span>
        )}
      </div>
    </header>
  )
}

export default function App() {
  return (
    <ViewerProvider>
      <ClockProvider>
        <Notices />
        <TopBar />
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/cases/:id" element={<CaseDetail />} />
          <Route path="/cases/:id/phase2" element={<Phase2Watch />} />
          <Route path="/replies" element={<Replies />} />
        </Routes>
      </ClockProvider>
    </ViewerProvider>
  )
}
