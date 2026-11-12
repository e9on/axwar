/** 서버가 받는 결정·의견 이름(backend engine.scenarios DECISIONS, UP_OPINIONS). 서버 값과 같아야 한다. */
export const D_APPROVE = '승인'
export const D_SPLIT = '분할승인'
export const D_REJECT = '거절'
export const OPINIONS = ['승인 권고', '반대 권고'] as const

/** 서버가 주는 단계(case.stage) 값 중 화면 문장을 가르는 것. 열림·끝남 판단은 case.open·case.stage로 하고 상태 이름 목록은 두지 않는다. */
export const ST_PHASE2_WAIT = '2차 승인 대기'
export const ST_ENDED = '끝남'
/** 상태 이름 중 남은 날 문장만 가르는 것 */
export const S_DEFAULT_DENY = '기본 거부'
/** 서버 건 종류 이름(backend flow.KIND_CONTRACT) */
export const KIND_CONTRACT = '계약'
