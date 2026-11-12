/** 건 상세·근거 API 응답의 모양(backend flow.case_detail, case_evidence). 화면이 쓰는 것만 적는다. */

export type Hit = { rule_id: string; text: string; source: string; badge: string; stage?: string }

export type Escalation = {
  stage: string
  from: string
  to: string
  actor: string
  opinion: string
  reason: string
  at: string
  active?: boolean
}

export type ApproverChange = { before: string[]; after: string[]; reason: string; at: string }

export type Reply = { id: number; text: string; attachments: number; created_at: string }
export type CaseRequest = {
  id: number
  dept: string
  purpose: string
  text: string
  status: string
  attach_required: boolean
  replies: Reply[]
}

export type Judgment = {
  id: number
  kind: string
  model: string
  sim_date: string
  input_summary: string
  needs_human: boolean
  confidence: number | null
  result: { stance?: string; qty_limit?: number | null; next_date?: string | null; needs_human?: boolean }
}

export type AiText = { text: string; ok: boolean; model: string; sim_date: string; stale: boolean }

export type CaseEvent = { id: number; sim_date: string; kind: string; actor: string; detail: Record<string, unknown> }

export type Task = { id: number; dept: string; title: string; due: string; status: string; detail: string }

export type Split = { phase1_qty: number; phase1_date: string | null; phase2_qty: number; phase2_date: string | null }

export type Phase2 = {
  plan: { qty: number; date: string | null; amount_krw?: number } | null
  approvers: string[] | null
  hits: Hit[]
  required_roles: string[]
  pending_roles: string[]
  approved_roles: string[]
  gate: { open: boolean; auto_hold?: boolean; reasons?: string[] }
  deadline: string | null
  deny_date: string | null
  approval_deadline: string | null
  decision: { amount_before?: number; amount_after?: number } | null
  result: unknown
}

export type CaseDetailData = {
  case: { id: number; kind: string; ref_id: string; status: string; origin: string; title?: string }
  facts: {
    amount_krw?: number
    plan_total_krw?: number
    settlement_date?: string
    phase1_date?: string | null
    deadline?: string
    expiry?: string
    annual_fixed_krw?: number
    demo_note?: string
    note?: string
    split?: Split | null
    stock?: { day_qty?: number | null; share?: number | null; want?: number | null; shortage?: boolean } | null
    volume?: { units?: number } | null
    [key: string]: unknown
  }
  rule: { approvers: string[]; hits: Hit[]; required_roles: string[]; approved_roles: string[]; pending_roles: string[] }
  phase2: Phase2 | null
  deadline: string | null
  deny_date: string | null
  approval_deadline: string | null
  escalations: Escalation[]
  briefing: AiText | null
  counterpoints: AiText | null
  approver_changes: ApproverChange[]
  requests: CaseRequest[]
  tasks: Task[]
  judgments: Judgment[]
  history: CaseEvent[]
  viewer?: {
    person: string
    role: string
    can_decide: boolean
    can_escalate: boolean
    can_escalate_phase2: boolean
    can_decide_phase2: boolean
  }
}

export type Detail = {
  formula: string
  inputs: { label: string; value: unknown }[]
  sources: string[]
  policies: { key: string; value: unknown; source: string; description: string }[]
}

export type SignalLine = {
  key: string
  label: string
  value: number | null
  compare: string
  level: 'red' | 'yellow' | 'green' | 'unmeasurable'
  badge: string
  judgment: string
  exclude_reason: string
  detail: Detail
}
export type IndicatorLine = {
  key: string
  label: string
  value: number | boolean | null
  rank: number | null
  of: number | null
  compare_label: string | null
  compare_value: number | null
  badge: string
  detail: Detail
}
export type CostRow = { key: string; label: string; amount: number; badge: string; detail: Detail }
export type RuleLine = { rule_id: string; text: string; source: string; badge: string; stage?: string; detail: Detail }

export type EvidenceData = {
  available: boolean
  reason: string | null
  signals: SignalLine[]
  key_indicators: IndicatorLine[]
  cost_breakdown: { note: string; rows: CostRow[] }
  breakeven: SignalLine | null
  attribution_note: string
  rule: { approver_hits: RuleLine[]; indicator_hits: RuleLine[]; phase2_approver_hits: RuleLine[] }
}
