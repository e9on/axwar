import { useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useClock } from '../state/clock'
import { useViewer } from '../state/viewer'
import { useCaseLink } from '../state/caseLink'
import { useLoad } from '../state/useLoad'
import { useNarrow } from '../state/narrow'
import { withWeekday } from '../date'
import {
  estimateWidth, monthRange, monthsIn, packRows, pct, toMarks, type CalEvent, type Mark,
} from '../timelineLayout'
import LoadFailed from './LoadFailed'

const BAND_KIND = '하회 구간' // 서버 calendar의 kind 이름
const ALERT_KINDS = ['알림', '2차 알림'] // 기본 거부 직전 알림 종류
const GROUP_MIN = 3 // 같은 날 같은 종류가 이 개수 이상이면 묶어 보임
const CHAR_PX = 12 // 글자 폭 추정(한글 한 자)
const PAD_PX = 14
const MAX_PX = 190
const GAP_PX = 6
const FALLBACK_WIDTH = 1000 // 폭을 잴 수 없을 때

const isAlert = (kind: string) => ALERT_KINDS.includes(kind)

function useWidth(): [React.RefObject<HTMLDivElement | null>, number] {
  const ref = useRef<HTMLDivElement | null>(null)
  const [width, setWidth] = useState(FALLBACK_WIDTH)
  useLayoutEffect(() => {
    const el = ref.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const read = () => {
      if (el.clientWidth > 0) setWidth(el.clientWidth)
    }
    read()
    const ro = new ResizeObserver(read)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  return [ref, width]
}

function Band({ ev, style }: { ev: CalEvent; style?: React.CSSProperties }) {
  return (
    <div className="band" data-testid="band" style={style}>
      <span>{ev.label}</span>
    </div>
  )
}

function Wide({ events, today, role }: { events: CalEvent[]; today: string; role?: string }) {
  const go = useCaseLink()
  const [ref, width] = useWidth()
  const [open, setOpen] = useState<string | null>(null)

  const { start, end } = useMemo(
    () => monthRange([today, ...events.flatMap((e) => (e.end ? [e.date, e.end] : [e.date]))]),
    [events, today],
  )
  const marks = useMemo(() => toMarks(events, role, GROUP_MIN), [events, role])
  const rows = useMemo(() => {
    const placed = marks.map((m) => {
      const w = estimateWidth(m.text, CHAR_PX, PAD_PX, MAX_PX)
      const x = (pct(m.date, start, end) / 100) * width
      return { left: Math.max(0, Math.min(x - w / 2, width - w)), width: w }
    })
    const row = packRows(placed, GAP_PX)
    return placed.map((p, i) => ({ ...p, row: row[i] }))
  }, [marks, start, end, width])
  const rowCount = rows.reduce((n, r) => Math.max(n, r.row + 1), 1)
  const bands = events.filter((e) => e.kind === BAND_KIND && e.end)
  const openMark = marks.find((m) => m.key === open)

  const press = (m: Mark) => {
    if (m.events.length > 1) setOpen(open === m.key ? null : m.key)
    else if (m.events[0].case_id !== null) go(m.events[0].case_id)
  }

  return (
    <div className="track-wrap">
      <div className="track" ref={ref} style={{ ['--rows' as string]: rowCount }}>
        {monthsIn(start, end).map((mo) => (
          <div key={mo.at} className="month" style={{ left: `${pct(mo.at, start, end)}%` }}>
            <span>{mo.label}</span>
          </div>
        ))}
        {bands.map((b, i) => (
          <Band key={i} ev={b} style={{ left: `${pct(b.date, start, end)}%`, width: `${pct(b.end!, start, end) - pct(b.date, start, end)}%` }} />
        ))}
        <div className="today" data-testid="today" style={{ left: `${pct(today, start, end)}%` }}>
          <span>오늘 {today.slice(5).replace('-', '/')}</span>
        </div>
        {marks.map((m, i) => (
          <button
            key={m.key}
            type="button"
            className="dot"
            data-mine={m.mine}
            data-alert={isAlert(m.kind)}
            data-row={rows[i].row}
            data-group={m.events.length > 1}
            aria-disabled={m.events.length === 1 && m.events[0].case_id === null}
            aria-expanded={m.events.length > 1 ? open === m.key : undefined}
            title={m.title}
            style={{ left: rows[i].left, width: rows[i].width, top: `calc(var(--tl-top) + ${rows[i].row} * var(--tl-row))` }}
            onClick={() => press(m)}
          >
            {m.text}
          </button>
        ))}
      </div>
      {openMark && (
        <ul className="group-list" aria-label={`${openMark.text} 목록`}>
          {openMark.events.map((e, i) => (
            <li key={i}>
              <button type="button" onClick={() => e.case_id !== null && go(e.case_id)}>{e.label}</button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function Narrow({ events, today, role }: { events: CalEvent[]; today: string; role?: string }) {
  const go = useCaseLink()
  const [showPast, setShowPast] = useState(false)
  const bands = events.filter((e) => e.kind === BAND_KIND)
  const items = events.filter((e) => e.kind !== BAND_KIND)
  const shown = items.filter((e) => showPast || e.date >= today)
  const pastCount = items.length - items.filter((e) => e.date >= today).length
  return (
    <div className="date-list-wrap">
      {bands.map((b, i) => (
        <Band key={i} ev={b} />
      ))}
      <ul className="date-list" aria-label="날짜 목록">
        {shown.map((e, i) => (
          <li key={i}>
            <button
              type="button"
              data-mine={role !== undefined && e.roles.includes(role)}
              data-alert={isAlert(e.kind)}
              data-past={e.date < today}
              aria-disabled={e.case_id === null}
              onClick={() => e.case_id !== null && go(e.case_id)}
            >
              <span className="d">{withWeekday(e.date).slice(5)}</span>
              <span className="l">{e.label}</span>
            </button>
          </li>
        ))}
      </ul>
      {!showPast && pastCount > 0 && (
        <button type="button" className="more" onClick={() => setShowPast(true)}>지난 일정 보기</button>
      )}
    </div>
  )
}

export default function Timeline() {
  const { version, date } = useClock()
  const { person } = useViewer()
  const narrow = useNarrow()
  const { data, error, loading, retry } = useLoad<CalEvent[]>('/api/calendar', [version])
  const today = date ?? ''

  return (
    <section className="tl" aria-label="일정">
      <div className="tl-head">
        <h2>일정</h2>
        <span>남색은 내 차례, 붉은 테두리는 기본 거부 직전 알림</span>
      </div>
      {error ? (
        <LoadFailed retry={retry} />
      ) : loading || !data || !today ? (
        <p className="muted">불러오는 중</p>
      ) : data.length === 0 ? (
        <p className="muted">잡힌 일정이 없어요</p>
      ) : narrow ? (
        <Narrow events={data} today={today} role={person?.role} />
      ) : (
        <Wide events={data} today={today} role={person?.role} />
      )}
    </section>
  )
}
