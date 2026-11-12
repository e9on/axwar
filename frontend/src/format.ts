/** 화면에 보이는 숫자·값 글자 만들기 */
export function num(v: number): string {
  return Number.isInteger(v) ? v.toLocaleString('ko-KR') : v.toLocaleString('ko-KR', { maximumFractionDigits: 3 })
}

export function won(v: number): string {
  return `${num(v)}원`
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
