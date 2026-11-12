/** 서버가 받는 결정·의견 이름(backend engine.scenarios DECISIONS, UP_OPINIONS). 서버 값과 같아야 한다. */
export const D_APPROVE = '승인'
export const D_SPLIT = '분할승인'
export const D_REJECT = '거절'
export const OPINIONS = ['승인 권고', '반대 권고'] as const

/** 서버 상태 이름 중 화면 문장을 가르는 것 */
export const S_PHASE2_WAIT = '2차 승인 대기'
export const S_DEFAULT_DENY = '기본 거부'
export const S_REJECTED = '거절'
export const S_HOLD = '확정 보류'
