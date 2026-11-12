import { S_DEFAULT_DENY, S_HOLD, S_REJECTED } from '../decisions'

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
  /** 지금 보는 사람의 역할(내 차례 칸 표시). 결재할 수 없으면 null */
  mineRole: string | null
  /** 건 상태: 기본 거부·거절·확정 보류로 끝났으면 남은 칸에 그 상태를 적는다 */
  status: string
}

const ENDED = [S_DEFAULT_DENY, S_REJECTED, S_HOLD]

export default function ApprovalStamps({ label, roles, approved, mineRole, status }: Props) {
  if (roles.length === 0) return null
  const ended = ENDED.includes(status)
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
