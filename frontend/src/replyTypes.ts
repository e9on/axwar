/** 회신 입력·2차 관찰 API 응답의 모양(backend api/main.py, flow.reply·phase2_view). 화면이 쓰는 것만 적는다. */
import type { Detail, Hit, ReplyJudgment } from './caseTypes'

/** GET /api/requests, /api/human-checks 한 줄 */
export type RequestRow = {
  id: number
  case_id: number
  dept: string
  purpose: string
  text: string
  status: string
  attach_required: boolean
  created_at?: string
  ref_id: string
  case_status: string
}

/** 회신·사람 확인 저장 응답. judgment는 AI 해석 결과. */
export type ReplyResult = {
  request_id: number
  case_id: number
  ignored: boolean
  reason?: string
  needs_human: boolean
  changed: boolean
  status: string
  judgment: { stance: string | null; qty_limit: number | null; next_date: string | null; needs_human: boolean; confidence: number | null; model: string } | null
}

export type PolicyRow = { key: string; value: unknown; source: string | null; description: string }

export type Gate = { open: boolean; auto_stopped: boolean; reasons: string[]; actions: string[]; blocked?: boolean }
export type Sales = { orders: number; returns: number; net: number; date: string }
export type Returns = { change_of_mind: number; color: number; date: string }
export type Sellthrough = {
  rate: number
  orders: number
  returns: number
  net: number
  p1_qty: number
  hold_ratio: number
  qty_before: number
  amount_before: number
  outcome: string
  qty_after: number
  amount_after: number
  excess?: number
  at: string
}
export type Phase2Decision = { choice: string; reason: string; actor: string; qty_before: number; qty_after: number; at: string }

/** 보는 사람이 2차 관찰에서 할 수 있는 동작과 막힌 동작의 이유(서버가 판정). 모르는 사람이면 error만 채워진다 */
export type Phase2Viewer = {
  person: string
  role: string | null
  error?: string
  actions: string[]
  blocked: { action: string; reason: string }[]
  actions_phase2: string[]
  blocked_phase2: { action: string; reason: string }[]
  can_decide_phase2: boolean
}

/** 리뷰 하나의 AI 해석. ok:false는 해석 실패, 리뷰의 judgment가 null이면 옛 리뷰(해석 기록 없음) */
export type ReviewJudgment =
  | { ok: true; id: number; reason: string | null; sentiment: string | null; content_gap: boolean | null; confidence: number | null; needs_human: boolean; model: string }
  | { ok: false; error: string }
export type ReviewWithJudgment = ReviewRow & { judgment: ReviewJudgment | null }

export type ReturnItem = {
  label: string
  baseline: number | null
  phase1_qty: number
  limit: number | null
  count: number
  rate: number | null
  over: boolean
  unit: string
  detail: Detail
}
/** 반품 관찰 기준 숫자(서버 계산). 화면은 나누지 않고 그대로 보인다 */
export type ReturnsCheck = {
  entered: boolean
  phase1_qty: number
  sales_orders: number | null
  z: number
  exception_applied: boolean
  observation: { required_days: number; elapsed_days: number | null; done: boolean; adjustment: string }
  items: ReturnItem[]
}

/** GET /api/cases/{id}/phase2?viewer= */
export type Phase2Observe = {
  plan: { qty: number; date: string | null; amount_krw?: number } | null
  approvers: string[] | null
  hits: Hit[]
  required_roles: string[]
  pending_roles: string[]
  approved_roles: string[]
  gate: Gate
  sales: Sales | null
  returns: Returns | null
  sellthrough: Sellthrough | null
  decision: Phase2Decision | null
  deadline: string | null
  deny_date: string | null
  approval_deadline: string | null
  viewer: Phase2Viewer | null
  returns_check: ReturnsCheck
  reviews: ReviewWithJudgment[]
}

export type ReviewRow = { id: number; product: string; text: string; created_at: string }

/** 건 상세 중 2차 관찰 화면이 쓰는 부분 */
export type ObserveCase = {
  case: { id: number; ref_id: string; status: string; title?: string; stage: string }
  facts: { phase1?: { qty?: number; date?: string | null } | null; reviews?: { total: number; color: number } | null; [key: string]: unknown }
}

/** 회신 화면이 읽는 건 상세 중 일부 */
export type ReplyCase = {
  case: { id: number; ref_id: string; status: string; title?: string }
  facts: { phase1_date?: string | null; [key: string]: unknown }
  deadline: string | null
  approval_deadline: string | null
  requests: {
    id: number
    dept: string
    purpose: string
    text: string
    status: string
    attach_required: boolean
    replies: { id: number; text: string; attachments: number; created_at: string; judgment: ReplyJudgment | null }[]
  }[]
  tasks: { id: number; dept: string; title: string; due: string; status: string; detail: string }[]
}
