import { useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useClock } from '../state/clock'
import { useViewer } from '../state/viewer'
import { useCaseLink } from '../state/caseLink'
import { useLoad } from '../state/useLoad'
import { useNarrow } from '../state/narrow'
import { koDate, withWeekday } from '../date'
import {
  BOLD_RATIO, DOT_BORDER_PX, DOT_CHAR_PX, DOT_GAP_PX, DOT_MAX_PX, DOT_PAD_PX,
  bandSpan, estimateWidth, monthRange, monthsIn, packRows, pct, placeLeft, toMarks, type CalEvent, type Mark,
} from '../timelineLayout'
import { shortTitle } from '../copy'
import type { CaseListRow } from '../caseTypes'
import LoadFailed from './LoadFailed'

const BAND_KIND = '하회 구간' // 서버 calendar의 kind 이름
const ALERT_KINDS = ['알림', '2차 알림'] // 기본 거부 직전 알림 종류
const GROUP_MIN = 3 // 같은 날 같은 종류가 이 개수 이상이면 묶어 보임
const FALLBACK_WIDTH = 1000 // 폭을 잴 수 없을 때
const KEY_KINDS = /기한|집행일|만료/ // 기본으로 보이는 일정 종류(서버 일정 종류 이름에 들어 있는 말)

const isAlert = (kind: string) => ALERT_KINDS.includes(kind)

/** 스크린리더용 이름: 날짜, 내용, 색에만 기대지 않도록 내 차례·알림 여부. */
function spoken(date: string, text: string, mine: boolean, alert: boolean): string {
  const tags = [mine && '내 차례', alert && '기본 거부 직전 알림'].filter(Boolean)
  return `${koDate(date)}, ${text}${tags.length ? ` (${tags.join(', ')})` : ''}`
}

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
      const w = estimateWidth(m.text, DOT_CHAR_PX * (m.mine ? BOLD_RATIO : 1), 2 * (DOT_PAD_PX + DOT_BORDER_PX), DOT_MAX_PX)
      const at = pct(m.date, start, end)
      return { left: placeLeft((at / 100) * width, w, width), width: w, at }
    })
    const row = packRows(placed, DOT_GAP_PX)
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
    <div className="track-wrap" data-bands={bands.length > 0}>
      <div
        className="track"
        ref={ref}
        style={{
          ['--rows' as string]: rowCount,
          ['--dot-px' as string]: `${DOT_PAD_PX}px`,
          ['--dot-border' as string]: `${DOT_BORDER_PX}px`,
          ['--dot-font' as string]: `${DOT_CHAR_PX}px`,
        }}
      >
        {monthsIn(start, end).map((mo) => (
          <div key={mo.at} className="month" style={{ left: `${pct(mo.at, start, end)}%` }}>
            <span>{mo.label}</span>
          </div>
        ))}
        {bands.map((b, i) => {
          const span = bandSpan(b.date, b.end!, start, end)
          return <Band key={i} ev={b} style={{ left: `${span.left}%`, width: `${span.width}%` }} />
        })}
        <div className="today" data-testid="today" style={{ left: `${pct(today, start, end)}%` }}>
          <span>오늘 {today.slice(5).replace('-', '/')}</span>
        </div>
        {marks.map((m, i) => (
          <span
            key={`${m.key}-tick`}
            className="tick"
            data-testid="tick"
            data-mine={m.mine}
            data-alert={isAlert(m.kind) && m.date >= today}
            style={{ left: `${rows[i].at}%`, ['--row' as string]: rows[i].row }}
          />
        ))}
        {marks.map((m, i) => (
          <button
            key={m.key}
            type="button"
            className="dot"
            data-mine={m.mine}
            data-alert={isAlert(m.kind) && m.date >= today}
            data-past={m.date < today}
            data-row={rows[i].row}
            data-group={m.events.length > 1}
            aria-disabled={m.events.length === 1 && m.events[0].case_id === null}
            aria-expanded={m.events.length > 1 ? open === m.key : undefined}
            aria-label={spoken(m.date, m.text, m.mine, isAlert(m.kind) && m.date >= today)}
            title={spoken(m.date, m.text, m.mine, isAlert(m.kind) && m.date >= today)}
            style={{ left: rows[i].left, width: rows[i].width, top: `calc(var(--tl-top) + ${rows[i].row} * var(--tl-row))` }}
            onClick={() => press(m)}
          >
            <span className="t">{m.text}</span>
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
              aria-label={spoken(e.date, e.label, role !== undefined && e.roles.includes(role), isAlert(e.kind))}
              aria-disabled={e.case_id === null}
              onClick={() => e.case_id !== null && go(e.case_id)}
            >
              <span className="d">{withWeekday(e.date).slice(5)}</span>
              <span className="l">{e.label}</span>
            </button>
          </li>
        ))}
      </ul>
      {!showPast && shown.length === 0 && <p className="muted">오늘 이후 일정이 없어요</p>}
      {!showPast && pastCount > 0 && (
        <button type="button" className="more" onClick={() => setShowPast(true)}>지난 일정 보기</button>
      )}
    </div>
  )
}

/** 서버 일정 이름 앞의 번호를 건 이름의 짧은 형태로("PLAN-001 확정 기한" -> "혜인 기초 · 확정 기한") */
function relabel(e: CalEvent, cases: Map<number, CaseListRow>): CalEvent {
  const c = e.case_id === null ? undefined : cases.get(e.case_id)
  if (!c || !e.label.startsWith(c.ref_id)) return e
  const rest = e.label.slice(c.ref_id.length).trim()
  return { ...e, label: rest ? `${shortTitle(c.title, c.ref_id)} · ${rest}` : shortTitle(c.title, c.ref_id) }
}

export default function Timeline() {
  const { version, date, failed: clockFailed, retry: retryClock } = useClock()
  const { person } = useViewer()
  const narrow = useNarrow()
  const { data, error, loading, retry } = useLoad<CalEvent[]>('/api/calendar', [version])
  const caseRows = useLoad<CaseListRow[]>('/api/cases', [version])
  const [all, setAll] = useState(false)
  const today = date ?? ''
  const role = person?.role

  const named = useMemo(() => {
    const byId = new Map((caseRows.data ?? []).map((c) => [c.id, c]))
    return (data ?? []).map((e) => relabel(e, byId))
  }, [data, caseRows.data])
  const isKey = (e: CalEvent) => e.kind === BAND_KIND || (role !== undefined && e.roles.includes(role)) || KEY_KINDS.test(e.kind)
  const shown = all ? named : named.filter(isKey)
  const hidden = named.length - shown.length

  return (
    <section className="tl" aria-label="일정">
      <div className="tl-head">
        <h2>일정</h2>
        <span>남색은 내 차례</span>
        {(hidden > 0 || all) && (
          <button type="button" className="more-sched" aria-pressed={all} onClick={() => setAll(!all)}>
            {all ? '중요한 일정만 보기' : '모든 일정 보기'}
          </button>
        )}
      </div>
      {error ? (
        <LoadFailed retry={retry} />
      ) : clockFailed && !today ? (
        <LoadFailed retry={retryClock} message="기준일을 불러오지 못했어요" buttonName="기준일 다시 시도" />
      ) : !data || !today ? (
        <p className="muted">{loading || !today ? '불러오는 중' : '일정을 읽지 못했어요'}</p>
      ) : data.length === 0 ? (
        <p className="muted">잡힌 일정이 없어요</p>
      ) : narrow ? (
        <Narrow events={shown} today={today} role={role} />
      ) : (
        <Wide events={shown} today={today} role={role} />
      )}
    </section>
  )
}
