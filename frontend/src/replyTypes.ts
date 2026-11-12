/** 회신 입력·2차 관찰 API 응답의 모양(backend api/main.py, flow.reply·phase2_view). 화면이 쓰는 것만 적는다. */
import type { Hit, ReplyJudgment } from './caseTypes'

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

/** GET /api/cases/{id}/phase2 */
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
}

export type ReviewRow = { id: number; product: string; text: string; created_at: string }

/** 건 상세 중 2차 관찰 화면이 쓰는 부분 */
export type ObserveCase = {
  case: { id: number; ref_id: string; status: string; title?: string; stage: string }
  facts: { phase1?: { qty?: number; date?: string | null } | null; reviews?: { total: number; color: number } | null; [key: string]: unknown }
  reviews: ReviewRow[]
  judgments: { id: number; kind: string; model: string; input_summary: string; needs_human: boolean; confidence: number | null; result: { reason?: string; sentiment?: string; content_gap?: boolean } }[]
  viewer?: { person: string; role: string; can_decide_phase2: boolean; actions_phase2?: string[] }
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
