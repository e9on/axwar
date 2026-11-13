/** AI가 쓴 글(브리핑·반대 근거)을 줄 단위로 읽는다. 서버가 주는 세 줄 형식의 머리말만 안다. */
export const AI_HEADS = ['권고', '이유', '주의', '반대로 결정하려면', '확인할 것']
export const AI_SHORT_LIMIT = 120
const HEAD_RE = new RegExp(`^\s*(${AI_HEADS.join('|')})\s*[:：]\s*(.*)$`)
const FIRST_SENTENCE = /^.*?[.!?。](?=\s|$)/

export type AiLine = { head: string | null; body: string }

export function aiLines(text: string): AiLine[] {
  return text
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean)
    .map((l) => {
      const m = HEAD_RE.exec(l)
      return m ? { head: m[1], body: m[2] } : { head: null, body: l }
    })
}

/** 머리말 줄이 하나라도 있으면 새 형식 */
export function isStructured(text: string): boolean {
  return aiLines(text).some((l) => l.head !== null)
}

export function clip(text: string, n = AI_SHORT_LIMIT): string {
  return text.length > n ? `${text.slice(0, n)}…` : text
}

/** 핵심 줄에 보이는 한 줄: 권고 줄, 없으면 첫 줄(옛 글은 첫 문장, 길면 120자) */
export function aiHeadline(text: string): string {
  const lines = aiLines(text)
  const rec = lines.find((l) => l.head === '권고')
  if (rec) return clip(rec.body)
  const first = lines[0]?.body ?? ''
  return clip(FIRST_SENTENCE.exec(first)?.[0] ?? first)
}
