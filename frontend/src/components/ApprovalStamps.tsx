import { ST_ENDED } from '../decisions'

/** 역할 이름 줄임 글자: 마지막 낱말에서 끝의 '팀'을 떼고 세 글자까지 ("Masil 대표" → "대표", "마케팅팀" → "마케팅"). */
export function shortRole(role: string): string {
  const last = role.trim().split(/\s+/).pop() ?? role
  const base = last.length > 2 && last.endsWith('팀') ? last.slice(0, -1) : last
  return base.slice(0, 3)
}

type Props = {
  label: string
  roles: string[]
  approved: string[]
  /** 지금 보는 사람의 역할 */
  viewerRole: string | null
  /** 이 결재란에서 지금 보는 사람이 결정할 수 있나. 대리 결재면 역할이 칸에 없어도 첫 대기 칸이 내 차례다 */
  canAct: boolean
  /** 건 상태 글자와 서버가 준 단계: 단계가 끝남이면 남은 칸에 상태 글자를 적는다 */
  status: string
  stage: string
}

export default function ApprovalStamps({ label, roles, approved, viewerRole, canAct, status, stage }: Props) {
  if (roles.length === 0) return null
  const ended = stage === ST_ENDED
  const waiting = roles.filter((r) => !approved.includes(r))
  const mineRole = !canAct ? null : viewerRole && waiting.includes(viewerRole) ? viewerRole : (waiting[0] ?? null)
  return (
    <div className="stamps" role="list" aria-label={label} style={{ ['--n' as string]: roles.length }}>
      {roles.map((role) => {
        const done = approved.includes(role)
        const mine = !done && !ended && mineRole === role
        const text = done ? '승인함' : ended ? status : mine ? '내 차례' : '대기'
        return (
          <div className="stamp" role="listitem" key={role} aria-label={`${role}: ${text}`}>
            <p className="r">{role}</p>
            <div className={`m${mine ? ' me' : ''}${ended && !done ? ' ended' : ''}`}>
              {done ? <span className="seal">{shortRole(role)}</span> : text}
            </div>
          </div>
        )
      })}
    </div>
  )
}
