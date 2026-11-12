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

/** 부서 요청 상태 이름(backend flow.R_WAIT·R_HUMAN·R_DONE). 서버 값과 같아야 한다. */
export const R_WAIT = '대기'
export const R_HUMAN = '사람 확인'
export const R_DONE = '처리됨'
/** 2차 보류 상태 이름과 판매율 판정 결과 이름(backend flow.S_PHASE2_HOLD, SELL_*) */
export const S_PHASE2_HOLD = '2차 보류'
export const SELL_HOLD = '보류'
export const SELL_ADJUST = '조절'
export const SELL_SOLDOUT = '품절'
/** 서버가 알려 주는 시스템 모드 이름(backend store.MODE_DEMO) */
export const DEMO_MODE = '시연'
/** 정책 항목 키(backend policy.toml). 값은 서버에서 읽는다. */
export const POLICY_CAMPAIGN_ROLE = 'roles.campaign'
export const POLICY_REVIEW_INPUTTERS = 'admin.review_inputters'
export const POLICY_RETURN_INPUTTERS = 'admin.return_inputters'
export const POLICY_STOP_Z = 'split.stop_z'
export const POLICY_OBSERVE_DAYS = 'split.return_observe_days'
