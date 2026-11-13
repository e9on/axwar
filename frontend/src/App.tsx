import { useState } from 'react'
import { NavLink, Route, Routes } from 'react-router-dom'
import { api } from './api'
import { ClockProvider, useClock } from './state/clock'
import { ViewerProvider, useViewer } from './state/viewer'
import { DemoRunProvider } from './state/demoRun'
import { useNarrow } from './state/narrow'
import { usePermissions } from './state/permissions'
import { addDays, withWeekday } from './date'
import { DEMO_MODE, OPERATION_MODE } from './decisions'
import FormDialog from './components/FormDialog'
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

/** 모드 전환 확인 창. 누가 바꿀 수 있는지는 서버가 정하고, 거절 문장은 창 안에 그대로 보인다 */
function ModeSwitch({ onClose }: { onClose: () => void }) {
  const { person } = useViewer()
  const { mode, refresh } = useClock()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const next = mode === DEMO_MODE ? OPERATION_MODE : DEMO_MODE

  async function send() {
    if (!person || busy) return
    setBusy(true)
    setError(null)
    try {
      await api.put('/api/mode', { actor: person.name, mode: next })
      await refresh() // 기준일·모드를 다시 읽어 시연 링크와 기준일 이동이 맞게 바뀐다
      onClose()
    } catch (e) {
      setError((e as Error).message)
      setBusy(false)
    }
  }

  return (
    <FormDialog title="모드 전환" confirmLabel={`${next} 모드로 바꾸기`} tone="deny" busy={busy} confirmDisabled={!person} error={error} onConfirm={send} onCancel={onClose}>
      <p>
        지금은 <b>{mode} 모드</b>예요. <b>{next} 모드로</b> 바꿀까요?
      </p>
      <p className="hint">
        {next === OPERATION_MODE
          ? '운영 모드에서는 기준일을 옮기거나 시연 조작판을 쓸 수 없어요.'
          : '시연 모드에서는 시연 조작판과 기준일 이동을 쓸 수 있어요.'}
      </p>
    </FormDialog>
  )
}

function TopBar() {
  const { person, setPerson, people } = useViewer()
  const { date, mode, advance } = useClock()
  const [target, setTarget] = useState('')
  const [menuOpen, setMenuOpen] = useState(false)
  const [switching, setSwitching] = useState(false)
  const narrow = useNarrow()
  const modePerm = usePermissions().of('mode')
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
          회신 입력
        </NavLink>
        <NavLink to={'/log' + asQuery} onClick={closeMenu}>
          처리 기록
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
          기준일 <span className="date">{date ? withWeekday(date) : '불러오는 중'}</span>
          {mode && <span className="mode">{mode} 모드</span>}
          {mode && modePerm?.allowed && (
            <button type="button" className="mode-btn" onClick={() => setSwitching(true)}>
              모드 전환
            </button>
          )}
          {mode && modePerm && !modePerm.allowed && (
            <details className="mode-why">
              <summary>모드 전환 불가</summary>
              <p>{modePerm.reason ?? '이 사람은 모드를 바꿀 수 없어요'}</p>
            </details>
          )}
        </span>
        {demo && date && (
          <span className="clock-move">
            <button type="button" onClick={() => advance(addDays(date, 1))} title="기준일을 하루 뒤(다음 날)로 옮겨요">
              다음 날로
            </button>
            <input type="date" lang="ko" aria-label="이동할 날짜" value={target} onChange={(e) => setTarget(e.target.value)} />
            <button type="button" disabled={!target} onClick={() => advance(target)}>
              날짜로 이동
            </button>
          </span>
        )}
      </div>
      {switching && <ModeSwitch onClose={() => setSwitching(false)} />}
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
