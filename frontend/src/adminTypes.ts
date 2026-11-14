/** 시연 조작판·기록·정책·등록 화면이 읽는 API 응답의 모양(backend api/main.py). 화면이 쓰는 것만 적는다. */

/** 시연 대본 한 단계(backend scenarios.ACTION_FIELDS). 행동마다 쓰는 항목이 달라 나머지는 열어 둔다 */
export type ScenarioStep = {
  action: string
  date?: string
  plan?: string
  contract?: string
  actor?: string
  dept?: string
  [key: string]: unknown
}

export type Scenario = {
  name: string
  title: string
  description: string
  /** 한 줄 요약(서버 대본에 있을 때) */
  summary?: string
  plans: string[]
  contracts: string[]
  script: ScenarioStep[]
}

/** 날짜가 지나며 서버가 한 일(조기 경고, 기본 거부 등) */
export type ServerAction = { date: string; case_id?: number | null; action: string; targets?: string[]; text: string }

/** play·run 한 단계의 결과. 행동에 따라 있는 항목이 다르다 */
export type StepOutcome = {
  action: string
  actions?: ServerAction[]
  status?: string
  changed?: boolean
  ignored?: boolean
  reason?: string
  case_id?: number
  judgment?: { stance?: string | null } | null
  [key: string]: unknown
}

export type EventRow = {
  id: number
  ts: string
  sim_date: string
  case_id: number | null
  kind: string
  actor: string
  detail: Record<string, unknown>
}

export type AiCall = {
  id: number
  ts: string
  day: string
  case_id: number | null
  kind: string
  model: string
  in_tok: number
  out_tok: number
  usd: number
  confidence: number | null
  summary: string
  state: string
}

export type AiUsage = {
  mode: string
  spent_usd: number
  spent_today_usd: number
  total_cap_usd: number
  daily_cap_usd: number
  calls_total: number
  calls: AiCall[]
}

/** GET /api/policy, /api/assumptions 한 줄 */
export type PolicyItem = {
  key: string
  value: unknown
  source: string
  description: string
  overridden: boolean
  file_value: unknown
  effective_source: string
}

export type PolicyChangeRow = { id: number; key: string; before: unknown; after: unknown; actor: string; at: string; reason: string }

export type PlanRow = {
  id: number
  plan_id: string
  campaign_id: string | null
  influencer_id: string | null
  channel: string | null
  requested_budget_krw: number | null
  expected_gmv_krw: number | null
  settlement_date: string | null
  contract_deadline: string | null
  origin: string
}

export type ContractRow = {
  id: number
  influencer_code: string
  influencer_name: string
  annual_fixed_krw: number
  performance_fee_text: string
  notice_deadline: string
  expiry_date: string
  auto_renew: boolean
  source_doc: string
  origin: string
}

export type RegisterReply = { plan_id?: string; influencer_code?: string; case_id: number | null; open_error: string | null }
export type PlanImport = { added: number; updated: number; unchanged: number; skipped: { plan_id: string; reason: string; source_changed: string[] }[]; warnings: string[]; actions: ServerAction[] }

/** GET /api/permissions?person= — 관리 동작마다 해도 되는지와 안 될 때의 이유 */
export type AdminKey = 'registry' | 'policy' | 'mode' | 'review' | 'return'
export type Permission = { allowed: boolean; reason: string | null }
export type PersonPermissions = { name: string; role: string; admin: Record<AdminKey, Permission> }

/** GET /api/demo/state — 시연 진행 위치(서버가 기억한다) */
export type DemoState = {
  scenario: string | null
  title: string | null
  done: number
  total: number
  finished: boolean
  next_step: ScenarioStep | null
  date: string
  /** 지금 시연자가 할 일(없으면 null). ready는 앞의 바깥 사건이 모두 도착했는지 */
  waiting?: DemoWaiting | null
  /** 다음 바깥 사건이 도착하는 날(없으면 null) */
  next_date?: string | null
  arrived?: string[]
  /** 장면 건마다 "번호 지금 상태"(끝났을 때 결과로 보인다) */
  outcome?: string[]
}

export type DemoWaiting = { index: number; action: string; actor: string | null; target: string | null; text: string; ready: boolean; step: ScenarioStep }

/** POST /api/demo/advance — 날짜로 진행한 결과(상태 항목과 함께) */
export type AdvanceReply = Partial<DemoState> & { applied: string[]; skipped: string[]; actions: ServerAction[] }
