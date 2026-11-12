import './Badge.css'

/** 근거 배지 6종 이름 → 색 클래스(토큰 --c-b-*). 모르는 이름은 의견색. */
const CLASS: Record<string, string> = { 원본: 'src', 계산: 'calc', 가정: 'asm', 회신: 'reply', 의견: 'op', AI: 'ai' }

export default function Badge({ kind }: { kind: string }) {
  return <span className={`b ${CLASS[kind] ?? 'op'}`}>{kind}</span>
}
