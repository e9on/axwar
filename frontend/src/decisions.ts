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
export const S_BLOCKED_1 = '1차 차단'
export const S_BLOCKED_2 = '2차 차단'
export const S_DONE = '완료'
export const S_AGREED = '합의'
/** 결정이 끝난 상태들(backend TERMINAL + 기본 거부·2차 차단). 이 상태면 남은 결재란 칸에 상태를 적는다. */
export const ENDED_STATUSES: readonly string[] = [S_REJECTED, S_HOLD, S_DEFAULT_DENY, S_BLOCKED_1, S_BLOCKED_2, S_DONE, S_AGREED]
/** 결정을 받는 중인 상태들(backend OPEN) */
export const OPEN_STATUSES: readonly string[] = ['회신 대기', '승인 대기', '재승인 대기', '검토']
