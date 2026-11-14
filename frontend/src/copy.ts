/** 화면 문구를 한 곳에 둔다. 짧은 평서문, 한 줄에 한 뜻. 서버 내부 문장은 기본 화면에 올리지 않는다. */
import { koDate } from './date'
import { josa } from './format'

/** 기본 화면에 보이면 안 되는 내부 용어(시험이 렌더된 글에서 찾는다). 서버 원문은 펼쳤을 때만 보인다. */
export const FORBIDDEN_TERMS: RegExp[] = [
  /covenant/i,
  /설계\s*\d/,
  /fake/i,
  /판정에는 쓰지 않음/,
  /참고 신호/,
  /→/,
  /해야 (해요|함)/,
  /(고정|성과|인플루언서) 피(?![가-힣])/, // 사용자 결정: 수수료는 '피' 대신 '값'
  /피 뒤/,
]

export function findForbidden(text: string): string[] {
  return FORBIDDEN_TERMS.filter((re) => re.test(text)).map((re) => re.source)
}

/** 서버 문장을 기본 화면에 쓸 한 줄로: 금지어가 나오기 전까지만, 길면 말줄임 */
export function plainLine(text: string | null | undefined, max = 40): string {
  let cut = text ?? ''
  for (const re of FORBIDDEN_TERMS) {
    const m = re.exec(cut)
    if (m) cut = cut.slice(0, m.index)
  }
  cut = cut.trim()
  const clipped = cut.length > max ? `${cut.slice(0, max).trim()}…` : cut
  return clipped || ''
}

/** "혜인 기초 캠페인3 · 혜인" → "혜인 기초" (건 이름의 짧은 형태) */
export function shortTitle(title: string | undefined, fallback: string): string {
  if (!title) return fallback
  const head = title.split(' · ')[0].replace(/\s*캠페인\s*\d*\s*$/, '').trim()
  return head || fallback
}

/** 할 일 칸(서버 todo 칸 이름) → 줄 맨 앞의 "무엇을" */
export const TODO_VERB: Record<string, string> = {
  '승인 대기': '승인해 주세요',
  '회신 대기': '회신해 주세요',
  '기한 임박': '기한이 다가와요',
  '권한 이동': '결재가 넘어왔어요',
  알림: '확인해 주세요',
  작업: '작업이 있어요',
}

/** 결재 이유(rule_id)의 짧은 이름표 */
export const RULE_LABEL: Record<string, string> = {
  plan_within_delegation: '한도 이하 전결',
  plan_item_over_limit: '건별 한도 초과',
  plan_total_over_limit: '총액 한도 초과',
  contract_over_limit: '계약 한도 초과',
  contract_within_limit: '계약 한도 이하',
  covenant_window: '현금 하회 구간',
  indicator_opposite: '지표가 나쁨',
  indicators_good: '지표 양호',
  escalation: '위로 올림',
  logistics_qty_limit: '물류 수량 한도',
  capacity_fallback: '물류 처리 한도',
}
export const RULE_LABEL_FALLBACK = '결재 규정'

/** 시연 장면 한 줄 요약(장면 이름별). 표에 없는 새 대본은 description 첫 문장을 쓴다. */
export const SCENE_SUMMARY: Record<string, string> = {
  scenario_1: '회신을 받고 Masil 대표가 승인해요',
  scenario_1_escalate: '마케팅팀장이 대표에게 올려 다시 결재해요',
  scenario_2: '재고가 모자라 분할 승인해요',
  scenario_2_exception: '2차가 보류돼 예외 승인으로 집행해요',
  scenario_2_reject: '재고 사용이 거절돼 수량이 줄어요',
  scenario_2_sales: '판매율에 맞춰 2차를 줄여 집행해요',
  scenario_3: '기한이 지나 기본 거부돼요',
  scenario_3_reject: '계약 갱신이 거절돼 조건변경을 통보해요',
}

export function sceneSummary(name: string, description: string): string {
  return SCENE_SUMMARY[name] ?? description.split(/(?<=[.。])\s/)[0]
}

/** 대본 단계 → 한 문장. 동작·사람·날짜 필드로 만든다. */
export type StepLike = { action: string; date?: string; actor?: string; dept?: string; decision?: string; [key: string]: unknown }

const DECISION_WORD: Record<string, string> = { 분할승인: '분할 승인' }

export function ga(word: string): string {
  const s = josa(word, '은')
  return s.endsWith('은') ? `${word}이` : `${word}가`
}

export function stepSentence(s: StepLike): string {
  const who = s.actor ?? s.dept ?? ''
  switch (s.action) {
    case '회신':
      return `${ga(who || '부서')} 회신해요`
    case '결정': {
      const d = typeof s.decision === 'string' ? (DECISION_WORD[s.decision] ?? s.decision) : '결정'
      return `${ga(who)} ${d}해요`
    }
    case '기준일':
      return s.date ? `기준일을 ${koDate(s.date)}${josa(koDate(s.date), '로').slice(koDate(s.date).length)} 옮겨요` : '기준일을 옮겨요'
    case '판매':
      return `${ga(who || '담당자')} 판매 실적을 넣어요`
    case '공지':
      return `${ga(who || '담당자')} 캠페인을 공지해요`
    case '리뷰':
      return '리뷰가 들어와요'
    case '반품':
      return '반품 수를 넣어요'
    case '발송':
      return `${ga(who || '담당자')} 통보를 보내요`
    case '상신':
      return `${ga(who)} 위로 올려요`
    case '예외 승인':
      return `${ga(who)} 예외 승인해요`
    default:
      return s.action
  }
}

/** 결정 성격의 단계(보는 사람을 바꿔 건을 열어야 하는 단계) */
export const DECISION_ACTIONS = ['결정', '상신', '예외 승인']

/** "A에서 B로" 한 덩이(받침에 맞는 조사) */
export function fromTo(a: string, b: string): string {
  return `${a}에서 ${josa(b, '로')}`
}

/** 결재선 변경 한 줄 */
export function changeLine(from: string, to: string, at: string): string {
  return `결재선이 바뀌었어요 (${from}에서 ${to}로, ${koDate(at)})`
}

/** AI 모델 이름: 서버의 시연용 해석기(fake…)는 "시연용 해석"으로 */
export function modelLabel(model: string): string {
  return /^fake/i.test(model) ? '시연용 해석' : model
}

/** 서버 문장의 화살표(A→B)를 "A에서 B로"로. 숫자에 단위가 오른쪽에만 붙어 있으면 왼쪽에도 붙인다(6,000→4,700개 → 6,000개에서 4,700개로) */
export function noArrow(text: string): string {
  return text.replace(/([^\s→]+)→((?:[^,·()\n→]|,(?=\d))+)/g, (_, a: string, b: string) => {
    const right = b.trim()
    const unit = right.match(/^[\d,.]+(\D+)$/)?.[1] ?? ''
    const left = unit && /^[\d,.]+$/.test(a) ? a + unit : a
    return `${left}에서 ${josa(right, '로')}${b.endsWith(' ') ? ' ' : ''}`
  })
}
