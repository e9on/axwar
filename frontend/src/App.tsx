import { useState } from 'react'
import { NavLink, Route, Routes } from 'react-router-dom'
import { ClockProvider, useClock } from './state/clock'
import { ViewerProvider, useViewer } from './state/viewer'
import { DemoRunProvider } from './state/demoRun'
import { useNarrow } from './state/narrow'
import { koDate } from './date'
import { DEMO_MODE } from './decisions'
import Notices from './Notices'
import Home from './pages/Home'
import CaseDetail from './pages/CaseDetail'
import Replies from './pages/Replies'
import Phase2Watch from './pages/Phase2Watch'
import Demo from './pages/Demo'
import Log from './pages/Log'
import Policy from './pages/Policy'
import Registry from './pages/Registry'
import './App.css'

function TopBar() {
  const { person, setPerson, people } = useViewer()
  const { date, mode } = useClock()
  const [menuOpen, setMenuOpen] = useState(false)
  const narrow = useNarrow()
  const demo = mode === DEMO_MODE
  const asQuery = person ? `?as=${encodeURIComponent(person.name)}` : ''
  const closeMenu = () => setMenuOpen(false)

  return (
    <header className="top">
      <span className="brand">Approval Planner</span>
      {narrow && (
        <button type="button" className="menu-btn" aria-expanded={menuOpen} aria-controls="main-nav" onClick={() => setMenuOpen((o) => !o)}>
          메뉴
        </button>
      )}
      <nav className="nav" id="main-nav" aria-label="화면 이동" hidden={narrow && !menuOpen}>
        <NavLink to={'/' + asQuery} end onClick={closeMenu}>
          메인
        </NavLink>
        <NavLink to={'/replies' + asQuery} onClick={closeMenu}>
          회신
        </NavLink>
        <NavLink to={'/log' + asQuery} onClick={closeMenu}>
          기록
        </NavLink>
        <NavLink to={'/policy' + asQuery} onClick={closeMenu}>
          정책
        </NavLink>
        <NavLink to={'/registry' + asQuery} onClick={closeMenu}>
          등록
        </NavLink>
        {demo && (
          <NavLink to={'/demo' + asQuery} onClick={closeMenu}>
            시연
          </NavLink>
        )}
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
          기준일 <span className="date">{date ? koDate(date) : '불러오는 중'}</span>
          {demo && <span className="mode">시연</span>}
        </span>
      </div>
    </header>
  )
}

export default function App() {
  return (
    <ViewerProvider>
      <ClockProvider>
        <DemoRunProvider>
          <Notices />
          <TopBar />
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/cases/:id" element={<CaseDetail />} />
            <Route path="/cases/:id/phase2" element={<Phase2Watch />} />
            <Route path="/replies" element={<Replies />} />
            <Route path="/log" element={<Log />} />
            <Route path="/policy" element={<Policy />} />
            <Route path="/registry" element={<Registry />} />
            <Route path="/demo" element={<Demo />} />
          </Routes>
        </DemoRunProvider>
      </ClockProvider>
    </ViewerProvider>
  )
}
