import { koDate } from './date'

/** 화면에 보이는 숫자·값 글자 만들기 */
const PERCENT = 100 // 비율(0~1) → 백분율 단위 변환
export function num(v: number): string {
  return Number.isInteger(v) ? v.toLocaleString('ko-KR') : v.toLocaleString('ko-KR', { maximumFractionDigits: 3 })
}

/** 0~1 비율을 백분율 글자로 */
export function pct(v: number, digits = 0): string {
  return `${(v * PERCENT).toLocaleString('ko-KR', { minimumFractionDigits: digits, maximumFractionDigits: digits })}%`
}

const USD_DIGITS = 4 // AI 호출 비용 소수 자릿수
export function usd(v: number): string {
  return `$${v.toFixed(USD_DIGITS)}`
}

export function won(v: number): string {
  return `${num(v)}원`
}

/** 서버가 근거 줄마다 붙이는 단위(unit)에 따른 값 글자. 모르는 단위나 단위 없음은 숫자 그대로. */
export function unitValue(v: number, unit: string | null | undefined): string {
  const fixed = (n: number, d: number) => n.toLocaleString('ko-KR', { minimumFractionDigits: d, maximumFractionDigits: d })
  switch (unit) {
    case 'ratio':
      return `${fixed(v * PERCENT, 2)}%` // 0~1 비율 → 백분율 단위 변환
    case 'percent':
      return `${fixed(v, 2)}%`
    case 'krw':
      return won(Math.round(v))
    case 'multiple':
      return fixed(v, 3)
    case 'score': // 점수(HHI 등): 정수, 천 단위 쉼표, 기호 없음(가정 F36)
      return num(Math.round(v))
    case 'diff': // 부호 붙은 차이: 소수 셋째 자리, 0은 부호 없음(가정 F36)
      return v.toLocaleString('ko-KR', { minimumFractionDigits: 3, maximumFractionDigits: 3, signDisplay: 'exceptZero' })
    case 'count':
      return num(Math.round(v))
    case 'days':
      return `${num(v)}일`
    default:
      return num(v)
  }
}

/** 입력값·정책 값처럼 모양이 정해지지 않은 값 */
export function anyValue(v: unknown): string {
  if (v === null || v === undefined || v === '') return '—'
  if (typeof v === 'boolean') return v ? '예' : '아니오'
  if (typeof v === 'number') return num(v)
  if (Array.isArray(v)) return v.map(anyValue).join(', ')
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

/** "02_masil/marketing/a.csv" → 폴더, 파일 이름 */
export function splitPath(path: string): { dir: string; file: string } {
  const i = Math.max(path.lastIndexOf('/'), path.lastIndexOf(String.fromCharCode(92)))
  return i < 0 ? { dir: '', file: path } : { dir: path.slice(0, i + 1), file: path.slice(i + 1) }
}

/** 서버가 날짜를 넘기며 한 일(조기 경고 등) 한 줄 */
export function actionLine(a: { date: string; action: string; text: string }): string {
  return `${koDate(a.date)} · ${a.action} · ${a.text}`
}
