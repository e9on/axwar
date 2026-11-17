import './Badge.css'

/** 표시는 "가정"(원본에 없어 정한 값)과 "AI"(AI가 쓴 글)만 그린다. 원본·계산·회신·의견은 펼친 근거 안의 출처로 알 수 있어 그리지 않는다. */
const CLASS: Record<string, string> = { 가정: 'asm', AI: 'ai' }

export default function Badge({ kind }: { kind: string }) {
  const cls = CLASS[kind]
  if (!cls) return null
  return <span className={`b ${cls}`}>{kind}</span>
}
