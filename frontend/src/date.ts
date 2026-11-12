/** 날짜 문자열(YYYY-MM-DD) 계산. 시간대에 흔들리지 않게 UTC로만 센다. */
const WEEKDAYS = ['일', '월', '화', '수', '목', '금', '토']

function parse(iso: string): Date {
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(Date.UTC(y, m - 1, d))
}

export function addDays(iso: string, days: number): string {
  const d = parse(iso)
  d.setUTCDate(d.getUTCDate() + days)
  return d.toISOString().slice(0, 10)
}

export function withWeekday(iso: string): string {
  return `${iso} (${WEEKDAYS[parse(iso).getUTCDay()]})`
}
