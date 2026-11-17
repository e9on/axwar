// hardcode-allow: 1.1 (굵은 글씨가 넓어지는 폭 배율 — 스타일 추정)
/** 일정 띠 배치 계산(그리는 일과 분리). 날짜는 YYYY-MM-DD 문자열, 계산은 UTC 일수로. */

export type CalEvent = { date: string; end: string | null; kind: string; label: string; case_id: number | null; roles: string[] }

const DAY = 24 * 60 * 60 * 1000
export const dayNum = (iso: string): number => {
  const [y, m, d] = iso.split('-').map(Number)
  return Date.UTC(y, m - 1, d) / DAY
}

/** 달력 응답과 오늘을 모두 담는 범위를 월 단위로 넓힌다. start는 첫 달 1일, end는 마지막 달 다음 달 1일(포함하지 않음). */
export function monthRange(dates: string[]): { start: string; end: string } {
  const sorted = [...dates].sort()
  const [y1, m1] = sorted[0].split('-').map(Number)
  const [y2, m2] = sorted[sorted.length - 1].split('-').map(Number)
  const next = new Date(Date.UTC(y2, m2, 1)).toISOString().slice(0, 10)
  return { start: `${y1}-${String(m1).padStart(2, '0')}-01`, end: next }
}

export function monthsIn(start: string, end: string): { label: string; at: string }[] {
  const out: { label: string; at: string }[] = []
  let [y, m] = start.split('-').map(Number)
  while (dayNum(`${y}-${String(m).padStart(2, '0')}-01`) < dayNum(end)) {
    out.push({ label: `${y}년 ${m}월`, at: `${y}-${String(m).padStart(2, '0')}-01` })
    m += 1
    if (m > 12) { m = 1; y += 1 }
  }
  return out
}

/** 표시 크기. CSS가 이 값을 변수(--dot-*)로 받아 쓰므로 폭 추정과 실제 모양이 늘 같다. */
export const DOT_PAD_PX = 8 // 표시 안쪽 좌우 여백(토큰 --s-2와 같은 값)
export const DOT_BORDER_PX = 2 // 가장 굵은 테두리(알림)
export const DOT_CHAR_PX = 12 // 글자 크기(토큰 --t-1과 같은 값), 한글 한 자 폭
export const DOT_MAX_PX = 190 // 한 줄 최대 폭. 넘으면 두 줄
export const DOT_GAP_PX = 6
export const BOLD_RATIO = 1.1

/** 날짜의 가로 위치(0~100%) */
export const pct = (date: string, start: string, end: string): number =>
  ((dayNum(date) - dayNum(start)) / (dayNum(end) - dayNum(start))) * 100

/** 띠(시작~끝, 끝날 포함)의 왼쪽 위치와 폭(%). */
export function bandSpan(date: string, end: string, start: string, rangeEnd: string): { left: number; width: number } {
  const total = dayNum(rangeEnd) - dayNum(start)
  const left = ((dayNum(date) - dayNum(start)) / total) * 100
  const right = ((dayNum(end) + 1 - dayNum(start)) / total) * 100
  return { left, width: right - left }
}

/** 표시의 왼쪽 끝(px): 날짜 위치에 두되 트랙 오른쪽 끝을 넘으면 안쪽으로만 민다. */
export const placeLeft = (x: number, w: number, trackWidth: number): number =>
  Math.max(0, Math.min(x, trackWidth - w))

export type Mark = {
  key: string
  date: string
  kind: string
  text: string // 보이는 글
  events: CalEvent[]
  mine: boolean
}

/** 같은 날·같은 종류·같은 내 차례 여부가 minGroup개 이상이면 한 표시로 묶는다. */
export function toMarks(events: CalEvent[], role: string | undefined, minGroup: number): Mark[] {
  const marks: Mark[] = []
  const buckets = new Map<string, CalEvent[]>()
  for (const e of events) {
    if (e.kind === '하회 구간') continue
    const mine = role !== undefined && e.roles.includes(role)
    const key = `${e.date}|${e.kind}|${mine}`
    buckets.set(key, [...(buckets.get(key) ?? []), e])
  }
  for (const [key, list] of buckets) {
    const mine = key.endsWith('|true')
    if (list.length >= minGroup) {
      const text = `${list[0].kind} ${list.length}건`
      marks.push({ key, date: list[0].date, kind: list[0].kind, text, events: list, mine })
    } else {
      list.forEach((e, i) => marks.push({ key: `${key}#${i}`, date: e.date, kind: e.kind, text: e.label, events: [e], mine }))
    }
  }
  return marks.sort((a, b) => a.date.localeCompare(b.date) || a.key.localeCompare(b.key))
}

/** 글자 폭 추정(px): 한글은 넓고 영문·숫자는 좁다. 표시 안쪽 여백 포함, 최대치로 자른다. */
export function estimateWidth(text: string, charPx: number, padPx: number, maxPx: number): number {
  let w = padPx
  const half = Math.ceil((charPx * 5) / 8)
  for (const ch of text) w += /[ᄀ-￿]/.test(ch) ? charPx : half
  return Math.min(w, maxPx)
}

/** 표시를 줄에 나눠 담는다. 같은 줄에서 앞 표시의 오른쪽 끝과 겹치면 다음 줄. 줄 번호 배열(입력 순서 그대로)을 돌려준다. */
export function packRows(items: { left: number; width: number }[], gap: number): number[] {
  const rightEdge: number[] = []
  return items.map(({ left, width }) => {
    let row = rightEdge.findIndex((r) => left >= r + gap)
    if (row < 0) { row = rightEdge.length; rightEdge.push(0) }
    rightEdge[row] = left + width
    return row
  })
}
